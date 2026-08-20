from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mail_agent_core.providers import ProviderHealth
from mail_agent_gateway.adaptive_intelligence import (
    AdaptiveSignalStore,
    OwnerProfileStore,
    RouteChoice,
)
from mail_agent_gateway.owner_profile_learning import OwnerProfileService


class FakeRouter:
    async def route(self, role: str):
        assert role == "owner_profile"
        return RouteChoice(role=role, provider_name="codex", model="strong", source="test")


class FakeProvider:
    name = "codex"

    async def health(self):
        return ProviderHealth(True, "ok")

    async def list_models(self):
        return ["strong"]

    async def complete(self, request):
        payload = json.loads(request.user)
        refs = [item["source_ref"] for item in payload["samples"]]
        return json.dumps(
            {
                "candidates": [
                    {
                        "key": "response_length",
                        "value": "kurz und direkt",
                        "confidence": 0.93,
                        "evidence_count": 99,
                        "rationale": "mehrfach bestätigt",
                        "source_refs": [refs[0], refs[2]],
                    },
                    {
                        "key": "closing",
                        "value": "Viele Grüße",
                        "confidence": 0.95,
                        "evidence_count": 3,
                        "rationale": "unbelegt",
                        "source_refs": ["src_invented", refs[1]],
                    },
                ]
            }
        )


class StubOwnerProfileService(OwnerProfileService):
    async def _samples(self, mailbox_id, limit):
        return [
            ("src_a", "Hallo A\n\nKurz und direkt.\nViele Grüße"),
            ("src_b", "Hallo B\n\nDanke, passt.\nViele Grüße"),
            ("src_c", "Hallo C\n\nBitte bis morgen prüfen.\nViele Grüße"),
        ]


class NullAudit:
    def append(self, *_args, **_kwargs):
        return None


def test_preview_keeps_only_actual_supporting_source_hashes(tmp_path: Path):
    profile = OwnerProfileStore(tmp_path / "profile.json")
    profile.set_consent(True)
    usage = AdaptiveSignalStore(tmp_path / "usage.db")
    service = StubOwnerProfileService(
        store=profile,
        router=FakeRouter(),
        providers={"codex": FakeProvider()},
        mailbox_supplier=lambda: [],
        vault=None,
        settings=None,
        google_token_supplier=None,
        microsoft_token_supplier=None,
        audit_log=NullAudit(),
        usage_store=usage,
    )

    preview = asyncio.run(service.preview(mailbox_id=None, limit=30))

    assert len(preview["preview"]) == 1
    learned = preview["preview"][0]
    assert learned["key"] == "response_length"
    assert learned["source_refs"] == ["src_a", "src_c"]
    assert learned["evidence_count"] == 2
    assert "src_invented" not in json.dumps(preview)


def test_latest_sent_uid_selection_uses_tail_of_mailbox_uid_set():
    class FakeImapConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def select(self, folder, readonly=True):
            assert folder == "Sent"
            assert readonly is True
            return "OK", []

        def uid(self, command, *_args):
            assert command == "search"
            return "OK", [b"1 2 3 40 41 42"]

    class FakeMailbox:
        def _login(self):
            return FakeImapConnection()

    assert OwnerProfileService._latest_sent_uids(FakeMailbox(), "Sent", 3) == [40, 41, 42]
