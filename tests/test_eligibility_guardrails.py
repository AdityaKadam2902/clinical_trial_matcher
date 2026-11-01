"""Guardrails for the eligibility agent.

These cover the two failure modes observed with the local model: a 260-second
call that never returns, and free-form model reasoning contradicting hard
protocol facts (age/sex) that are already known deterministically.
"""

import asyncio
import time

from clinical_trial_matcher.agents import eligibility_checker
from clinical_trial_matcher.agents.pipeline_state import PipelineState
from clinical_trial_matcher.core.config import settings
from clinical_trial_matcher.schemas.trial import EligibilityDecision
from tests.test_pipeline_fixes import make_patient, make_trial


def make_state(trials, patient=None) -> PipelineState:
    return {
        "patient": patient or make_patient(),
        "search_id": "TEST-ELIG",
        "requested_page": 1,
        "page_size": 5,
        "processing_start_time": time.time(),
        "normalized_conditions": ["Type 2 Diabetes Mellitus"],
        "normalized_medications": [],
        "search_keywords": [],
        "profile_summary": "52-year-old female with type 2 diabetes on metformin.",
        "raw_trials": trials,
        "total_trials_found": len(trials),
        "fetch_error": None,
        "trials_dropped_by_phase": 0,
        "trials_dropped_by_location": 0,
        "eligibility_results": [],
        "eligible_count": 0,
        "safety_assessments": {},
        "drug_flags": [],
        "rule_violations": {},
        "pipeline_halted": False,
        "halt_reason": None,
        "ranked_trials": [],
        "physician_summary": "",
    }


def test_age_below_minimum_is_excluded_without_llm(monkeypatch):
    """A protocol age floor must be enforced by code, not by the model."""

    def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM must not be called for a deterministic age exclusion")

    monkeypatch.setattr(eligibility_checker, "_check_single_trial_sync", fail_if_called)

    patient = make_patient(age=52)
    trial = make_trial(
        nct_id="NCT00000090",
        eligibility_raw="Inclusion Criteria:\n- Adults 18 years and older",
        inclusion=["Adults 18 years and older"],
    )
    trial.eligibility.minimum_age = 60  # patient is 52

    result = asyncio.run(eligibility_checker.eligibility_checker_agent(make_state([trial], patient)))

    assessment = result["eligibility_results"][0]["assessment"]
    assert assessment["decision"] == EligibilityDecision.NOT_ELIGIBLE.value
    assert assessment["match_score"] == 0.0
    assert "below the trial minimum age" in assessment["reasoning"]


def test_sex_mismatch_is_excluded_without_llm(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM must not be called for a deterministic sex exclusion")

    monkeypatch.setattr(eligibility_checker, "_check_single_trial_sync", fail_if_called)

    trial = make_trial(
        nct_id="NCT00000091",
        eligibility_raw="Inclusion Criteria:\n- Male participants",
        inclusion=["Male participants"],
    )
    trial.eligibility.sex_eligible = "Male"

    result = asyncio.run(eligibility_checker.eligibility_checker_agent(make_state([trial], make_patient(sex="female"))))

    assessment = result["eligibility_results"][0]["assessment"]
    assert assessment["decision"] == EligibilityDecision.NOT_ELIGIBLE.value
    assert "only enrolls male participants" in assessment["reasoning"]


def test_slow_llm_returns_needs_review_instead_of_hanging(monkeypatch):
    """A call that outlives the per-trial limit must degrade honestly."""

    def slow_call(*args, **kwargs):
        time.sleep(3)
        raise AssertionError("the timeout must win before the call returns")

    monkeypatch.setattr(eligibility_checker, "_check_single_trial_sync", slow_call)
    monkeypatch.setattr(settings, "eligibility_timeout_seconds", 0.2)
    monkeypatch.setattr(settings, "pipeline_budget_seconds", 30.0)

    trial = make_trial(
        nct_id="NCT00000092",
        eligibility_raw="Inclusion Criteria:\n- Adults 18 years and older\nExclusion Criteria:\n- Pregnancy",
        inclusion=["Adults 18 years and older"],
        exclusion=["Pregnancy"],
    )

    started = time.time()
    result = asyncio.run(eligibility_checker.eligibility_checker_agent(make_state([trial])))
    elapsed = time.time() - started

    assessment = result["eligibility_results"][0]["assessment"]
    assert assessment["decision"] == EligibilityDecision.NEEDS_REVIEW.value
    assert "time limit" in assessment["reasoning"]
    assert elapsed < 2.0, f"agent should honour the per-call timeout, took {elapsed:.1f}s"


def test_exhausted_budget_marks_remaining_trials_as_not_evaluated(monkeypatch):
    """Once the budget is gone, no further LLM calls may start."""

    calls = {"n": 0}

    def counting_call(*args, **kwargs):
        calls["n"] += 1
        time.sleep(1)
        raise AssertionError("budget check must prevent this call")

    monkeypatch.setattr(eligibility_checker, "_check_single_trial_sync", counting_call)
    monkeypatch.setattr(settings, "pipeline_budget_seconds", 0.0)
    monkeypatch.setattr(settings, "eligibility_timeout_seconds", 30.0)

    trials = [
        make_trial(
            nct_id=f"NCT0000010{i}",
            eligibility_raw="Inclusion Criteria:\n- Adults 18 years and older",
            inclusion=["Adults 18 years and older"],
        )
        for i in range(3)
    ]

    result = asyncio.run(eligibility_checker.eligibility_checker_agent(make_state(trials)))

    assert calls["n"] == 0
    assert len(result["eligibility_results"]) == 3
    assert all(
        r["assessment"]["decision"] == EligibilityDecision.NEEDS_REVIEW.value for r in result["eligibility_results"]
    )
    assert all("time budget" in r["assessment"]["reasoning"] for r in result["eligibility_results"])
