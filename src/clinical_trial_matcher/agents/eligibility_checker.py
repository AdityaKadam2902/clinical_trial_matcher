"""
agents/eligibility_checker.py
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Agent 3: Eligibility Checker

Uses DSPy with structured signatures to evaluate whether a patient
meets a trial's eligibility criteria.

WHY DSPy HERE:
  - Eligibility criteria are complex clinical text
  - We need typed, validated output (not free-form text)
  - DSPy ensures every field in EligibilityAssessment is populated
  - DSPy's ChainOfThought forces step-by-step reasoning
  - Self-correcting: if output doesn't match schema, DSPy retries

Uses the configured complex model â€” this is the most critical reasoning step.
"""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import dspy
from loguru import logger

from clinical_trial_matcher.agents.llm import get_dspy_lm
from clinical_trial_matcher.agents.pipeline_state import PipelineState
from clinical_trial_matcher.core.config import settings
from clinical_trial_matcher.schemas.trial import EligibilityAssessment, EligibilityDecision

# â”€â”€ Configure DSPy â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# DSPy needs a language model configured globally. The provider is selected by
# settings.llm_provider (local by default, Groq only for explicit development).
dspy.configure_cache(enable_disk_cache=False)
dspy.configure(lm=get_dspy_lm())


# â”€â”€ DSPy Signature â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


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
    inclusion_criteria: str = dspy.InputField(desc="List of criteria the patient MUST meet to qualify for the trial")
    exclusion_criteria: str = dspy.InputField(desc="List of criteria that would DISQUALIFY the patient from the trial")
    trial_name: str = dspy.InputField(desc="Name of the clinical trial being evaluated")

    # Outputs â€” DSPy validates these are present in the response
    is_eligible: bool = dspy.OutputField(
        desc="True if patient appears to meet inclusion criteria and has no exclusion criteria"
    )
    confidence_score: float = dspy.OutputField(desc="Confidence level from 0.0 (no confidence) to 1.0 (very confident)")
    match_score: float = dspy.OutputField(desc="Eligibility match score from 0 to 100")
    met_criteria: list = dspy.OutputField(desc="List of inclusion criteria the patient meets")
    unmet_criteria: list = dspy.OutputField(desc="List of inclusion criteria the patient does NOT meet")
    exclusion_triggers: list = dspy.OutputField(desc="List of exclusion criteria that apply to this patient")
    reasoning: str = dspy.OutputField(desc="Step-by-step clinical reasoning explaining the eligibility decision")


# â”€â”€ DSPy Module â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


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
        # DSPy assertion â€” automatically retries if this fails
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


def _coerce_text(value: Any) -> str:
    """Turn a model-produced value into a clean string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("value", "criterion", "text", "description", "reason"):
            if value.get(key) not in (None, ""):
                return _coerce_text(value[key])
        parts = []
        for item in value.values():
            text = _coerce_text(item)
            if text:
                parts.append(text)
        return "; ".join(parts)
    if isinstance(value, (list, tuple, set)):
        parts = []
        for item in value:
            text = _coerce_text(item)
            if text:
                parts.append(text)
        return "; ".join(parts)
    return str(value).strip()


def _coerce_string_list(value: Any, *, max_items: int = 25) -> list[str]:
    """Normalise list-like model output into ``list[str]``.

    Small local models frequently return objects such as
    ``{"criterion": "..."}`` or ``{"key": "age", "value": "18+"}`` instead of
    plain strings. Pydantic would reject those, which used to turn every
    eligibility check into NEEDS_REVIEW.
    """
    if value is None:
        return []
    items = list(value) if isinstance(value, (list, tuple, set)) else [value]
    cleaned: list[str] = []
    for item in items:
        text = _coerce_text(item)
        if text:
            cleaned.append(text[:500])
        if len(cleaned) >= max_items:
            break
    return cleaned


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "y", "1", "eligible"}
    return bool(value)


def _not_evaluated(trial, reason: str) -> dict[str, Any]:
    """Return an honest NEEDS_REVIEW result for a trial we did not evaluate."""
    messages = {
        "timeout": "Eligibility evaluation exceeded the per-trial time limit.",
        "budget_exhausted": "The pipeline time budget was exhausted before this trial could be evaluated.",
        "llm_error": "The eligibility model returned an unusable response for this trial.",
    }
    explanation = messages.get(reason, "Eligibility could not be evaluated automatically.")
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
                f"{explanation} This is not an eligibility decision: the trial must be reviewed manually at {trial.url}"
            ),
            physician_notes=(
                "IMPORTANT: Eligibility was not assessed automatically. Manual review required "
                "before any enrollment decision."
            ),
        ).model_dump(),
    }


def _deterministic_assessment(trial, patient) -> EligibilityAssessment | None:
    """Decide hard protocol facts without an LLM call.

    Minimum age, maximum age and sex eligibility are parsed deterministically from the
    ClinicalTrials.gov protocol. They must not be re-derived by the model: that is both
    the slowest and the least reliable part of the pipeline.
    """
    criteria = trial.eligibility
    blockers: list[str] = []

    if criteria.minimum_age is not None and patient.age < criteria.minimum_age:
        blockers.append(f"patient age {patient.age} is below the trial minimum age of {criteria.minimum_age}")
    if criteria.maximum_age is not None and patient.age > criteria.maximum_age:
        blockers.append(f"patient age {patient.age} is above the trial maximum age of {criteria.maximum_age}")
    if criteria.sex_eligible == "Male" and patient.sex != "male":
        blockers.append("the trial only enrolls male participants")
    if criteria.sex_eligible == "Female" and patient.sex != "female":
        blockers.append("the trial only enrolls female participants")

    if not blockers:
        return None

    return EligibilityAssessment(
        decision=EligibilityDecision.NOT_ELIGIBLE,
        confidence=1.0,
        match_score=0.0,
        met_criteria=[],
        unmet_criteria=blockers,
        exclusion_triggers=blockers,
        reasoning="Deterministic protocol screen: " + "; ".join(blockers) + ".",
        physician_notes="Excluded by protocol age/sex criteria before LLM evaluation.",
    )


def _check_single_trial_sync(
    patient_profile: str,
    inclusion_criteria: str,
    exclusion_criteria: str,
    trial_name: str,
    nct_id: str,
) -> dict[str, Any]:
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

        # Normalise model output before validation: local models may return
        # dicts, strings, or 0-1 scores instead of the documented shapes.
        match_score = _coerce_float(result.match_score)
        if 0.0 < match_score <= 1.0:
            match_score *= 100.0
        match_score = max(0.0, min(100.0, match_score))

        confidence = _coerce_float(result.confidence_score)
        if 1.0 < confidence <= 100.0:
            confidence /= 100.0
        confidence = max(0.0, min(1.0, confidence))

        is_eligible = _coerce_bool(result.is_eligible)
        met_criteria = _coerce_string_list(result.met_criteria)
        unmet_criteria = _coerce_string_list(result.unmet_criteria)
        exclusion_triggers = _coerce_string_list(result.exclusion_triggers)

        if not is_eligible or exclusion_triggers:
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
                met_criteria=met_criteria,
                unmet_criteria=unmet_criteria,
                exclusion_triggers=exclusion_triggers,
                reasoning=_coerce_text(result.reasoning) or "No reasoning provided.",
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

    # Limit to a manageable batch. Groq's free tier is rate limited; local
    # models are slower per call, so they use a smaller default cap.
    max_trials = 20
    if settings.llm_provider == "local":
        max_trials = min(max_trials, settings.local_llm_max_eligibility_trials)
    trials_to_check = trials[:max_trials]

    # Prepare tasks for concurrent execution
    loop = asyncio.get_running_loop()

    async def check_one(trial, timeout_seconds: float):
        """Check one trial asynchronously via thread executor.

        When eligibility criteria are genuinely unavailable (e.g. from the
        TrialsMap fallback), we must not send the LLM a prompt that implies
        criteria exist.  Instead we immediately return a NEEDS_REVIEW result
        with explicit uncertainty â€” no LLM call is made, no false confidence
        is produced.
        """
        criteria_unavailable = (
            trial.eligibility.raw_text == "Eligibility details unavailable from TrialsMap fallback."
            or (
                not trial.eligibility.inclusion
                and not trial.eligibility.exclusion
                and not trial.eligibility.raw_text.strip()
            )
        )

        if criteria_unavailable:
            logger.debug(
                f"[EligibilityChecker] Skipping LLM for {trial.nct_id} â€” "
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
                        "IMPORTANT: Eligibility was not assessed â€” criteria unavailable. "
                        "Manual review required before any enrollment decision."
                    ),
                ).model_dump(),
            }

        deterministic = _deterministic_assessment(trial, state["patient"])
        if deterministic is not None:
            logger.debug(f"[EligibilityChecker] {trial.nct_id} excluded by protocol age/sex screen (no LLM call)")
            return {"nct_id": trial.nct_id, "assessment": deterministic.model_dump()}

        inclusion_text = (
            "\n".join(
                f"- {c}"
                for c in trial.eligibility.inclusion[:15]  # Limit to avoid context overflow
            )
            or "Not specified"
        )
        exclusion_text = "\n".join(f"- {c}" for c in trial.eligibility.exclusion[:15]) or "Not specified"

        try:
            return await asyncio.wait_for(
                loop.run_in_executor(
                    _executor,
                    _check_single_trial_sync,
                    patient_profile_text,
                    inclusion_text,
                    exclusion_text,
                    trial.brief_title,
                    trial.nct_id,
                ),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            logger.warning(
                f"[EligibilityChecker] {trial.nct_id} exceeded the "
                f"{timeout_seconds:.0f}s evaluation limit; returning NEEDS_REVIEW"
            )
            return _not_evaluated(trial, "timeout")

    # Run all checks concurrently (thread pool handles actual parallelism).
    # A hard deadline guarantees the API request finishes even when the local
    # model is slow: trials that do not fit are reported as not evaluated.
    deadline = start + settings.pipeline_budget_seconds
    batch_size = 5
    all_results: list[dict[str, Any]] = []

    for i in range(0, len(trials_to_check), batch_size):
        remaining = deadline - time.time()
        if remaining <= 0:
            skipped = trials_to_check[i:]
            logger.warning(
                f"[EligibilityChecker] Time budget exhausted; "
                f"{len(skipped)} trial(s) returned as NEEDS_REVIEW without evaluation"
            )
            all_results.extend(_not_evaluated(trial, "budget_exhausted") for trial in skipped)
            break

        batch = trials_to_check[i : i + batch_size]
        # Never let one call outlive the remaining pipeline budget.
        per_call_timeout = max(0.1, min(settings.eligibility_timeout_seconds, remaining))
        tasks = [check_one(trial, per_call_timeout) for trial in batch]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for trial, result in zip(batch, batch_results, strict=False):
            if isinstance(result, BaseException):
                # Preserve coverage: an unexpected failure is not a reason to
                # silently drop the trial from the response.
                logger.warning(f"[EligibilityChecker] Batch error for {trial.nct_id}: {result}")
                all_results.append(_not_evaluated(trial, "llm_error"))
            else:
                all_results.append(result)

        # Rate limit buffer between batches (only needed for the hosted API)
        if settings.llm_provider == "groq" and i + batch_size < len(trials_to_check):
            await asyncio.sleep(2)

    # Count eligible trials
    eligible_count = 0
    eligible_decisions = {
        EligibilityDecision.ELIGIBLE.value,
        EligibilityDecision.LIKELY_ELIGIBLE.value,
        EligibilityDecision.POSSIBLY_ELIGIBLE.value,
    }
    for result in all_results:
        decision = result.get("assessment", {}).get("decision")
        if decision in eligible_decisions:
            eligible_count += 1

    elapsed = time.time() - start
    logger.success(
        f"[EligibilityChecker] Complete in {elapsed:.2f}s. {eligible_count}/{len(all_results)} trials eligible"
    )

    return {
        **state,
        "eligibility_results": all_results,
        "eligible_count": eligible_count,
    }
