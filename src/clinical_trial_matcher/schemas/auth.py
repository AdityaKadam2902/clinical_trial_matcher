"""Authentication request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from clinical_trial_matcher.core.config import settings


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)

    @field_validator("password")
    @classmethod
    def _validate_password_strength(cls, value: str) -> str:
        if len(value) < settings.password_min_length:
            raise ValueError(f"Password must be at least {settings.password_min_length} characters")
        if value.lower() == value or value.upper() == value:
            raise ValueError("Password must include both upper and lower case letters")
        if not any(char.isdigit() for char in value):
            raise ValueError("Password must include at least one digit")
        return value


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID | None
    email: EmailStr
    full_name: str | None = None
    role: str
    is_active: bool
    is_verified: bool
    created_at: datetime | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=4096)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=4096)
