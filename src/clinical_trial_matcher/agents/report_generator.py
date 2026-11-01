"""
agents/report_generator.py
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Agent 6: Report Generator

Produces a physician-ready summary of the top trial matches.
Uses the configured complex model for professional medical language.

The summary is designed to be printed or emailed to a referring physician
and contains everything they need to understand the recommendations.
"""

import time

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from clinical_trial_matcher.agents.llm import get_complex_chat_model
from clinical_trial_matcher.agents.pipeline_state import PipelineState
from clinical_trial_matcher.schemas.trial import SafetyLevel


async def report_generator_agent(state: PipelineState) -> PipelineState:
    """
    Agent 6: Report Generator

    Input:  state["ranked_trials"], state["patient"], state["profile_summary"]
    Output: state["physician_summary"]
    """
    logger.info("[ReportGenerator] Generating physician summary")
    start = time.time()

    ranked_trials = state.get("ranked_trials", [])
    patient = state["patient"]
    profile_summary = state.get("profile_summary", "")

    # Also get eligibility results to detect the all-NEEDS_REVIEW case
    eligibility_results = state.get("eligibility_results", [])
    all_needs_review = len(eligibility_results) > 0 and all(
        r.get("assessment", {}).get("decision") == "NEEDS_REVIEW" for r in eligibility_results
    )

    if not ranked_trials:
        dropped_phase = state.get("trials_dropped_by_phase", 0)
        dropped_location = state.get("trials_dropped_by_location", 0)
        conditions_str = ", ".join(patient.get_condition_names())

        if all_needs_review:
            # Trials were found but eligibility criteria were missing (fallback source)
            fallback_summary = (
                f"Clinical trial search completed for patient with {conditions_str}. "
                f"{len(eligibility_results)} trial(s) were identified but eligibility "
                f"could not be determined automatically: criteria were unavailable, "
                f"or the evaluation time budget was reached before a decision. "
                f"A physician or research coordinator should manually review the candidate "
                f"trials at ClinicalTrials.gov before any enrollment decision. "
                f"This summary is AI-generated and requires physician review."
            )
        elif dropped_phase and not dropped_location:
            # Trials existed but the patient's phase preference excluded all of them
            phase_pref = ", ".join(patient.trial_phases) if patient.trial_phases else "requested phases"
            fallback_summary = (
                f"Clinical trial search for {conditions_str} identified "
                f"{dropped_phase} recruiting trial(s), but none matched the "
                f"requested phase(s): {phase_pref}. "
                f"Consider broadening the phase preference, or ask your research "
                f"coordinator to check for trials in other phases. "
                f"This summary is AI-generated and requires physician review."
            )
        elif dropped_location and not dropped_phase:
            # Trials existed but the patient's location preference excluded all of them
            loc_pref = ", ".join(patient.preferred_locations) if patient.preferred_locations else "preferred location"
            fallback_summary = (
                f"Clinical trial search for {conditions_str} identified "
                f"{dropped_location} recruiting trial(s), but none were located "
                f"in {loc_pref}. "
                f"Consider broadening the location preference or searching nationally. "
                f"This summary is AI-generated and requires physician review."
            )
        elif dropped_phase and dropped_location:
            phase_pref = ", ".join(patient.trial_phases) if patient.trial_phases else "requested phases"
            loc_pref = ", ".join(patient.preferred_locations) if patient.preferred_locations else "preferred location"
            fallback_summary = (
                f"Clinical trial search for {conditions_str} identified recruiting "
                f"trial(s), but all were excluded by the applied filters "
                f"(phases: {phase_pref}; location: {loc_pref}). "
                f"Consider relaxing one or both preferences. "
                f"This summary is AI-generated and requires physician review."
            )
        else:
            # Genuinely no trials found from any source
            fallback_summary = (
                f"No recruiting clinical trials were found for {conditions_str} "
                f"at this time. The search used ClinicalTrials.gov and a fallback "
                f"source; both returned no results. "
                f"Recommend consulting a clinical research coordinator for a manual search. "
                f"This summary is AI-generated and requires physician review."
            )
        return {**state, "physician_summary": fallback_summary}

    # Prepare top 3 trials for summary
    top_trials = ranked_trials[:3]

    trial_summaries = []
    for i, match in enumerate(top_trials, 1):
        trial = match.trial
        eligibility = match.eligibility_assessment
        safety = match.safety_assessment

        safety_note = ""
        if safety.overall_level == SafetyLevel.WARNING:
            interaction_notes = [
                f"{flag.patient_drug} + {flag.trial_drug}: {flag.recommendation}"
                for flag in safety.drug_interactions[:1]
            ]
            safety_note = f" Safety note: {'; '.join(interaction_notes) or 'Review required.'}"
        elif safety.overall_level == SafetyLevel.CRITICAL:
            safety_note = " CRITICAL safety concern â€” do not enroll."

        trial_summaries.append(
            f"#{i} {trial.brief_title} ({trial.nct_id})\n"
            f"   Phase: {trial.phase.value} | Status: {trial.status.value}\n"
            f"   Match Score: {match.final_score:.1f}/100 | Decision: {match.decision.value}\n"
            f"   Sponsor: {trial.sponsor or 'N/A'}\n"
            f"   Eligibility reasoning: {eligibility.reasoning[:200]}...\n"
            f"   Location: {', '.join(trial.countries[:3]) or 'Not specified'}\n"
            f"   URL: {trial.url}\n"
            f"   {safety_note}"
        )

    trials_text = "\n\n".join(trial_summaries)

    prompt = f"""You are a clinical research specialist writing a summary for a referring physician.

Patient Profile:
{profile_summary}

Top Matched Clinical Trials:
{trials_text}

Write a concise, professional physician summary that:
1. Briefly states what conditions/symptoms were searched.
2. Summarizes only the trials listed above â€” do not invent or assume additional trials exist.
3. For each trial, state whether eligibility was determined or was unavailable (NEEDS_REVIEW).
4. Highlights any important safety considerations drawn directly from the trial data above.
5. States concrete next steps for enrollment (e.g. contact trial coordinator, visit trial URL).

STRICT RULES â€” violating any of these is a clinical error:
- Do NOT recommend adjusting, continuing, stopping, or modifying the patient's current medications.
  Medication management is outside the scope of trial matching and is not supported by this data.
- Do NOT make any treatment recommendations beyond trial enrollment guidance.
- Do NOT express a confidence level higher than what the eligibility assessment shows.
  If a trial is NEEDS_REVIEW, say so explicitly â€” do not present it as a confirmed match.
- Do NOT speculate about why the patient is ineligible beyond what is stated in the reasoning above.
- If no trials were found or all are NEEDS_REVIEW, say so clearly instead of implying matches exist.

Keep it under 250 words. Use medical terminology appropriately.
Do not include markdown formatting â€” write in clean paragraphs.
End with the standard disclaimer that this is AI-generated and requires physician review before any clinical decision.
"""

    try:
        response = await get_complex_chat_model().ainvoke(
            [
                SystemMessage(
                    content=(
                        "You are a board-certified clinical research specialist. "
                        "Write clear, professional physician summaries. "
                        "Be concise and clinically precise."
                    )
                ),
                HumanMessage(content=prompt),
            ]
        )
        content = response.content
        physician_summary = (content if isinstance(content, str) else str(content)).strip()
    except Exception as e:
        logger.warning(f"[ReportGenerator] LLM failed: {e} â€” using fallback")
        physician_summary = (
            f"Clinical trial matching completed for patient with "
            f"{', '.join(patient.get_condition_names())}. "
            f"Found {len(ranked_trials)} potential matches. "
            f"Top match: {top_trials[0].trial.brief_title} "
            f"(Score: {top_trials[0].final_score:.1f}/100). "
            f"Please review matched trials and contact research coordinators for enrollment details. "
            f"This summary was generated by an AI system and requires physician review before any clinical decision."
        )

    elapsed = time.time() - start
    logger.success(f"[ReportGenerator] Summary generated in {elapsed:.2f}s")

    return {
        **state,
        "physician_summary": physician_summary,
    }
