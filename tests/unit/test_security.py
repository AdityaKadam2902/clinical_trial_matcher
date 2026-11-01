import uuid
from datetime import UTC, datetime

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from clinical_trial_matcher.api.deps import Principal, get_current_user, require_roles
from clinical_trial_matcher.api.errors import ForbiddenError, UnauthorizedError
from clinical_trial_matcher.core.config import settings
from clinical_trial_matcher.core.rate_limit import rate_limit_key
from clinical_trial_matcher.core.security import (
    ACCESS_TOKEN_TYPE,
    REFRESH_TOKEN_TYPE,
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from clinical_trial_matcher.db.enums import UserRole


def test_password_hash_roundtrip():
    hashed = hash_password("CorrectHorseBattery1")
    assert hashed != "CorrectHorseBattery1"
    assert verify_password("CorrectHorseBattery1", hashed) is True
    assert verify_password("WrongPassword1", hashed) is False


def test_access_token_contains_role_and_subject():
    user_id = uuid.uuid4()
    token, expires_in = create_access_token(user_id, UserRole.PHYSICIAN.value)
    claims = decode_token(token, ACCESS_TOKEN_TYPE)
    assert claims["sub"] == str(user_id)
    assert claims["role"] == UserRole.PHYSICIAN.value
    assert expires_in == settings.access_token_expire_minutes * 60


def test_refresh_token_has_jti_and_future_expiry():
    user_id = uuid.uuid4()
    token, jti, expires_at = create_refresh_token(user_id)
    claims = decode_token(token, REFRESH_TOKEN_TYPE)
    assert claims["jti"] == jti
    assert expires_at > datetime.now(UTC)


def test_refresh_token_cannot_be_used_as_access_token():
    token, _, _ = create_refresh_token(uuid.uuid4())
    with pytest.raises(TokenError):
        decode_token(token, ACCESS_TOKEN_TYPE)


def test_tampered_token_is_rejected():
    token, _ = create_access_token(uuid.uuid4(), UserRole.VIEWER.value)
    with pytest.raises(TokenError):
        decode_token(token + "x", ACCESS_TOKEN_TYPE)


@pytest.mark.asyncio
async def test_role_dependency_allows_and_denies():
    admin = Principal(id=uuid.uuid4(), email="admin@example.com", role=UserRole.ADMIN.value)
    viewer = Principal(id=uuid.uuid4(), email="viewer@example.com", role=UserRole.VIEWER.value)
    dependency = require_roles(UserRole.ADMIN, UserRole.PHYSICIAN)

    assert dependency.__name__ == "dependency"

    assert await dependency(admin) == admin
    with pytest.raises(ForbiddenError):
        await dependency(viewer)


@pytest.mark.asyncio
async def test_auth_can_be_disabled_for_development(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    principal = await get_current_user(credentials=None, db=None)  # type: ignore[arg-type]
    assert principal.role == UserRole.ADMIN.value
    assert principal.id is None


@pytest.mark.asyncio
async def test_missing_bearer_token_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    with pytest.raises(UnauthorizedError):
        await get_current_user(credentials=None, db=None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_invalid_bearer_token_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-jwt")
    with pytest.raises(UnauthorizedError):
        await get_current_user(credentials=credentials, db=None)  # type: ignore[arg-type]


def _request(headers: dict[str, str], client: tuple[str, int] = ("10.0.0.1", 1234)) -> Request:
    scope = {
        "type": "http",
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        "client": client,
    }
    return Request(scope)


def test_rate_limit_key_uses_remote_address_by_default(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_count", 0)
    request = _request({"x-forwarded-for": "203.0.113.1"})
    assert rate_limit_key(request) == "10.0.0.1"


def test_rate_limit_key_honors_trusted_proxy(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_count", 1)
    request = _request({"x-forwarded-for": "203.0.113.1, 10.0.0.2"})
    assert rate_limit_key(request) == "10.0.0.2"
