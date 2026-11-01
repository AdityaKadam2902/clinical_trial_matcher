"""
schemas/trial.py
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Pydantic schemas for cleaned, structured clinical trial data.

ClinicalTrials.gov API returns raw, messy JSON with nested fields,
HTML tags in descriptions, inconsistent formatting, and sometimes
missing fields. These schemas define exactly what cleaned output looks like.

Every field is typed and validated. Frontend always receives consistent data.
"""

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# â”€â”€ Enums â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TrialStatus(StrEnum):
    RECRUITING = "RECRUITING"
    NOT_YET_RECRUITING = "NOT_YET_RECRUITING"
    ACTIVE_NOT_RECRUITING = "ACTIVE_NOT_RECRUITING"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"
    WITHDRAWN = "WITHDRAWN"
    SUSPENDED = "SUSPENDED"
    UNKNOWN = "UNKNOWN"


class TrialPhase(StrEnum):
    PHASE1 = "PHASE1"
    PHASE2 = "PHASE2"
    PHASE3 = "PHASE3"
    PHASE4 = "PHASE4"
    EARLY_PHASE1 = "EARLY_PHASE1"
    NA = "NA"


class EligibilityDecision(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    LIKELY_ELIGIBLE = "LIKELY_ELIGIBLE"
    POSSIBLY_ELIGIBLE = "POSSIBLY_ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class SafetyLevel(StrEnum):
    SAFE = "SAFE"
    CAUTION = "CAUTION"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


# â”€â”€ Sub-schemas â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TrialLocation(BaseModel):
    """A single trial site location."""

    facility: str | None = None
    city: str | None = None
    state: str | None = None
    country: str = Field(default="United States")
    zip_code: str | None = None
    status: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None


class TrialIntervention(BaseModel):
    """A drug, device, or procedure being tested in the trial."""

    intervention_type: str = Field(description="e.g. 'Drug', 'Device', 'Behavioral'")
    name: str
    description: str | None = None
    arm_group: str | None = None


class EligibilityCriteria(BaseModel):
    """
    Parsed eligibility criteria.
    Raw text from ClinicalTrials.gov is split into
    structured inclusion and exclusion lists.
    """

    raw_text: str = Field(description="Original unprocessed criteria text")
    inclusion: list[str] = Field(default_factory=list, description="Parsed list of inclusion criteria")
    exclusion: list[str] = Field(default_factory=list, description="Parsed list of exclusion criteria")
    minimum_age: int | None = Field(None, description="Minimum age in years")
    maximum_age: int | None = Field(None, description="Maximum age in years")
    sex_eligible: Literal["All", "Male", "Female"] | None = Field(default="All")
    accepts_healthy_volunteers: bool = Field(default=False)


class DrugInteractionFlag(BaseModel):
    """A drug interaction warning between patient medication and trial drug."""

    patient_drug: str
    trial_drug: str
    interaction_description: str
    severity: SafetyLevel
    source: Literal["OpenFDA", "RxNorm", "RuleEngine"] = "OpenFDA"
    recommendation: str


class SafetyAssessment(BaseModel):
    """Complete safety assessment for a trial-patient combination."""

    overall_level: SafetyLevel
    drug_interactions: list[DrugInteractionFlag] = Field(default_factory=list)
    allergy_conflicts: list[str] = Field(default_factory=list)
    contraindications: list[str] = Field(default_factory=list)
    rule_engine_flags: list[str] = Field(default_factory=list)
    is_safe_to_proceed: bool
    halt_reason: str | None = Field(None, description="If pipeline halted, explains why")


class EligibilityAssessment(BaseModel):
    """LLM-generated eligibility assessment for a specific trial."""

    decision: EligibilityDecision
    confidence: float = Field(ge=0.0, le=1.0)
    match_score: float = Field(ge=0.0, le=100.0, description="0-100 eligibility score")
    met_criteria: list[str] = Field(default_factory=list, description="Inclusion criteria the patient meets")
    unmet_criteria: list[str] = Field(default_factory=list, description="Inclusion criteria the patient does NOT meet")
    exclusion_triggers: list[str] = Field(
        default_factory=list, description="Exclusion criteria that apply to this patient"
    )
    reasoning: str = Field(description="Step-by-step clinical reasoning")
    physician_notes: str | None = Field(None, description="Important notes for the referring physician")


# â”€â”€ Main Trial Schema â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class ClinicalTrial(BaseModel):
    """
    Cleaned, structured clinical trial data.

    Raw ClinicalTrials.gov data has:
    - HTML tags in descriptions (we strip them)
    - Nested JSON structures (we flatten)
    - Missing fields (we handle gracefully)
    - Inconsistent date formats (we normalize)
    - Verbose text walls (we parse into lists)

    This schema is what the frontend always receives â€” clean, consistent, typed.
    """

    # Identifiers
    nct_id: str = Field(description="ClinicalTrials.gov identifier e.g. NCT04892173")
    brief_title: str
    official_title: str | None = None
    acronym: str | None = None

    # Status
    status: TrialStatus
    phase: TrialPhase
    study_type: str = Field(default="Interventional")

    # Description
    brief_summary: str = Field(description="Plain-language trial description (HTML stripped)")
    detailed_description: str | None = None

    # Conditions and Interventions
    conditions: list[str] = Field(description="Medical conditions being studied")
    keywords: list[str] = Field(default_factory=list)
    interventions: list[TrialIntervention] = Field(default_factory=list)
    intervention_names: list[str] = Field(
        default_factory=list, description="Flat list of intervention names for quick reference"
    )

    # Eligibility
    eligibility: EligibilityCriteria

    # Locations
    locations: list[TrialLocation] = Field(default_factory=list)
    location_count: int = Field(default=0)
    countries: list[str] = Field(default_factory=list)

    # Sponsor
    sponsor: str | None = None
    collaborators: list[str] = Field(default_factory=list)

    # Timeline
    start_date: str | None = None
    completion_date: str | None = None
    primary_completion_date: str | None = None

    # Enrollment
    enrollment_count: int | None = None
    enrollment_type: str | None = None

    # Contact
    overall_contact_name: str | None = None
    overall_contact_phone: str | None = None
    overall_contact_email: str | None = None

    # URLs
    url: str = Field(description="Direct link to trial on ClinicalTrials.gov")

    @field_validator("brief_summary", "detailed_description", mode="before")
    @classmethod
    def strip_html(cls, v):
        """Remove HTML tags from text fields."""
        if v is None:
            return v
        # Remove HTML tags
        clean = re.sub(r"<[^>]+>", " ", str(v))
        # Normalize whitespace
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    @field_validator("conditions", "keywords", mode="before")
    @classmethod
    def normalize_list(cls, v):
        if not v:
            return []
        if isinstance(v, str):
            return [v.strip()]
        return [str(item).strip() for item in v if item]


# â”€â”€ Matched Trial (with scoring) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class MatchedTrial(BaseModel):
    """
    A clinical trial with full matching assessment for a specific patient.
    This is what the ranking agent produces and what the frontend displays.
    """

    trial: ClinicalTrial
    eligibility_assessment: EligibilityAssessment
    safety_assessment: SafetyAssessment

    # Computed ranking fields
    final_score: float = Field(
        ge=0.0, le=100.0, description="Weighted final score combining eligibility + safety + relevance"
    )
    rank: int = Field(description="1-based ranking among all matched trials")

    # Quick access fields (avoid deep nesting in frontend)
    is_safe: bool
    decision: EligibilityDecision
    match_percentage: float = Field(ge=0.0, le=100.0)
    confidence: float = Field(ge=0.0, le=1.0)


# â”€â”€ Paginated Response â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class PaginationMeta(BaseModel):
    """Pagination metadata included in every list response."""

    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_items: int = Field(ge=0)
    total_pages: int = Field(ge=0)
    has_next: bool
    has_previous: bool


class MatchResponse(BaseModel):
    """
    Complete pipeline output returned to the frontend.
    Uses cursor-based pagination for smooth UX.
    """

    # Search context
    patient_id: str
    search_id: str = Field(description="Unique ID for this search session")
    query_summary: str = Field(description="Human-readable summary of what was searched")

    # Results
    matches: list[MatchedTrial]
    pagination: PaginationMeta

    # Pipeline metadata
    total_trials_searched: int
    total_eligible: int
    processing_time_seconds: float

    # Pipeline was halted for safety
    safety_halt: bool = Field(default=False)
    safety_halt_reason: str | None = None

    # Physician summary
    physician_summary: str = Field(description="AI-generated summary for the referring physician")
    disclaimer: str = Field(
        default=(
            "This tool is for informational purposes only and does not constitute "
            "medical advice. All trial matches should be reviewed by a qualified "
            "healthcare provider before any enrollment decision."
        )
    )
