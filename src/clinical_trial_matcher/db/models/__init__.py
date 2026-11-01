"""Import all models so SQLAlchemy and Alembic see the full metadata."""

from clinical_trial_matcher.db.models.audit import AuditLog
from clinical_trial_matcher.db.models.eval import EvalRun
from clinical_trial_matcher.db.models.idempotency import IdempotencyKey
from clinical_trial_matcher.db.models.llm import LLMCall, PromptVersion
from clinical_trial_matcher.db.models.match import MatchRun, MatchRunEvent
from clinical_trial_matcher.db.models.patient import PatientRecord
from clinical_trial_matcher.db.models.trial import (
    EligibilityAssessmentRecord,
    SafetyAssessmentRecord,
    TrialSnapshot,
)
from clinical_trial_matcher.db.models.user import RefreshToken, User

__all__ = [
    "AuditLog",
    "EligibilityAssessmentRecord",
    "EvalRun",
    "IdempotencyKey",
    "LLMCall",
    "MatchRun",
    "MatchRunEvent",
    "PatientRecord",
    "PromptVersion",
    "RefreshToken",
    "SafetyAssessmentRecord",
    "TrialSnapshot",
    "User",
]
