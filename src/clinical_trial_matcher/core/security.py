"""Password hashing and JWT helpers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from clinical_trial_matcher.core.config import settings

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"

_password_hasher = PasswordHash.recommended()


class TokenError(Exception):
    """Raised when a JWT is missing, malformed, expired, or of the wrong type."""


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return _password_hasher.verify(password, hashed_password)
    except Exception:
        return False


def _now() -> datetime:
    return datetime.now(UTC)


def _encode(
    *,
    subject: uuid.UUID,
    token_type: str,
    expires_delta: timedelta,
    jti: str,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = _now()
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "jti": jti,
        "iat": now,
        "nbf": now,
        "exp": now + expires_delta,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(
        payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def create_access_token(user_id: uuid.UUID, role: str) -> tuple[str, int]:
    expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    token = _encode(
        subject=user_id,
        token_type=ACCESS_TOKEN_TYPE,
        expires_delta=expires_delta,
        jti=uuid.uuid4().hex,
        extra_claims={"role": role},
    )
    return token, int(expires_delta.total_seconds())


def create_refresh_token(user_id: uuid.UUID) -> tuple[str, str, datetime]:
    expires_delta = timedelta(days=settings.refresh_token_expire_days)
    jti = uuid.uuid4().hex
    token = _encode(
        subject=user_id,
        token_type=REFRESH_TOKEN_TYPE,
        expires_delta=expires_delta,
        jti=jti,
    )
    return token, jti, _now() + expires_delta


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "jti", "type"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid or expired token") from exc

    if payload.get("type") != expected_type:
        raise TokenError(f"Expected a {expected_type} token")
    return payload
