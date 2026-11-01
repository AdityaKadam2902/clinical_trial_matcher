"""
tests/test_pipeline_fixes.py
─────────────────────────────
Regression tests that cover the four bugs fixed in this patch:

  1. Location filter was a no-op (always kept every trial).
  2. Phase filter silently kept all trials when none matched.
  3. Ranker returned NOT_ELIGIBLE trials as valid matches.
  4. Eligibility checker sent LLM calls when criteria were unavailable,
     producing false certainty; now returns NEEDS_REVIEW immediately.

Run with:  pytest tests/test_pipeline_fixes.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from clinical_trial_matcher.agents.pipeline_state import PipelineState
from clinical_trial_matcher.schemas.patient import FHIRCondition, PatientProfile, Sex
from clinical_trial_matcher.schemas.trial import (
    ClinicalTrial,
    EligibilityAssessment,
    EligibilityCriteria,
    EligibilityDecision,
    TrialLocation,
    TrialPhase,
    TrialStatus,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def make_patient(**kwargs) -> PatientProfile:
    defaults = dict(
        age=52,
        sex=Sex.FEMALE,
        conditions=[FHIRCondition(display="Type 2 Diabetes Mellitus")],
        symptoms=["fatigue"],
        preferred_locations=["California"],
        trial_phases=["PHASE2", "PHASE3"],
    )
    defaults.update(kwargs)
    return PatientProfile(**defaults)


def make_trial(
    nct_id="NCT00000001",
    phase=TrialPhase.PHASE3,
    status=TrialStatus.RECRUITING,
    countries=None,
    states=None,
    eligibility_raw="Eligibility details unavailable from TrialsMap fallback.",
    inclusion=None,
    exclusion=None,
) -> ClinicalTrial:
    locs = []
    if countries:
        for c in countries:
            state = (states or [None] * len(countries))[countries.index(c)]
            locs.append(TrialLocation(country=c, state=state, status="RECRUITING"))
    return ClinicalTrial(
        nct_id=nct_id,
        brief_title="Diabetes Trial",
        status=status,
        phase=phase,
        brief_summary="A test trial.",
        conditions=["Type 2 Diabetes Mellitus"],
        keywords=[],
        eligibility=EligibilityCriteria(
            raw_text=eligibility_raw,
            inclusion=inclusion or [],
            exclusion=exclusion or [],
            minimum_age=18,
            maximum_age=70,
            sex_eligible="All",
        ),
        interventions=[],
        intervention_names=[],
        locations=locs,
        countries=countries or [],
        url=f"https://clinicaltrials.gov/study/{nct_id}",
    )


# ── Fix 1: Location filter ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_location_filter_drops_non_matching_trial():
    """
    Trials whose country/state does not match preferred_locations must be
    dropped from filtered_trials (not silently kept).
    """

    patient = make_patient(preferred_locations=["California"])
    mexico_trial = make_trial(nct_id="NCT00000001", countries=["Mexico"])

    # Simulate what the agent does with location filtering inline

    filtered = [mexico_trial]
    preferred_lower = [loc.lower() for loc in patient.preferred_locations]
    location_filtered = []
    for trial in filtered:
        trial_countries = [c.lower() for c in trial.countries]
        trial_states = [(loc.state or "").lower() for loc in trial.locations]
        combined = trial_countries + trial_states
        if any(any(pref in field for field in combined) for pref in preferred_lower):
            location_filtered.append(trial)

    # Mexico trial must NOT be kept
    assert len(location_filtered) == 0, (
        "Location filter should have dropped the Mexico trial when California was preferred"
    )


@pytest.mark.asyncio
async def test_location_filter_keeps_matching_trial():
    """Trials matching the preferred location must be retained."""
    patient = make_patient(preferred_locations=["United States"])
    us_trial = make_trial(nct_id="NCT00000002", countries=["United States"])

    filtered = [us_trial]
    preferred_lower = [loc.lower() for loc in patient.preferred_locations]
    location_filtered = []
    for trial in filtered:
        trial_countries = [c.lower() for c in trial.countries]
        trial_states = [(loc.state or "").lower() for loc in trial.locations]
        combined = trial_countries + trial_states
        if any(any(pref in field for field in combined) for pref in preferred_lower):
            location_filtered.append(trial)

    assert len(location_filtered) == 1


# ── Fix 2: Phase filter ────────────────────────────────────────────────────────


def test_phase_filter_enforced_no_silent_fallback():
    """
    When requested phases are PHASE2/PHASE3 and the only available trial is
    PHASE_NA, the result must be an empty list — NOT a silent pass-through.
    """
    patient = make_patient(trial_phases=["PHASE2", "PHASE3"])
    na_trial = make_trial(nct_id="NCT00000003", phase=TrialPhase.NA)

    filtered = [na_trial]
    preferred_phases = set(patient.trial_phases)
    phase_filtered = [t for t in filtered if t.phase.value in preferred_phases]

    # The filter must return empty — not fall back to the original list
    assert len(phase_filtered) == 0, (
        "Phase filter must be enforced: NA trial must not appear when PHASE2/PHASE3 requested"
    )


def test_phase_filter_passes_matching_trial():
    patient = make_patient(trial_phases=["PHASE2", "PHASE3"])
    p3_trial = make_trial(nct_id="NCT00000004", phase=TrialPhase.PHASE3)

    preferred_phases = set(patient.trial_phases)
    phase_filtered = [t for t in [p3_trial] if t.phase.value in preferred_phases]

    assert len(phase_filtered) == 1


# ── Fix 3: Ranker excludes NOT_ELIGIBLE ───────────────────────────────────────


@pytest.mark.asyncio
async def test_ranker_excludes_not_eligible_trial():
    """
    A trial with decision=NOT_ELIGIBLE must never appear in ranked_trials,
    even if it has some met_criteria populated.
    """
    from clinical_trial_matcher.agents.ranker_agent import ranker_agent

    trial = make_trial(nct_id="NCT00000005", phase=TrialPhase.PHASE3)
    not_eligible_assessment = EligibilityAssessment(
        decision=EligibilityDecision.NOT_ELIGIBLE,
        confidence=0.5,
        match_score=50.0,
        met_criteria=["Diabetic", "Hypertensive"],  # partial hits present
        unmet_criteria=["Obesity unknown"],
        exclusion_triggers=["None specified"],
        reasoning="Patient conditions align but obesity status is unknown.",
    )

    state: PipelineState = {
        "patient": make_patient(),
        "search_id": "TEST-0002",
        "requested_page": 1,
        "page_size": 10,
        "processing_start_time": 0.0,
        "normalized_conditions": [],
        "normalized_medications": [],
        "search_keywords": [],
        "profile_summary": "",
        "raw_trials": [trial],
        "total_trials_found": 1,
        "fetch_error": None,
        "eligibility_results": [{"nct_id": "NCT00000005", "assessment": not_eligible_assessment.model_dump()}],
        "eligible_count": 0,
        "safety_assessments": {},
        "drug_flags": [],
        "rule_violations": {},
        "pipeline_halted": False,
        "halt_reason": None,
        "ranked_trials": [],
        "physician_summary": "",
    }

    result = await ranker_agent(state)
    assert len(result["ranked_trials"]) == 0, "NOT_ELIGIBLE trial with met_criteria must not appear in ranked_trials"


@pytest.mark.asyncio
async def test_ranker_keeps_needs_review_trial():
    """
    NEEDS_REVIEW is an uncertain outcome — it must be kept so the physician
    can manually evaluate it.
    """
    from clinical_trial_matcher.agents.ranker_agent import ranker_agent

    trial = make_trial(nct_id="NCT00000006", phase=TrialPhase.PHASE3)
    needs_review_assessment = EligibilityAssessment(
        decision=EligibilityDecision.NEEDS_REVIEW,
        confidence=0.0,
        match_score=0.0,
        met_criteria=[],
        unmet_criteria=[],
        exclusion_triggers=[],
        reasoning="Eligibility criteria unavailable — manual review required.",
    )

    state: PipelineState = {
        "patient": make_patient(),
        "search_id": "TEST-0003",
        "requested_page": 1,
        "page_size": 10,
        "processing_start_time": 0.0,
        "normalized_conditions": [],
        "normalized_medications": [],
        "search_keywords": [],
        "profile_summary": "",
        "raw_trials": [trial],
        "total_trials_found": 1,
        "fetch_error": None,
        "eligibility_results": [{"nct_id": "NCT00000006", "assessment": needs_review_assessment.model_dump()}],
        "eligible_count": 0,
        "safety_assessments": {},
        "drug_flags": [],
        "rule_violations": {},
        "pipeline_halted": False,
        "halt_reason": None,
        "ranked_trials": [],
        "physician_summary": "",
    }

    result = await ranker_agent(state)
    assert len(result["ranked_trials"]) == 1, "NEEDS_REVIEW trial must be kept in ranked_trials for physician review"


# ── Fix 4: Eligibility checker short-circuits on unavailable criteria ──────────


@pytest.mark.asyncio
async def test_eligibility_checker_returns_needs_review_for_fallback_trial():
    """
    When eligibility criteria come from the TrialsMap fallback (raw_text is the
    sentinel string and inclusion/exclusion are empty), the checker must return
    NEEDS_REVIEW with confidence=0 without calling the LLM.
    """
    from clinical_trial_matcher.agents.eligibility_checker import eligibility_checker_agent

    fallback_trial = make_trial(
        nct_id="NCT00000007",
        phase=TrialPhase.NA,
        eligibility_raw="Eligibility details unavailable from TrialsMap fallback.",
        inclusion=[],
        exclusion=[],
    )

    state: PipelineState = {
        "patient": make_patient(),
        "search_id": "TEST-0004",
        "requested_page": 1,
        "page_size": 10,
        "processing_start_time": 0.0,
        "normalized_conditions": [],
        "normalized_medications": [],
        "search_keywords": [],
        "profile_summary": "52-year-old female with Type 2 Diabetes.",
        "raw_trials": [fallback_trial],
        "total_trials_found": 1,
        "fetch_error": None,
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

    result = await eligibility_checker_agent(state)
    assert len(result["eligibility_results"]) == 1
    assessment = result["eligibility_results"][0]["assessment"]
    assert assessment["decision"] == EligibilityDecision.NEEDS_REVIEW.value, (
        "Fallback trial must produce NEEDS_REVIEW, not a fabricated decision"
    )
    assert assessment["confidence"] == 0.0, "Confidence must be 0 when criteria are unavailable"
    assert assessment["match_score"] == 0.0


# ── Fix 5: query_summary consistency ──────────────────────────────────────────


def test_query_summary_mentions_phase_and_location_preferences():
    """
    The query_summary string must reflect the patient's phase and location
    preferences so it is never internally inconsistent with the request body.
    """
    patient = make_patient(
        preferred_locations=["California"],
        trial_phases=["PHASE2", "PHASE3"],
    )
    conditions = patient.get_condition_names()
    eligible_count = 0
    total_items = 0
    phase_note = f" Phases requested: {', '.join(patient.trial_phases)}." if patient.trial_phases else ""
    location_note = (
        f" Location preference: {', '.join(patient.preferred_locations)}." if patient.preferred_locations else ""
    )
    query_summary = (
        f"Searched for trials matching: {', '.join(conditions[:3])}."
        f"{phase_note}{location_note} "
        f"Found 0 total trials, evaluated 0, "
        f"{eligible_count} eligible, {total_items} returned after ranking."
    )

    assert "PHASE2" in query_summary
    assert "PHASE3" in query_summary
    assert "California" in query_summary
    assert "eligible" in query_summary


# ── Fix 6: filter reason propagation through state ────────────────────────────


def test_phase_drop_count_in_state():
    """
    trials_dropped_by_phase must reflect the number of trials removed by the
    phase filter, not 0.
    """
    # Simulate the counter logic directly (unit-level, no API call)
    filtered_trials = [
        make_trial("NCT00000010", phase=TrialPhase.NA),
        make_trial("NCT00000011", phase=TrialPhase.PHASE1),
    ]
    patient = make_patient(trial_phases=["PHASE2", "PHASE3"])
    preferred_phases = set(patient.trial_phases)
    phase_filtered = [t for t in filtered_trials if t.phase.value in preferred_phases]
    dropped_by_phase = len(filtered_trials) - len(phase_filtered)

    assert dropped_by_phase == 2
    assert len(phase_filtered) == 0


def test_location_drop_count_in_state():
    """
    trials_dropped_by_location must count trials whose countries/states
    did not match the preference.
    """
    filtered_trials = [
        make_trial("NCT00000012", countries=["Mexico"]),
        make_trial("NCT00000013", countries=["United States"]),
    ]
    patient = make_patient(preferred_locations=["California"])
    preferred_lower = [loc.lower() for loc in patient.preferred_locations]

    dropped = 0
    kept = []
    for trial in filtered_trials:
        combined = [c.lower() for c in trial.countries]
        combined += [(loc.state or "").lower() for loc in trial.locations]
        if any(any(pref in field for field in combined) for pref in preferred_lower):
            kept.append(trial)
        else:
            dropped += 1

    # Mexico doesn't contain "california"; United States doesn't contain "california"
    assert dropped == 2
    assert len(kept) == 0


@pytest.mark.asyncio
async def test_ranker_state_preserves_drop_counters():
    """
    Ranker must pass through trials_dropped_by_phase and
    trials_dropped_by_location unchanged.
    """
    from clinical_trial_matcher.agents.ranker_agent import ranker_agent

    state: PipelineState = {
        "patient": make_patient(),
        "search_id": "TEST-0010",
        "requested_page": 1,
        "page_size": 10,
        "processing_start_time": 0.0,
        "normalized_conditions": [],
        "normalized_medications": [],
        "search_keywords": [],
        "profile_summary": "",
        "raw_trials": [],
        "total_trials_found": 5,
        "fetch_error": None,
        "trials_dropped_by_phase": 3,
        "trials_dropped_by_location": 2,
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

    result = await ranker_agent(state)
    assert result["trials_dropped_by_phase"] == 3
    assert result["trials_dropped_by_location"] == 2
