from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from mail_agent_core.agent import MailMessageContext
from mail_agent_core.models import AgentBehaviorSettings, AgentProfile


class IdentitySetupRequest(BaseModel):
    owner_id: str = Field(min_length=1, max_length=200)
    agent_name: str = Field(min_length=1, max_length=80)
    usage_type: Literal["private", "work", "business", "custom"]


class RegistrationResponse(BaseModel):
    agent_id: str
    installation_id: str
    fingerprint: str
    registered: bool


class ProviderProbeRequest(BaseModel):
    provider: Literal["ollama", "codex"]


class OnboardingCompleteRequest(BaseModel):
    profile: AgentProfile
    provider: Literal["ollama", "codex"]
    model: str


class LLMSettingsRequest(BaseModel):
    provider: Literal["ollama", "codex"]
    model: str = Field(min_length=1, max_length=200)


class BehaviorSettingsRequest(BaseModel):
    behavior: AgentBehaviorSettings


class ProfileSettingsRequest(BaseModel):
    profile: AgentProfile


class AgentRunRequest(BaseModel):
    mailbox_id: str | None = Field(default=None, max_length=128)
    force: bool = False


class MailboxProbeRequest(BaseModel):
    email_address: str = Field(min_length=3, max_length=320)
    username: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=2048)
    imap_host: str = Field(min_length=1, max_length=255)
    imap_port: int = Field(default=993, ge=1, le=65535)
    smtp_host: str = Field(min_length=1, max_length=255)
    smtp_port: int = Field(default=465, ge=1, le=65535)


class OAuthStartRequest(BaseModel):
    login_hint: str | None = Field(default=None, max_length=320)


class SyncRunRequest(BaseModel):
    mailbox_id: str | None = Field(default=None, max_length=128)
    limit: int = Field(default=100, ge=1, le=1000)


class ApprovalDecisionRequest(BaseModel):
    actor: str = Field(default="local-user", min_length=1, max_length=200)


class DraftUpdateRequest(BaseModel):
    subject: str = Field(default="", max_length=998)
    body: str = Field(min_length=1, max_length=200_000)
    recipient: str | None = Field(default=None, max_length=320)
    actor: str = Field(default="local-user", min_length=1, max_length=200)


class DraftSubmitRequest(BaseModel):
    actor: str = Field(default="local-user", min_length=1, max_length=200)


class AgentAnalyzeRequest(BaseModel):
    message: MailMessageContext