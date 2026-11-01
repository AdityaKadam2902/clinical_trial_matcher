"""HTTP-level authentication tests.

Covers the client-facing behaviour that token unit tests cannot see: login
issuing tokens, refresh-token rotation invalidating the old token, and RBAC on
``/match``.

The real FastAPI app and real SQLAlchemy models are used, but the PostgreSQL
session is replaced with an in-memory SQLite session so the suite still runs
without external services. Only the ``users`` and ``refresh_tokens`` tables are
created, which is all the auth routes touch.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import clinical_trial_matcher.db.models  # noqa: F401  (registers every mapper)
from clinical_trial_matcher.core.config import settings
from clinical_trial_matcher.core.database import get_db
from clinical_trial_matcher.core.security import (
    REFRESH_TOKEN_TYPE,
    create_access_token,
    decode_token,
    hash_password,
)
from clinical_trial_matcher.db.base import Base
from clinical_trial_matcher.db.enums import UserRole
from clinical_trial_matcher.db.models.user import RefreshToken, User
from clinical_trial_matcher.main import create_app
from clinical_trial_matcher.schemas.trial import MatchResponse, PaginationMeta

PASSWORD = "CorrectHorseBattery1"

PATIENT_PAYLOAD = {
    "age": 52,
    "sex": "female",
    "conditions": [{"display": "Type 2 Diabetes Mellitus", "is_active": True}],
}


class _AsyncSessionAdapter:
    """Expose the async Session methods the auth routes and dependencies use."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, instance: Any) -> None:
        self._session.add(instance)

    async def flush(self) -> None:
        self._session.flush()

    async def commit(self) -> None:
        self._session.commit()

    async def rollback(self) -> None:
        self._session.rollback()

    async def refresh(self, instance: Any) -> None:
        self._session.refresh(instance)

    async def get(self, entity: Any, ident: Any) -> Any:
        return self._session.get(entity, ident)

    async def scalar(self, statement: Any) -> Any:
        value = self._session.scalar(statement)
        # SQLite drops timezone information, while the refresh route compares
        # ``expires_at`` with an aware ``datetime.now(UTC)``.
        if isinstance(value, RefreshToken) and value.expires_at.tzinfo is None:
            value.expires_at = value.expires_at.replace(tzinfo=UTC)
        return value


@pytest.fixture()
def db_engine() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _register_now(dbapi_connection: Any, _record: Any) -> None:
        # The models use ``server_default=func.now()``, which SQLite lacks.
        dbapi_connection.create_function(
            "now",
            0,
            lambda: datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f"),
        )

    Base.metadata.create_all(engine, tables=[User.__table__, RefreshToken.__table__])
    yield engine
    engine.dispose()


@pytest.fixture()
def client(db_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # A developer's .env may disable auth; these tests must exercise it.
    monkeypatch.setattr(settings, "auth_enabled", True)

    async def override_get_db() -> AsyncIterator[_AsyncSessionAdapter]:
        session = Session(db_engine)
        adapter = _AsyncSessionAdapter(session)
        try:
            yield adapter
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def pipeline_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def fake_run_pipeline(patient: Any, page: int = 1, page_size: int = 10) -> MatchResponse:
        calls.append(patient.patient_id)
        return MatchResponse(
            patient_id=patient.patient_id,
            search_id="SEARCH-TEST0001",
            query_summary="stubbed pipeline",
            matches=[],
            pagination=PaginationMeta(
                page=page,
                page_size=page_size,
                total_items=0,
                total_pages=0,
                has_next=False,
                has_previous=False,
            ),
            total_trials_searched=0,
            total_eligible=0,
            processing_time_seconds=0.0,
            physician_summary="stubbed summary",
        )

    monkeypatch.setattr("clinical_trial_matcher.api.routes.run_pipeline", fake_run_pipeline)
    return calls


def _create_user(
    engine: Engine,
    *,
    email: str,
    role: UserRole = UserRole.ADMIN,
    is_active: bool = True,
) -> UUID:
    with Session(engine) as session:
        user = User(
            email=email,
            hashed_password=hash_password(PASSWORD),
            role=role.value,
            is_active=is_active,
            is_verified=True,
        )
        session.add(user)
        session.commit()
        return user.id


def _login(client: TestClient, email: str, password: str = PASSWORD):
    return client.post("/api/v1/auth/login", data={"username": email, "password": password})


def _bearer(user_id: UUID, role: UserRole) -> dict[str, str]:
    token, _ = create_access_token(user_id, role.value)
    return {"Authorization": f"Bearer {token}"}


# ── Login ─────────────────────────────────────────────────────────────────────


def test_login_returns_tokens_and_persists_refresh_token(client: TestClient, db_engine: Engine):
    user_id = _create_user(db_engine, email="doctor@example.com")

    response = _login(client, "doctor@example.com")

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in"] == settings.access_token_expire_minutes * 60

    claims = decode_token(body["access_token"], "access")
    assert claims["sub"] == str(user_id)
    assert claims["role"] == UserRole.ADMIN.value

    with Session(db_engine) as session:
        stored = session.scalar(select(RefreshToken))
        assert stored is not None
        assert stored.user_id == user_id
        assert stored.revoked_at is None


def test_login_rejects_wrong_password(client: TestClient, db_engine: Engine):
    _create_user(db_engine, email="doctor@example.com")

    response = _login(client, "doctor@example.com", "WrongPassword123")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_login_rejects_inactive_account(client: TestClient, db_engine: Engine):
    _create_user(db_engine, email="disabled@example.com", is_active=False)

    response = _login(client, "disabled@example.com")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


# ── Refresh rotation ──────────────────────────────────────────────────────────


def test_refresh_rotates_the_token_and_revokes_the_old_one(client: TestClient, db_engine: Engine):
    _create_user(db_engine, email="doctor@example.com")
    login = _login(client, "doctor@example.com")
    old_refresh = login.json()["refresh_token"]
    old_jti = decode_token(old_refresh, REFRESH_TOKEN_TYPE)["jti"]

    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})

    assert refreshed.status_code == 200
    new_refresh = refreshed.json()["refresh_token"]
    assert new_refresh != old_refresh

    with Session(db_engine) as session:
        revoked = session.scalar(select(RefreshToken).where(RefreshToken.jti == old_jti))
        assert revoked is not None
        assert revoked.revoked_at is not None

    # The rotated access token is usable.
    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "doctor@example.com"

    # The newly issued refresh token still works.
    second = client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert second.status_code == 200


def test_refresh_rejects_a_revoked_token(client: TestClient, db_engine: Engine):
    _create_user(db_engine, email="doctor@example.com")
    old_refresh = _login(client, "doctor@example.com").json()["refresh_token"]
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh}).status_code == 200

    reused = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})

    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "unauthorized"


def test_refresh_rejects_a_malformed_token(client: TestClient):
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": "x" * 40})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


# ── RBAC on /match ────────────────────────────────────────────────────────────


def test_match_requires_authentication(client: TestClient, pipeline_calls: list[str]):
    response = client.post("/api/v1/match", json=PATIENT_PAYLOAD)

    assert response.status_code == 401
    assert pipeline_calls == []


def test_match_forbids_viewer_role(client: TestClient, db_engine: Engine, pipeline_calls: list[str]):
    viewer_id = _create_user(db_engine, email="viewer@example.com", role=UserRole.VIEWER)

    response = client.post(
        "/api/v1/match",
        json=PATIENT_PAYLOAD,
        headers=_bearer(viewer_id, UserRole.VIEWER),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert pipeline_calls == []


@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.PHYSICIAN, UserRole.RESEARCHER])
def test_match_allows_clinical_roles(
    client: TestClient,
    db_engine: Engine,
    pipeline_calls: list[str],
    role: UserRole,
):
    user_id = _create_user(db_engine, email=f"{role.value}@example.com", role=role)

    response = client.post(
        "/api/v1/match",
        json=PATIENT_PAYLOAD,
        headers=_bearer(user_id, role),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["search_id"] == "SEARCH-TEST0001"
    assert body["matches"] == []
    assert len(pipeline_calls) == 1
