from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import threading
import time
import uuid
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from mail_agent_core.agent import MailAgent
from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import AgentBehaviorSettings, AgentProfile, AgentRule, MailActionType, MailCategory, RuleMode
from mail_agent_core.policy import PolicyEngine
from mail_agent_core.providers import CodexCliProvider, OllamaProvider
from mail_agent_core.update import UpdateClient
from mail_agent_imap import ImapMailbox, MailboxConfig, SmtpSender

from .action_executor import MailActionExecutor
from .agent_runtime import AgentRuntime
from .audit import AuditLog
from .cloud_sync import GoogleGmailSyncService, MicrosoftGraphSyncService
from .conversation_store import ConversationStore
from .draft_service import DraftService
from .key_store import create_master_key_store
from .mail_store import MailStore
from .oauth_controller import OAuthController
from .oauth_runtime import current_google_access_token, current_microsoft_access_token
from .recovery import RecoveryManager
from .registry_client import RegistryClient
from .schemas import (
    AgentAnalyzeRequest,
    AgentRunRequest,
    AttentionResolveRequest,
    BehaviorSettingsRequest,
    ConversationSnoozeRequest,
    BrainUpdateRequest,
    DraftSubmitRequest,
    DraftUpdateRequest,
    LLMSettingsRequest,
    LearningDecisionRequest,
    ProfileSettingsRequest,
    ApprovalDecisionRequest,
    IdentitySetupRequest,
    MailboxProbeRequest,
    OnboardingCompleteRequest,
    OAuthStartRequest,
    ProviderProbeRequest,
    RegistrationResponse,
    RecoveryReconcileRequest,
    RuleSimulationRequest,
    SenderPatternDecisionRequest,
    ShadowReplayRequest,
    SyncRunRequest,
    UndoActionRequest,
)
from .settings import settings
from .state import JsonStateStore
from .sync import MailboxRuntimeConfig, MailSyncService
from .undo_service import UndoService
from .vault import CredentialVault

settings.data_dir.mkdir(parents=True, exist_ok=True)
identity_manager = IdentityManager(settings.data_dir / "identity")
state_store = JsonStateStore(settings.data_dir / "state.json")
audit_log = AuditLog(settings.data_dir / "audit.jsonl")
mail_store = MailStore(settings.data_dir / "mail.db")
conversation_store = ConversationStore(settings.data_dir / "conversations.db")
vault = CredentialVault(
    settings.data_dir / "secrets.vault",
    master_key_store=create_master_key_store(settings.data_dir),
)
policy_engine = PolicyEngine()
mail_agent = MailAgent(policy_engine)
sync_service = MailSyncService(mail_store, vault)
gmail_sync_service = GoogleGmailSyncService(mail_store)
microsoft_sync_service = MicrosoftGraphSyncService(mail_store)
oauth_controller = OAuthController(
    settings=settings,
    state_store=state_store,
    vault=vault,
    audit_log=audit_log,
)
providers = {
    "ollama": OllamaProvider(settings.ollama_base_url),
    "codex": CodexCliProvider(settings.codex_binary),
}
_sync_stop = asyncio.Event()
_shadow_jobs: dict[str, dict] = {}


def _mailbox_id(email_address: str, imap_host: str) -> str:
    seed = f"{email_address.strip().lower()}|{imap_host.strip().lower()}".encode()
    return "mb_" + hashlib.sha256(seed).hexdigest()[:24]


def _configured_mailboxes() -> list[dict]:
    state = state_store.read()
    mailboxes = state.get("mailboxes")
    if isinstance(mailboxes, dict):
        return list(mailboxes.values())
    legacy = state.get("mailbox")
    return [legacy] if isinstance(legacy, dict) and legacy.get("mailbox_id") else []


def _public_mailbox(mailbox: dict) -> dict:
    return {key: value for key, value in mailbox.items() if key != "credential_ref"}


def _mailbox_by_id(mailbox_id: str) -> dict:
    mailbox = next((item for item in _configured_mailboxes() if item.get("mailbox_id") == mailbox_id), None)
    if mailbox is None:
        raise KeyError(mailbox_id)
    return mailbox


def _runtime_mailbox(mailbox_id: str) -> MailboxRuntimeConfig:
    mailbox = _mailbox_by_id(mailbox_id)
    credential_ref = mailbox.get("credential_ref")
    if not credential_ref or not vault.contains(credential_ref):
        raise RuntimeError("Mailbox credential is missing from the encrypted vault")
    return MailboxRuntimeConfig(
        mailbox_id=mailbox_id,
        email_address=mailbox["email_address"],
        username=mailbox["username"],
        imap_host=mailbox["imap_host"],
        imap_port=int(mailbox["imap_port"]),
        smtp_host=mailbox["smtp_host"],
        smtp_port=int(mailbox["smtp_port"]),
        credential_ref=credential_ref,
    )


action_executor = MailActionExecutor(
    mail_store=mail_store,
    identity_manager=identity_manager,
    vault=vault,
    mailbox_lookup=_mailbox_by_id,
    google_client_id=settings.google_client_id,
    google_client_secret=settings.google_client_secret,
    audit_log=audit_log,
    microsoft_client_id=settings.microsoft_client_id,
    microsoft_tenant=settings.microsoft_tenant,
)
agent_runtime = AgentRuntime(
    mail_agent=mail_agent,
    identity_manager=identity_manager,
    mail_store=mail_store,
    state_store=state_store,
    providers=providers,
    audit_log=audit_log,
    action_executor=action_executor,
    conversation_store=conversation_store,
)
undo_service = UndoService(conversation_store=conversation_store, action_executor=action_executor, mail_store=mail_store)

draft_service = DraftService(
    mail_store=mail_store,
    identity_manager=identity_manager,
    state_store=state_store,
    policy_engine=policy_engine,
    audit_log=audit_log,
    brain=agent_runtime.brain,
)
recovery_manager = RecoveryManager(
    data_dir=settings.data_dir,
    mail_store=mail_store,
    identity_manager=identity_manager,
    state_store=state_store,
    vault=vault,
    providers=providers,
    mailbox_supplier=_configured_mailboxes,
)


async def _sync_mailbox(mailbox: dict, *, limit: int = 100) -> dict:
    mailbox_id = mailbox["mailbox_id"]
    try:
        if mailbox.get("connector") == "gmail_api":
            if not settings.google_client_id:
                raise RuntimeError("Google OAuth is not configured in this MAIL-AGENT build")
            access_token = await current_google_access_token(
                mailbox,
                vault=vault,
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
            )
            result = await gmail_sync_service.sync(
                mailbox_id=mailbox_id,
                access_token=access_token,
                limit=limit,
            )
        elif mailbox.get("connector") == "microsoft_graph":
            if not settings.microsoft_client_id:
                raise RuntimeError("Microsoft OAuth is not configured in this MAIL-AGENT build")
            access_token = await current_microsoft_access_token(
                mailbox,
                vault=vault,
                client_id=settings.microsoft_client_id,
                tenant=settings.microsoft_tenant,
            )
            result = await microsoft_sync_service.sync(
                mailbox_id=mailbox_id,
                access_token=access_token,
            )
        else:
            result = await sync_service.sync(_runtime_mailbox(mailbox_id), limit=limit)
        audit_log.append("mailbox_synced", details=result)
        synced_count = next(
            (int(result.get(key) or 0) for key in ("imported", "inserted", "new_messages", "fetched") if result.get(key) is not None),
            None,
        )
        agent_runtime.activity.record_sync(
            mailbox_id=mailbox_id,
            status="completed",
            detail="Postfach erfolgreich synchronisiert.",
            connector=str(mailbox.get("connector") or "imap"),
            messages_synced=synced_count,
        )
        state = state_store.read()
        if state.get("onboarding_completed") and state.get("configuration"):
            try:
                result["agent"] = await agent_runtime.run_mailbox(mailbox_id)
            except Exception as agent_exc:
                audit_log.append(
                    "agent_cycle_failed",
                    details={"mailbox_id": mailbox_id, "error": str(agent_exc)},
                )
                result["agent"] = {
                    "mailbox_id": mailbox_id,
                    "processed": 0,
                    "error": str(agent_exc),
                }
        return result
    except Exception as exc:
        agent_runtime.activity.record_sync(
            mailbox_id=mailbox_id,
            status="failed",
            detail=f"Synchronisierung fehlgeschlagen: {exc}",
            connector=str(mailbox.get("connector") or "imap"),
        )
        mail_store.record_sync(
            mailbox_id,
            last_uid=mail_store.get_last_uid(mailbox_id),
            error=str(exc),
            cursor=mail_store.sync_status(mailbox_id).get("cursor"),
        )
        audit_log.append(
            "mailbox_sync_failed",
            details={"mailbox_id": mailbox_id, "error": str(exc)},
        )
        raise


async def _sync_loop() -> None:
    while not _sync_stop.is_set():
        for mailbox in _configured_mailboxes():
            mailbox_id = mailbox.get("mailbox_id")
            if not mailbox_id:
                continue
            try:
                await _sync_mailbox(mailbox)
            except Exception:
                # Per-mailbox error is persisted/audited; the worker must survive transient failures.
                pass
        try:
            await asyncio.wait_for(_sync_stop.wait(), timeout=settings.sync_interval_seconds)
        except TimeoutError:
            continue


@asynccontextmanager
async def lifespan(_: FastAPI):
    task: asyncio.Task | None = None
    recovered = recovery_manager.recover_stale_executions()
    if recovered['outbound_uncertain'] or recovered['retryable_failed']:
        audit_log.append('startup_execution_recovery', details=recovered)
    _sync_stop.clear()
    if settings.auto_sync_enabled:
        task = asyncio.create_task(_sync_loop(), name="mail-agent-mailbox-sync")
    try:
        yield
    finally:
        _sync_stop.set()
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


APP_VERSION = "0.15.0"
update_client = UpdateClient(
    feed_url=settings.update_feed_url,
    release_page=settings.update_release_page,
    token=os.getenv("MAIL_AGENT_UPDATE_TOKEN", "").strip() or None,
)

app = FastAPI(title="MAIL-AGENT Gateway", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "mail-agent-gateway", "version": APP_VERSION}


@app.get("/v1/system/health")
async def system_health() -> dict:
    return await recovery_manager.report()


@app.post("/v1/system/recovery/approvals/{approval_id}/reconcile")
async def reconcile_uncertain_approval(
    approval_id: str, body: RecoveryReconcileRequest
) -> dict:
    try:
        approval = recovery_manager.reconcile_uncertain(approval_id, outcome=body.outcome)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Approval not found") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit_log.append(
        "uncertain_outbound_reconciled",
        actor=body.actor,
        details={
            "approval_id": approval_id,
            "outcome": body.outcome,
            "action": approval.get("action"),
        },
    )
    return approval


@app.get("/v1/onboarding/status")
async def onboarding_status() -> dict:
    state = state_store.read()
    identity = asdict(identity_manager.load()) if identity_manager.exists() else None
    mailboxes = _configured_mailboxes()
    return {
        "identity_created": identity is not None,
        "identity": identity,
        "completed": bool(state.get("onboarding_completed")),
        "configuration": state.get("configuration"),
        "mailbox": _public_mailbox(mailboxes[0]) if mailboxes else None,
        "mailboxes": [_public_mailbox(item) for item in mailboxes],
    }


@app.post("/v1/onboarding/identity", response_model=RegistrationResponse)
async def create_and_register_identity(body: IdentitySetupRequest) -> RegistrationResponse:
    if identity_manager.exists():
        identity = identity_manager.load()
    else:
        identity = identity_manager.create(
            owner_id=body.owner_id,
            agent_name=body.agent_name,
            usage_type=body.usage_type,
        )

    registry = RegistryClient(settings.registry_url, identity_manager)
    try:
        result = await registry.register(identity)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Agent registry unavailable: {exc}") from exc

    audit_log.append(
        "agent_identity_registered",
        details={
            "agent_id": identity.agent_id,
            "owner_id": identity.owner_id,
            "fingerprint": identity.fingerprint,
        },
    )
    return RegistrationResponse(
        agent_id=identity.agent_id,
        installation_id=identity.installation_id,
        fingerprint=identity.fingerprint,
        registered=bool(result.get("registered")),
    )


@app.post("/v1/mailboxes/probe")
async def mailbox_probe(body: MailboxProbeRequest) -> dict:
    config = MailboxConfig(
        email_address=body.email_address,
        username=body.username,
        password=body.password,
        imap_host=body.imap_host,
        imap_port=body.imap_port,
        smtp_host=body.smtp_host,
        smtp_port=body.smtp_port,
    )
    try:
        await asyncio.to_thread(ImapMailbox(config).test_connection)
        await asyncio.to_thread(SmtpSender(config).test_connection)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Mailbox connection failed: {exc}") from exc

    mailbox_id = _mailbox_id(body.email_address, body.imap_host)
    credential_ref = f"mailbox:{mailbox_id}:password"
    vault.set_secret(credential_ref, body.password)

    state = state_store.read()
    mailboxes = state.setdefault("mailboxes", {})
    if not isinstance(mailboxes, dict):
        mailboxes = {}
        state["mailboxes"] = mailboxes
    mailboxes[mailbox_id] = {
        "mailbox_id": mailbox_id,
        "email_address": body.email_address,
        "username": body.username,
        "imap_host": body.imap_host,
        "imap_port": body.imap_port,
        "smtp_host": body.smtp_host,
        "smtp_port": body.smtp_port,
        "credential_ref": credential_ref,
        "credential_state": "encrypted-vault",
    }
    state.pop("mailbox", None)
    state_store.write(state)
    audit_log.append(
        "mailbox_connection_validated",
        details={"mailbox_id": mailbox_id, "email_address": body.email_address, "vaulted": True},
    )
    return {
        "connected": True,
        "mailbox_id": mailbox_id,
        "email_address": body.email_address,
        "secrets_persisted": True,
        "secret_storage": "encrypted-local-vault",
    }


@app.get("/v1/mailboxes")
async def list_mailboxes() -> dict:
    result = []
    for mailbox in _configured_mailboxes():
        safe = _public_mailbox(mailbox)
        safe["credential_available"] = bool(
            mailbox.get("credential_ref") and vault.contains(mailbox["credential_ref"])
        )
        safe["sync"] = mail_store.sync_status(mailbox["mailbox_id"])
        result.append(safe)
    return {"mailboxes": result}


@app.post("/v1/sync/run")
async def sync_now(body: SyncRunRequest) -> dict:
    mailbox_ids = [body.mailbox_id] if body.mailbox_id else [item["mailbox_id"] for item in _configured_mailboxes()]
    if not mailbox_ids:
        raise HTTPException(status_code=409, detail="No mailbox is configured")
    results = []
    for mailbox_id in mailbox_ids:
        try:
            results.append(await _sync_mailbox(_mailbox_by_id(mailbox_id), limit=body.limit))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown mailbox: {mailbox_id}") from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Mailbox sync failed: {exc}") from exc
    return {"results": results}


@app.get("/v1/mailboxes/{mailbox_id}/messages")
async def list_messages(mailbox_id: str, limit: int = 50) -> dict:
    if not any(item.get("mailbox_id") == mailbox_id for item in _configured_mailboxes()):
        raise HTTPException(status_code=404, detail="Unknown mailbox")
    return {"messages": mail_store.list_messages(mailbox_id, limit)}


@app.get("/v1/oauth/providers")
async def oauth_provider_status() -> dict:
    return oauth_controller.provider_status()


@app.post("/v1/oauth/google/start")
async def start_google_oauth(body: OAuthStartRequest) -> dict:
    try:
        result = oauth_controller.start_google(body.login_hint)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "provider": result.provider,
        "state": result.state,
        "authorization_url": result.authorization_url,
    }


@app.post("/v1/oauth/microsoft/start")
async def start_microsoft_oauth(body: OAuthStartRequest) -> dict:
    try:
        result = oauth_controller.start_microsoft(body.login_hint)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "provider": result.provider,
        "state": result.state,
        "authorization_url": result.authorization_url,
    }


@app.get("/v1/oauth/sessions/{state}")
async def oauth_session_status(state: str) -> dict:
    try:
        return oauth_controller.sessions.get(state).public()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="OAuth session not found or expired") from exc


async def _finish_google_oauth(
    *,
    state: str | None,
    code: str | None,
    error: str | None,
    error_description: str | None,
) -> HTMLResponse:
    if not state:
        raise HTTPException(status_code=400, detail="Missing OAuth state")
    if error:
        message = error_description or error
        oauth_controller.fail(state=state, provider="google", error=message)
        return HTMLResponse(_oauth_result_page(False, "Google-Anmeldung abgebrochen", message))
    if not code:
        oauth_controller.fail(state=state, provider="google", error="Authorization code is missing")
        return HTMLResponse(_oauth_result_page(False, "Google-Anmeldung fehlgeschlagen", "Kein Autorisierungscode erhalten."))
    try:
        result = await oauth_controller.complete_google(state=state, code=code)
        return HTMLResponse(
            _oauth_result_page(
                True,
                "Gmail ist verbunden",
                f"{result.get('email_address') or 'Das Postfach'} wurde sicher mit MAIL-AGENT verbunden.",
            )
        )
    except KeyError as exc:
        raise HTTPException(status_code=400, detail="OAuth session not found or expired") from exc
    except Exception as exc:
        return HTMLResponse(
            _oauth_result_page(False, "Google-Anmeldung fehlgeschlagen", str(exc)),
            status_code=502,
        )


@app.get("/v1/oauth/google/callback", response_class=HTMLResponse, include_in_schema=False)
async def google_oauth_callback(
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> HTMLResponse:
    return await _finish_google_oauth(
        state=state, code=code, error=error, error_description=error_description
    )


async def _finish_microsoft_oauth(
    *,
    state: str | None,
    code: str | None,
    error: str | None,
    error_description: str | None,
) -> HTMLResponse:
    if not state:
        raise HTTPException(status_code=400, detail="Missing OAuth state")
    if error:
        message = error_description or error
        oauth_controller.fail(state=state, provider="microsoft", error=message)
        return HTMLResponse(_oauth_result_page(False, "Microsoft-Anmeldung abgebrochen", message))
    if not code:
        oauth_controller.fail(
            state=state,
            provider="microsoft",
            error="Authorization code is missing",
        )
        return HTMLResponse(
            _oauth_result_page(
                False,
                "Microsoft-Anmeldung fehlgeschlagen",
                "Kein Autorisierungscode erhalten.",
            )
        )
    try:
        result = await oauth_controller.complete_microsoft(state=state, code=code)
        return HTMLResponse(
            _oauth_result_page(
                True,
                "Microsoft 365 ist verbunden",
                f"{result.get('email_address') or 'Das Postfach'} wurde sicher mit MAIL-AGENT verbunden.",
            )
        )
    except KeyError as exc:
        raise HTTPException(status_code=400, detail="OAuth session not found or expired") from exc
    except Exception as exc:
        return HTMLResponse(
            _oauth_result_page(False, "Microsoft-Anmeldung fehlgeschlagen", str(exc)),
            status_code=502,
        )


@app.get("/v1/oauth/microsoft/callback", response_class=HTMLResponse, include_in_schema=False)
async def microsoft_oauth_callback(
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> HTMLResponse:
    return await _finish_microsoft_oauth(
        state=state, code=code, error=error, error_description=error_description
    )


@app.get("/v1/system/update")
async def system_update_status() -> dict:
    info = await asyncio.to_thread(update_client.check, APP_VERSION)
    result = info.public()
    result.update(
        {
            "channel": "Preview",
            "automatic_checks": True,
            "check_interval_seconds": 21600,
        }
    )
    return result


def _terminate_for_update(delay: float = 1.5) -> None:
    time.sleep(delay)
    os._exit(0)


@app.post("/v1/system/update/install")
async def install_system_update() -> dict:
    if os.name != "nt":
        raise HTTPException(
            status_code=409,
            detail="Automatische Installation ist aktuell nur unter Windows verfügbar",
        )
    info = await asyncio.to_thread(update_client.check, APP_VERSION)
    if info.error:
        raise HTTPException(
            status_code=503,
            detail=f"Der automatische Update-Kanal ist momentan nicht erreichbar: {info.error}",
        )
    if not info.available:
        return {"installing": False, "up_to_date": True, "version": APP_VERSION}
    try:
        updates_dir = settings.data_dir.parent / "updates"
        updates_dir.mkdir(parents=True, exist_ok=True)
        installer = updates_dir / f"Mail-Agent-Setup-{info.latest_version}.exe"
        installer = await asyncio.to_thread(update_client.download, info, installer)
        helper = installer.with_name("apply-mail-agent-update.cmd")
        helper.write_text(
            "@echo off\\r\\n"
            "timeout /t 2 /nobreak >nul\\r\\n"
            f'"{installer}" /SP- /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS\\r\\n'
            'del "%~f0" >nul 2>&1\\r\\n',
            encoding="utf-8",
        )
        subprocess.Popen(
            [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(helper)],
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Update konnte nicht gestartet werden: {exc}") from exc
    threading.Thread(
        target=_terminate_for_update,
        daemon=True,
        name="mail-agent-update-exit",
    ).start()
    return {"installing": True, "latest_version": info.latest_version}


@app.post("/v1/providers/probe")
async def provider_probe(body: ProviderProbeRequest) -> dict:
    provider = providers[body.provider]
    health_result = await provider.health()
    models: list[str] = []
    if health_result.available:
        try:
            models = await provider.list_models()
        except Exception:
            models = []
    audit_log.append(
        "provider_probed",
        details={"provider": body.provider, "available": health_result.available},
    )
    return {
        "provider": body.provider,
        "available": health_result.available,
        "detail": health_result.detail,
        "models": models,
    }


@app.post("/v1/onboarding/complete")
async def complete_onboarding(body: OnboardingCompleteRequest) -> dict:
    if not identity_manager.exists():
        raise HTTPException(status_code=409, detail="Mandatory agent identity is missing")
    if not _configured_mailboxes():
        raise HTTPException(status_code=409, detail="At least one mailbox must be connected")

    identity = identity_manager.load()
    if identity.owner_id != body.profile.owner_id:
        raise HTTPException(status_code=409, detail="Profile owner does not match registered agent owner")

    provider = providers[body.provider]
    provider_health = await provider.health()
    if not provider_health.available:
        raise HTTPException(status_code=409, detail=provider_health.detail)

    state = state_store.read()
    state["onboarding_completed"] = True
    state["configuration"] = {
        "profile": body.profile.model_dump(mode="json"),
        "provider": body.provider,
        "model": body.model,
        "behavior": AgentBehaviorSettings().model_dump(mode="json"),
    }
    state_store.write(state)
    audit_log.append(
        "onboarding_completed",
        details={"agent_id": identity.agent_id, "provider": body.provider, "model": body.model},
    )
    return {"completed": True, "agent_id": identity.agent_id}


@app.get("/v1/providers")
async def list_providers() -> dict:
    result = {}
    for name, provider in providers.items():
        health_result = await provider.health()
        result[name] = {"available": health_result.available, "detail": health_result.detail}
    return result


def _configuration_or_409() -> tuple[dict, dict]:
    state = state_store.read()
    config = state.get("configuration")
    if not state.get("onboarding_completed") or not isinstance(config, dict):
        raise HTTPException(status_code=409, detail="Onboarding is not complete")
    return state, config


async def _settings_payload() -> dict:
    _state, config = _configuration_or_409()
    identity = asdict(identity_manager.load())
    catalog: dict[str, dict] = {}
    for name, provider in providers.items():
        health_result = await provider.health()
        models: list[str] = []
        if health_result.available:
            try:
                models = await provider.list_models()
            except Exception:
                models = []
        catalog[name] = {
            "available": health_result.available,
            "detail": health_result.detail,
            "models": models,
        }
    behavior = AgentBehaviorSettings.model_validate(config.get("behavior") or {})
    return {
        "identity": identity,
        "provider": config["provider"],
        "model": config["model"],
        "profile": config["profile"],
        "behavior": behavior.model_dump(mode="json"),
        "brain": agent_runtime.brain.public_status(),
        "providers": catalog,
        "invariants": {
            "agent_identity_required": True,
            "shadow_side_effects_forbidden": True,
            "shadow_uses_separate_processing_queue": True,
            "agent_signature_required": True,
            "agent_signature_removable": False,
            "send_requires_approval": True,
            "approved_send_executes_immediately": True,
            "mailbox_mutations_policy_gated": True,
            "draft_edits_are_resigned": True,
            "delete_means_trash": True,
        },
    }


@app.get("/v1/settings")
async def get_runtime_settings() -> dict:
    return await _settings_payload()


@app.put("/v1/settings/llm")
async def update_llm_settings(body: LLMSettingsRequest) -> dict:
    state, config = _configuration_or_409()
    provider = providers[body.provider]
    health_result = await provider.health()
    if not health_result.available:
        raise HTTPException(status_code=409, detail=health_result.detail)
    config["provider"] = body.provider
    config["model"] = body.model
    state["configuration"] = config
    state_store.write(state)
    audit_log.append(
        "llm_settings_changed",
        details={"provider": body.provider, "model": body.model},
    )
    return await _settings_payload()


@app.put("/v1/settings/behavior")
async def update_behavior_settings(body: BehaviorSettingsRequest) -> dict:
    state, config = _configuration_or_409()
    config["behavior"] = body.behavior.model_dump(mode="json")
    state["configuration"] = config
    state_store.write(state)
    audit_log.append("agent_behavior_changed", details=config["behavior"])
    return await _settings_payload()


@app.put("/v1/settings/profile")
async def update_profile_settings(body: ProfileSettingsRequest) -> dict:
    state, config = _configuration_or_409()
    identity = identity_manager.load()
    if body.profile.owner_id != identity.owner_id:
        raise HTTPException(status_code=409, detail="Profile owner does not match Agent-ID owner")
    profile = body.profile.model_copy(update={"agent_name": identity.agent_name})
    config["profile"] = profile.model_dump(mode="json")
    state["configuration"] = config
    state_store.write(state)
    audit_log.append(
        "agent_profile_changed",
        details={"agent_id": identity.agent_id, "autonomy": profile.autonomy_mode.value},
    )
    return await _settings_payload()


def _brain_payload() -> dict:
    _state, config = _configuration_or_409()
    identity = identity_manager.load()
    profile = AgentProfile.model_validate(config["profile"])
    agent_runtime.brain.ensure(identity, profile)
    snapshot = agent_runtime.brain.snapshot()
    mailboxes = []
    for mailbox in _configured_mailboxes():
        mailbox_id = str(mailbox.get("mailbox_id") or "")
        if not mailbox_id:
            continue
        status = agent_runtime.mailbox_status(mailbox_id)
        status["email_address"] = mailbox.get("email_address")
        if not status["enabled"] or not status["auto_analyze_new_mail"]:
            status["state"] = "paused"
        elif not status["schedule_active"]:
            status["state"] = "outside_schedule"
        elif status["pending"]:
            status["state"] = "work_pending"
        else:
            status["state"] = "idle"
        mailboxes.append(status)
    return {
        "status": agent_runtime.brain.public_status(),
        "soul": snapshot.soul,
        "memory": snapshot.memory,
        "learning_candidates": agent_runtime.brain.learning_candidates(),
        "recent_activity": agent_runtime.brain.recent_activity(30),
        "activity": agent_runtime.activity.recent_traces(25),
        "activity_summary": agent_runtime.activity.summary(),
        "mailboxes": mailboxes,
        "pending_total": sum(int(item.get("pending") or 0) for item in mailboxes),
    }


@app.get("/v1/agent/brain")
async def get_agent_brain() -> dict:
    return _brain_payload()


@app.get("/v1/agent/activity")
async def get_agent_activity(limit: int = 50, mailbox_id: str | None = None) -> dict:
    _configuration_or_409()
    return {
        "traces": agent_runtime.activity.recent_traces(limit, mailbox_id=mailbox_id),
        "summary": agent_runtime.activity.summary(mailbox_id=mailbox_id),
    }


def _public_shadow_job(job: dict) -> dict:
    return {
        key: value
        for key, value in job.items()
        if not key.startswith("_") and key != "report"
    }


def _shadow_payload() -> dict:
    _state, config = _configuration_or_409()
    behavior = AgentBehaviorSettings.model_validate(config.get("behavior") or {})
    mailboxes = []
    for mailbox in _configured_mailboxes():
        mailbox_id = str(mailbox.get("mailbox_id") or "")
        if not mailbox_id:
            continue
        status = agent_runtime.mailbox_status(mailbox_id)
        status["email_address"] = mailbox.get("email_address")
        mailboxes.append(status)
    jobs = sorted(
        (_public_shadow_job(item) for item in _shadow_jobs.values()),
        key=lambda item: str(item.get("started_at") or ""),
        reverse=True,
    )[:20]
    return {
        "execution_mode": behavior.execution_mode.value,
        "side_effects_allowed": False,
        "mailboxes": mailboxes,
        "jobs": jobs,
        "reports": agent_runtime.shadow_reports.recent_reports(10),
    }


async def _run_shadow_replay_job(job_id: str, mailbox_id: str, limit: int) -> None:
    job = _shadow_jobs[job_id]
    job["status"] = "running"

    def progress(done: int, total: int) -> None:
        job["completed"] = done
        job["total"] = total

    try:
        report = await agent_runtime.shadow_replay(
            mailbox_id,
            limit=limit,
            progress=progress,
        )
        job["status"] = "completed"
        job["completed"] = report.get("analyzed", 0) + report.get("errors", 0)
        job["total"] = len(report.get("results") or [])
        job["report"] = report
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)
        audit_log.append(
            "agent_shadow_replay_failed",
            details={"job_id": job_id, "mailbox_id": mailbox_id, "error": str(exc)},
        )


@app.get("/v1/agent/shadow")
async def get_shadow_status() -> dict:
    return _shadow_payload()


@app.get("/v1/agent/shadow/jobs/{job_id}")
async def get_shadow_job(job_id: str) -> dict:
    _configuration_or_409()
    job = _shadow_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Shadow replay job not found")
    return _public_shadow_job(job)


@app.post("/v1/agent/shadow/replay")
async def start_shadow_replay(body: ShadowReplayRequest) -> dict:
    _configuration_or_409()
    mailbox_id = body.mailbox_id
    if not mailbox_id:
        configured = _configured_mailboxes()
        if not configured:
            raise HTTPException(status_code=409, detail="No mailbox is configured")
        mailbox_id = configured[0]["mailbox_id"]
    try:
        _mailbox_by_id(mailbox_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown mailbox: {mailbox_id}") from exc
    active = next(
        (
            item
            for item in _shadow_jobs.values()
            if item.get("mailbox_id") == mailbox_id
            and item.get("status") in {"queued", "running"}
        ),
        None,
    )
    if active is not None:
        raise HTTPException(status_code=409, detail="A Shadow replay is already running for this mailbox")
    job_id = "shadow_job_" + uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "mailbox_id": mailbox_id,
        "status": "queued",
        "requested": body.limit,
        "completed": 0,
        "total": body.limit,
        "started_at": datetime.now(UTC).isoformat(),
        "side_effects": 0,
    }
    _shadow_jobs[job_id] = job
    job["_task"] = asyncio.create_task(
        _run_shadow_replay_job(job_id, mailbox_id, body.limit),
        name=f"mail-agent-shadow-{job_id[-8:]}",
    )
    audit_log.append(
        "agent_shadow_replay_started",
        details={"job_id": job_id, "mailbox_id": mailbox_id, "limit": body.limit},
    )
    return _public_shadow_job(job)


@app.post("/v1/agent/rules/simulate")
async def simulate_agent_rule(body: RuleSimulationRequest) -> dict:
    _configuration_or_409()
    return agent_runtime.simulate_rule(
        sender=body.sender,
        action=body.action,
        confidence=body.confidence,
        priority=body.priority,
        category=body.category,
        needs_reply=body.needs_reply,
    )


@app.put("/v1/agent/brain")
async def update_agent_brain(body: BrainUpdateRequest) -> dict:
    if body.soul is None and body.memory is None:
        raise HTTPException(status_code=400, detail="SOUL.md or MEMORY.md must be supplied")
    _configuration_or_409()
    try:
        agent_runtime.brain.update_owner_memory(soul=body.soul, memory=body.memory)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_log.append(
        "agent_brain_owner_memory_changed",
        actor=body.actor,
        details={"soul_changed": body.soul is not None, "memory_changed": body.memory is not None},
    )
    return _brain_payload()


@app.post("/v1/agent/brain/learning/{candidate_id}/accept")
async def accept_agent_learning(candidate_id: str, body: LearningDecisionRequest) -> dict:
    _configuration_or_409()
    try:
        candidate = agent_runtime.brain.accept_learning(candidate_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Learning candidate not found") from exc
    audit_log.append(
        "agent_learning_accepted",
        actor=body.actor,
        details={"candidate_id": candidate_id, "title": candidate.get("title")},
    )
    return _brain_payload()


@app.post("/v1/agent/brain/learning/{candidate_id}/reject")
async def reject_agent_learning(candidate_id: str, body: LearningDecisionRequest) -> dict:
    _configuration_or_409()
    try:
        candidate = agent_runtime.brain.reject_learning(candidate_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Learning candidate not found") from exc
    audit_log.append(
        "agent_learning_rejected",
        actor=body.actor,
        details={"candidate_id": candidate_id, "title": candidate.get("title")},
    )
    return _brain_payload()


@app.post("/v1/providers/codex/login")
async def start_codex_chatgpt_login() -> dict:
    provider = providers["codex"]
    if not isinstance(provider, CodexCliProvider):
        raise HTTPException(status_code=500, detail="Codex provider is unavailable")
    try:
        detail = provider.start_chatgpt_login()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit_log.append("chatgpt_login_started", details={"provider": "codex"})
    return {"started": True, "detail": detail}


@app.post("/v1/agent/run")
async def run_agent_cycle(body: AgentRunRequest) -> dict:
    _configuration_or_409()
    mailbox_ids = (
        [body.mailbox_id]
        if body.mailbox_id
        else [item["mailbox_id"] for item in _configured_mailboxes()]
    )
    if not mailbox_ids:
        raise HTTPException(status_code=409, detail="No mailbox is configured")
    results = []
    for mailbox_id in mailbox_ids:
        try:
            _mailbox_by_id(mailbox_id)
            results.append(await agent_runtime.run_mailbox(mailbox_id, force=body.force))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown mailbox: {mailbox_id}") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"results": results}

@app.get("/v1/audit")
async def recent_audit(limit: int = 100) -> dict:
    return {"events": audit_log.read_recent(limit)}



@app.get("/v1/attention")
async def list_attention(mailbox_id: str | None = None, limit: int = 100) -> dict:
    _state, config = _configuration_or_409()
    limit = max(1, min(int(limit), 500))
    items = list(mail_store.list_attention(mailbox_id, limit))
    seen_keys = {
        (str(item.get("mailbox_id") or ""), str(item.get("remote_id") or item.get("internet_message_id") or item.get("uid") or ""))
        for item in items
    }
    behavior = AgentBehaviorSettings.model_validate(config.get("behavior") or {})
    if behavior.execution_mode == AgentExecutionMode.SHADOW:
        reports = agent_runtime.shadow_reports.recent_reports(20, mailbox_id=mailbox_id)
        for report in reports:
            report_mailbox = str(report.get("mailbox_id") or "")
            for result in report.get("results", []) or []:
                message_id = str(result.get("message_id") or "")
                key = (report_mailbox, message_id)
                if not report_mailbox or not message_id or key in seen_keys:
                    continue
                priority = str(result.get("priority") or "normal")
                category = str(result.get("category") or "other")
                needs_reply = result.get("needs_reply") is True
                if not (needs_reply or priority in {"high", "urgent"} or category == "security"):
                    continue
                if mail_store.attention_is_resolved(report_mailbox, message_id):
                    seen_keys.add(key)
                    continue
                source = mail_store.get_message(report_mailbox, message_id)
                if source is None:
                    continue
                item = dict(source)
                item.update(
                    {
                        "agent_priority": priority,
                        "agent_category": category,
                        "agent_summary": str(result.get("reason") or "Shadow-Analyse: Aufmerksamkeit empfohlen."),
                        "needs_reply": needs_reply,
                        "analyzed_at": report.get("finished_at"),
                        "attention_status": "open",
                        "attention_source": "shadow",
                    }
                )
                items.append(item)
                seen_keys.add(key)
                if len(items) >= limit:
                    break
            if len(items) >= limit:
                break
    rank = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    items.sort(
        key=lambda item: (
            rank.get(str(item.get("agent_priority") or "normal"), 4),
            0 if item.get("needs_reply") is True else 1,
            str(item.get("analyzed_at") or item.get("sent_at") or ""),
        )
    )
    return {"attention": items[:limit]}


@app.post("/v1/attention/resolve")
async def resolve_attention(body: AttentionResolveRequest) -> dict:
    _configuration_or_409()
    try:
        item = mail_store.resolve_attention(
            body.mailbox_id,
            body.message_id,
            owner_note=body.owner_note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Attention message not found") from exc
    audit_log.append(
        "owner_attention_resolved",
        actor=body.actor,
        details={"mailbox_id": body.mailbox_id, "message_id": body.message_id},
    )
    return item



def _record_outbound_conversation(approval: dict) -> None:
    proposal = dict(approval.get("proposal") or {})
    if proposal.get("action") != MailActionType.SEND_REPLY.value:
        return
    thread_id = str(proposal.get("thread_id") or proposal.get("message_id") or "")
    if not thread_id:
        return
    _state, config = _configuration_or_409()
    behavior = AgentBehaviorSettings.model_validate(config.get("behavior") or {})
    conversation_store.mark_outbound_sent(
        mailbox_id=str(proposal.get("mailbox_id") or ""),
        thread_id=thread_id,
        source_message_id=proposal.get("message_id"),
        recipient=str(proposal.get("recipient") or ""),
        subject=str(proposal.get("subject") or ""),
        awaiting_reply_days=behavior.follow_up_awaiting_reply_days,
    )



@app.get("/v1/conversations")
async def list_conversations(mailbox_id: str | None = None, status: str | None = None, limit: int = 200, include_snoozed: bool = False) -> dict:
    _state, config = _configuration_or_409()
    behavior = AgentBehaviorSettings.model_validate(config.get("behavior") or {})
    allowed = {None, "to_reply", "awaiting_reply", "fyi", "actioned"}
    if status not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported conversation status")
    return {
        "threads": conversation_store.list_threads(mailbox_id=mailbox_id, status=status, limit=limit, include_snoozed=include_snoozed),
        "due": conversation_store.due_followups(mailbox_id, limit=100) if mailbox_id else [],
        "patterns": conversation_store.list_pattern_suggestions(
            mailbox_id=mailbox_id,
            min_samples=behavior.sender_pattern_min_samples,
            confidence_threshold=behavior.sender_pattern_confidence,
        ),
    }


@app.post("/v1/conversations/snooze")
async def snooze_conversation(body: ConversationSnoozeRequest) -> dict:
    _configuration_or_409()
    try:
        item = conversation_store.snooze(body.mailbox_id, body.thread_id, body.until)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_log.append("conversation_snoozed", actor=body.actor, details={"mailbox_id": body.mailbox_id, "thread_id": body.thread_id, "until": body.until})
    return item


@app.post("/v1/sender-patterns/accept")
async def accept_sender_pattern(body: SenderPatternDecisionRequest) -> dict:
    state, config = _configuration_or_409()
    behavior = AgentBehaviorSettings.model_validate(config.get("behavior") or {})
    normalized = body.sender.strip().lower()
    if not any(rule.pattern == normalized for rule in behavior.rules):
        behavior.rules.append(AgentRule(pattern=normalized, mode=RuleMode.NORMAL, category=body.category))
    config["behavior"] = behavior.model_dump(mode="json")
    state["configuration"] = config
    state_store.write(state)
    conversation_store.decide_pattern(body.mailbox_id, normalized, body.category.value, status="accepted")
    audit_log.append("sender_pattern_accepted", actor=body.actor, details={"mailbox_id": body.mailbox_id, "sender": normalized, "category": body.category.value})
    return await _settings_payload()


@app.post("/v1/sender-patterns/reject")
async def reject_sender_pattern(body: SenderPatternDecisionRequest) -> dict:
    _configuration_or_409()
    conversation_store.decide_pattern(body.mailbox_id, body.sender, body.category.value, status="rejected")
    audit_log.append("sender_pattern_rejected", actor=body.actor, details={"mailbox_id": body.mailbox_id, "sender": body.sender, "category": body.category.value})
    return {"status": "rejected"}


@app.post("/v1/actions/undo/{token}")
async def undo_mailbox_action(token: str, body: UndoActionRequest) -> dict:
    _configuration_or_409()
    try:
        result = await undo_service.undo(token)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Undo action not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit_log.append("mailbox_action_undone", actor=body.actor, details=result)
    return result


@app.get("/v1/drafts")
async def list_drafts(mailbox_id: str | None = None, limit: int = 100) -> dict:
    return {
        "drafts": [
            draft_service.public_draft(item)
            for item in mail_store.list_drafts(mailbox_id, limit)
        ]
    }


@app.get("/v1/drafts/{draft_id}")
async def get_draft(draft_id: str) -> dict:
    try:
        return draft_service.public_draft(mail_store.get_draft(draft_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Draft not found") from exc


@app.put("/v1/drafts/{draft_id}")
async def update_draft(draft_id: str, body: DraftUpdateRequest) -> dict:
    try:
        return draft_service.edit(
            draft_id,
            subject=body.subject,
            body=body.body,
            recipient=body.recipient,
            actor=body.actor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Draft not found") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/drafts/{draft_id}/submit")
async def submit_draft(draft_id: str, body: DraftSubmitRequest) -> dict:
    try:
        return draft_service.submit_for_approval(draft_id, actor=body.actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Draft not found") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@app.get("/v1/approvals")
async def list_approvals(status: str = "pending", limit: int = 100) -> dict:
    if status == "attention":
        pending = mail_store.list_approvals("pending", limit)
        recoverable = [
            item
            for item in mail_store.list_approvals("approved", limit)
            if item.get("execution_status") in {"failed", "uncertain", "ready"}
        ]
        combined = sorted(
            pending + recoverable,
            key=lambda item: item.get("created_at") or "",
            reverse=True,
        )
        return {"approvals": combined[:limit]}
    if status not in {"pending", "approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Unsupported approval status")
    return {"approvals": mail_store.list_approvals(status, limit)}

@app.post("/v1/approvals/{approval_id}/approve")
async def approve_action(approval_id: str, body: ApprovalDecisionRequest) -> dict:
    try:
        approval = mail_store.decide_approval(approval_id, decision="approved", actor=body.actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Approval not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit_log.append("approval_approved", actor=body.actor, details={"approval_id": approval_id, "action": approval["action"]})
    if approval.get("execution_status") == "ready":
        try:
            approval = await action_executor.execute_approval(approval_id)
            _record_outbound_conversation(approval)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    return approval


@app.post("/v1/approvals/{approval_id}/execute")
async def execute_approved_action(approval_id: str) -> dict:
    try:
        approval = await action_executor.execute_approval(approval_id)
        _record_outbound_conversation(approval)
        return approval
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Approval not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@app.post("/v1/approvals/{approval_id}/reject")
async def reject_action(approval_id: str, body: ApprovalDecisionRequest) -> dict:
    try:
        approval = mail_store.decide_approval(approval_id, decision="rejected", actor=body.actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Approval not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit_log.append(
        "approval_rejected",
        actor=body.actor,
        details={"approval_id": approval_id, "action": approval["action"]},
    )
    return approval


@app.post("/v1/agent/analyze")
async def analyze_mail(body: AgentAnalyzeRequest) -> dict:
    try:
        return await agent_runtime.analyze_message(body.message, create_artifacts=True)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Model analysis failed: {exc}") from exc


def _oauth_result_page(success: bool, title: str, message: str) -> str:
    accent = "#4ade80" if success else "#fb7185"
    safe_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe_message = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{safe_title}</title><style>body{{margin:0;background:#08111f;color:#edf3ff;font-family:Segoe UI,system-ui,sans-serif;display:grid;place-items:center;min-height:100vh}}main{{width:min(520px,calc(100% - 40px));background:#0d1726;border:1px solid #20304a;border-radius:22px;padding:34px;box-shadow:0 30px 80px #0008}}i{{display:block;width:14px;height:14px;border-radius:50%;background:{accent};box-shadow:0 0 28px {accent};margin-bottom:22px}}h1{{font-size:25px;margin:0 0 10px}}p{{color:#91a4c2;line-height:1.55;margin:0}}small{{display:block;color:#64748b;margin-top:24px}}</style></head><body><main><i></i><h1>{safe_title}</h1><p>{safe_message}</p><small>Dieses Fenster kann geschlossen werden. MAIL-AGENT übernimmt automatisch.</small></main><script>try{{window.opener&&window.opener.postMessage({{type:'mail-agent-oauth',provider:'google',success:{str(success).lower()}}},location.origin)}}catch(e){{}}setTimeout(()=>window.close(),1400)</script></body></html>"""


web_dir = Path(os.getenv("MAIL_AGENT_WEB_DIR", str(Path(__file__).resolve().parents[2] / "web")))
if web_dir.exists():
    @app.get("/", include_in_schema=False)
    async def web_root(
        state: str | None = None,
        code: str | None = None,
        error: str | None = None,
        error_description: str | None = None,
    ):
        if state or code or error:
            return await _finish_google_oauth(
                state=state, code=code, error=error, error_description=error_description
            )
        return FileResponse(web_dir / "index.html")

    app.mount("/assets", StaticFiles(directory=web_dir), name="assets")
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
