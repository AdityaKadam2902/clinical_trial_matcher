"""
agents/ranker_agent.py
──────────────────────
Agent 5: Ranker

Scores and ranks all trials using a weighted multi-dimensional formula.
Pure Python — no LLM needed. Scoring is deterministic and explainable.

Scoring dimensions and weights:
  - Eligibility match score  : 40%  (most important — does patient qualify?)
  - Safety level             : 30%  (is it safe to proceed?)
  - Trial phase              : 15%  (Phase 3 = most proven)
  - Enrollment proximity     : 10%  (is enrollment open and nearby?)
  - Recency                  : 5%   (more recently started = better)
"""

import time
from datetime import datetime

from loguru import logger

from clinical_trial_matcher.agents.pipeline_state import PipelineState
from clinical_trial_matcher.schemas.trial import (
    ClinicalTrial,
    EligibilityAssessment,
    EligibilityDecision,
    MatchedTrial,
    SafetyAssessment,
    SafetyLevel,
    TrialPhase,
    TrialStatus,
)

# ── Scoring weights ────────────────────────────────────────────────────────────
WEIGHT_ELIGIBILITY = 0.40
WEIGHT_SAFETY = 0.30
WEIGHT_PHASE = 0.15
WEIGHT_ENROLLMENT = 0.10
WEIGHT_RECENCY = 0.05

# Phase scores (Phase 3 has most evidence, Phase 1 is early/experimental)
PHASE_SCORES = {
    TrialPhase.PHASE4: 100,
    TrialPhase.PHASE3: 90,
    TrialPhase.PHASE2: 70,
    TrialPhase.PHASE1: 50,
    TrialPhase.EARLY_PHASE1: 30,
    TrialPhase.NA: 60,
}

# Safety scores
SAFETY_SCORES = {
    SafetyLevel.SAFE: 100,
    SafetyLevel.CAUTION: 75,
    SafetyLevel.WARNING: 40,
    SafetyLevel.CRITICAL: 0,
}


def _compute_trial_score(
    trial: ClinicalTrial,
    eligibility: EligibilityAssessment,
    safety: SafetyAssessment,
) -> float:
    """
    Compute final weighted score for a trial-patient pair.
    Returns a score from 0 to 100.

    This function is deterministic — same inputs always give same score.
    No LLM involved. Auditable and explainable.
    """
    # 1. Eligibility score (0-100)
    eligibility_score = eligibility.match_score

    # 2. Safety score (0-100)
    safety_score = SAFETY_SCORES.get(safety.overall_level, 0)

    # 3. Phase score (0-100)
    phase_score = PHASE_SCORES.get(trial.phase, 60)

    # 4. Enrollment score (0-100)
    # Active recruiting = 100, not yet recruiting = 70
    enrollment_score = 100 if trial.status == TrialStatus.RECRUITING else 70
    # Bonus for open enrollment count
    if trial.enrollment_count and trial.enrollment_count > 100:
        enrollment_score = min(100, enrollment_score + 10)

    # 5. Recency score (0-100)
    # Trials started in last 2 years score higher
    recency_score = 60  # default
    if trial.start_date:
        try:
            # Try parsing various date formats
            for fmt in ["%Y-%m-%d", "%Y-%m", "%Y"]:
                try:
                    start = datetime.strptime(trial.start_date[: len(fmt)], fmt)
                    years_ago = (datetime.now() - start).days / 365.25
                    if years_ago <= 1:
                        recency_score = 100
                    elif years_ago <= 2:
                        recency_score = 85
                    elif years_ago <= 3:
                        recency_score = 70
                    else:
                        recency_score = 50
                    break
                except ValueError:
                    continue
        except Exception:
            pass

    # Weighted composite score
    final_score = (
        eligibility_score * WEIGHT_ELIGIBILITY
        + safety_score * WEIGHT_SAFETY
        + phase_score * WEIGHT_PHASE
        + enrollment_score * WEIGHT_ENROLLMENT
        + recency_score * WEIGHT_RECENCY
    )

    return round(final_score, 2)


async def ranker_agent(state: PipelineState) -> PipelineState:
    """
    Agent 5: Ranker

    Combines eligibility and safety assessments to produce ranked trial list.

    Input:  state["raw_trials"], state["eligibility_results"],
            state["safety_assessments"], state["rule_violations"]
    Output: state["ranked_trials"]
    """
    logger.info("[Ranker] Scoring and ranking trials")
    start = time.time()

    raw_trials = state["raw_trials"]
    eligibility_results = state["eligibility_results"]
    safety_assessments = state["safety_assessments"]

    # Build lookup maps
    trial_map = {t.nct_id: t for t in raw_trials}
    eligibility_map: dict[str, EligibilityAssessment] = {}
    for r in eligibility_results:
        nct_id = r["nct_id"]
        assessment_data = r.get("assessment", {})
        try:
            eligibility_map[nct_id] = EligibilityAssessment(**assessment_data)
        except Exception as e:
            logger.warning(f"[Ranker] Failed to parse eligibility for {nct_id}: {e}")

    matched_trials: list[MatchedTrial] = []

    for nct_id, trial in trial_map.items():
        eligibility = eligibility_map.get(nct_id)
        safety = safety_assessments.get(nct_id)

        # Skip trials with no assessment (not evaluated due to pre-filtering)
        if not eligibility:
            continue

        # Create default safe assessment if drug safety wasn't checked
        # (happens for ineligible trials that were skipped in drug safety agent)
        if not safety:
            safety = SafetyAssessment(
                overall_level=SafetyLevel.SAFE,
                is_safe_to_proceed=True,
            )

        # Hard exclude: a definitive NOT_ELIGIBLE decision must never surface
        # as a match, regardless of met_criteria.  The eligibility checker may
        # populate met_criteria with partial hits even when it rules a patient
        # ineligible, so checking met_criteria alone is insufficient.
        # NEEDS_REVIEW and POSSIBLY_ELIGIBLE are intentionally kept so uncertain
        # cases surface to the physician rather than being silently discarded.
        if eligibility.decision == EligibilityDecision.NOT_ELIGIBLE:
            logger.debug(f"[Ranker] Excluding {nct_id} from ranked results (decision=NOT_ELIGIBLE)")
            continue

        # Skip critically unsafe trials
        if safety.overall_level == SafetyLevel.CRITICAL:
            logger.debug(f"[Ranker] Excluding {nct_id} from ranked results (safety=CRITICAL)")
            continue

        # Compute final score
        final_score = _compute_trial_score(trial, eligibility, safety)

        matched_trial = MatchedTrial(
            trial=trial,
            eligibility_assessment=eligibility,
            safety_assessment=safety,
            final_score=final_score,
            rank=0,  # Set after sorting
            is_safe=safety.is_safe_to_proceed,
            decision=eligibility.decision,
            match_percentage=eligibility.match_score,
            confidence=eligibility.confidence,
        )
        matched_trials.append(matched_trial)

    # Sort by final score descending
    matched_trials.sort(key=lambda x: x.final_score, reverse=True)

    # Assign ranks
    for i, matched in enumerate(matched_trials):
        matched.rank = i + 1

    elapsed = time.time() - start
    logger.success(
        f"[Ranker] Complete in {elapsed:.2f}s. "
        f"Ranked {len(matched_trials)} trials. "
        f"Top score: {matched_trials[0].final_score if matched_trials else 'N/A'}"
    )

    return {
        **state,
        "ranked_trials": matched_trials,
    }
