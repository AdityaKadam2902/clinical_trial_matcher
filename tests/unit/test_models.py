from sqlalchemy.orm import configure_mappers

import clinical_trial_matcher.db.models  # noqa: F401
from clinical_trial_matcher.db.base import Base

EXPECTED_TABLES = {
    "audit_logs",
    "eligibility_assessments",
    "eval_runs",
    "idempotency_keys",
    "llm_calls",
    "match_run_events",
    "match_runs",
    "patient_records",
    "prompt_versions",
    "refresh_tokens",
    "safety_assessments",
    "trial_snapshots",
    "users",
}


def test_all_expected_tables_are_registered():
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_orm_mappers_configure_without_errors():
    configure_mappers()
