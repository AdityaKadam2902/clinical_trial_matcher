"""
api/routes.py
─────────────
FastAPI route definitions for the Clinical Trial Matcher API.
"""

from fastapi import APIRouter, HTTPException, Query, Request
from loguru import logger
from slowapi import Limiter
from slowapi.util import get_remote_address
import time
import httpx

from schemas.patient import PatientProfile
from schemas.trial import MatchResponse
from agents.pipeline import run_pipeline
from utils.api_clients import clinical_trials_client, openfda_client, rxnorm_client
from core.config import settings

router = APIRouter(prefix="/api/v1", tags=["Clinical Trial Matcher"])
limiter = Limiter(key_func=get_remote_address)


@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "1.0.0",
        "model": settings.groq_model_complex,
        "environment": settings.app_env,
        "timestamp": time.time(),
    }


@router.post("/match", response_model=MatchResponse)
@limiter.limit("5/minute")
async def match_trials(
    request: Request,
    patient: PatientProfile,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
):
    """
    Main endpoint — runs full 6-agent pipeline.
    Rate limited: 5 requests/minute to protect Groq free tier.
    """
    logger.info(f"[API] Match request: patient={patient.patient_id}")
    try:
        result = await run_pipeline(
            patient=patient,
            page=page,
            page_size=min(page_size, settings.max_page_size),
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"[API] Pipeline error: {e}")
        raise HTTPException(status_code=500, detail=str(e)[:300])


@router.get("/trial/{nct_id}")
@limiter.limit("20/minute")
async def get_trial_detail(request: Request, nct_id: str):
    """Fetch full details for a specific trial by NCT ID."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), trust_env=False) as client:
            response = await client.get(
                f"{settings.clinicaltrials_base_url}/studies/{nct_id}",
                params={"format": "json"}
            )
            if response.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Trial {nct_id} not found")
            response.raise_for_status()
            raw = response.json()
        trial = clinical_trials_client.parse_trial(raw)
        if not trial:
            raise HTTPException(status_code=404, detail=f"Could not parse trial {nct_id}")
        return trial
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            fallback = await clinical_trials_client._search_trials_via_trialsmap(
                conditions=[nct_id],
                keywords=[],
                page_size=5,
            )
            for trial in fallback.get("parsed_trials", []):
                if trial.nct_id == nct_id:
                    return trial
        raise HTTPException(status_code=500, detail=str(e)[:300])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/drugs/check")
@limiter.limit("10/minute")
async def check_drug_interaction(
    request: Request,
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
@limiter.limit("20/minute")
async def normalize_drug(request: Request, name: str = Query(...)):
    """Convert brand name to generic via RxNorm."""
    normalized = await rxnorm_client.normalize_drug_name(name)
    return {"input": name, "normalized": normalized, "source": "RxNorm NLM API"}
