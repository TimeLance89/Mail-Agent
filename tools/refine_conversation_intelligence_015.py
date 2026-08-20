from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, value: str) -> None:
    (ROOT / path).write_text(value, encoding="utf-8")


def once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, got {count}")
    return text.replace(old, new, 1)


# Keep undo payloads privacy-minimized and expose only still-valid capability tokens.
path = "apps/gateway/mail_agent_gateway/conversation_store.py"
text = read(path)
insert = '''    def list_available_undo(self, limit: int = 10) -> list[dict[str, Any]]:\n        now = utc_now()\n        limit = max(1, min(int(limit), 50))\n        with self._lock, self._connect() as conn:\n            conn.execute(\n                "UPDATE undo_actions SET status='expired' WHERE status='available' AND expires_at<=?",\n                (now,),\n            )\n            rows = conn.execute(\n                """\n                SELECT token, mailbox_id, message_id, thread_id, action, created_at, expires_at, status\n                FROM undo_actions\n                WHERE status='available' AND expires_at>?\n                ORDER BY created_at DESC LIMIT ?\n                """,\n                (now, limit),\n            ).fetchall()\n        return [dict(row) for row in rows]\n\n'''
text = once(text, "    def get_undo(self, token: str) -> dict[str, Any]:\n", insert + "    def get_undo(self, token: str) -> dict[str, Any]:\n", "undo listing")
write(path, text)

path = "apps/gateway/mail_agent_gateway/agent_runtime.py"
text = read(path)
text = once(
    text,
    '                            payload={"source": source_before, "execution": execution},',
    '''                            payload={\n                                "source": {\n                                    key: source_before.get(key)\n                                    for key in ("mailbox_id", "uid", "remote_id", "internet_message_id", "thread_key", "connector")\n                                },\n                                "execution": {\n                                    key: execution.get(key)\n                                    for key in ("connector", "action", "remote_id", "source_remote_id", "destination")\n                                },\n                            },''',
    "minimal undo payload",
)
write(path, text)

path = "apps/gateway/mail_agent_gateway/undo_service.py"
text = read(path)
text = text.replace("from .mail_store import MailStore, StoredMessage", "from .mail_store import MailStore")
text = text.replace("            self._restore_local_source(source)\n", "")
text = once(
    text,
    '        self.conversation_store.complete_undo(token)\n        return {"token": token, "status": "completed", "action": action.value, "mailbox_id": item["mailbox_id"]}\n\n    def _restore_local_source',
    '''        self.conversation_store.complete_undo(token)\n        return {\n            "token": token,\n            "status": "completed",\n            "action": action.value,\n            "mailbox_id": item["mailbox_id"],\n            "resync_required": action == MailActionType.ARCHIVE,\n        }\n\n    def _restore_local_source''',
    "undo response",
)
# Remove the now-unused local restoration method entirely.
method_start = text.find("    def _restore_local_source")
if method_start < 0:
    raise RuntimeError("undo restore method missing")
text = text[:method_start].rstrip() + "\n"
write(path, text)

path = "apps/gateway/mail_agent_gateway/main.py"
text = read(path)
text = once(
    text,
    '        "patterns": conversation_store.list_pattern_suggestions(\n            mailbox_id=mailbox_id,\n            min_samples=behavior.sender_pattern_min_samples,\n            confidence_threshold=behavior.sender_pattern_confidence,\n        ),\n    }',
    '        "patterns": conversation_store.list_pattern_suggestions(\n            mailbox_id=mailbox_id,\n            min_samples=behavior.sender_pattern_min_samples,\n            confidence_threshold=behavior.sender_pattern_confidence,\n        ),\n        "undo_actions": conversation_store.list_available_undo(limit=10),\n    }',
    "conversation undo payload",
)
write(path, text)

# Activity journal includes follow-up outcomes from cycles.
path = "packages/agent_core/mail_agent_core/brain.py"
text = read(path)
text = once(
    text,
    '            "postprocess_errors",\n            "pending_before",',
    '            "postprocess_errors",\n            "due_followups",\n            "followup_drafts",\n            "pending_before",',
    "brain cycle followup fields",
)
write(path, text)

# Frontend adapter keeps legacy renderer details out of app.js and surfaces undo capabilities.
write(
    "apps/web/conversation-intelligence-ui.js",
    r'''/* MAIL-AGENT 0.15 Conversation Intelligence UI adapter. */
(() => {
  const VERSION = '0.15.0';
  let shownUndoToken = '';
  let pollTimer = null;

  if (typeof setupLayout === 'function') {
    const originalSetupLayout = setupLayout;
    setupLayout = function conversationSetupLayout(content) {
      return originalSetupLayout(content).replace(/MAIL-AGENT v[0-9.]+ · Lokales Gateway/g, `MAIL-AGENT v${VERSION} · Lokales Gateway`);
    };
  }

  if (typeof ruleRow === 'function') {
    const originalRuleRow = ruleRow;
    ruleRow = function conversationRuleRow(rule, index) {
      let html = originalRuleRow(rule, index);
      const category = String(rule?.category || '');
      const extra = [
        `<option value="advertising" ${category === 'advertising' ? 'selected' : ''}>advertising</option>`,
        `<option value="cold_outreach" ${category === 'cold_outreach' ? 'selected' : ''}>cold_outreach</option>`,
      ].join('');
      return html.replace('<option value="newsletter"', `${extra}<option value="newsletter"`);
    };
  }

  function removeBanner() {
    document.getElementById('conversation-undo-banner')?.remove();
  }

  async function applyUndo(token) {
    try {
      const result = await post(`/v1/actions/undo/${encodeURIComponent(token)}`, { actor: 'local-user' });
      removeBanner();
      shownUndoToken = '';
      showNotice('Mailbox-Aktion rückgängig gemacht.');
      if (result.resync_required && typeof syncNow === 'function') {
        await syncNow();
      } else if (typeof loadDashboard === 'function') {
        await loadDashboard(true);
        render();
      }
    } catch (error) {
      showNotice(error.message, 'error');
      removeBanner();
    }
  }

  function showUndo(item) {
    if (!item?.token || item.token === shownUndoToken) return;
    const remaining = Math.max(0, Math.ceil((new Date(item.expires_at).getTime() - Date.now()) / 1000));
    if (!remaining) return;
    shownUndoToken = item.token;
    removeBanner();
    const banner = document.createElement('div');
    banner.id = 'conversation-undo-banner';
    banner.className = 'conversation-undo-banner';
    const label = item.action === 'archive' ? 'Mail archiviert' : item.action === 'mark_read' ? 'Mail als gelesen markiert' : 'Mailbox-Aktion ausgeführt';
    banner.innerHTML = `<div><strong>${esc(label)}</strong><span>Rückgängig noch ${remaining}s möglich</span></div><button type="button">Rückgängig</button>`;
    banner.querySelector('button')?.addEventListener('click', () => applyUndo(item.token));
    document.body.appendChild(banner);
    const timer = window.setInterval(() => {
      const left = Math.max(0, Math.ceil((new Date(item.expires_at).getTime() - Date.now()) / 1000));
      const text = banner.querySelector('span');
      if (text) text.textContent = left ? `Rückgängig noch ${left}s möglich` : 'Rückgängig abgelaufen';
      if (!left) {
        window.clearInterval(timer);
        window.setTimeout(removeBanner, 700);
      }
    }, 500);
  }

  async function refreshUndo() {
    if (typeof installed !== 'undefined' && !installed) return;
    try {
      const payload = await get('/v1/conversations?limit=1');
      const item = (payload.undo_actions || [])[0];
      if (item) showUndo(item);
    } catch (_) {
      // UI convenience must never disturb the main application.
    }
  }

  const originalFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    try {
      const raw = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
      if (response.ok && String(raw).includes('/v1/agent/run')) {
        window.setTimeout(refreshUndo, 100);
      }
    } catch (_) {}
    return response;
  };

  window.setTimeout(refreshUndo, 700);
  pollTimer = window.setInterval(refreshUndo, 2500);
  window.addEventListener('beforeunload', () => pollTimer && window.clearInterval(pollTimer), { once: true });

  const style = document.createElement('style');
  style.textContent = `.conversation-undo-banner{position:fixed;right:24px;bottom:24px;z-index:10050;display:flex;align-items:center;gap:18px;min-width:330px;padding:14px 14px 14px 16px;background:#1a1916;border:1px solid rgba(201,166,96,.5);box-shadow:0 18px 54px rgba(0,0,0,.38);color:#f1eee7}.conversation-undo-banner div{display:grid;gap:3px;flex:1}.conversation-undo-banner strong{font-size:13px}.conversation-undo-banner span{font-size:12px;color:#aaa49a}.conversation-undo-banner button{border:1px solid rgba(201,166,96,.55);background:#c9a660;color:#15130f;padding:9px 12px;font-weight:700;cursor:pointer}`;
  document.head.appendChild(style);
})();
''',
)

path = "apps/web/index.html"
text = read(path)
text = once(
    text,
    '  <script src="/assets/workbench-ui.js?v=0.15.0" defer></script>\n  <script src="/assets/mail-provider-setup.js?v=0.15.0" defer></script>',
    '  <script src="/assets/workbench-ui.js?v=0.15.0" defer></script>\n  <script src="/assets/conversation-intelligence-ui.js?v=0.15.0" defer></script>\n  <script src="/assets/mail-provider-setup.js?v=0.15.0" defer></script>',
    "conversation UI asset",
)
write(path, text)

# Add focused tests for the sensitive parts introduced in 0.15.
write(
    "tests/test_followup_and_undo.py",
    '''from __future__ import annotations\n\nimport asyncio\nfrom pathlib import Path\n\nfrom mail_agent_core.agent import MailAgent, MailMessageContext\nfrom mail_agent_core.identity import IdentityManager\nfrom mail_agent_core.models import AgentProfile, AutonomyMode, MailActionType, UsageType\nfrom mail_agent_core.providers import CompletionRequest, LLMProvider, ProviderHealth\nfrom mail_agent_core.signature import assert_mandatory_agent_signature\nfrom mail_agent_gateway.conversation_store import ConversationStore\nfrom mail_agent_gateway.mail_store import MailStore, StoredMessage\nfrom mail_agent_gateway.undo_service import UndoService\n\n\nclass FollowUpProvider(LLMProvider):\n    name = "fake"\n\n    async def health(self):\n        return ProviderHealth(True, "ok")\n\n    async def list_models(self):\n        return ["fake"]\n\n    async def complete(self, request: CompletionRequest):\n        assert "FOLLOW-UP DRAFT MODE" in request.system\n        return ''' + "'''" + '''{\n          "action": "send_reply",\n          "mailbox_id": "attacker",\n          "message_id": "attacker",\n          "recipient": "wrong@example.com",\n          "subject": "Re: Angebot",\n          "body": "Guten Tag, ich wollte freundlich nachfragen, ob es hierzu bereits einen Stand gibt.",\n          "confidence": 0.96,\n          "reason": "Follow-up"\n        }''' + "'''" + '''\n\n\ndef test_followup_is_local_draft_and_is_cryptographically_signed(tmp_path: Path):\n    agent = MailAgent()\n    profile = AgentProfile(owner_id="owner", agent_name="Nova", usage_type=UsageType.WORK, autonomy_mode=AutonomyMode.AUTONOMOUS)\n    message = MailMessageContext(mailbox_id="mb", message_id="m1", thread_id="t1", sender="person@example.com", recipients=["owner@example.com"], subject="Angebot", body="Bitte um Rückmeldung")\n    manager = IdentityManager(tmp_path / "identity")\n    identity = manager.create(owner_id="owner", agent_name="Nova", usage_type="work")\n    proposal = asyncio.run(agent.draft_follow_up(profile=profile, provider=FollowUpProvider(), model="fake", message=message, identity=identity, sign_payload=manager.sign, rationale="Warte seit vier Tagen"))\n    assert proposal.action == MailActionType.CREATE_DRAFT\n    assert proposal.mailbox_id == "mb"\n    assert proposal.message_id == "m1"\n    assert proposal.thread_id == "t1"\n    assert proposal.recipient == "person@example.com"\n    assert proposal.metadata["drafted_from_action"] == MailActionType.SEND_REPLY.value\n    assert proposal.metadata["follow_up_draft"] is True\n    assert_mandatory_agent_signature(proposal.body or "", identity)\n\n\nclass FakeGoogleClient:\n    def __init__(self):\n        self.calls = []\n\n    async def modify_message(self, message_id, **kwargs):\n        self.calls.append((message_id, kwargs))\n\n\nclass FakeExecutor:\n    def __init__(self, client):\n        self.client = client\n        self.mailbox_lookup = lambda mailbox_id: {"mailbox_id": mailbox_id, "connector": "gmail_api"}\n\n    async def _google_client(self, mailbox):\n        return self.client\n\n\ndef test_mark_read_undo_is_capability_scoped_and_restores_unread(tmp_path: Path):\n    mail_store = MailStore(tmp_path / "mail.db")\n    mail_store.upsert_messages([StoredMessage(mailbox_id="mb", uid=1, internet_message_id="<1@x>", thread_key="t1", sender="a@example.com", recipients=["owner@example.com"], subject="Subject", sent_at=None, body_text="body", seen=True, remote_id="r1", connector="gmail_api")])\n    conversations = ConversationStore(tmp_path / "conversations.db")\n    undo = conversations.create_undo(mailbox_id="mb", message_id="r1", thread_id="t1", action="mark_read", payload={"source":{"remote_id":"r1","connector":"gmail_api"},"execution":{"action":"mark_read"}}, ttl_seconds=30)\n    client = FakeGoogleClient()\n    service = UndoService(conversation_store=conversations, action_executor=FakeExecutor(client), mail_store=mail_store)\n    result = asyncio.run(service.undo(undo["token"]))\n    assert client.calls == [("r1", {"add_label_ids": ["UNREAD"]})]\n    assert mail_store.get_message("mb", "r1")["seen"] is False\n    assert result["resync_required"] is False\n    assert conversations.get_undo(undo["token"])["status"] == "completed"\n\n\ndef test_available_undo_list_never_exposes_payload(tmp_path: Path):\n    store = ConversationStore(tmp_path / "conversations.db")\n    store.create_undo(mailbox_id="mb", message_id="r1", thread_id="t1", action="archive", payload={"source":{"remote_id":"r1"},"secret":"must-stay-internal"}, ttl_seconds=30)\n    public = store.list_available_undo()\n    assert public and public[0]["action"] == "archive"\n    assert "payload" not in public[0]\n    assert "payload_json" not in public[0]\n''',
)

write(
    "tests/test_conversation_ui_adapter.py",
    '''from __future__ import annotations\n\nimport shutil\nimport subprocess\nfrom pathlib import Path\n\nimport pytest\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef test_conversation_ui_adapter_is_loaded_and_has_undo():\n    html=(ROOT/"apps/web/index.html").read_text(encoding="utf-8")\n    source=(ROOT/"apps/web/conversation-intelligence-ui.js").read_text(encoding="utf-8")\n    assert "/assets/conversation-intelligence-ui.js?v=0.15.0" in html\n    assert "/v1/actions/undo/" in source\n    assert "Rückgängig" in source\n    assert "cold_outreach" in source\n    assert "MAIL-AGENT v${VERSION}" in source\n    assert "MutationObserver" not in source\n\n\ndef test_conversation_ui_adapter_javascript_syntax():\n    node=shutil.which("node")\n    if not node:\n        pytest.skip("Node.js is not available")\n    result=subprocess.run([node,"--check",str(ROOT/"apps/web/conversation-intelligence-ui.js")],capture_output=True,text=True,check=False)\n    assert result.returncode==0,result.stderr\n''',
)

print("0.15 refinements materialized")
