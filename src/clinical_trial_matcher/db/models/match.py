"""Match-run persistence and append-only progress events."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from clinical_trial_matcher.db.base import Base, TimestampMixin
from clinical_trial_matcher.db.enums import MatchStatus

if TYPE_CHECKING:
    from clinical_trial_matcher.db.models.llm import LLMCall
    from clinical_trial_matcher.db.models.patient import PatientRecord
    from clinical_trial_matcher.db.models.trial import (
        EligibilityAssessmentRecord,
        SafetyAssessmentRecord,
        TrialSnapshot,
    )
    from clinical_trial_matcher.db.models.user import User


class MatchRun(TimestampMixin, Base):
    __tablename__ = "match_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    search_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default=MatchStatus.QUEUED.value,
        server_default=MatchStatus.QUEUED.value,
        nullable=False,
        index=True,
    )
    requested_page: Mapped[int] = mapped_column(default=1, nullable=False)
    page_size: Mapped[int] = mapped_column(default=10, nullable=False)
    progress: Mapped[int] = mapped_column(default=0, nullable=False)
    current_step: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    patient: Mapped[PatientRecord] = relationship(back_populates="match_runs")
    created_by: Mapped[User | None] = relationship()
    events: Mapped[list[MatchRunEvent]] = relationship(
        back_populates="match_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    trial_snapshots: Mapped[list[TrialSnapshot]] = relationship(
        back_populates="match_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    eligibility_assessments: Mapped[list[EligibilityAssessmentRecord]] = relationship(
        back_populates="match_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    safety_assessments: Mapped[list[SafetyAssessmentRecord]] = relationship(
        back_populates="match_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    llm_calls: Mapped[list[LLMCall]] = relationship(
        back_populates="match_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<MatchRun id={self.id} search_id={self.search_id!r} status={self.status!r}>"


class MatchRunEvent(Base):
    __tablename__ = "match_run_events"
    __table_args__ = (Index("ix_match_run_events_run_id_id", "match_run_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    match_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("match_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    match_run: Mapped[MatchRun] = relationship(back_populates="events")

    def __repr__(self) -> str:
        return f"<MatchRunEvent id={self.id} type={self.event_type!r}>"
