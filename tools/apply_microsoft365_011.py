from pathlib import Path

path = Path("apps/gateway/mail_agent_gateway/action_executor.py")
text = path.read_text(encoding="utf-8")
old = '''            await client.send_mail(
                to=proposal.recipient or "",
                subject=subject,
                body=proposal.body or "",
            )
            return {
                "connector": "microsoft_graph",
                "remote_id": None,
                "thread_id": source.get("remote_thread_id") or source.get("thread_key"),
            }
'''
new = '''            payload = await client.send_forward(
                source_message_id=remote_id,
                recipient=proposal.recipient or "",
                subject=subject,
                body=proposal.body or "",
            )
            return {
                "connector": "microsoft_graph",
                "remote_id": payload.get("id"),
                "thread_id": payload.get("conversationId") or source.get("remote_thread_id"),
            }
'''
if old not in text:
    raise SystemExit("Expected Microsoft forward executor marker is missing")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Native Microsoft Graph createForward execution integrated.")
