// Full type definitions — updated
export interface Condition { display: string; snomed_code?: string; severity?: string; is_active?: boolean }
export interface Medication { name: string; dosage?: string; frequency?: string }
export interface Allergy { substance: string; severity?: string }
export interface LabValue { test_name: string; value: number; unit: string; is_abnormal?: boolean }

export interface PatientProfile {
  age: number; sex: string; weight_kg?: number; height_cm?: number
  conditions: Condition[]; symptoms: string[]; medications: Medication[]
  allergies: Allergy[]; lab_values: LabValue[]
  prior_treatments: string[]; surgeries: string[]
  smoking_status: string; is_pregnant: boolean; is_breastfeeding: boolean
  preferred_locations: string[]; trial_phases?: string[]
}

export interface EligibilityAssessment {
  decision: string; confidence: number; match_score: number
  met_criteria: string[]; unmet_criteria: string[]; exclusion_triggers: string[]
  reasoning: string; physician_notes?: string
}

export interface DrugInteraction {
  patient_drug: string; trial_drug: string
  interaction_description: string; severity: string
  source: string; recommendation: string
}

export interface SafetyAssessment {
  overall_level: string; drug_interactions: DrugInteraction[]
  allergy_conflicts: string[]; contraindications: string[]
  rule_engine_flags: string[]; is_safe_to_proceed: boolean; halt_reason?: string
}

export interface TrialLocation {
  facility?: string; city?: string; state?: string; country: string; zip_code?: string
}

export interface TrialIntervention { intervention_type: string; name: string; description?: string }

export interface EligibilityCriteria {
  raw_text: string; inclusion: string[]; exclusion: string[]
  minimum_age?: number; maximum_age?: number; sex_eligible?: string
  accepts_healthy_volunteers: boolean
}

export interface ClinicalTrial {
  nct_id: string; brief_title: string; official_title?: string
  status: string; phase: string; study_type: string
  brief_summary: string; conditions: string[]; keywords: string[]
  interventions: TrialIntervention[]; intervention_names: string[]
  eligibility: EligibilityCriteria; locations: TrialLocation[]
  location_count: number; countries: string[]
  sponsor?: string; start_date?: string; completion_date?: string
  enrollment_count?: number; overall_contact_email?: string; url: string
}

export interface MatchedTrial {
  trial: ClinicalTrial; eligibility_assessment: EligibilityAssessment
  safety_assessment: SafetyAssessment; final_score: number
  rank: number; is_safe: boolean; decision: string
  match_percentage: number; confidence: number
}

export interface PaginationMeta {
  page: number; page_size: number; total_items: number; total_pages: number
  has_next: boolean; has_previous: boolean
}

export interface MatchResponse {
  patient_id: string; search_id: string; query_summary: string
  matches: MatchedTrial[]; pagination: PaginationMeta
  total_trials_searched: number; total_eligible: number
  processing_time_seconds: number; safety_halt: boolean; safety_halt_reason?: string
  physician_summary: string; disclaimer: string
}
