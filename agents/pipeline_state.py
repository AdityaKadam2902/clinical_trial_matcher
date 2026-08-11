"""
agents/pipeline_state.py
────────────────────────
LangGraph shared state definition.

In LangGraph, all agents share a single TypedDict state object.
Each agent reads from state, does its work, and writes results back.
The state flows through the graph like a relay baton.

Think of it as the "shared whiteboard" that all 7 agents can read and write.
"""

from typing import TypedDict, List, Optional, Dict, Any
from schemas.patient import PatientProfile
from schemas.trial import ClinicalTrial, MatchedTrial, SafetyAssessment


class PipelineState(TypedDict):
    """
    Shared state for the Clinical Trial Matcher agent pipeline.
    Fields are populated incrementally as each agent completes.
    """

    # ── Input (set before pipeline starts) ─────────────────────────────────────
    patient: PatientProfile              # FHIR R4 patient profile
    search_id: str                       # Unique ID for this search session
    requested_page: int                  # Which page of results user wants
    page_size: int                       # Results per page

    # ── Agent 1: Profile Parser output ─────────────────────────────────────────
    normalized_conditions: List[str]     # Cleaned condition names for API queries
    normalized_medications: List[str]    # RxNorm-normalized medication names
    search_keywords: List[str]           # Extracted search keywords
    profile_summary: str                 # Human-readable profile summary

    # ── Agent 2: Trial Fetcher output ───────────────────────────────────────────
    raw_trials: List[ClinicalTrial]      # Cleaned trials from ClinicalTrials.gov
    total_trials_found: int              # Total available (for pagination)
    fetch_error: Optional[str]           # Error message if fetch failed
    trials_dropped_by_phase: int         # Trials eliminated by phase filter
    trials_dropped_by_location: int      # Trials eliminated by location filter

    # ── Agent 3: Eligibility Checker output ─────────────────────────────────────
    eligibility_results: List[Dict[str, Any]]  # Per-trial eligibility assessment
    eligible_count: int                         # How many trials passed eligibility

    # ── Agent 4: Drug Safety Agent output ───────────────────────────────────────
    safety_assessments: Dict[str, SafetyAssessment]  # nct_id -> SafetyAssessment
    drug_flags: List[str]               # High-level safety flag summaries

    # ── Agent 5: Rule Engine output ─────────────────────────────────────────────
    rule_violations: Dict[str, List[str]]  # nct_id -> list of violation descriptions
    pipeline_halted: bool                   # True if safety halt was triggered
    halt_reason: Optional[str]             # Why pipeline was halted

    # ── Agent 6: Ranker output ──────────────────────────────────────────────────
    ranked_trials: List[MatchedTrial]   # Fully scored and ranked trials

    # ── Agent 7: Report Generator output ────────────────────────────────────────
    physician_summary: str              # Final AI-generated physician summary
    processing_start_time: float        # Unix timestamp when pipeline started
