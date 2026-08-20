from __future__ import annotations

import pytest

# Importing the 0.17 runtime hardening installs Google's current writable-role semantics.
from mail_agent_gateway import calendar_concierge_v17 as _calendar_v17  # noqa: F401
from mail_agent_gateway.calendar_reliable import ReliableCalendarService


class FakeService:
    def __init__(self, role: str):
        self.role = role

    async def _calendar_meta(self, mailbox_id: str, calendar_id: str):
        assert mailbox_id == "mb"
        assert calendar_id == "shared"
        return {"id": "shared", "access_role": self.role}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["owner", "writer", "writerWithoutPrivateAccess"])
async def test_google_writable_roles_are_accepted(role: str):
    fake = FakeService(role)
    result = await ReliableCalendarService._ensure_writable_calendar(fake, "mb", "shared")
    assert result["access_role"] == role


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["reader", "freeBusyReader", "none", ""])
async def test_google_readonly_roles_are_rejected(role: str):
    fake = FakeService(role)
    with pytest.raises(PermissionError, match="read-only"):
        await ReliableCalendarService._ensure_writable_calendar(fake, "mb", "shared")
