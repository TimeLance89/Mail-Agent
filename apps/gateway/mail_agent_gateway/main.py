from __future__ import annotations

from dataclasses import asdict
import asyncio

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from mail_agent_core.agent import MailAgent
from mail_agent_core.identity import IdentityManager
from mail_agent_core.policy import PolicyEngine
from mail_agent_core.providers import CodexCliProvider, OllamaProvider
from mail_agent_imap import ImapMailbox, MailboxConfig, SmtpSender

from .audit import AuditLog
from .registry_client import RegistryClient
from .schemas import AgentAnalyzeRequest, IdentitySetupRequest, MailboxProbeRequest, OnboardingCompleteRequest, ProviderProbeRequest, RegistrationResponse
from .settings import settings
from .state import JsonStateStore

app = FastAPI(title="MAIL-AGENT Gateway", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings.data_dir.mkdir(parents=True, exist_ok=True)
identity_manager = IdentityManager(settings.data_dir / "identity")
state_store = JsonStateStore(settings.data_dir / "state.json")
audit_log = AuditLog(settings.data_dir / "audit.jsonl")
policy_engine = PolicyEngine()
mail_agent = MailAgent(policy_engine)
providers = {
    "ollama": OllamaProvider(settings.ollama_base_url),
    "codex": CodexCliProvider(settings.codex_binary),
}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "mail-agent-gateway", "version": "0.1.0"}


@app.get("/v1/onboarding/status")
async def onboarding_status() -> dict:
    state = state_store.read()
    identity = asdict(identity_manager.load()) if identity_manager.exists() else None
    return {
        "identity_created": identity is not None,
        "identity": identity,
        "completed": bool(state.get("onboarding_completed")),
        "configuration": state.get("configuration"),
        "mailbox": state.get("mailbox"),
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
        # Registration is mandatory: onboarding cannot silently continue offline.
        raise HTTPException(status_code=503, detail=f"Agent registry unavailable: {exc}") from exc

    audit_log.append(
        "agent_identity_registered",
        details={"agent_id": identity.agent_id, "owner_id": identity.owner_id, "fingerprint": identity.fingerprint},
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

    # Never persist the password from the probe request. Secret-vault storage is a later module.
    state = state_store.read()
    state["mailbox"] = {
        "email_address": body.email_address,
        "username": body.username,
        "imap_host": body.imap_host,
        "imap_port": body.imap_port,
        "smtp_host": body.smtp_host,
        "smtp_port": body.smtp_port,
        "credential_state": "validated-not-persisted",
    }
    state_store.write(state)
    audit_log.append("mailbox_connection_validated", details={"email_address": body.email_address})
    return {"connected": True, "email_address": body.email_address, "secrets_persisted": False}


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
    audit_log.append(
        "mail_analyzed",
        details={
            "mailbox_id": body.message.mailbox_id,
            "message_id": body.message.message_id,
            "proposed_action": analysis.proposal.action.value,
            "risk": analysis.policy.risk,
            "requires_approval": analysis.policy.requires_approval,
        },
    )
    return analysis.model_dump(mode="json")


web_dir = __import__("pathlib").Path(__file__).resolve().parents[2] / "web"
if web_dir.exists():
    app.mount("/assets", StaticFiles(directory=web_dir), name="assets")
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
