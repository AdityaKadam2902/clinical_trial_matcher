"""
agents/profile_parser.py
────────────────────────
Agent 1: Profile Parser

Takes the raw patient profile and prepares it for the pipeline:
1. Normalizes medication names via RxNorm API
2. Extracts search-optimized condition keywords
3. Creates a human-readable profile summary
4. Uses fast Groq model (8B) since this is extraction, not reasoning

Uses DSPy for structured output — every field is typed and validated.
"""

from loguru import logger
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
import json
import time
from typing import Iterable, List

from core.config import settings
from agents.pipeline_state import PipelineState
from utils.api_clients import rxnorm_client


# Fast model for extraction tasks
_fast_llm = ChatGroq(
    api_key=settings.groq_api_key,
    model=settings.groq_model_fast,
    temperature=0.0,
)


_NON_CONDITION_TERMS = {
    "male",
    "female",
    "other",
    "unknown",
    "man",
    "woman",
    "symptom",
    "symptoms",
}


def _clean_condition_terms(
    candidate_terms: Iterable[str],
    fallback_terms: Iterable[str],
) -> List[str]:
    """Keep downstream trial-search conditions focused on actual diagnoses."""
    cleaned: List[str] = []
    seen = set()

    for source in (fallback_terms, candidate_terms):
        for raw_term in source:
            if not raw_term:
                continue

            term = " ".join(raw_term.strip().split())
            if not term:
                continue

            if term.split()[0].lower() in _NON_CONDITION_TERMS:
                continue

            key = term.casefold()
            if key in seen:
                continue

            seen.add(key)
            cleaned.append(term)

    return cleaned


async def profile_parser_agent(state: PipelineState) -> PipelineState:
    """
    Agent 1: Profile Parser

    Input:  state["patient"] — raw PatientProfile
    Output: state["normalized_conditions"], state["normalized_medications"],
            state["search_keywords"], state["profile_summary"]
    """
    logger.info(f"[ProfileParser] Starting for patient {state['patient'].patient_id}")
    start = time.time()

    patient = state["patient"]

    # Step 1: Normalize medication names via RxNorm
    # This converts brand names to generic names for consistent drug interaction checking
    raw_meds = patient.get_all_drug_names()
    if raw_meds:
        try:
            normalized_meds = await rxnorm_client.normalize_medications(raw_meds)
            logger.debug(f"[ProfileParser] Normalized medications: {normalized_meds}")
        except Exception as e:
            logger.warning(f"[ProfileParser] RxNorm normalization failed: {e} — using raw names")
            normalized_meds = [m.lower() for m in raw_meds]
    else:
        normalized_meds = []

    # Step 2: Use LLM to extract optimized search keywords from the patient profile
    # The LLM converts verbose condition descriptions into clean search terms
    condition_names = patient.get_condition_names()
    symptoms = patient.symptoms

    keywords_prompt = f"""You are a clinical informatics specialist.

Extract the most important search keywords for finding relevant clinical trials.

Patient conditions: {condition_names}
Patient symptoms: {symptoms}
Patient age: {patient.age}
Patient sex: {patient.sex.value}

Return a JSON object with exactly these fields:
{{
  "primary_conditions": ["list", "of", "3-5", "main", "conditions", "for", "search"],
  "secondary_keywords": ["list", "of", "2-3", "additional", "search", "terms"],
  "normalized_conditions": ["medically", "precise", "condition", "names"]
}}

Rules:
- Use standard medical terminology (e.g., "type 2 diabetes mellitus" not "sugar disease")
- primary_conditions should be the most specific and searchable terms
- Keep lists concise — fewer better keywords beat many generic ones
- Return ONLY the JSON object, no other text
"""

    try:
        response = _fast_llm.invoke([
            SystemMessage(content="You are a clinical informatics specialist. Return only valid JSON."),
            HumanMessage(content=keywords_prompt)
        ])

        # Parse JSON response
        raw_text = response.content.strip()
        # Remove markdown code blocks if present
        if "```" in raw_text:
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]

        keyword_data = json.loads(raw_text)
        primary_conditions = keyword_data.get("primary_conditions", condition_names[:3])
        secondary_keywords = keyword_data.get("secondary_keywords", symptoms[:2])
        normalized_conditions = _clean_condition_terms(
            keyword_data.get("normalized_conditions", []),
            condition_names,
        )

    except Exception as e:
        logger.warning(f"[ProfileParser] LLM keyword extraction failed: {e} — using fallbacks")
        primary_conditions = condition_names[:5]
        secondary_keywords = symptoms[:3]
        normalized_conditions = _clean_condition_terms([], condition_names)

    # Step 3: Generate human-readable profile summary
    all_conditions = ", ".join(condition_names) if condition_names else "No documented conditions"
    all_symptoms = ", ".join(patient.symptoms) if patient.symptoms else "None"
    all_meds = ", ".join(normalized_meds) if normalized_meds else "None"

    profile_summary = (
        f"Patient {patient.patient_id}: {patient.age}-year-old {patient.sex.value}. "
        f"Conditions: {all_conditions}. "
        f"Symptoms: {all_symptoms}. "
        f"Medications: {all_meds}. "
        f"Smoking: {patient.smoking_status.value}. "
        f"Pregnant: {'Yes' if patient.is_pregnant else 'No'}."
    )

    elapsed = time.time() - start
    logger.success(
        f"[ProfileParser] Complete in {elapsed:.2f}s. "
        f"Conditions: {normalized_conditions}, Keywords: {secondary_keywords}"
    )

    return {
        **state,
        "normalized_conditions": normalized_conditions,
        "normalized_medications": normalized_meds,
        "search_keywords": secondary_keywords,
        "profile_summary": profile_summary,
        "processing_start_time": state.get("processing_start_time", start),
    }
