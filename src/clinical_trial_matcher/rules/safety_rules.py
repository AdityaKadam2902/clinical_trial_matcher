"""
rules/safety_rules.py
─────────────────────
Pure Python deterministic safety rule engine.

This is the MOST IMPORTANT component of the entire system.
These rules run on every trial BEFORE and AFTER any LLM evaluation.

WHY PURE PYTHON AND NOT LLM:
  - LLMs can hallucinate. A hallucinated "safe" result could enroll
    a patient in a dangerous trial.
  - Rule engine is deterministic — same input ALWAYS gives same output.
  - Rule engine is auditable — you can trace exactly why a trial was flagged.
  - Rule engine is fast — no API call, no latency, no rate limits.
  - Regulators and hospital compliance teams require deterministic safety logic.

MENTAL MODEL:
  Rule Engine = hard walls (NEVER cross these regardless of LLM confidence)
  LLM         = intelligent reasoning WITHIN those hard walls
"""

from dataclasses import dataclass, field

from loguru import logger

from clinical_trial_matcher.schemas.patient import PatientProfile, Sex
from clinical_trial_matcher.schemas.trial import ClinicalTrial, SafetyLevel, TrialStatus

# ── Data classes for rule results ─────────────────────────────────────────────


@dataclass
class RuleViolation:
    """A single safety rule violation."""

    rule_id: str
    severity: SafetyLevel
    description: str
    recommendation: str
    halt_pipeline: bool = False  # If True, stop entire pipeline immediately


@dataclass
class RuleEngineResult:
    """Complete output of the rule engine for one patient-trial pair."""

    trial_nct_id: str
    violations: list[RuleViolation] = field(default_factory=list)
    is_safe: bool = True
    halt_pipeline: bool = False
    overall_severity: SafetyLevel = SafetyLevel.SAFE
    flags_summary: list[str] = field(default_factory=list)

    def add_violation(self, violation: RuleViolation):
        self.violations.append(violation)
        self.flags_summary.append(violation.description)

        if violation.halt_pipeline:
            self.halt_pipeline = True
            self.is_safe = False

        # Update overall severity (escalates, never de-escalates)
        severity_order = {
            SafetyLevel.SAFE: 0,
            SafetyLevel.CAUTION: 1,
            SafetyLevel.WARNING: 2,
            SafetyLevel.CRITICAL: 3,
        }
        if severity_order.get(violation.severity, 0) > severity_order.get(self.overall_severity, 0):
            self.overall_severity = violation.severity
            if violation.severity == SafetyLevel.CRITICAL:
                self.is_safe = False


# ── Absolute Contraindication Rules ───────────────────────────────────────────
# These are hard medical rules. No exceptions. No LLM override.

PREGNANCY_DANGEROUS_INTERVENTIONS: set[str] = {
    "chemotherapy",
    "doxorubicin",
    "cyclophosphamide",
    "methotrexate",
    "paclitaxel",
    "cisplatin",
    "carboplatin",
    "radiation",
    "thalidomide",
    "lenalidomide",
    "pomalidomide",
    "warfarin",
    "valproate",
    "isotretinoin",
    "ribavirin",
    "live vaccine",
    "experimental",
    "immunotherapy",
}

PEDIATRIC_EXCLUDED_KEYWORDS: set[str] = {
    "adults only",
    "18 years and older",
    "18 years or older",
    "adult patients",
    "age 18",
    "minimum age 18",
}

RENAL_DANGEROUS_DRUGS: set[str] = {
    "nsaid",
    "ibuprofen",
    "naproxen",
    "indomethacin",
    "contrast",
    "gadolinium",
    "aminoglycoside",
    "gentamicin",
    "tobramycin",
    "vancomycin",
    "cyclosporine",
    "tacrolimus",
    "metformin",  # Contraindicated in severe renal failure
}

LIVER_DANGEROUS_DRUGS: set[str] = {
    "acetaminophen",
    "paracetamol",
    "isoniazid",
    "valproate",
    "amiodarone",
    "methotrexate",
    "leflunomide",
    "niacin",
    "ketoconazole",
}

CARDIAC_DANGEROUS_DRUGS: set[str] = {
    "doxorubicin",
    "anthracycline",
    "trastuzumab",
    "sunitinib",
    "bevacizumab",
    "5-fluorouracil",
    "capecitabine",
}

AGE_RELATED_CAUTIONS = {
    "children": (0, 12),
    "adolescents": (12, 18),
    "elderly": (65, 999),
    "geriatric": (65, 999),
    "pediatric": (0, 18),
}


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN RULE ENGINE
# ═══════════════════════════════════════════════════════════════════════════════


class ClinicalSafetyRuleEngine:
    """
    Deterministic rule-based safety engine.

    Runs all safety rules in sequence and returns a complete RuleEngineResult.
    Called BEFORE LLM eligibility checking — if halt_pipeline is True,
    LangGraph routes to the safety halt node and skips all remaining agents.
    """

    def evaluate(
        self,
        patient: PatientProfile,
        trial: ClinicalTrial,
    ) -> RuleEngineResult:
        """
        Run all safety rules for a patient-trial pair.

        Returns RuleEngineResult with all violations found.
        This function is pure Python — no I/O, no LLM, no network calls.
        Runs in < 1ms per trial.
        """
        result = RuleEngineResult(trial_nct_id=trial.nct_id)

        # Run each rule category
        self._check_status_rules(trial, result)
        self._check_age_rules(patient, trial, result)
        self._check_sex_rules(patient, trial, result)
        self._check_pregnancy_rules(patient, trial, result)
        self._check_allergy_rules(patient, trial, result)
        self._check_renal_rules(patient, trial, result)
        self._check_liver_rules(patient, trial, result)
        self._check_cardiac_rules(patient, trial, result)
        self._check_pediatric_rules(patient, trial, result)

        if result.violations:
            logger.debug(
                f"Rule engine: {trial.nct_id} — "
                f"{len(result.violations)} violations, "
                f"severity={result.overall_severity.value}, "
                f"halt={result.halt_pipeline}"
            )

        return result

    # ── Individual Rule Checks ─────────────────────────────────────────────────

    def _check_status_rules(self, trial: ClinicalTrial, result: RuleEngineResult):
        """Trials that are not recruiting should be flagged."""
        non_recruiting = {
            TrialStatus.COMPLETED,
            TrialStatus.TERMINATED,
            TrialStatus.WITHDRAWN,
            TrialStatus.SUSPENDED,
        }
        if trial.status in non_recruiting:
            result.add_violation(
                RuleViolation(
                    rule_id="STATUS_001",
                    severity=SafetyLevel.CRITICAL,
                    description=f"Trial is not recruiting (status: {trial.status.value})",
                    recommendation="This trial is not accepting new participants.",
                    halt_pipeline=True,
                )
            )

    def _check_age_rules(
        self,
        patient: PatientProfile,
        trial: ClinicalTrial,
        result: RuleEngineResult,
    ):
        """Patient age must fall within trial's age eligibility window."""
        eligibility = trial.eligibility

        if eligibility.minimum_age is not None and patient.age < eligibility.minimum_age:
            result.add_violation(
                RuleViolation(
                    rule_id="AGE_001",
                    severity=SafetyLevel.CRITICAL,
                    description=(f"Patient age {patient.age} is below trial minimum age {eligibility.minimum_age}"),
                    recommendation="Patient does not meet minimum age requirement for this trial.",
                    halt_pipeline=True,
                )
            )

        if eligibility.maximum_age is not None and patient.age > eligibility.maximum_age:
            result.add_violation(
                RuleViolation(
                    rule_id="AGE_002",
                    severity=SafetyLevel.CRITICAL,
                    description=(f"Patient age {patient.age} exceeds trial maximum age {eligibility.maximum_age}"),
                    recommendation="Patient exceeds maximum age requirement for this trial.",
                    halt_pipeline=True,
                )
            )

    def _check_sex_rules(
        self,
        patient: PatientProfile,
        trial: ClinicalTrial,
        result: RuleEngineResult,
    ):
        """Check biological sex eligibility."""
        sex_eligible = trial.eligibility.sex_eligible
        patient_sex = patient.sex

        if sex_eligible == "Male" and patient_sex == Sex.FEMALE:
            result.add_violation(
                RuleViolation(
                    rule_id="SEX_001",
                    severity=SafetyLevel.CRITICAL,
                    description="Trial is restricted to male participants only.",
                    recommendation="Patient sex does not meet trial eligibility.",
                    halt_pipeline=True,
                )
            )
        elif sex_eligible == "Female" and patient_sex == Sex.MALE:
            result.add_violation(
                RuleViolation(
                    rule_id="SEX_002",
                    severity=SafetyLevel.CRITICAL,
                    description="Trial is restricted to female participants only.",
                    recommendation="Patient sex does not meet trial eligibility.",
                    halt_pipeline=True,
                )
            )

    def _check_pregnancy_rules(
        self,
        patient: PatientProfile,
        trial: ClinicalTrial,
        result: RuleEngineResult,
    ):
        """
        Pregnant patients must never be enrolled in trials with teratogenic interventions.
        This is the most critical safety rule.
        """
        if not patient.is_pregnant and not patient.is_breastfeeding:
            return

        trial_drugs = " ".join(trial.intervention_names).lower()
        trial_conditions_text = " ".join(trial.conditions).lower()

        for dangerous_drug in PREGNANCY_DANGEROUS_INTERVENTIONS:
            if dangerous_drug in trial_drugs:
                result.add_violation(
                    RuleViolation(
                        rule_id="PREG_001",
                        severity=SafetyLevel.CRITICAL,
                        description=(
                            f"Patient is pregnant/breastfeeding. Trial involves "
                            f"'{dangerous_drug}' which is potentially teratogenic."
                        ),
                        recommendation=(
                            "ABSOLUTE CONTRAINDICATION: Pregnant/breastfeeding patients "
                            f"must not receive {dangerous_drug}. Enrollment prohibited."
                        ),
                        halt_pipeline=True,
                    )
                )
                return  # One critical flag is enough

        # General warning for experimental trials during pregnancy
        if patient.is_pregnant and "experimental" in trial_conditions_text:
            result.add_violation(
                RuleViolation(
                    rule_id="PREG_002",
                    severity=SafetyLevel.WARNING,
                    description="Experimental trial — pregnancy safety not established.",
                    recommendation="Review with maternal-fetal medicine specialist before proceeding.",
                    halt_pipeline=False,
                )
            )

    def _check_allergy_rules(
        self,
        patient: PatientProfile,
        trial: ClinicalTrial,
        result: RuleEngineResult,
    ):
        """Check if patient has known allergy to any trial intervention."""
        if not patient.allergies:
            return

        allergy_substances = {a.substance.lower() for a in patient.allergies}
        trial_drugs_lower = {name.lower() for name in trial.intervention_names}

        for allergen in allergy_substances:
            for trial_drug in trial_drugs_lower:
                if allergen in trial_drug or trial_drug in allergen:
                    # Find allergy severity
                    allergy_severity = next(
                        (a.severity for a in patient.allergies if a.substance.lower() == allergen), None
                    )
                    severity = SafetyLevel.CRITICAL if allergy_severity == "severe" else SafetyLevel.WARNING

                    result.add_violation(
                        RuleViolation(
                            rule_id="ALLERGY_001",
                            severity=severity,
                            description=(
                                f"Patient has documented allergy to '{allergen}'. Trial involves '{trial_drug}'."
                            ),
                            recommendation=(
                                f"Review allergy history for {allergen} with allergist. "
                                "Enrollment requires detailed allergy evaluation."
                            ),
                            halt_pipeline=(severity == SafetyLevel.CRITICAL),
                        )
                    )

    def _check_renal_rules(
        self,
        patient: PatientProfile,
        trial: ClinicalTrial,
        result: RuleEngineResult,
    ):
        """Flag nephrotoxic drugs for patients with renal conditions."""
        renal_conditions = {
            "kidney failure",
            "renal failure",
            "renal insufficiency",
            "chronic kidney disease",
            "ckd",
            "dialysis",
            "renal impairment",
        }

        patient_conditions_lower = {c.display.lower() for c in patient.conditions}
        has_renal_issue = bool(patient_conditions_lower & renal_conditions)

        if not has_renal_issue:
            return

        trial_drugs_text = " ".join(trial.intervention_names).lower()
        for drug in RENAL_DANGEROUS_DRUGS:
            if drug in trial_drugs_text:
                result.add_violation(
                    RuleViolation(
                        rule_id="RENAL_001",
                        severity=SafetyLevel.WARNING,
                        description=(
                            f"Patient has renal condition. Trial involves '{drug}' "
                            "which may be nephrotoxic or requires dose adjustment."
                        ),
                        recommendation=(
                            f"Nephrology consultation required before {drug} administration. "
                            "Dose adjustment or monitoring protocol may be needed."
                        ),
                        halt_pipeline=False,
                    )
                )

    def _check_liver_rules(
        self,
        patient: PatientProfile,
        trial: ClinicalTrial,
        result: RuleEngineResult,
    ):
        """Flag hepatotoxic drugs for patients with liver conditions."""
        liver_conditions = {
            "liver disease",
            "hepatitis",
            "cirrhosis",
            "liver failure",
            "hepatic impairment",
            "liver cirrhosis",
            "fatty liver",
        }

        patient_conditions_lower = {c.display.lower() for c in patient.conditions}
        has_liver_issue = bool(patient_conditions_lower & liver_conditions)

        if not has_liver_issue:
            return

        trial_drugs_text = " ".join(trial.intervention_names).lower()
        for drug in LIVER_DANGEROUS_DRUGS:
            if drug in trial_drugs_text:
                result.add_violation(
                    RuleViolation(
                        rule_id="LIVER_001",
                        severity=SafetyLevel.WARNING,
                        description=(f"Patient has liver condition. Trial involves '{drug}' which may be hepatotoxic."),
                        recommendation=(
                            f"Hepatology consultation required before {drug} use. Liver function monitoring required."
                        ),
                        halt_pipeline=False,
                    )
                )

    def _check_cardiac_rules(
        self,
        patient: PatientProfile,
        trial: ClinicalTrial,
        result: RuleEngineResult,
    ):
        """Flag cardiotoxic drugs for patients with cardiac conditions."""
        cardiac_conditions = {
            "heart failure",
            "cardiomyopathy",
            "cardiac arrhythmia",
            "coronary artery disease",
            "myocardial infarction",
            "ejection fraction",
            "atrial fibrillation",
        }

        patient_conditions_lower = {c.display.lower() for c in patient.conditions}
        has_cardiac_issue = bool(patient_conditions_lower & cardiac_conditions)

        if not has_cardiac_issue:
            return

        trial_drugs_text = " ".join(trial.intervention_names).lower()
        for drug in CARDIAC_DANGEROUS_DRUGS:
            if drug in trial_drugs_text:
                result.add_violation(
                    RuleViolation(
                        rule_id="CARDIAC_001",
                        severity=SafetyLevel.WARNING,
                        description=(
                            f"Patient has cardiac condition. Trial involves '{drug}' "
                            "which has documented cardiotoxicity risk."
                        ),
                        recommendation=(
                            "Cardiology evaluation required. Baseline echocardiogram "
                            "and regular cardiac monitoring during trial participation."
                        ),
                        halt_pipeline=False,
                    )
                )

    def _check_pediatric_rules(
        self,
        patient: PatientProfile,
        trial: ClinicalTrial,
        result: RuleEngineResult,
    ):
        """Flag adult-only trials for pediatric patients."""
        if patient.age >= 18:
            return

        eligibility_text = trial.eligibility.raw_text.lower()
        title_text = trial.brief_title.lower()
        combined = eligibility_text + " " + title_text

        for keyword in PEDIATRIC_EXCLUDED_KEYWORDS:
            if keyword in combined:
                result.add_violation(
                    RuleViolation(
                        rule_id="PEDS_001",
                        severity=SafetyLevel.CRITICAL,
                        description=f"Trial appears restricted to adults ('{keyword}' found in criteria).",
                        recommendation="Pediatric patients are not eligible for this adult trial.",
                        halt_pipeline=True,
                    )
                )
                return


# ── Global singleton instance ──────────────────────────────────────────────────
rule_engine = ClinicalSafetyRuleEngine()
