"""Patient record model. Stores structured profile snapshots, not raw FHIR bundles."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from clinical_trial_matcher.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from clinical_trial_matcher.db.models.match import MatchRun
    from clinical_trial_matcher.db.models.user import User


class PatientRecord(TimestampMixin, Base):
    __tablename__ = "patient_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    external_id: Mapped[str | None] = mapped_column(String(128), index=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    age: Mapped[int | None]
    sex: Mapped[str | None] = mapped_column(String(16))
    is_pregnant: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
    )
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    created_by: Mapped[User | None] = relationship(back_populates="patients")
    match_runs: Mapped[list[MatchRun]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<PatientRecord id={self.id} external_id={self.external_id!r}>"
