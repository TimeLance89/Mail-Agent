from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class UsageType(StrEnum):
    PRIVATE = "private"
    WORK = "work"
    BUSINESS = "business"
    CUSTOM = "custom"


class AutonomyMode(StrEnum):
    OBSERVER = "observer"
    ASSISTANT = "assistant"
    COPILOT = "copilot"
    AUTONOMOUS = "autonomous"


class MailActionType(StrEnum):
    READ = "read"
    SUMMARIZE = "summarize"
    CLASSIFY = "classify"
    CREATE_DRAFT = "create_draft"
    MARK_READ = "mark_read"
    MOVE = "move"
    ARCHIVE = "archive"
    DELETE = "delete"
    SEND_REPLY = "send_reply"
    FORWARD = "forward"


class AgentProfile(BaseModel):
    owner_id: str = Field(min_length=1, max_length=200)
    agent_name: str = Field(min_length=1, max_length=80)
    usage_type: UsageType
    autonomy_mode: AutonomyMode = AutonomyMode.ASSISTANT
    language: str = "de"
    tone: str = "friendly"
    response_length: str = "medium"
    use_humor: bool = False
    salutation_style: str = "adaptive"
    email_signature: str = ""


class MailActionProposal(BaseModel):
    action: MailActionType
    mailbox_id: str
    message_id: str | None = None
    thread_id: str | None = None
    recipient: str | None = None
    subject: str | None = None
    body: str | None = None
    destination_folder: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolicyDecision(BaseModel):
    allowed: bool
    requires_approval: bool
    risk: str
    reason: str
