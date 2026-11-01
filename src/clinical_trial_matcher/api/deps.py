"""Authentication and authorization dependencies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from clinical_trial_matcher.api.errors import ForbiddenError, UnauthorizedError
from clinical_trial_matcher.core.config import settings
from clinical_trial_matcher.core.database import get_db
from clinical_trial_matcher.core.security import ACCESS_TOKEN_TYPE, TokenError, decode_token
from clinical_trial_matcher.db.enums import UserRole
from clinical_trial_matcher.db.models.user import User

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class Principal:
    id: uuid.UUID | None
    email: str
    role: str
    is_active: bool = True
    is_verified: bool = False


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Principal:
    if not settings.auth_enabled:
        return Principal(
            id=None,
            email="dev@example.com",
            role=UserRole.ADMIN.value,
        )

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError("Missing bearer token")

    try:
        payload = decode_token(credentials.credentials, ACCESS_TOKEN_TYPE)
        user_id = uuid.UUID(str(payload["sub"]))
    except (TokenError, ValueError, KeyError) as exc:
        raise UnauthorizedError("Invalid or expired access token") from exc

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("User not found or inactive")

    return Principal(
        id=user.id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        is_verified=user.is_verified,
    )


CurrentPrincipal = Annotated[Principal, Depends(get_current_user)]


def require_roles(*roles: UserRole | str):
    """Return a dependency that allows only the supplied roles."""
    allowed = {role.value if isinstance(role, UserRole) else role for role in roles}

    async def dependency(user: CurrentPrincipal) -> Principal:
        if user.role not in allowed:
            raise ForbiddenError("Insufficient permissions")
        return user

    return dependency


ClinicianOrAdmin = Annotated[
    Principal,
    Depends(
        require_roles(
            UserRole.ADMIN,
            UserRole.PHYSICIAN,
            UserRole.RESEARCHER,
        )
    ),
]
