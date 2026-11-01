"""Trial snapshots and per-trial clinical assessments."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Float, ForeignKey, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from clinical_trial_matcher.db.base import Base

if TYPE_CHECKING:
    from clinical_trial_matcher.db.models.match import MatchRun


class TrialSnapshot(Base):
    __tablename__ = "trial_snapshots"
    __table_args__ = (UniqueConstraint("match_run_id", "nct_id", name="uq_trial_snapshots_run_nct"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    match_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("match_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    nct_id: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source: Mapped[str] = mapped_column(
        String(64),
        default="clinicaltrials.gov",
        server_default="clinicaltrials.gov",
        nullable=False,
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    match_run: Mapped[MatchRun] = relationship(back_populates="trial_snapshots")
    eligibility_assessments: Mapped[list[EligibilityAssessmentRecord]] = relationship(
        back_populates="trial_snapshot",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    safety_assessments: Mapped[list[SafetyAssessmentRecord]] = relationship(
        back_populates="trial_snapshot",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<TrialSnapshot nct_id={self.nct_id!r}>"


class EligibilityAssessmentRecord(Base):
    __tablename__ = "eligibility_assessments"
    __table_args__ = (UniqueConstraint("match_run_id", "trial_snapshot_id", name="uq_eligibility_run_trial"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    match_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("match_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trial_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trial_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    match_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    assessment: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    match_run: Mapped[MatchRun] = relationship(back_populates="eligibility_assessments")
    trial_snapshot: Mapped[TrialSnapshot] = relationship(back_populates="eligibility_assessments")


class SafetyAssessmentRecord(Base):
    __tablename__ = "safety_assessments"
    __table_args__ = (UniqueConstraint("match_run_id", "trial_snapshot_id", name="uq_safety_run_trial"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    match_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("match_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trial_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trial_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    overall_level: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    is_safe_to_proceed: Mapped[bool] = mapped_column(default=False, nullable=False)
    assessment: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    match_run: Mapped[MatchRun] = relationship(back_populates="safety_assessments")
    trial_snapshot: Mapped[TrialSnapshot] = relationship(back_populates="safety_assessments")
