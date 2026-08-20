from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from mail_agent_core.models import MailActionProposal

from . import cloud_sync as cloud_sync_module
from . import main as base
from . import sync as sync_module
from .adaptive_intelligence import (
    ModelRoutingRequest,
    OwnerProfileConsentRequest,
    OwnerProfilePreviewRequest,
    OwnerProfileReview,
    extract_rfc822_signals,
)
from .codex_usage_reader import CodexUsageReader
from .decision_provenance import normalize_decision_path
from .oauth_runtime import current_google_access_token, current_microsoft_access_token
from .owner_profile_learning import OwnerProfileService
from .release_audit_fixes import (
    ReleaseAdaptiveMailAgent,
    ReleaseEfficiencySignalStore,
    ReleaseModelRouter,
    ReleaseOwnerProfileStore,
    install_release_runtime_fixes,
)

APP_VERSION = "0.16.1"

# The existing composition root remains authoritative for security-sensitive services. 0.16.x adds
# a narrow adaptive layer and swaps only the MailAgent reasoning implementation. Policy, identity,
# approval, executor, mailbox and queue ownership remain untouched.
base.APP_VERSION = APP_VERSION
base.app.version = APP_VERSION

signal_store = ReleaseEfficiencySignalStore(base.settings.data_dir / "adaptive-intelligence.db")
owner_profile_store = ReleaseOwnerProfileStore(base.settings.data_dir / "owner-profile.json")
model_router = ReleaseModelRouter(base.state_store, base.providers)
adaptive_mail_agent = ReleaseAdaptiveMailAgent(
    policy_engine=base.policy_engine,
    state_store=base.state_store,
    providers=base.providers,
    conversation_store=base.conversation_store,
    signal_store=signal_store,
    owner_profile=owner_profile_store,
)
base.mail_agent = adaptive_mail_agent
base.agent_runtime.mail_agent = adaptive_mail_agent
install_release_runtime_fixes(base.agent_runtime)


def _install_decision_path_provenance() -> None:
    """Correct the legacy `llm` explainability slot without changing runtime authority.

    AgentRuntime owns the policy/artifact flow and remains untouched. The adaptive MailAgent marks
    the real decision origin in proposal metadata. We normalize only the returned and persisted
    decision-path presentation so deterministic skips cannot be reported as an LLM call.
    """

    if getattr(base.agent_runtime, "_adaptive_decision_path_installed", False):
        return

    original_record_analysis = base.conversation_store.record_analysis

    def record_analysis_with_provenance(**kwargs: Any):
        proposal = kwargs.get("proposal")
        if isinstance(proposal, MailActionProposal):
            kwargs["decision_path"] = normalize_decision_path(
                kwargs.get("decision_path"),
                proposal,
            )
        return original_record_analysis(**kwargs)

    base.conversation_store.record_analysis = record_analysis_with_provenance  # type: ignore[method-assign]

    original_analyze_message = base.agent_runtime.analyze_message

    async def analyze_message_with_provenance(message: Any, *args: Any, **kwargs: Any):
        payload = await original_analyze_message(message, *args, **kwargs)
        if not isinstance(payload, dict):
            return payload
        try:
            proposal = MailActionProposal.model_validate(payload.get("proposal") or {})
        except Exception:
            return payload
        normalized = normalize_decision_path(payload.get("decision_path"), proposal)
        payload["decision_path"] = normalized
        conversation = payload.get("conversation")
        if isinstance(conversation, dict):
            conversation["decision_path"] = normalized
        return payload

    base.agent_runtime.analyze_message = analyze_message_with_provenance  # type: ignore[method-assign]
    base.agent_runtime._adaptive_decision_path_installed = True  # type: ignore[attr-defined]


_install_decision_path_provenance()

owner_profile_service = OwnerProfileService(
    store=owner_profile_store,
    router=model_router,
    providers=base.providers,
    mailbox_supplier=base._configured_mailboxes,
    vault=base.vault,
    settings=base.settings,
    google_token_supplier=current_google_access_token,
    microsoft_token_supplier=current_microsoft_access_token,
    audit_log=base.audit_log,
    usage_store=signal_store,
)


def _install_rfc822_signal_capture() -> None:
    """Capture privacy-minimized routing headers during existing sync paths.

    This is intentionally a parser wrapper rather than a second mailbox reader. It never persists
    mail text; only the boolean/enumerated signals accepted by AdaptiveSignalStore are written.
    """

    if getattr(sync_module.parse_message, "_mail_agent_adaptive", False):
        return
    original_parse = sync_module.parse_message

    def instrumented_parse(mailbox_id: str, uid: int, raw: bytes, *, seen: bool):
        stored = original_parse(mailbox_id, uid, raw, seen=seen)
        message_id = str(stored.internet_message_id or stored.uid)
        try:
            signal_store.record_signals(mailbox_id, message_id, extract_rfc822_signals(raw))
        except Exception:
            pass
        return stored

    instrumented_parse._mail_agent_adaptive = True  # type: ignore[attr-defined]
    sync_module.parse_message = instrumented_parse
    cloud_sync_module.parse_message = instrumented_parse

    original_gmail = cloud_sync_module._gmail_message
    if not getattr(original_gmail, "_mail_agent_adaptive", False):
        def instrumented_gmail(mailbox_id: str, remote_id: str, payload: dict[str, Any]):
            stored = original_gmail(mailbox_id, remote_id, payload)
            try:
                raw = payload.get("raw_bytes")
                if isinstance(raw, bytes):
                    signal_store.record_signals(mailbox_id, remote_id, extract_rfc822_signals(raw))
            except Exception:
                pass
            return stored

        instrumented_gmail._mail_agent_adaptive = True  # type: ignore[attr-defined]
        cloud_sync_module._gmail_message = instrumented_gmail


_install_rfc822_signal_capture()


@base.app.get("/v1/adaptive/status")
async def adaptive_status() -> dict[str, Any]:
    configuration = base.state_store.read().get("configuration") or {}
    return {
        "version": APP_VERSION,
        "owner_profile": owner_profile_store.public(),
        "model_routing": model_router.settings().model_dump(mode="json"),
        "configured_provider": configuration.get("provider"),
        "configured_model": configuration.get("model"),
        "privacy": {
            "usage_contains_mail_content": False,
            "owner_profile_writes_memory": False,
            "foreign_mail_can_activate_profile": False,
        },
    }


@base.app.get("/v1/owner-profile")
async def owner_profile_status() -> dict[str, Any]:
    return owner_profile_store.public()


@base.app.post("/v1/owner-profile/consent")
async def owner_profile_consent(request: OwnerProfileConsentRequest) -> dict[str, Any]:
    result = owner_profile_store.set_consent(request.enabled)
    base.audit_log.append(
        "owner_profile_consent_changed",
        actor=request.actor,
        details={"enabled": request.enabled},
    )
    return result


@base.app.post("/v1/owner-profile/preview")
async def owner_profile_preview(request: OwnerProfilePreviewRequest) -> dict[str, Any]:
    try:
        return await owner_profile_service.preview(mailbox_id=request.mailbox_id, limit=request.limit)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Owner-Profil-Analyse fehlgeschlagen: {exc}") from exc


@base.app.post("/v1/owner-profile/activate")
async def owner_profile_activate(request: OwnerProfileReview) -> dict[str, Any]:
    try:
        result = owner_profile_store.activate(request)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    base.audit_log.append(
        "owner_profile_activated",
        details={
            "profile_version": result.get("profile_version"),
            "candidate_count": len(result.get("active") or []),
        },
    )
    return result


@base.app.delete("/v1/owner-profile")
async def owner_profile_delete(actor: str = "local-user") -> dict[str, Any]:
    result = owner_profile_store.reset()
    base.audit_log.append("owner_profile_deleted", actor=actor, details={})
    return result


@base.app.get("/v1/settings/model-routing")
async def model_routing_status() -> dict[str, Any]:
    return model_router.settings().model_dump(mode="json")


@base.app.put("/v1/settings/model-routing")
async def model_routing_update(request: ModelRoutingRequest) -> dict[str, Any]:
    routing = request.routing
    if routing.mode == "automatic":
        current = model_router.settings()
        routing = routing.model_copy(
            update={
                role: getattr(routing, role) or getattr(current, role)
                for role in ("classification", "normal", "complex", "draft", "owner_profile")
            }
        )
    try:
        model_router.save(routing)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    base.audit_log.append(
        "model_routing_updated",
        actor=request.actor,
        details={"mode": routing.mode},
    )
    return routing.model_dump(mode="json")


@base.app.get("/v1/usage")
async def usage_summary(days: int = 7) -> dict[str, Any]:
    days = max(1, min(int(days), 3650))
    configuration = base.state_store.read().get("configuration") or {}
    codex_provider = base.providers.get("codex")
    if codex_provider is not None:
        codex = await CodexUsageReader(codex_provider).snapshot()
    else:
        codex = {
            "available": False,
            "source": "unknown",
            "detail": "Codex provider unavailable",
            "rate_limits": None,
            "account_usage": None,
        }
    local = signal_store.summary(days=days)
    today = signal_store.summary(days=1)
    # `summary(days=1)` is a rolling 24h window. Expose the already-computed UTC calendar-day
    # counters under the generic fields used by the UI so "Heute" cannot include yesterday.
    today["llm_calls"] = today.get("today_llm_calls", 0)
    today["decision_events"] = today.get("today_events", 0)
    return {
        "configured_provider": configuration.get("provider"),
        "configured_model": configuration.get("model"),
        "model_routing": model_router.settings().model_dump(mode="json"),
        "local": local,
        "today": today,
        "codex": codex,
        "semantics": {
            "provider_reported": "Vom Provider/CLI gemeldeter Wert",
            "estimated": "Lokal aus Textlänge geschätzter Tokenwert",
            "mixed": "Enthält sowohl Provider-Messungen als auch lokale Schätzungen",
            "unknown": "Nicht zuverlässig verfügbar; MAIL-AGENT erfindet keinen Wert",
        },
    }


@base.app.get("/v1/usage/privacy")
async def usage_privacy_contract() -> dict[str, Any]:
    return {
        "tables": signal_store.assert_privacy_contract(),
        "forbidden_usage_fields": [
            "body",
            "subject",
            "sender",
            "recipient",
            "prompt",
            "content",
            "secret",
            "credential",
        ],
    }


def _move_catch_all_web_mount_to_end() -> None:
    """Keep APIs registered after the legacy composition root reachable.

    The base gateway mounts StaticFiles at `/` after all legacy routes. 0.16.x routes are additive
    and are therefore registered later. Starlette matches routes in order, so the catch-all web
    mount must stay last or it intercepts `/v1/adaptive/*` with a static 404.
    """

    routes = base.app.router.routes
    for index, route in enumerate(routes):
        if getattr(route, "name", None) != "web":
            continue
        if getattr(route, "path", None) not in {"", "/"}:
            continue
        routes.append(routes.pop(index))
        break


_move_catch_all_web_mount_to_end()

# Export the augmented application for uvicorn/PyInstaller.
app = base.app
