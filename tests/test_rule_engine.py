"""
tests/test_rule_engine.py
─────────────────────────
Unit tests for the safety rule engine.
These tests are the most critical in the entire project.
Run with: pytest tests/ -v
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from schemas.patient import PatientProfile, FHIRCondition, FHIRMedication, Allergy, Sex, SmokingStatus
from schemas.trial import (
    ClinicalTrial, TrialStatus, TrialPhase, EligibilityCriteria,
    TrialIntervention, SafetyLevel
)
from rules.safety_rules import rule_engine


# ── Fixtures ───────────────────────────────────────────────────────────────────

def make_patient(**kwargs) -> PatientProfile:
    defaults = dict(
        age=45, sex=Sex.MALE,
        conditions=[FHIRCondition(display="Type 2 Diabetes Mellitus")],
        symptoms=["frequent urination"],
    )
    defaults.update(kwargs)
    return PatientProfile(**defaults)


def make_trial(**kwargs) -> ClinicalTrial:
    defaults = dict(
        nct_id="NCT99999999",
        brief_title="Test Trial",
        status=TrialStatus.RECRUITING,
        phase=TrialPhase.PHASE3,
        brief_summary="A test trial.",
        conditions=["Type 2 Diabetes"],
        eligibility=EligibilityCriteria(
            raw_text="Inclusion: Age 18-70. Exclusion: Pregnancy.",
            inclusion=["Age 18-70"],
            exclusion=["Pregnancy"],
            minimum_age=18,
            maximum_age=70,
            sex_eligible="All",
        ),
        interventions=[TrialIntervention(intervention_type="Drug", name="metformin")],
        intervention_names=["metformin"],
        url="https://clinicaltrials.gov/study/NCT99999999",
    )
    defaults.update(kwargs)
    return ClinicalTrial(**defaults)


# ── Tests ───────────────────────────────────────────────────────────────────────

def test_safe_patient_passes():
    patient = make_patient()
    trial = make_trial()
    result = rule_engine.evaluate(patient, trial)
    assert result.is_safe is True
    assert result.halt_pipeline is False
    assert result.overall_severity == SafetyLevel.SAFE


def test_patient_too_young():
    patient = make_patient(age=15)
    trial = make_trial()
    result = rule_engine.evaluate(patient, trial)
    assert result.halt_pipeline is True
    assert result.overall_severity == SafetyLevel.CRITICAL
    assert any("AGE_001" in v.rule_id for v in result.violations)


def test_patient_too_old():
    patient = make_patient(age=80)
    trial = make_trial()
    result = rule_engine.evaluate(patient, trial)
    assert result.halt_pipeline is True
    assert any("AGE_002" in v.rule_id for v in result.violations)


def test_wrong_sex():
    patient = make_patient(sex=Sex.FEMALE)
    trial = make_trial(
        eligibility=EligibilityCriteria(
            raw_text="Males only",
            sex_eligible="Male",
            minimum_age=18,
        )
    )
    result = rule_engine.evaluate(patient, trial)
    assert result.halt_pipeline is True
    assert any("SEX" in v.rule_id for v in result.violations)


def test_pregnancy_with_chemo():
    patient = make_patient(
        sex=Sex.FEMALE,
        is_pregnant=True,
        conditions=[FHIRCondition(display="Breast Cancer")],
    )
    trial = make_trial(
        intervention_names=["doxorubicin", "chemotherapy"],
        interventions=[
            TrialIntervention(intervention_type="Drug", name="doxorubicin"),
            TrialIntervention(intervention_type="Drug", name="chemotherapy"),
        ]
    )
    result = rule_engine.evaluate(patient, trial)
    assert result.halt_pipeline is True
    assert result.overall_severity == SafetyLevel.CRITICAL
    assert any("PREG" in v.rule_id for v in result.violations)


def test_allergy_to_trial_drug():
    patient = make_patient(
        allergies=[Allergy(substance="metformin", reaction="anaphylaxis", severity="severe")]
    )
    trial = make_trial(intervention_names=["metformin"])
    result = rule_engine.evaluate(patient, trial)
    assert result.halt_pipeline is True
    assert any("ALLERGY" in v.rule_id for v in result.violations)


def test_completed_trial_halts():
    patient = make_patient()
    trial = make_trial(status=TrialStatus.COMPLETED)
    result = rule_engine.evaluate(patient, trial)
    assert result.halt_pipeline is True
    assert any("STATUS" in v.rule_id for v in result.violations)


def test_renal_patient_with_nsaid():
    patient = make_patient(
        conditions=[
            FHIRCondition(display="Chronic Kidney Disease"),
            FHIRCondition(display="Type 2 Diabetes Mellitus"),
        ]
    )
    trial = make_trial(
        intervention_names=["ibuprofen"],
        interventions=[TrialIntervention(intervention_type="Drug", name="ibuprofen")]
    )
    result = rule_engine.evaluate(patient, trial)
    # Warning, not halt
    assert result.halt_pipeline is False
    assert result.overall_severity in [SafetyLevel.WARNING, SafetyLevel.CAUTION]
    assert any("RENAL" in v.rule_id for v in result.violations)


def test_pediatric_patient_adult_trial():
    patient = make_patient(age=10)
    trial = make_trial(
        brief_title="Adults Only Diabetes Trial",
        eligibility=EligibilityCriteria(
            raw_text="Inclusion: 18 years and older",
            inclusion=["18 years and older"],
            minimum_age=18,
        )
    )
    result = rule_engine.evaluate(patient, trial)
    assert result.halt_pipeline is True


def test_multiple_violations():
    """Multiple violations should all be captured."""
    patient = make_patient(
        age=10,
        sex=Sex.FEMALE,
        is_pregnant=True,
        conditions=[FHIRCondition(display="Cancer")],
    )
    trial = make_trial(
        status=TrialStatus.TERMINATED,
        intervention_names=["chemotherapy"],
        eligibility=EligibilityCriteria(
            raw_text="Males only, age 18-70",
            sex_eligible="Male",
            minimum_age=18,
            maximum_age=70,
        )
    )
    result = rule_engine.evaluate(patient, trial)
    assert len(result.violations) >= 2
    assert result.halt_pipeline is True
