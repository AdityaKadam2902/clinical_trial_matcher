"""Database package: models, enums, and session access."""

from clinical_trial_matcher.db.base import Base, TimestampMixin
from clinical_trial_matcher.db.enums import EvalStatus, LLMCallStatus, MatchStatus, UserRole
from clinical_trial_matcher.db.models import (
    AuditLog,
    EligibilityAssessmentRecord,
    EvalRun,
    IdempotencyKey,
    LLMCall,
    MatchRun,
    MatchRunEvent,
    PatientRecord,
    PromptVersion,
    RefreshToken,
    SafetyAssessmentRecord,
    TrialSnapshot,
    User,
)

__all__ = [
    "AuditLog",
    "Base",
    "EligibilityAssessmentRecord",
    "EvalRun",
    "EvalStatus",
    "IdempotencyKey",
    "LLMCall",
    "LLMCallStatus",
    "MatchRun",
    "MatchRunEvent",
    "MatchStatus",
    "PatientRecord",
    "PromptVersion",
    "RefreshToken",
    "SafetyAssessmentRecord",
    "TimestampMixin",
    "TrialSnapshot",
    "User",
    "UserRole",
]
