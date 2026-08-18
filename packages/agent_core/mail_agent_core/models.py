from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


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


class AgentBehaviorSettings(BaseModel):
    enabled: bool = True
    auto_analyze_new_mail: bool = True
    auto_create_drafts: bool = True
    auto_mark_read: bool = False
    auto_archive_low_priority: bool = False
    minimum_confidence: float = Field(default=0.72, ge=0.0, le=1.0)
    max_messages_per_cycle: int = Field(default=20, ge=1, le=200)
    active_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])
    active_from: str = Field(default="00:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    active_until: str = Field(default="23:59", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    vip_senders: list[str] = Field(default_factory=list)
    never_auto_act_senders: list[str] = Field(default_factory=list)

    @field_validator("active_days")
    @classmethod
    def validate_days(cls, value: list[int]) -> list[int]:
        normalized = sorted(set(value))
        if not normalized or any(day < 0 or day > 6 for day in normalized):
            raise ValueError("active_days must contain weekdays 0 through 6")
        return normalized

    @field_validator("vip_senders", "never_auto_act_senders")
    @classmethod
    def normalize_senders(cls, value: list[str]) -> list[str]:
        return sorted({item.strip().lower() for item in value if item.strip()})


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
