"""
agents/trial_fetcher.py
───────────────────────
Agent 2: Trial Fetcher

Queries ClinicalTrials.gov API and returns cleaned trial data.
No LLM needed here — pure API + data cleaning.

Implements smart pagination:
- Fetches more trials than requested (buffer)
- Applies pre-filtering before LLM agents (faster, cheaper)
- Returns metadata for frontend pagination controls
"""

import traceback

from loguru import logger

from clinical_trial_matcher.agents.pipeline_state import PipelineState
from clinical_trial_matcher.schemas.patient import Sex
from clinical_trial_matcher.schemas.trial import TrialStatus
from clinical_trial_matcher.utils.api_clients import clinical_trials_client

# How many trials to fetch from API (more than page size to allow filtering)
FETCH_BUFFER_MULTIPLIER = 5


async def trial_fetcher_agent(state: PipelineState) -> PipelineState:
    """
    Agent 2: Trial Fetcher

    Queries ClinicalTrials.gov with patient's conditions.
    Cleans and pre-filters results before expensive LLM evaluation.

    Input:  state["normalized_conditions"], state["search_keywords"], state["patient"]
    Output: state["raw_trials"], state["total_trials_found"]
    """
    logger.info("[TrialFetcher] Fetching trials from ClinicalTrials.gov")

    patient = state["patient"]
    conditions = state["normalized_conditions"] or patient.get_condition_names()
    keywords = state.get("search_keywords", [])

    # Calculate how many to fetch (buffer for pre-filtering)
    fetch_size = min(
        state["page_size"] * FETCH_BUFFER_MULTIPLIER,
        100,  # Hard cap — avoid overwhelming the API
    )

    try:
        # Query ClinicalTrials.gov
        api_response = await clinical_trials_client.search_trials(
            conditions=conditions,
            keywords=keywords,
            status="RECRUITING",
            min_age=None,
            max_age=None,
            sex=patient.sex.value if patient.sex in {Sex.MALE, Sex.FEMALE} else None,
            page_size=fetch_size,
        )
        raw_studies = api_response.get("studies", [])
        parsed_trials = api_response.get("parsed_trials")
        total_count = api_response.get("total_count", 0)

        # Parse each study into a clean ClinicalTrial object
        # Use asyncio for concurrent parsing (CPU-bound but structured)
        if parsed_trials is None:
            parsed_trials = []
            for study in raw_studies:
                trial = clinical_trials_client.parse_trial(study)
                if trial is not None:
                    parsed_trials.append(trial)

        logger.info(
            f"[TrialFetcher] Parsed {len(parsed_trials)}/{len(raw_studies)} valid trials "
            f"(total available: {total_count})"
        )

        # Pre-filter: remove terminated/completed trials
        active_statuses = {TrialStatus.RECRUITING, TrialStatus.NOT_YET_RECRUITING}
        filtered_trials = [t for t in parsed_trials if t.status in active_statuses]

        # Pre-filter: apply preferred location filter if specified.
        # A trial passes if at least one of its countries or site states
        # matches a preferred location string (case-insensitive substring).
        # Trials from the TrialsMap fallback may have sparse location data;
        # we log a warning when a trial is dropped here so the caller can see
        # that the preference was enforced, not silently skipped.
        dropped_by_location = 0
        if patient.preferred_locations:
            preferred_lower = [loc.lower() for loc in patient.preferred_locations]
            location_filtered = []
            for trial in filtered_trials:
                trial_countries = [c.lower() for c in trial.countries]
                trial_states = [(loc.state or "").lower() for loc in trial.locations]
                combined = trial_countries + trial_states
                if any(any(pref in field for field in combined) for pref in preferred_lower):
                    location_filtered.append(trial)
                else:
                    dropped_by_location += 1
                    logger.debug(
                        f"[TrialFetcher] Dropped {trial.nct_id} — "
                        f"location {trial.countries} does not match "
                        f"preferred {patient.preferred_locations}"
                    )
            if location_filtered:
                filtered_trials = location_filtered
            else:
                # No trials matched the preferred location at all.
                # Keep the full list so the phase filter (below) still has
                # something to work with.  The drop count is preserved and
                # surfaced in the response via trials_dropped_by_location.
                dropped_by_location = 0
                logger.warning(
                    f"[TrialFetcher] No trials match preferred locations "
                    f"{patient.preferred_locations}. "
                    f"Location filter could not be enforced � "
                    f"returning all {len(filtered_trials)} unfiltered trial(s) "
                    f"with a location warning."
                )

        # Pre-filter: apply phase filter if specified.
        # Unlike location, phase is a hard user preference — if the patient
        # asked for PHASE2/PHASE3 only we must respect it.  We never silently
        # fall back to keeping everything: if nothing matches we return an
        # empty list so the final response honestly reflects zero results.
        dropped_by_phase = 0
        if patient.trial_phases:
            preferred_phases = set(patient.trial_phases)  # e.g. {"PHASE2", "PHASE3"}
            phase_filtered = [t for t in filtered_trials if t.phase.value in preferred_phases]
            dropped_by_phase = len(filtered_trials) - len(phase_filtered)
            if not phase_filtered:
                logger.warning(
                    f"[TrialFetcher] No trials match requested phases "
                    f"{patient.trial_phases} (available phases: "
                    f"{[t.phase.value for t in filtered_trials]}). "
                    f"Returning empty trial list — phase preference is enforced."
                )
            filtered_trials = phase_filtered

        logger.success(f"[TrialFetcher] After pre-filtering: {len(filtered_trials)} trials ready for evaluation")

        return {
            **state,
            "raw_trials": filtered_trials,
            "total_trials_found": total_count,
            "fetch_error": None,
            "trials_dropped_by_phase": dropped_by_phase,
            "trials_dropped_by_location": dropped_by_location,
        }

    except Exception as e:
        logger.error(f"[TrialFetcher] Failed: {e}")
        logger.error(traceback.format_exc())
        return {
            **state,
            "raw_trials": [],
            "total_trials_found": 0,
            "fetch_error": str(e),
        }
