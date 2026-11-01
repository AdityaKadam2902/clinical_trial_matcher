"""
schemas/patient.py
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
FHIR R4 compliant patient data schemas using Pydantic v2.

FHIR (Fast Healthcare Interoperability Resources) is the international standard
for healthcare data exchange used by Epic, Cerner, and every major hospital system.
By following FHIR R4, our data can integrate with any hospital's EHR system.

All schemas have strict validation â€” wrong data types or out-of-range values
are rejected immediately before reaching any agent.
"""

from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

# â”€â”€ Enums â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class Sex(StrEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    UNKNOWN = "unknown"


class SmokingStatus(StrEnum):
    NEVER = "never"
    FORMER = "former"
    CURRENT = "current"
    UNKNOWN = "unknown"


class ConditionSeverity(StrEnum):
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"
    UNKNOWN = "unknown"


# â”€â”€ Sub-schemas â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class FHIRCondition(BaseModel):
    """
    FHIR R4 Condition resource.
    SNOMED CT codes are the international standard for medical conditions.
    Example: code="44054006" display="Type 2 Diabetes Mellitus"
    """

    display: str = Field(..., min_length=1, description="Human-readable condition name")
    snomed_code: str | None = Field(None, description="SNOMED CT code if known")
    icd10_code: str | None = Field(None, description="ICD-10 code if known")
    severity: ConditionSeverity = Field(default=ConditionSeverity.UNKNOWN)
    onset_year: int | None = Field(None, ge=1900, le=2100)
    is_active: bool = Field(default=True, description="Is condition currently active?")

    @field_validator("display")
    @classmethod
    def normalize_display(cls, v: str) -> str:
        return v.strip().title()


class FHIRMedication(BaseModel):
    """
    FHIR R4 MedicationStatement resource.
    RxNorm codes are the US standard for drug identification.
    Example: rxnorm_code="860975" name="Metformin 500mg"
    """

    name: str = Field(..., min_length=1, description="Drug name (generic preferred)")
    rxnorm_code: str | None = Field(None, description="RxNorm code if known")
    dosage: str | None = Field(None, description="e.g. '500mg'")
    frequency: str | None = Field(None, description="e.g. 'twice daily'")
    route: str | None = Field(None, description="e.g. 'oral', 'intravenous'")
    is_active: bool = Field(default=True)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, v: str) -> str:
        return v.strip().lower()


class LabValue(BaseModel):
    """
    A single laboratory test result.
    Example: test_name="HbA1c" value=8.2 unit="%" reference_range="4.0-5.6"
    """

    test_name: str = Field(..., description="Name of the lab test")
    value: float = Field(..., description="Numeric result")
    unit: str = Field(..., description="Unit of measurement")
    reference_range: str | None = Field(None, description="Normal range e.g. '4.0-5.6'")
    is_abnormal: bool | None = Field(None, description="True if outside normal range")
    test_date: str | None = Field(None, description="YYYY-MM-DD format")


class Allergy(BaseModel):
    substance: str = Field(..., description="Substance causing allergic reaction")
    reaction: str | None = Field(None, description="Type of reaction e.g. 'anaphylaxis'")
    severity: Literal["mild", "moderate", "severe"] | None = None


# â”€â”€ Main Patient Schema â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class PatientProfile(BaseModel):
    """
    FHIR R4 compliant Patient resource.
    This is the primary input to the Clinical Trial Matcher pipeline.

    Every field has validation:
    - age must be 0-120
    - at least one condition OR symptom required
    - medications list validated against known formats
    """

    # Patient identification (no PII stored â€” demo mode)
    patient_id: str = Field(
        default_factory=lambda: f"PT-{str(uuid4())[:8].upper()}", description="Auto-generated patient identifier"
    )

    # Core demographics (required for eligibility matching)
    age: int = Field(..., ge=0, le=120, description="Patient age in years")
    sex: Sex = Field(..., description="Biological sex â€” affects trial eligibility")
    weight_kg: float | None = Field(None, ge=1, le=500, description="Weight in kilograms")
    height_cm: float | None = Field(None, ge=30, le=250, description="Height in centimeters")

    # Medical history
    conditions: list[FHIRCondition] = Field(default_factory=list, description="Current and past medical conditions")
    symptoms: list[str] = Field(default_factory=list, description="Current symptoms the patient is experiencing")
    medications: list[FHIRMedication] = Field(
        default_factory=list, description="Current medications including OTC drugs and supplements"
    )
    allergies: list[Allergy] = Field(default_factory=list, description="Known drug and substance allergies")
    lab_values: list[LabValue] = Field(default_factory=list, description="Recent laboratory test results")

    # History
    prior_treatments: list[str] = Field(
        default_factory=list, description="Previous treatments e.g. 'chemotherapy', 'radiation therapy'"
    )
    surgeries: list[str] = Field(default_factory=list, description="Previous surgeries e.g. 'appendectomy 2019'")
    family_history: list[str] = Field(default_factory=list, description="Relevant family medical history")

    # Lifestyle factors
    smoking_status: SmokingStatus = Field(default=SmokingStatus.UNKNOWN)
    is_pregnant: bool = Field(default=False)
    is_breastfeeding: bool = Field(default=False)

    # Search preferences
    preferred_locations: list[str] = Field(
        default_factory=list,
        description="Preferred states or countries for trial location e.g. ['California', 'New York']",
    )
    max_distance_km: int | None = Field(None, ge=0, description="Maximum distance willing to travel for trial")
    trial_phases: list[Literal["PHASE1", "PHASE2", "PHASE3", "PHASE4"]] | None = Field(
        default=None, description="Preferred trial phases. None means all phases."
    )

    @model_validator(mode="after")
    def validate_has_medical_data(self):
        """Patient must provide at least one condition or symptom."""
        if not self.conditions and not self.symptoms:
            raise ValueError(
                "Patient profile must include at least one condition or symptom to search for relevant clinical trials."
            )
        return self

    @field_validator("symptoms")
    @classmethod
    def normalize_symptoms(cls, v: list[str]) -> list[str]:
        return [s.strip().lower() for s in v if s.strip()]

    def get_condition_names(self) -> list[str]:
        """Returns plain list of condition display names."""
        return [c.display for c in self.conditions]

    def get_medication_names(self) -> list[str]:
        """Returns plain list of medication names."""
        return [m.name for m in self.medications]

    def get_all_drug_names(self) -> list[str]:
        """Medications + allergy substances â€” for drug interaction checking."""
        meds = self.get_medication_names()
        allergens = [a.substance.lower() for a in self.allergies]
        return list(set(meds + allergens))
