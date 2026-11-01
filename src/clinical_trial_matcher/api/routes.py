"""
api/routes.py
─────────────
FastAPI route definitions for the Clinical Trial Matcher API.
"""

import httpx
from fastapi import APIRouter, Query, Request
from loguru import logger

from clinical_trial_matcher.agents.pipeline import run_pipeline
from clinical_trial_matcher.api.deps import ClinicianOrAdmin, CurrentPrincipal
from clinical_trial_matcher.api.errors import (
    AppError,
    NotFoundError,
    ServiceUnavailableError,
    UnprocessableEntityError,
)
from clinical_trial_matcher.core.config import settings
from clinical_trial_matcher.core.rate_limit import limiter
from clinical_trial_matcher.schemas.patient import PatientProfile
from clinical_trial_matcher.schemas.trial import MatchResponse
from clinical_trial_matcher.utils.api_clients import clinical_trials_client, openfda_client, rxnorm_client

router = APIRouter(prefix="/api/v1", tags=["Clinical Trial Matcher"])


@router.post("/match", response_model=MatchResponse)
@limiter.limit(settings.rate_limit_match)
async def match_trials(
    request: Request,
    patient: PatientProfile,
    _principal: ClinicianOrAdmin,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
):
    """
    Main endpoint — runs the full 6-agent pipeline.

    Restricted to clinicians, researchers, and admins. Rate limited to protect
    local model capacity.
    """
    logger.info(f"[API] Match request: patient={patient.patient_id}")
    try:
        result = await run_pipeline(
            patient=patient,
            page=page,
            page_size=min(page_size, settings.max_page_size),
        )
        return result
    except ValueError as exc:
        raise UnprocessableEntityError(str(exc)) from exc
    except Exception as exc:
        logger.exception("[API] Pipeline error")
        raise AppError("Matching pipeline failed", code="pipeline_error") from exc


@router.get("/trial/{nct_id}")
@limiter.limit(settings.rate_limit_read)
async def get_trial_detail(
    request: Request,
    nct_id: str,
    _principal: CurrentPrincipal,
):
    """Fetch full details for a specific trial by NCT ID."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), trust_env=False) as client:
            response = await client.get(
                f"{settings.clinicaltrials_base_url}/studies/{nct_id}", params={"format": "json"}
            )
            if response.status_code == 404:
                raise NotFoundError(f"Trial {nct_id} not found")
            response.raise_for_status()
            raw = response.json()
        trial = clinical_trials_client.parse_trial(raw)
        if not trial:
            raise NotFoundError(f"Could not parse trial {nct_id}")
        return trial
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            fallback = await clinical_trials_client._search_trials_via_trialsmap(
                conditions=[nct_id],
                keywords=[],
                page_size=5,
            )
            for trial in fallback.get("parsed_trials", []):
                if trial.nct_id == nct_id:
                    return trial
        raise ServiceUnavailableError("Trial lookup failed") from exc
    except AppError:
        raise
    except Exception as exc:
        raise ServiceUnavailableError("Trial lookup failed") from exc


@router.get("/drugs/check")
@limiter.limit(settings.rate_limit_read)
async def check_drug_interaction(
    request: Request,
    _principal: CurrentPrincipal,
    drug1: str = Query(...),
    drug2: str = Query(...),
):
    """Quick drug interaction check between two drugs."""
    n1 = await rxnorm_client.normalize_drug_name(drug1)
    n2 = await rxnorm_client.normalize_drug_name(drug2)
    interactions = await openfda_client.get_drug_interactions(n1, [n2])
    reverse = await openfda_client.get_drug_interactions(n2, [n1])
    all_i = interactions + reverse
    return {
        "drug1": {"input": drug1, "normalized": n1},
        "drug2": {"input": drug2, "normalized": n2},
        "interactions_found": len(all_i),
        "interactions": [i.model_dump() for i in all_i],
        "is_safe": all(i.severity.value != "CRITICAL" for i in all_i),
    }


@router.get("/drugs/normalize")
@limiter.limit(settings.rate_limit_read)
async def normalize_drug(
    request: Request,
    _principal: CurrentPrincipal,
    name: str = Query(...),
):
    """Convert brand name to generic via RxNorm."""
    normalized = await rxnorm_client.normalize_drug_name(name)
    return {"input": name, "normalized": normalized, "source": "RxNorm NLM API"}
