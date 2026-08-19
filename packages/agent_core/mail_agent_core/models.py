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


class AgentExecutionMode(StrEnum):
    LIVE = "live"
    SHADOW = "shadow"


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


class MailPriority(StrEnum):
    URGENT = "urgent"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class MailCategory(StrEnum):
    PERSONAL = "personal"
    WORK = "work"
    FINANCE = "finance"
    SUPPORT = "support"
    SALES = "sales"
    NEWSLETTER = "newsletter"
    NOTIFICATION = "notification"
    SECURITY = "security"
    OTHER = "other"


class RuleMode(StrEnum):
    NORMAL = "normal"
    ANALYZE_ONLY = "analyze_only"
    DRAFT_ONLY = "draft_only"
    IGNORE = "ignore"


class AgentRule(BaseModel):
    pattern: str = Field(min_length=1, max_length=320)
    mode: RuleMode = RuleMode.NORMAL
    priority: MailPriority | None = None
    category: MailCategory | None = None

    @field_validator("pattern")
    @classmethod
    def normalize_pattern(cls, value: str) -> str:
        return value.strip().lower()


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
    execution_mode: AgentExecutionMode = AgentExecutionMode.LIVE
    auto_analyze_new_mail: bool = True
    auto_create_drafts: bool = True
    auto_mark_read: bool = False
    auto_archive_low_priority: bool = False
    minimum_confidence: float = Field(default=0.72, ge=0.0, le=1.0)
    max_messages_per_cycle: int = Field(default=20, ge=1, le=200)
    thread_context_messages: int = Field(default=8, ge=0, le=30)
    active_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])
    active_from: str = Field(default="00:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    active_until: str = Field(default="23:59", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    vip_senders: list[str] = Field(default_factory=list)
    never_auto_act_senders: list[str] = Field(default_factory=list)
    rules: list[AgentRule] = Field(default_factory=list)

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
    summary: str = Field(default="", max_length=1200)
    priority: MailPriority = MailPriority.NORMAL
    category: MailCategory = MailCategory.OTHER
    needs_reply: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolicyDecision(BaseModel):
    allowed: bool
    requires_approval: bool
    risk: str
    reason: str
