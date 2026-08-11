"""
agents/pipeline.py
──────────────────
LangGraph pipeline orchestration for the Clinical Trial Matcher.

Defines the directed graph of agents with conditional routing.
The graph has one safety bypass: if drug safety finds critical issues,
a subset of trials are flagged but the pipeline continues.

Graph flow:
  profile_parser → trial_fetcher → eligibility_checker
  → drug_safety → ranker → report_generator → END
"""

from langgraph.graph import StateGraph, END
from loguru import logger
import time
import uuid

from agents.pipeline_state import PipelineState
from agents.profile_parser import profile_parser_agent
from agents.trial_fetcher import trial_fetcher_agent
from agents.eligibility_checker import eligibility_checker_agent
from agents.drug_safety_agent import drug_safety_agent
from agents.ranker_agent import ranker_agent
from agents.report_generator import report_generator_agent
from schemas.trial import MatchResponse, PaginationMeta
from schemas.patient import PatientProfile
from core.config import settings


def _should_continue_after_fetch(state: PipelineState) -> str:
    """
    Conditional edge after trial fetcher.
    If no trials found, skip to report generation directly.
    """
    if state.get("fetch_error") or not state.get("raw_trials"):
        logger.warning("[Pipeline] No trials fetched — routing to report directly")
        return "report_generator"
    return "eligibility_checker"


def build_pipeline() -> StateGraph:
    """
    Build and compile the LangGraph agent pipeline.

    Returns a compiled StateGraph that can be invoked with a PipelineState.
    """
    graph = StateGraph(PipelineState)

    # Register all agents as nodes
    graph.add_node("profile_parser",      profile_parser_agent)
    graph.add_node("trial_fetcher",       trial_fetcher_agent)
    graph.add_node("eligibility_checker", eligibility_checker_agent)
    graph.add_node("drug_safety",         drug_safety_agent)
    graph.add_node("ranker",              ranker_agent)
    graph.add_node("report_generator",    report_generator_agent)

    # Entry point
    graph.set_entry_point("profile_parser")

    # Sequential edges
    graph.add_edge("profile_parser", "trial_fetcher")

    # Conditional edge after fetcher
    graph.add_conditional_edges(
        "trial_fetcher",
        _should_continue_after_fetch,
        {
            "eligibility_checker": "eligibility_checker",
            "report_generator":    "report_generator",
        }
    )

    # Continue pipeline
    graph.add_edge("eligibility_checker", "drug_safety")
    graph.add_edge("drug_safety",         "ranker")
    graph.add_edge("ranker",              "report_generator")
    graph.add_edge("report_generator",    END)

    compiled = graph.compile()
    logger.success("Clinical Trial Matcher pipeline compiled successfully")
    return compiled


# Global pipeline instance — compiled once at startup
pipeline = build_pipeline()


# ── Pipeline entry function ────────────────────────────────────────────────────

async def run_pipeline(
    patient: PatientProfile,
    page: int = 1,
    page_size: int = 10,
) -> MatchResponse:
    """
    Run the complete 6-agent pipeline for a patient.

    This is the main function called by the FastAPI route.
    Takes a patient profile and returns a fully structured MatchResponse
    with pagination, rankings, safety assessments, and physician summary.
    """
    search_id = f"SEARCH-{str(uuid.uuid4())[:8].upper()}"
    start_time = time.time()

    logger.info(
        f"[Pipeline] Starting run {search_id} for patient {patient.patient_id}"
    )

    # Build initial state
    initial_state: PipelineState = {
        # Input
        "patient": patient,
        "search_id": search_id,
        "requested_page": page,
        "page_size": page_size,
        "processing_start_time": start_time,

        # These will be populated by agents
        "normalized_conditions": [],
        "normalized_medications": [],
        "search_keywords": [],
        "profile_summary": "",
        "raw_trials": [],
        "total_trials_found": 0,
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

    # Invoke the pipeline
    try:
        final_state = await pipeline.ainvoke(initial_state)
    except Exception as e:
        logger.error(f"[Pipeline] Critical error in run {search_id}: {e}")
        # Return graceful error response
        return MatchResponse(
            patient_id=patient.patient_id,
            search_id=search_id,
            query_summary=f"Search failed: {str(e)[:200]}",
            matches=[],
            pagination=PaginationMeta(
                page=page, page_size=page_size,
                total_items=0, total_pages=0,
                has_next=False, has_previous=False,
            ),
            total_trials_searched=0,
            total_eligible=0,
            processing_time_seconds=time.time() - start_time,
            physician_summary="Pipeline error — please try again.",
        )

    # ── Apply pagination to ranked results ─────────────────────────────────────
    all_ranked = final_state.get("ranked_trials", [])
    total_items = len(all_ranked)
    total_pages = max(1, (total_items + page_size - 1) // page_size)

    # Slice for requested page
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_results = all_ranked[start_idx:end_idx]

    # Build query summary — values must match what is returned in the response
    # body so the summary is never internally inconsistent.
    conditions = patient.get_condition_names()
    eligible_count = final_state.get("eligible_count", 0)
    phase_note = (
        f" Phases requested: {', '.join(patient.trial_phases)}."
        if patient.trial_phases else ""
    )
    location_note = (
        f" Location preference: {', '.join(patient.preferred_locations)}."
        if patient.preferred_locations else ""
    )
    dropped_phase    = final_state.get("trials_dropped_by_phase", 0)
    dropped_location = final_state.get("trials_dropped_by_location", 0)
    filter_note = ""
    if dropped_phase:
        filter_note += f" {dropped_phase} trial(s) excluded by phase filter."
    if dropped_location:
        filter_note += f" {dropped_location} trial(s) excluded by location filter."

    query_summary = (
        f"Searched for trials matching: {', '.join(conditions[:3])}."
        f"{phase_note}{location_note} "
        f"Found {final_state.get('total_trials_found', 0)} total trials, "
        f"evaluated {len(final_state.get('eligibility_results', []))}, "
        f"{eligible_count} eligible, {total_items} returned after ranking."
        f"{filter_note}"
    )

    processing_time = time.time() - start_time
    logger.success(
        f"[Pipeline] Run {search_id} complete in {processing_time:.2f}s. "
        f"{total_items} matches, page {page}/{total_pages}"
    )

    return MatchResponse(
        patient_id=patient.patient_id,
        search_id=search_id,
        query_summary=query_summary,
        matches=page_results,
        pagination=PaginationMeta(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1,
        ),
        total_trials_searched=final_state.get("total_trials_found", 0),
        total_eligible=final_state.get("eligible_count", 0),
        processing_time_seconds=round(processing_time, 2),
        safety_halt=final_state.get("pipeline_halted", False),
        safety_halt_reason=final_state.get("halt_reason"),
        physician_summary=final_state.get("physician_summary", ""),
    )
