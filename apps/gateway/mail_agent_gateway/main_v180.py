from __future__ import annotations

from typing import Any

from . import main_v173 as previous
from .schemas import OnboardingResetRequest

APP_VERSION = "0.18.0"
base = previous.base
owner_profile_store = previous.owner_profile_store

previous.APP_VERSION = APP_VERSION
previous.previous.APP_VERSION = APP_VERSION
previous.previous.previous.APP_VERSION = APP_VERSION
previous.previous.previous.previous.APP_VERSION = APP_VERSION
previous.previous.previous.previous.previous.APP_VERSION = APP_VERSION
base.APP_VERSION = APP_VERSION
base.app.version = APP_VERSION


@base.app.post("/v1/onboarding/reset")
async def reset_onboarding(request: OnboardingResetRequest) -> dict[str, Any]:
    """Restart guided setup while preserving the installation and operational history.

    Identity, connected mailboxes, encrypted credentials, mail history, approvals and audit records
    stay intact. The active configuration and all optional owner-learning data are removed, so the
    agent cannot continue autonomous work until onboarding is completed again.
    """

    state = base.state_store.read()
    state["onboarding_completed"] = False
    state.pop("configuration", None)
    base.state_store.write(state)
    owner_profile_store.reset()
    base.agent_runtime.brain.reset_owner_learning()
    base.audit_log.append(
        "onboarding_reset",
        actor=request.actor,
        details={
            "identity_preserved": base.identity_manager.exists(),
            "mailboxes_preserved": len(base._configured_mailboxes()),
            "operational_history_preserved": True,
            "owner_learning_deleted": True,
        },
    )
    return {
        "completed": False,
        "restart_onboarding": True,
        "identity_preserved": base.identity_manager.exists(),
        "mailboxes_preserved": len(base._configured_mailboxes()),
        "operational_history_preserved": True,
        "owner_learning_deleted": True,
    }


# The static web mount is a catch-all route. The reset API must remain reachable before it.
previous.previous.previous._move_catch_all_web_mount_to_end()
app = base.app
