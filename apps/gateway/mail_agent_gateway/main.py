from __future__ import annotations

import asyncio
import hashlib
import os
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from mail_agent_core.agent import MailAgent
from mail_agent_core.identity import IdentityManager
from mail_agent_core.policy import PolicyEngine
from mail_agent_core.providers import CodexCliProvider, OllamaProvider
from mail_agent_imap import ImapMailbox, MailboxConfig, SmtpSender

from .audit import AuditLog
from .key_store import create_master_key_store
from .mail_store import MailStore
from .registry_client import RegistryClient
from .schemas import (
    AgentAnalyzeRequest,
    ApprovalDecisionRequest,
    IdentitySetupRequest,
    MailboxProbeRequest,
    OnboardingCompleteRequest,
    ProviderProbeRequest,
    RegistrationResponse,
    SyncRunRequest,
)
from .settings import settings
from .state import JsonStateStore
from .sync import MailboxRuntimeConfig, MailSyncService
from .vault import CredentialVault

settings.data_dir.mkdir(parents=True, exist_ok=True)
identity_manager = IdentityManager(settings.data_dir / "identity")
state_store = JsonStateStore(settings.data_dir / "state.json")
audit_log = AuditLog(settings.data_dir / "audit.jsonl")
mail_store = MailStore(settings.data_dir / "mail.db")
vault = CredentialVault(
    settings.data_dir / "secrets.vault",
    master_key_store=create_master_key_store(settings.data_dir),
)
policy_engine = PolicyEngine()
mail_agent = MailAgent(policy_engine)
sync_service = MailSyncService(mail_store, vault)
providers = {
    "ollama": OllamaProvider(settings.ollama_base_url),
    "codex": CodexCliProvider(settings.codex_binary),
}
_sync_stop = asyncio.Event()


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


def _runtime_mailbox(mailbox_id: str) -> MailboxRuntimeConfig:
    mailbox = next((item for item in _configured_mailboxes() if item.get("mailbox_id") == mailbox_id), None)
    if mailbox is None:
        raise KeyError(mailbox_id)
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


async def _sync_once(config: MailboxRuntimeConfig, *, limit: int = 100) -> dict:
    try:
        result = await sync_service.sync(config, limit=limit)
        audit_log.append("mailbox_synced", details=result)
        return result
    except Exception as exc:
        audit_log.append(
            "mailbox_sync_failed",
            details={"mailbox_id": config.mailbox_id, "error": str(exc)},
        )
        raise


async def _sync_loop() -> None:
    while not _sync_stop.is_set():
        for mailbox in _configured_mailboxes():
            mailbox_id = mailbox.get("mailbox_id")
            if not mailbox_id:
                continue
            try:
                await _sync_once(_runtime_mailbox(mailbox_id))
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
    _sync_stop.clear()
    if settings.auto_sync_enabled:
        task = asyncio.create_task(_sync_loop(), name="mail-agent-imap-sync")
    try:
        yield
    finally:
        _sync_stop.set()
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="MAIL-AGENT Gateway", version="0.2.1", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "mail-agent-gateway", "version": "0.2.1"}


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
            results.append(await _sync_once(_runtime_mailbox(mailbox_id), limit=body.limit))
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


@app.get("/v1/audit")
async def recent_audit(limit: int = 100) -> dict:
    return {"events": audit_log.read_recent(limit)}


@app.get("/v1/drafts")
async def list_drafts(mailbox_id: str | None = None, limit: int = 100) -> dict:
    return {"drafts": mail_store.list_drafts(mailbox_id, limit)}


@app.get("/v1/approvals")
async def list_approvals(status: str = "pending", limit: int = 100) -> dict:
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
    audit_log.append(
        "approval_approved",
        actor=body.actor,
        details={"approval_id": approval_id, "action": approval["action"]},
    )
    return approval


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
    state = state_store.read()
    config = state.get("configuration")
    if not state.get("onboarding_completed") or not config:
        raise HTTPException(status_code=409, detail="Onboarding is not complete")
    provider_name = config["provider"]
    provider = providers.get(provider_name)
    if provider is None:
        raise HTTPException(status_code=409, detail="Configured provider is unavailable")
    from mail_agent_core.models import AgentProfile

    profile = AgentProfile.model_validate(config["profile"])
    try:
        analysis = await mail_agent.analyze(
            profile=profile,
            provider=provider,
            model=config["model"],
            message=body.message,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Model analysis failed: {exc}") from exc

    approval = None
    if analysis.policy.allowed and analysis.policy.requires_approval:
        approval = mail_store.enqueue_approval(analysis.proposal, analysis.policy)

    draft = None
    if analysis.policy.allowed and analysis.proposal.body and analysis.proposal.action.value in {"create_draft", "send_reply"}:
        draft = mail_store.create_draft(
            analysis.proposal,
            approval_id=approval["approval_id"] if approval else None,
        )

    audit_log.append(
        "mail_analyzed",
        details={
            "mailbox_id": body.message.mailbox_id,
            "message_id": body.message.message_id,
            "proposed_action": analysis.proposal.action.value,
            "risk": analysis.policy.risk,
            "requires_approval": analysis.policy.requires_approval,
            "approval_id": approval["approval_id"] if approval else None,
            "draft_id": draft["draft_id"] if draft else None,
        },
    )
    payload = analysis.model_dump(mode="json")
    payload["approval"] = approval
    payload["draft"] = draft
    return payload


web_dir = Path(os.getenv("MAIL_AGENT_WEB_DIR", str(Path(__file__).resolve().parents[2] / "web")))
if web_dir.exists():
    app.mount("/assets", StaticFiles(directory=web_dir), name="assets")
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
