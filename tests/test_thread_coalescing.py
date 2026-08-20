from __future__ import annotations

from mail_agent_gateway.agent_queue import AgentWorkQueue
from mail_agent_gateway.mail_store import MailStore, StoredMessage


def msg(uid, thread):
    return StoredMessage(mailbox_id="mb",uid=uid,internet_message_id=f"<{uid}@x>",thread_key=thread,sender="a@example.com",recipients=["b@example.com"],subject=f"s{uid}",sent_at=None,body_text="body",seen=False,remote_id=f"r{uid}")

def test_claim_threads_coalesces_multiple_new_messages(tmp_path):
    store=MailStore(tmp_path/"mail.db")
    store.upsert_messages([msg(1,"t1"),msg(2,"t1"),msg(3,"t2")])
    queue=AgentWorkQueue(store)
    items=queue.list_pending_threads("mb",10)
    assert len(items)==2
    t1=next(item for item in items if item["thread_key"]=="t1")
    assert t1["remote_id"]=="r2"
    assert t1["_coalesced_count"]==2
    assert set(t1["_coalesced_message_ids"])=={"r1","r2"}
    # Claimed messages cannot be selected by an overlapping cycle.
    assert queue.list_pending_threads("mb",10)==[]
