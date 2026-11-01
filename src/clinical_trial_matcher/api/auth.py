"""Authentication endpoints: register, login, refresh, logout, and profile."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from clinical_trial_matcher.api.deps import CurrentPrincipal
from clinical_trial_matcher.api.errors import (
    ConflictError,
    ForbiddenError,
    UnauthorizedError,
)
from clinical_trial_matcher.core.config import settings
from clinical_trial_matcher.core.database import get_db
from clinical_trial_matcher.core.rate_limit import limiter
from clinical_trial_matcher.core.security import (
    REFRESH_TOKEN_TYPE,
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from clinical_trial_matcher.db.enums import UserRole
from clinical_trial_matcher.db.models.user import RefreshToken, User
from clinical_trial_matcher.schemas.auth import (
    LogoutRequest,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserRead,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


def _client_metadata(request: Request) -> tuple[str | None, str | None]:
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None
    return user_agent, ip_address


def _issue_tokens(
    *,
    user: User,
    request: Request,
    db: AsyncSession,
) -> TokenResponse:
    access_token, expires_in = create_access_token(user.id, user.role)
    refresh_token, jti, expires_at = create_refresh_token(user.id)
    user_agent, ip_address = _client_metadata(request)
    db.add(
        RefreshToken(
            user_id=user.id,
            jti=jti,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_auth)
async def register(
    request: Request,
    payload: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserRead:
    if not settings.allow_registration:
        raise ForbiddenError("Registration is disabled")

    email = payload.email.lower()
    existing = await db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise ConflictError("An account with this email already exists")

    user = User(
        email=email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=UserRole.VIEWER.value,
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    logger.info("user_registered user_id={} email={}", user.id, user.email)
    return UserRead.model_validate(user)


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.rate_limit_auth)
async def login(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    email = form_data.username.strip().lower()
    user = await db.scalar(select(User).where(User.email == email))

    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise UnauthorizedError("Invalid email or password")
    if not user.is_active:
        raise ForbiddenError("This account is disabled")

    user.last_login_at = datetime.now(UTC)
    tokens = _issue_tokens(user=user, request=request, db=db)
    await db.flush()
    logger.info("user_login user_id={} email={}", user.id, user.email)
    return tokens


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(settings.rate_limit_auth)
async def refresh(
    request: Request,
    payload: RefreshRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    try:
        claims = decode_token(payload.refresh_token, REFRESH_TOKEN_TYPE)
        user_id = uuid.UUID(str(claims["sub"]))
        jti = str(claims["jti"])
    except (TokenError, ValueError, KeyError) as exc:
        raise UnauthorizedError("Invalid refresh token") from exc

    stored = await db.scalar(select(RefreshToken).where(RefreshToken.jti == jti).with_for_update())
    now = datetime.now(UTC)
    if stored is None or stored.revoked_at is not None or stored.expires_at <= now:
        raise UnauthorizedError("Refresh token has been revoked or expired")
    if stored.user_id != user_id:
        raise UnauthorizedError("Invalid refresh token")

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("User not found or inactive")

    stored.revoked_at = now
    tokens = _issue_tokens(user=user, request=request, db=db)
    await db.flush()
    logger.info("token_refreshed user_id={}", user.id)
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(settings.rate_limit_auth)
async def logout(
    request: Request,
    payload: LogoutRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    try:
        claims = decode_token(payload.refresh_token, REFRESH_TOKEN_TYPE)
        jti = str(claims["jti"])
    except (TokenError, KeyError):
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    stored = await db.scalar(select(RefreshToken).where(RefreshToken.jti == jti))
    if stored is not None and stored.revoked_at is None:
        stored.revoked_at = datetime.now(UTC)
        logger.info("user_logout user_id={}", stored.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserRead)
@limiter.limit(settings.rate_limit_read)
async def me(
    request: Request,
    principal: CurrentPrincipal,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserRead:
    if principal.id is None:
        return UserRead(
            id=None,
            email=principal.email,
            full_name="Development User",
            role=principal.role,
            is_active=True,
            is_verified=True,
        )

    user = await db.get(User, principal.id)
    if user is None:
        raise UnauthorizedError("User not found")
    return UserRead.model_validate(user)
