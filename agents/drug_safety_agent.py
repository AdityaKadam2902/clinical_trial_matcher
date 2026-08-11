"""
agents/drug_safety_agent.py
────────────────────────────
Agent 4: Drug Safety Agent

Checks for drug interactions between patient's current medications
and the drugs being tested in each trial.

Uses:
1. OpenFDA API — official FDA drug interaction database
2. RxNorm API  — drug normalization for consistent matching
3. Rule Engine — hard contraindication rules (runs first)

This agent runs BEFORE the LLM ranker so safety information
is available for ranking decisions.
"""

import asyncio
from loguru import logger
from typing import Dict, List
import time

from agents.pipeline_state import PipelineState
from rules.safety_rules import rule_engine, RuleEngineResult
from utils.api_clients import openfda_client
from schemas.trial import SafetyAssessment, SafetyLevel, DrugInteractionFlag


async def drug_safety_agent(state: PipelineState) -> PipelineState:
    """
    Agent 4: Drug Safety Agent

    For each trial that passed eligibility checking:
    1. Run rule engine (fast, deterministic, no API)
    2. Check OpenFDA for drug interactions
    3. Combine results into SafetyAssessment

    Input:  state["eligibility_results"], state["raw_trials"], state["patient"]
    Output: state["safety_assessments"], state["drug_flags"],
            state["pipeline_halted"], state["halt_reason"]
    """
    logger.info("[DrugSafety] Running safety checks")
    start = time.time()

    patient = state["patient"]
    raw_trials = state["raw_trials"]
    eligibility_results = state["eligibility_results"]

    # Build lookup: nct_id -> trial
    trial_map = {trial.nct_id: trial for trial in raw_trials}

    # Only check trials that passed eligibility (optimization)
    eligible_nct_ids = {
        r["nct_id"] for r in eligibility_results
        if r.get("assessment", {}).get("decision") not in ["NOT_ELIGIBLE"]
    }

    safety_assessments: Dict[str, SafetyAssessment] = {}
    drug_flags: List[str] = []
    rule_violations_map: Dict[str, List[str]] = {}

    # Process each eligible trial
    for nct_id in eligible_nct_ids:
        trial = trial_map.get(nct_id)
        if not trial:
            continue

        # ── Step 1: Run deterministic rule engine (no I/O) ────────────────────
        rule_result: RuleEngineResult = rule_engine.evaluate(patient, trial)
        rule_violations_map[nct_id] = rule_result.flags_summary

        # If rule engine says halt — this is a HARD stop
        if rule_result.halt_pipeline:
            safety = SafetyAssessment(
                overall_level=SafetyLevel.CRITICAL,
                drug_interactions=[],
                allergy_conflicts=[],
                contraindications=rule_result.flags_summary,
                rule_engine_flags=rule_result.flags_summary,
                is_safe_to_proceed=False,
                halt_reason=rule_result.flags_summary[0] if rule_result.flags_summary else "Safety rule violation",
            )
            safety_assessments[nct_id] = safety
            logger.warning(f"[DrugSafety] {nct_id} HALTED by rule engine: {rule_result.flags_summary}")
            continue

        # ── Step 2: OpenFDA drug interaction check ────────────────────────────
        fda_interactions: List[DrugInteractionFlag] = []
        patient_meds = state["normalized_medications"]

        if patient_meds and trial.intervention_names:
            # Check each trial drug against patient medications
            fda_tasks = [
                openfda_client.get_drug_interactions(
                    drug_name=trial_drug,
                    patient_medications=patient_meds,
                )
                for trial_drug in trial.intervention_names[:3]  # Check first 3 drugs
            ]

            try:
                fda_results = await asyncio.gather(*fda_tasks, return_exceptions=True)
                for result in fda_results:
                    if isinstance(result, list):
                        fda_interactions.extend(result)
                    elif isinstance(result, Exception):
                        logger.debug(f"[DrugSafety] FDA check error: {result}")
            except Exception as e:
                logger.warning(f"[DrugSafety] FDA batch check failed for {nct_id}: {e}")

        # ── Step 3: Determine overall safety level ────────────────────────────
        has_critical = any(f.severity == SafetyLevel.CRITICAL for f in fda_interactions)
        has_warning = any(f.severity == SafetyLevel.WARNING for f in fda_interactions)
        has_rule_violations = bool(rule_result.violations)

        if has_critical:
            overall_level = SafetyLevel.CRITICAL
            is_safe = False
        elif has_warning or has_rule_violations:
            overall_level = SafetyLevel.WARNING
            is_safe = True  # Warning doesn't stop enrollment, just requires review
        elif rule_result.overall_severity == SafetyLevel.CAUTION:
            overall_level = SafetyLevel.CAUTION
            is_safe = True
        else:
            overall_level = SafetyLevel.SAFE
            is_safe = True

        # Build allergy conflicts list
        allergy_conflicts = []
        if patient.allergies:
            for allergen in patient.allergies:
                for drug in trial.intervention_names:
                    if allergen.substance.lower() in drug.lower():
                        allergy_conflicts.append(
                            f"Allergy to {allergen.substance} — trial uses {drug}"
                        )

        safety = SafetyAssessment(
            overall_level=overall_level,
            drug_interactions=fda_interactions,
            allergy_conflicts=allergy_conflicts,
            contraindications=[v.description for v in rule_result.violations if "contraindication" in v.description.lower()],
            rule_engine_flags=rule_result.flags_summary,
            is_safe_to_proceed=is_safe,
            halt_reason=None,
        )
        safety_assessments[nct_id] = safety

        # Collect high-level drug flags for summary
        for interaction in fda_interactions:
            if interaction.severity in [SafetyLevel.CRITICAL, SafetyLevel.WARNING]:
                drug_flags.append(
                    f"{nct_id}: {interaction.patient_drug} + {interaction.trial_drug} "
                    f"({interaction.severity.value})"
                )

    elapsed = time.time() - start
    critical_count = sum(
        1 for s in safety_assessments.values()
        if s.overall_level == SafetyLevel.CRITICAL
    )
    logger.success(
        f"[DrugSafety] Complete in {elapsed:.2f}s. "
        f"{len(safety_assessments)} trials assessed, {critical_count} critical flags"
    )

    return {
        **state,
        "safety_assessments": safety_assessments,
        "drug_flags": drug_flags,
        "rule_violations": rule_violations_map,
        "pipeline_halted": False,  # Only halt if ALL trials are critical
        "halt_reason": None,
    }
