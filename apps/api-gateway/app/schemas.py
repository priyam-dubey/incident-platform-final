from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

Role = Literal["owner", "admin", "developer", "viewer"]
Environment = Literal["development", "staging", "production"]


def _strong_password(v: str) -> str:
    if len(v) < 10:
        raise ValueError("Password must be at least 10 characters")
    if len(v) > 128:
        raise ValueError("Password must be at most 128 characters")
    if not (re.search(r"[A-Za-z]", v) and re.search(r"\d", v)):
        raise ValueError("Password must contain letters and digits")
    return v


class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str
    display_name: str = Field(default="", max_length=100)
    workspace_name: str = Field(default="My Workspace", min_length=1, max_length=80)
    _pw = field_validator("password")(_strong_password)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    new_password: str
    _pw = field_validator("new_password")(_strong_password)


class ProfileUpdate(BaseModel):
    display_name: str = Field(max_length=100)


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class MemberAdd(BaseModel):
    email: EmailStr
    role: Role = "viewer"


class MemberRoleUpdate(BaseModel):
    role: Role


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    environment: Environment
    framework: Literal["nodejs-express"] = "nodejs-express"
    backend_url: str | None = Field(default=None, max_length=300, pattern=r"^https?://")
    is_synthetic: bool = False


class ApplicationOut(BaseModel):
    id: uuid.UUID
    name: str
    environment: str
    framework: str
    backend_url: str | None
    is_synthetic: bool
    connection_status: Literal["waiting_for_telemetry", "connected", "stale"]
    last_telemetry_at: str | None
    active_key_prefix: str | None
    created_at: str


class DeploymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str | None = Field(default=None, max_length=100)
    commit_sha: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{7,64}$")
    branch: str | None = Field(default=None, max_length=200)
    repository: str | None = Field(default=None, max_length=200, pattern=r"^[\w.-]+/[\w.-]+$")
    deployed_by: str | None = Field(default=None, max_length=200)
    deployed_at: "datetime | None" = None
    environment: Environment | None = None
    metadata: dict = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _small(cls, v: dict) -> dict:
        import json as _j
        if len(_j.dumps(v)) > 4000:
            raise ValueError("metadata too large")
        return v


class NoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=4000)


class IncidentTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["resolved", "dismissed", "candidate", "pending_review"]


class HypothesisReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["accepted", "rejected", "edited"]
    notes: str | None = Field(default=None, max_length=2000)
    edited_text: str | None = Field(default=None, max_length=1500)

    @model_validator(mode="after")
    def _need_text(self):
        if self.verdict == "edited" and not self.edited_text:
            raise ValueError("edited_text is required when verdict is 'edited'")
        return self
