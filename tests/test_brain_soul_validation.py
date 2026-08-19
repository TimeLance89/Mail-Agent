import pytest

from mail_agent_core.brain import AgentBrain
from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import AgentProfile, UsageType


def test_owner_cannot_save_empty_soul(tmp_path):
    manager = IdentityManager(tmp_path / "identity")
    identity = manager.create(owner_id="owner", agent_name="Nova", usage_type="private")
    profile = AgentProfile(owner_id="owner", agent_name="Nova", usage_type=UsageType.PRIVATE)
    brain = AgentBrain(tmp_path / "brain")
    brain.ensure(identity, profile)

    with pytest.raises(ValueError, match="SOUL.md must not be empty"):
        brain.update_owner_memory(soul="   ")
