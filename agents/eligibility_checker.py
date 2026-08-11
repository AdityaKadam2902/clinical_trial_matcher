"""
agents/eligibility_checker.py
──────────────────────────────
Agent 3: Eligibility Checker

Uses DSPy with structured signatures to evaluate whether a patient
meets a trial's eligibility criteria.

WHY DSPy HERE:
  - Eligibility criteria are complex clinical text
  - We need typed, validated output (not free-form text)
  - DSPy ensures every field in EligibilityAssessment is populated
  - DSPy's ChainOfThought forces step-by-step reasoning
  - Self-correcting: if output doesn't match schema, DSPy retries

Uses COMPLEX model (70B) — this is the most critical reasoning step.
"""

import dspy
from loguru import logger
from typing import List, Dict, Any
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

from core.config import settings
from agents.pipeline_state import PipelineState
from schemas.trial import EligibilityAssessment, EligibilityDecision


# ── Configure DSPy with Groq ───────────────────────────────────────────────────
# DSPy needs a language model configured globally
groq_lm = dspy.LM(
    model=f"groq/{settings.groq_model_complex}",
    api_key=settings.groq_api_key,
    temperature=0.0,  # Deterministic for medical decisions
    max_tokens=1000,
)
dspy.configure(lm=groq_lm)


# ── DSPy Signature ─────────────────────────────────────────────────────────────

class EligibilityCheckSignature(dspy.Signature):
    """
    Determine if a patient meets clinical trial eligibility criteria.

    DSPy Signature defines the INPUT and OUTPUT fields.
    DSPy automatically structures the prompt and validates the output.
    The docstring becomes the task description in the prompt.
    """
    # Inputs
    patient_profile: str = dspy.InputField(
        desc="Structured patient medical profile including age, sex, conditions, medications, and lab values"
    )
    inclusion_criteria: str = dspy.InputField(
        desc="List of criteria the patient MUST meet to qualify for the trial"
    )
    exclusion_criteria: str = dspy.InputField(
        desc="List of criteria that would DISQUALIFY the patient from the trial"
    )
    trial_name: str = dspy.InputField(
        desc="Name of the clinical trial being evaluated"
    )

    # Outputs — DSPy validates these are present in the response
    is_eligible: bool = dspy.OutputField(
        desc="True if patient appears to meet inclusion criteria and has no exclusion criteria"
    )
    confidence_score: float = dspy.OutputField(
        desc="Confidence level from 0.0 (no confidence) to 1.0 (very confident)"
    )
    match_score: float = dspy.OutputField(
        desc="Eligibility match score from 0 to 100"
    )
    met_criteria: list = dspy.OutputField(
        desc="List of inclusion criteria the patient meets"
    )
    unmet_criteria: list = dspy.OutputField(
        desc="List of inclusion criteria the patient does NOT meet"
    )
    exclusion_triggers: list = dspy.OutputField(
        desc="List of exclusion criteria that apply to this patient"
    )
    reasoning: str = dspy.OutputField(
        desc="Step-by-step clinical reasoning explaining the eligibility decision"
    )


# ── DSPy Module ────────────────────────────────────────────────────────────────

class EligibilityChecker(dspy.Module):
    """
    DSPy Module that wraps the eligibility checking logic.

    dspy.ChainOfThought forces the LLM to reason step-by-step
    before producing the final output. This improves accuracy for
    complex medical reasoning.
    """

    def __init__(self):
        super().__init__()
        # ChainOfThought = "Think step by step" before answering
        self.check = dspy.ChainOfThought(EligibilityCheckSignature)

    def forward(
        self,
        patient_profile: str,
        inclusion_criteria: str,
        exclusion_criteria: str,
        trial_name: str,
    ):
        # DSPy assertion — automatically retries if this fails
        result = self.check(
            patient_profile=patient_profile,
            inclusion_criteria=inclusion_criteria,
            exclusion_criteria=exclusion_criteria,
            trial_name=trial_name,
        )

        # DSPy assertion: confidence must be between 0 and 1
        # dspy.Suggest(
        #     0.0 <= float(result.confidence_score) <= 1.0,
        #     "Confidence score must be between 0.0 and 1.0"
        # )

        return result


# Singleton checker instance
_eligibility_checker = EligibilityChecker()
_executor = ThreadPoolExecutor(max_workers=3)  # For running DSPy in threads


def _check_single_trial_sync(
    patient_profile: str,
    inclusion_criteria: str,
    exclusion_criteria: str,
    trial_name: str,
    nct_id: str,
) -> Dict[str, Any]:
    """
    Synchronous wrapper for DSPy call.
    DSPy is not async-native, so we run it in a thread executor.
    """
    try:
        result = _eligibility_checker(
            patient_profile=patient_profile,
            inclusion_criteria=inclusion_criteria,
            exclusion_criteria=exclusion_criteria,
            trial_name=trial_name,
        )

        # Determine decision enum from is_eligible and match_score
        match_score = float(result.match_score)
        is_eligible = bool(result.is_eligible)
        confidence = float(result.confidence_score)

        if not is_eligible or result.exclusion_triggers:
            decision = EligibilityDecision.NOT_ELIGIBLE
        elif match_score >= 80 and confidence >= 0.7:
            decision = EligibilityDecision.ELIGIBLE
        elif match_score >= 60 and confidence >= 0.5:
            decision = EligibilityDecision.LIKELY_ELIGIBLE
        elif match_score >= 40:
            decision = EligibilityDecision.POSSIBLY_ELIGIBLE
        else:
            decision = EligibilityDecision.NEEDS_REVIEW

        return {
            "nct_id": nct_id,
            "assessment": EligibilityAssessment(
                decision=decision,
                confidence=confidence,
                match_score=match_score,
                met_criteria=result.met_criteria if isinstance(result.met_criteria, list) else [],
                unmet_criteria=result.unmet_criteria if isinstance(result.unmet_criteria, list) else [],
                exclusion_triggers=result.exclusion_triggers if isinstance(result.exclusion_triggers, list) else [],
                reasoning=result.reasoning,
                physician_notes=None,
            ).model_dump(),
        }

    except Exception as e:
        logger.warning(f"[EligibilityChecker] DSPy error for {nct_id}: {e}")
        return {
            "nct_id": nct_id,
            "assessment": EligibilityAssessment(
                decision=EligibilityDecision.NEEDS_REVIEW,
                confidence=0.0,
                match_score=0.0,
                reasoning=f"Eligibility check failed: {str(e)[:200]}",
            ).model_dump(),
        }


async def eligibility_checker_agent(state: PipelineState) -> PipelineState:
    """
    Agent 3: Eligibility Checker

    Evaluates each trial's eligibility criteria against the patient profile.
    Runs DSPy checks concurrently using ThreadPoolExecutor.

    Input:  state["raw_trials"], state["patient"], state["profile_summary"]
    Output: state["eligibility_results"], state["eligible_count"]
    """
    logger.info(f"[EligibilityChecker] Checking {len(state['raw_trials'])} trials")
    start = time.time()

    trials = state["raw_trials"]
    patient_profile_text = state["profile_summary"]

    if not trials:
        logger.warning("[EligibilityChecker] No trials to evaluate")
        return {**state, "eligibility_results": [], "eligible_count": 0}

    # Limit to manageable batch to respect rate limits
    # Rate limit: 30 req/min on Groq free tier
    # With 6 agents, we target max 20 eligibility checks
    trials_to_check = trials[:20]

    # Prepare tasks for concurrent execution
    loop = asyncio.get_event_loop()

    async def check_one(trial):
        """Check one trial asynchronously via thread executor.

        When eligibility criteria are genuinely unavailable (e.g. from the
        TrialsMap fallback), we must not send the LLM a prompt that implies
        criteria exist.  Instead we immediately return a NEEDS_REVIEW result
        with explicit uncertainty — no LLM call is made, no false confidence
        is produced.
        """
        criteria_unavailable = (
            trial.eligibility.raw_text
            == "Eligibility details unavailable from TrialsMap fallback."
            or (
                not trial.eligibility.inclusion
                and not trial.eligibility.exclusion
                and not trial.eligibility.raw_text.strip()
            )
        )

        if criteria_unavailable:
            logger.debug(
                f"[EligibilityChecker] Skipping LLM for {trial.nct_id} — "
                f"eligibility criteria not available (fallback source)"
            )
            return {
                "nct_id": trial.nct_id,
                "assessment": EligibilityAssessment(
                    decision=EligibilityDecision.NEEDS_REVIEW,
                    confidence=0.0,
                    match_score=0.0,
                    met_criteria=[],
                    unmet_criteria=[],
                    exclusion_triggers=[],
                    reasoning=(
                        "Eligibility criteria could not be retrieved for this trial. "
                        "The trial data came from a fallback source that does not provide "
                        "structured inclusion/exclusion criteria. "
                        "A physician or research coordinator must manually review the full "
                        "protocol at: " + trial.url
                    ),
                    physician_notes=(
                        "IMPORTANT: Eligibility was not assessed — criteria unavailable. "
                        "Manual review required before any enrollment decision."
                    ),
                ).model_dump(),
            }

        inclusion_text = "\n".join(
            f"- {c}" for c in trial.eligibility.inclusion[:15]  # Limit to avoid context overflow
        ) or "Not specified"
        exclusion_text = "\n".join(
            f"- {c}" for c in trial.eligibility.exclusion[:15]
        ) or "Not specified"

        return await loop.run_in_executor(
            _executor,
            _check_single_trial_sync,
            patient_profile_text,
            inclusion_text,
            exclusion_text,
            trial.brief_title,
            trial.nct_id,
        )

    # Run all checks concurrently (thread pool handles actual parallelism)
    # Add small delay between batches to respect rate limits
    batch_size = 5
    all_results = []

    for i in range(0, len(trials_to_check), batch_size):
        batch = trials_to_check[i:i + batch_size]
        tasks = [check_one(trial) for trial in batch]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in batch_results:
            if isinstance(result, Exception):
                logger.warning(f"[EligibilityChecker] Batch error: {result}")
            else:
                all_results.append(result)

        # Rate limit buffer between batches
        if i + batch_size < len(trials_to_check):
            await asyncio.sleep(2)

    # Count eligible trials
    eligible_count = sum(
        1 for r in all_results
        if r.get("assessment", {}).get("decision") in [
            EligibilityDecision.ELIGIBLE.value,
            EligibilityDecision.LIKELY_ELIGIBLE.value,
            EligibilityDecision.POSSIBLY_ELIGIBLE.value,
        ]
    )

    elapsed = time.time() - start
    logger.success(
        f"[EligibilityChecker] Complete in {elapsed:.2f}s. "
        f"{eligible_count}/{len(all_results)} trials eligible"
    )

    return {
        **state,
        "eligibility_results": all_results,
        "eligible_count": eligible_count,
    }
