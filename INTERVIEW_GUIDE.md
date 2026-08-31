# Clinical Trial Matcher — Complete Interview Preparation Guide

> **Purpose of this document:** A file-by-file, concept-by-concept breakdown of the entire
> **Clinical Trial Matcher** project so you can explain *any* part of it confidently in an
> interview. Read it top to bottom, then use the **Interview Q&A** section at the end to self-test.
>
> Every claim here is verified against the actual source code in this repository.

---

## Table of Contents

1. [Project Overview — What This System Does](#1-project-overview)
2. [High-Level Architecture & Request Flow](#2-high-level-architecture--request-flow)
3. [Tech Stack — Every Technology Explained](#3-tech-stack)
4. [Directory Structure — What Every File Is For](#4-directory-structure)
5. [Entry Point: `main.py`](#5-entry-point-mainpy)
6. [Core Layer: Config / Database / Logger](#6-core-layer)
7. [API Layer: `api/routes.py`](#7-api-layer)
8. [Data Models: `schemas/`](#8-data-models)
9. [The 6-Agent LangGraph Pipeline — Deep Dive](#9-the-6-agent-langgraph-pipeline)
10. [The Safety Rule Engine — Deep Dive](#10-the-safety-rule-engine)
11. [The External API Clients — Deep Dive](#11-the-external-api-clients)
12. [The Scoring Model — Every Formula](#12-the-scoring-model)
13. [Pagination & Response Contract](#13-pagination--response-contract)
14. [Frontend — React + TypeScript Deep Dive](#14-frontend)
15. [Resilience, Error Handling & Rate Limiting](#15-resilience-error-handling--rate-limiting)
16. [Testing — What Is Covered](#16-testing)
17. [Deployment & Environment](#17-deployment--environment)
18. [Interview Q&A — Likely Questions & Model Answers](#18-interview-qa)
19. [Quick Reference Cheat Sheet](#19-quick-reference-cheat-sheet)

---

## 1. Project Overview

**Clinical Trial Matcher** is an **end-to-end, AI-powered clinical trial matching platform**.

### The problem it solves
Finding a clinical trial for a patient is notoriously hard because:
- Eligibility criteria are dense, free-form clinical text.
- Drug–drug interactions must be cross-checked against the patient's medications.
- Data is fragmented across several government/public sources.
- A wrong "match" can be dangerous for the patient.

### What the system does
Given a **structured patient profile** (age, sex, conditions, symptoms, medications, allergies,
lab values, etc.), it:

1. **Normalizes** the patient data (RxNorm medication standardization + LLM keyword extraction).
2. **Searches** ClinicalTrials.gov for actively recruiting trials (with automatic fallback).
3. **Evaluates eligibility** — an AI reasoner (DSPy + Groq 70B) reads each trial's
   inclusion/exclusion criteria and judges the patient against them.
4. **Checks safety** — a **deterministic rule engine** (age, sex, pregnancy, allergies, renal/
   liver/cardiac status) plus **OpenFDA** drug-interaction lookups.
5. **Ranks** the results with an **explainable, weighted, deterministic scoring formula**.
6. **Summarizes** the findings into a **physician-ready report**.

**Output:** a paginated, ranked list of trial matches with per-trial eligibility reasoning,
safety assessments, and an AI-generated physician summary.

### The core design philosophy (THE most important interview point)
> **Rule Engine = hard walls (never crossed, regardless of LLM confidence).**
> **LLM = intelligent reasoning WITHIN those hard walls.**

LLMs can hallucinate. A hallucinated "safe" result could enroll a patient in a dangerous trial.
So the project puts a **deterministic, pure-Python safety rule engine** in front of and around
the LLM. The LLM is used only for *reasoning* (eligibility interpretation, report writing),
never for *hard safety decisions*.

### Data sources (all free, no API keys)
| Source | Used for |
|--------|----------|
| **ClinicalTrials.gov v2 API** | Trial data (status, phase, eligibility, locations) |
| **TrialsMap** (HTML fallback) | Automatic fallback when ClinicalTrials.gov blocks/403s |
| **OpenFDA** | Drug labels, interactions, contraindications |
| **RxNorm (NLM)** | Drug-name normalization (brand → generic) + RxCUI codes |

---

## 2. High-Level Architecture & Request Flow

### System diagram
```
   React SPA (localhost:3000)
        │  POST /api/v1/match   (Vite proxy → localhost:8000)
        ▼
   FastAPI (main.py) → api/routes.py
        │
        ▼  run_pipeline()
   LangGraph StateGraph (agents/pipeline.py)
        │
        ├─▶ Agent 1  Profile Parser   [Groq 8B fast] + RxNorm   → normalized data
        ├─▶ Agent 2  Trial Fetcher    [no LLM] + ClinicalTrials.gov/TrialsMap
        │                               + pre-filter: status / location / phase
        │◀─ conditional edge: no trials → jump straight to Agent 6 (report)
        ├─▶ Agent 3  Eligibility Checker [DSPy ChainOfThought + Groq 70B]
        ├─▶ Agent 4  Drug Safety Agent [Rule Engine (deterministic)] + OpenFDA
        ├─▶ Agent 5  Ranker           [pure Python weighted formula]
        └─▶ Agent 6  Report Generator [Groq 70B] → physician summary
        │
        ▼
   MatchResponse (ranked trials + pagination + safety flags + summary)
        │
        ▼
   React results view (TrialCard components)
```

### End-to-end walkthrough (trace a request)
1. **Frontend** submits a `PatientProfile` JSON to `POST /api/v1/match`.
2. **Route** validates it with Pydantic (`PatientProfile`), enforces rate limit (5/min), calls `run_pipeline()`.
3. **`run_pipeline`** builds an initial `PipelineState`, invokes the compiled LangGraph graph via `pipeline.ainvoke()`.
4. Each agent reads state, does work, returns an updated state (relay baton).
5. `run_pipeline` applies pagination, builds a human-readable `query_summary`, and wraps everything in a `MatchResponse`.
6. Frontend renders the loading stepper, then the results view.

---

## 3. Tech Stack

### Backend
| Category | Technology | What it does here |
|----------|-----------|-------------------|
| Web framework | **FastAPI** + Uvicorn | Async REST API, automatic OpenAPI docs at `/docs` |
| Agent orchestration | **LangGraph** | Builds the state machine / directed graph of agents |
| Structured LLM reasoning | **DSPy** (`ChainOfThought`) | Guarantees typed, validated eligibility output |
| LLM provider | **Groq** via `langchain-groq` | `llama-3.3-70b-versatile` (complex) / `llama-3.1-8b-instant` (fast) |
| Validation | **Pydantic v2** + pydantic-settings | All schemas + centralized env config |
| Database | **PostgreSQL** via SQLAlchemy 2.0 + asyncpg | Async connection, session factory |
| HTTP + resilience | **httpx**, **aiohttp**, **tenacity** | Async HTTP, retries with exponential backoff |
| Rate limiting | **slowapi** | Per-IP endpoint throttling |
| Logging | **Loguru** | Rotating console + file + error logs |
| Serialization | **orjson** | Fast JSON |

### Frontend
| Category | Technology |
|----------|-----------|
| Framework | React 18 + TypeScript |
| Build tool | Vite 5 (dev server on :3000, proxies `/api` → :8000) |
| Styling | Tailwind CSS 3 |
| Data fetching | Axios + TanStack Query |
| Icons | lucide-react |

### Notable library details (be ready to explain these)
- **`dspy-ai`** is the PyPI package name (not `dspy`). README calls this out as a common install gotcha.
- **`uvicorn[standard]`**, **`psycopg2-binary`** (sync driver for tooling), **`asyncpg`** (async driver), **`alembic`** (migrations — declared but no migration files in this repo; tables are created at startup with `Base.metadata.create_all`).

---

## 4. Directory Structure

```
clinical_trial_matcher/
├── main.py                        # FastAPI entry point
├── requirements.txt               # Python deps
├── .env / .env.example            # Environment configuration
├── .gitignore                     # Secrets/artifacts ignored
├── README.md                      # Full project documentation
│
├── agents/                        # The 6-agent LangGraph pipeline
│   ├── __init__.py
│   ├── pipeline_state.py          # Shared TypedDict state (relay baton)
│   ├── pipeline.py                # Graph orchestration + conditional routing
│   ├── profile_parser.py          # Agent 1
│   ├── trial_fetcher.py           # Agent 2
│   ├── eligibility_checker.py     # Agent 3 (DSPy)
│   ├── drug_safety_agent.py       # Agent 4
│   ├── ranker_agent.py            # Agent 5
│   └── report_generator.py        # Agent 6
│
├── api/
│   ├── __init__.py
│   └── routes.py                  # REST endpoints
│
├── core/
│   ├── __init__.py
│   ├── config.py                  # Pydantic-settings config
│   ├── database.py                # Async PostgreSQL
│   └── logger.py                  # Loguru setup
│
├── data/                          # (empty package placeholder)
│   └── __init__.py
│
├── rules/
│   ├── __init__.py
│   └── safety_rules.py            # Deterministic clinical safety engine
│
├── schemas/
│   ├── __init__.py
│   ├── patient.py                 # FHIR R4-aligned patient models
│   └── trial.py                   # Trial / assessment / response models
│
├── utils/
│   ├── __init__.py
│   └── api_clients.py             # ClinicalTrials.gov, OpenFDA, RxNorm clients
│
├── tests/
│   ├── __init__.py
│   ├── test_api_clients.py        # API parsing tests (no network)
│   ├── test_rule_engine.py        # Safety engine tests (most critical)
│   └── test_pipeline_fixes.py     # Regression tests for pipeline fixes
│
├── logs/                          # Runtime logs (gitignored)
└── frontend/                      # React + TS SPA
    ├── index.html
    ├── package.json
    ├── vite.config.ts             # dev :3000, proxy /api → :8000
    ├── tailwind.config.js
    ├── postcss.config.js
    ├── tsconfig.json
    └── src/
        ├── main.tsx               # React root + QueryClient
        ├── index.css              # Tailwind + custom classes
        ├── App.tsx                # Form → loading → results state machine
        ├── services/api.ts        # Axios client
        ├── types/index.ts         # TS type contract
        └── components/
            ├── PatientForm.tsx    # Multi-section intake form
            └── TrialCard.tsx      # Ranked trial card
```

---

## 5. Entry Point: `main.py`

`main.py` is the FastAPI application bootstrap. Read it line by line:

```python
import os, time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from loguru import logger
```

### Key pieces

1. **`os.makedirs("logs", exist_ok=True)`** — guarantees the logs folder exists before logging starts.

2. **`setup_logger()`** — initializes Loguru sinks (console + rotating files).

3. **Lifespan context manager** (`@asynccontextmanager`):
   - **Startup:** `await create_tables()` — creates PostgreSQL tables from SQLAlchemy models.
   - **Shutdown:** `await close_db()` — disposes the engine / closes connections.
   - This is the modern FastAPI way to manage startup/shutdown (replaces deprecated `@app.on_event`).

4. **Rate limiter**:
   - `Limiter(key_func=get_remote_address)` — identifies each client by IP address.
   - `app.state.limiter = limiter` — slowapi reads this from app state.
   - `app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)` — returns a standard 429 response when a limit is hit.

5. **CORS middleware**:
   - `allow_origins=settings.cors_origins_list` (from env, comma-separated).
   - `allow_credentials=False`, all methods/headers allowed.

6. **Custom HTTP timing middleware**:
   ```python
   @app.middleware("http")
   async def timing(request: Request, call_next):
       start = time.time()
       response = await call_next(request)
       response.headers["X-Process-Time"] = f"{time.time()-start:.3f}s"
       return response
   ```
   Adds an `X-Process-Time` response header for observability.

7. **Router inclusion**: `app.include_router(router)` mounts all `/api/v1` endpoints.

8. **SPA static serving** (single-server deployment):
   - If `frontend/dist` exists (i.e., the frontend was built with `npm run build`):
     - Mounts `/assets` as static files.
     - Adds a catch-all route `/{full_path:path}` that serves `index.html` — this is the standard
       SPA pattern so client-side routes all fall back to the React app.
   - If not built, `/` returns a small JSON with links to `/docs` and `/health`.

**Interview talking point:** this design lets you run either two servers (Vite dev + FastAPI) or one
server (FastAPI serving the built SPA), which is why `frontend/dist` is gitignored.

---

## 6. Core Layer

### 6.1 `core/config.py` — Centralized configuration

Uses **pydantic-settings** (`BaseSettings`):

- **Required fields** (no default, `...`): `groq_api_key`, `database_url`, `database_url_sync`.
  If missing, the app fails fast at startup with a clear error — no runtime surprises.
- **Optional with defaults**: model names, Qdrant host/port/collection, external API base URLs,
  app host/port/env, secret key, CORS origins, pagination sizes.
- **`@property cors_origins_list`** — splits the comma-separated `CORS_ORIGINS` string into a list,
  trimming whitespace. Used by the CORS middleware.
- **`@property is_production`** — `app_env == "production"`.
- **`class Config`**: `env_file=".env"`, `env_file_encoding="utf-8"`, `case_sensitive=False`.
- **`@lru_cache()` on `get_settings()`** — the settings object is created **once per process** and
  cached. This is a cheap singleton pattern.
- **Module-level `settings = get_settings()`** — importable everywhere.

### 6.2 `core/database.py` — Async PostgreSQL

```python
engine = create_async_engine(
    settings.database_url,
    echo=not settings.is_production,   # SQL logging in dev only
    pool_size=10, max_overflow=20,     # connection pool
    pool_pre_ping=True,                # validate connections before use
)
```

- **`create_async_engine`** from `sqlalchemy.ext.asyncio` — async engine using the **asyncpg** driver.
- **Pool config**: 10 persistent connections, up to 20 overflow, `pool_pre_ping` avoids stale connections.
- **`async_sessionmaker(...)`** — creates `AsyncSession` instances with `expire_on_commit=False`
  (so objects remain usable after commit).
- **`Base(DeclarativeBase)`** — the base class all ORM models would inherit.
- **`get_db()`** — a FastAPI dependency that:
  - Yields a session inside `async with AsyncSessionLocal()`.
  - Commits on success, rolls back + logs + re-raises on error.
  - Auto-closes when the request completes.
- **`create_tables()`** — runs `Base.metadata.create_all` at startup.
- **`close_db()`** — `engine.dispose()` at shutdown.

**Honest interview note:** the app currently creates tables via metadata but defines **no ORM models**
— the DB is wired up and production-ready, but actual persistence isn't used in the current code
(no PII is stored, per the disclaimer). Acknowledge this if asked.

### 6.3 `core/logger.py` — Loguru setup

- **`logger.remove()`** removes Loguru's default handler, then adds three sinks:
  1. **Console** (`sys.stdout`) — colorized, level `DEBUG` in dev / `INFO` in prod.
     Format includes timestamp, level, file:function:line.
  2. **`logs/clinical_trial_matcher.log`** — rotates at 10 MB, retains 7 days, compresses to zip, level DEBUG.
  3. **`logs/errors.log`** — errors only, rotates 10 MB, retains 30 days, level ERROR.
- Loguru auto-adds timestamp/level/function/line metadata.

---

## 7. API Layer

`api/routes.py` defines the router with prefix `/api/v1`. Every endpoint is rate-limited.

### `GET /health`
Returns `{status, version, model, environment, timestamp}` — used by the frontend (and ops) to check service health and which Groq model is active.

### `POST /match` — the main pipeline endpoint
```python
@router.post("/match", response_model=MatchResponse)
@limiter.limit("5/minute")
async def match_trials(request: Request, patient: PatientProfile,
                       page: int = Query(default=1, ge=1),
                       page_size: int = Query(default=10, ge=1, le=50)):
```
- **`response_model=MatchResponse`** — FastAPI validates/serializes output with the Pydantic schema.
- **Rate limit 5/min** — protects the Groq free tier (≈30 req/min).
- **Query params**: `page` (≥1), `page_size` (1–50), then clamped to `settings.max_page_size`.
- Calls `run_pipeline(patient, page, page_size)`.
- Error mapping: `ValueError` → **422**, anything else → **500** (with first 300 chars of the message).
- Note: slowapi requires the `request: Request` parameter to derive the client IP.

### `GET /trial/{nct_id}`
- Fetches a single trial directly from ClinicalTrials.gov using `httpx.AsyncClient` (timeout 15s, `trust_env=False`).
- **404** → "not found". Other HTTP errors → 500, but a **403 triggers the TrialsMap fallback** and tries to find the trial there.
- Parses via `clinical_trials_client.parse_trial()`.

### `GET /drugs/check?drug1=&drug2=`
- Normalizes both drug names via RxNorm.
- Calls OpenFDA interactions in **both directions** and merges results.
- Returns `is_safe = True` only if **no CRITICAL** interaction exists.

### `GET /drugs/normalize?name=`
- One-liner brand → generic conversion via RxNorm.

**Interview note:** The route name in the router is `/trial/{nct_id}` (singular) while the README
documents `/trials/{nct_id}` — a small naming discrepancy; be aware of it.

---

## 8. Data Models

### 8.1 `schemas/patient.py` — FHIR R4-aligned patient model

**FHIR** = Fast Healthcare Interoperability Resources, the international standard for healthcare
data exchange used by Epic, Cerner, etc. Following it means the data can integrate with hospital EHRs.

**Enums:**
- `Sex`: MALE / FEMALE / OTHER / UNKNOWN
- `SmokingStatus`: NEVER / FORMER / CURRENT / UNKNOWN
- `ConditionSeverity`: MILD / MODERATE / SEVERE / UNKNOWN

**Sub-schemas (each maps to a FHIR resource):**
- `FHIRCondition` → FHIR **Condition** resource. Fields: `display` (required, trimmed + title-cased
  by a `field_validator`), `snomed_code` (SNOMED CT — international condition coding standard),
  `icd10_code` (ICD-10), `severity`, `onset_year` (1900–2100), `is_active`.
- `FHIRMedication` → FHIR **MedicationStatement**. Fields: `name` (required, lower-cased by
  `field_validator`), `rxnorm_code`, `dosage`, `frequency`, `route`, `is_active`.
- `LabValue` — `test_name`, `value` (float), `unit`, `reference_range`, `is_abnormal`, `test_date`.
- `Allergy` — `substance`, `reaction`, `severity` (Literal "mild"/"moderate"/"severe").

**`PatientProfile` (main schema):**
- `patient_id` auto-generated `PT-XXXXXXXX` via `default_factory=lambda: f"PT-{uuid4()[:8].upper()}"`.
- `age` 0–120, `sex` required, optional `weight_kg` (1–500), `height_cm` (30–250).
- Lists: `conditions`, `symptoms`, `medications`, `allergies`, `lab_values`,
  `prior_treatments`, `surgeries`, `family_history`.
- `smoking_status`, `is_pregnant`, `is_breastfeeding`.
- Search prefs: `preferred_locations`, `max_distance_km`, `trial_phases`
  (Literal `PHASE1..PHASE4`, `None` = all phases).

**Validation logic worth quoting in an interview:**
- `@model_validator(mode="after") validate_has_medical_data` — **at least one condition or symptom
  is required** or the profile is rejected with 422.
- `@field_validator("symptoms")` — strips and lower-cases symptoms.
- **Helper methods** (used by agents):
  - `get_condition_names()` → plain list of condition `display` strings.
  - `get_medication_names()` → medication names.
  - `get_all_drug_names()` → medications **+ allergy substances** deduplicated (used for interaction checks).

### 8.2 `schemas/trial.py` — Trial + assessment models

**Enums:**
- `TrialStatus`: RECRUITING, NOT_YET_RECRUITING, ACTIVE_NOT_RECRUITING, COMPLETED, TERMINATED, WITHDRAWN, SUSPENDED, UNKNOWN.
- `TrialPhase`: PHASE1–PHASE4, EARLY_PHASE1, NA.
- `EligibilityDecision`: ELIGIBLE, LIKELY_ELIGIBLE, POSSIBLY_ELIGIBLE, NOT_ELIGIBLE, NEEDS_REVIEW.
- `SafetyLevel`: SAFE, CAUTION, WARNING, CRITICAL.

**Sub-schemas:**
- `TrialLocation` — facility, city, state, country, zip, status, contact info.
- `TrialIntervention` — type (Drug/Device/Behavioral), name, description, arm_group.
- `EligibilityCriteria` — `raw_text`, structured `inclusion[]`/`exclusion[]`, `minimum_age`,
  `maximum_age`, `sex_eligible` ("All"/"Male"/"Female"), `accepts_healthy_volunteers`.
- `DrugInteractionFlag` — patient_drug, trial_drug, description, severity, source
  (Literal "OpenFDA"/"RxNorm"/"RuleEngine"), recommendation.
- `SafetyAssessment` — overall_level, drug_interactions[], allergy_conflicts[],
  contraindications[], rule_engine_flags[], `is_safe_to_proceed`, halt_reason.
- `EligibilityAssessment` — decision, confidence (0–1), match_score (0–100), met/unmet criteria,
  exclusion_triggers, reasoning, physician_notes.

**`ClinicalTrial` (cleaned trial):** a flattened, validated version of the messy raw ClinicalTrials.gov JSON.
- **Field validators:**
  - `strip_html` (on `brief_summary`/`detailed_description`) — regex `<[^>]+>` → space, collapses whitespace.
  - `normalize_list` (on `conditions`/`keywords`) — handles strings vs lists.
- Contains identifiers, status, phase, summaries, conditions, interventions,
  `intervention_names` (flat list for quick access), eligibility, locations, sponsor,
  timeline dates, enrollment, contacts, and `url` (`https://clinicaltrials.gov/study/{nct_id}`).

**`MatchedTrial`:** trial + eligibility + safety + `final_score` (0–100), `rank` (1-based),
plus quick-access fields `is_safe`, `decision`, `match_percentage`, `confidence`.

**`PaginationMeta`:** page, page_size, total_items, total_pages, has_next, has_previous.

**`MatchResponse`:** the full pipeline output — patient_id, search_id, query_summary, matches[],
pagination, total_trials_searched, total_eligible, processing_time_seconds, safety_halt,
safety_halt_reason, physician_summary, and a built-in `disclaimer`.

---

## 9. The 6-Agent LangGraph Pipeline

### 9.0 LangGraph concepts you must be able to explain

- **LangGraph** is a library for building **stateful, graph-structured LLM applications**.
- **`StateGraph`** — a directed graph of nodes (functions).
- **Nodes** — the agents; each is an `async` function `(state) -> new state`.
- **Edges** — define execution order.
- **Conditional edges** — a routing function decides which node runs next.
- **State** — a shared `TypedDict` passed between nodes like a relay baton; each node returns an
  updated dict (returning only the keys it changed is enough — LangGraph merges them).
- **`graph.compile()`** — produces a `CompiledStateGraph` that can be invoked with
  `ainvoke(initial_state)` (async) or `invoke()` (sync).
- The compiled graph is a **singleton created once at import time** (`pipeline = build_pipeline()`).

### 9.1 `pipeline_state.py` — the shared state (TypedDict)

Fields (grouped by producer):
- **Input:** `patient`, `search_id`, `requested_page`, `page_size`.
- **Agent 1 (Profile Parser):** `normalized_conditions`, `normalized_medications`,
  `search_keywords`, `profile_summary`.
- **Agent 2 (Trial Fetcher):** `raw_trials`, `total_trials_found`, `fetch_error`,
  `trials_dropped_by_phase`, `trials_dropped_by_location`.
- **Agent 3 (Eligibility Checker):** `eligibility_results`, `eligible_count`.
- **Agent 4 (Drug Safety):** `safety_assessments` (dict nct_id → SafetyAssessment), `drug_flags`.
- **Rule engine (run inside Agent 4):** `rule_violations`, `pipeline_halted`, `halt_reason`.
- **Agent 5 (Ranker):** `ranked_trials`.
- **Agent 6 (Report Generator):** `physician_summary`, `processing_start_time`.

**Interesting detail:** the docstring comments say "7 agents" and label the rule engine as "Agent 5"
and the report as "Agent 7". That's leftover from an earlier 7-node design. **The actual compiled
graph has exactly 6 nodes**, and the rule engine runs *inside* the drug-safety agent. If an
interviewer asks "how many agents?", say **6** — and if they've read the comments, explain the
discrepancy honestly.

### 9.2 `pipeline.py` — graph construction + entry function

**Graph construction (`build_pipeline`):**
```python
graph = StateGraph(PipelineState)
graph.add_node("profile_parser",      profile_parser_agent)
graph.add_node("trial_fetcher",       trial_fetcher_agent)
graph.add_node("eligibility_checker", eligibility_checker_agent)
graph.add_node("drug_safety",         drug_safety_agent)
graph.add_node("ranker",              ranker_agent)
graph.add_node("report_generator",    report_generator_agent)

graph.set_entry_point("profile_parser")
graph.add_edge("profile_parser", "trial_fetcher")

graph.add_conditional_edges(
    "trial_fetcher",
    _should_continue_after_fetch,
    {"eligibility_checker": "eligibility_checker",
     "report_generator":    "report_generator"},
)
graph.add_edge("eligibility_checker", "drug_safety")
graph.add_edge("drug_safety", "ranker")
graph.add_edge("ranker", "report_generator")
graph.add_edge("report_generator", END)
```

**Conditional routing function:**
```python
def _should_continue_after_fetch(state):
    if state.get("fetch_error") or not state.get("raw_trials"):
        return "report_generator"     # skip eligibility/safety/ranking
    return "eligibility_checker"
```
This is the **resilience/short-circuit** path: if no trials were found (or fetching failed),
skip straight to the report generator so the patient still gets an honest, actionable summary
explaining why no matches exist.

**`run_pipeline(patient, page, page_size)`** — the entry function:
1. Generates `search_id = f"SEARCH-{uuid4()[:8].upper()}"` and records `start_time`.
2. Builds the **initial state** (all fields pre-populated with empty defaults).
3. Calls `pipeline.ainvoke(initial_state)` inside try/except.
4. On exception → returns a **graceful `MatchResponse`** with empty matches and
   `physician_summary="Pipeline error — please try again."` (never a bare 500 crash).
5. On success → applies **pagination slicing**:
   - `total_pages = max(1, (total_items + page_size - 1) // page_size)` (ceil division).
   - `page_results = all_ranked[(page-1)*page_size : page*page_size]`.
6. Builds a **human-readable `query_summary`** that reflects conditions, requested phases,
   preferred locations, trials found, evaluated, eligible, returned, and drop counts — designed so
   the summary text is never internally inconsistent with the response numbers.
7. Returns the final `MatchResponse` (with `processing_time_seconds` rounded to 2 decimals).

### 9.3 Agent 1 — Profile Parser (`profile_parser.py`)

**Model:** `ChatGroq(model=groq_model_fast, temperature=0.0)` — the **8B fast model**, because this
is extraction, not reasoning.

**Responsibilities:**
1. **Normalize medications via RxNorm**: `rxnorm_client.normalize_medications(raw_meds)` (concurrent,
   `asyncio.gather`). On failure → falls back to lowercase raw names.
2. **Extract search keywords via LLM**: builds a JSON prompt from conditions/symptoms/age/sex,
   asks for `primary_conditions`, `secondary_keywords`, `normalized_conditions`. It:
   - Strips markdown code fences if the model wraps the JSON.
   - Parses with `json.loads`.
   - On any error → deterministic fallbacks (`condition_names[:5]`, `symptoms[:3]`).
3. **Clean condition terms** via `_clean_condition_terms`: removes non-condition words
   (`male`, `female`, `other`, `unknown`, `man`, `woman`, `symptom(s)`), dedupes case-insensitively,
   collapses whitespace.
4. **Build `profile_summary`**: a human-readable sentence with age, sex, conditions, symptoms,
   meds, smoking status, pregnancy — this becomes the patient text passed to the DSPy eligibility checker.
5. Returns updated state.

### 9.4 Agent 2 — Trial Fetcher (`trial_fetcher.py`)

**Model:** none — pure API + data cleaning.

**Key constant:** `FETCH_BUFFER_MULTIPLIER = 5`, hard-capped at **100 trials**:
```python
fetch_size = min(state["page_size"] * 5, 100)
```
Why a buffer? Because we pre-filter locally; we need more raw trials than the requested page size.

**Flow:**
1. Calls `clinical_trials_client.search_trials(conditions, keywords, status="RECRUITING", sex=...)`
   (sex only passed if MALE/FEMALE).
2. Parses raw studies via `parse_trial()` (skipping unusable ones).
3. **Pre-filter 1 — status**: keeps only `RECRUITING` and `NOT_YET_RECRUITING`.
4. **Pre-filter 2 — location** (only if `preferred_locations` set):
   - A trial passes if **any preferred location is a case-insensitive substring** of any of its
     countries or site states.
   - **Soft filter:** if *no* trial matches, it keeps the full list but records the drop count and
     logs a warning ("location filter could not be enforced"). Why? So results aren't silently emptied.
5. **Pre-filter 3 — phase** (only if `trial_phases` set):
   - Keeps only trials whose `phase.value` is in the requested set (e.g., {"PHASE2","PHASE3"}).
   - **Hard filter:** if *nothing* matches, it returns an **empty list** — the phase preference is
     respected and the report explains why. (This asymmetry — location is soft, phase is hard — is a
     deliberate design decision and a great interview talking point.)
6. Tracks `trials_dropped_by_phase` / `trials_dropped_by_location` counters for the query summary.
7. On exception → sets `fetch_error`, empty trials, `total_trials_found=0` (this triggers the
   conditional route to report generator).

### 9.5 Agent 3 — Eligibility Checker (`eligibility_checker.py`) — THE DSPy agent

**Model:** `dspy.LM(model=f"groq/{groq_model_complex}", api_key=..., temperature=0.0, max_tokens=1000)`,
configured globally via `dspy.configure(lm=groq_lm)`. **70B complex model**, temperature 0 for
deterministic medical decisions.

**Why DSPy here (from the code docstring):**
- Eligibility criteria are complex clinical text → need typed, validated output.
- DSPy guarantees every field in the output signature is populated.
- `ChainOfThought` forces step-by-step reasoning (like "think step by step").
- DSPy can self-correct if the output doesn't match the schema.

**`EligibilityCheckSignature` (a DSPy Signature):**
- **Inputs:** `patient_profile`, `inclusion_criteria`, `exclusion_criteria`, `trial_name`.
- **Outputs (typed, validated):** `is_eligible` (bool), `confidence_score` (float 0–1),
  `match_score` (float 0–100), `met_criteria` (list), `unmet_criteria` (list),
  `exclusion_triggers` (list), `reasoning` (str).
- The docstring becomes the task description in the generated prompt.

**`EligibilityChecker(dspy.Module)`:** wraps `dspy.ChainOfThought(EligibilityCheckSignature)`.
(`dspy.Suggest` assertions are commented out — noted honestly.)

**Concurrency model (important):**
- DSPy is **synchronous / not async-native**, so it runs in a `ThreadPoolExecutor(max_workers=3)`
  via `loop.run_in_executor(...)`.
- Trials are checked in **batches of 5** with `asyncio.gather`, with a **2-second sleep between
  batches** to respect Groq free-tier rate limits (~30 req/min).
- Only the **first 20 trials** are evaluated (`trials[:20]`) to stay within rate limits.

**Decision mapping (from `_check_single_trial_sync`):**
```python
if not is_eligible or result.exclusion_triggers:
    decision = NOT_ELIGIBLE
elif match_score >= 80 and confidence >= 0.7:
    decision = ELIGIBLE
elif match_score >= 60 and confidence >= 0.5:
    decision = LIKELY_ELIGIBLE
elif match_score >= 40:
    decision = POSSIBLY_ELIGIBLE
else:
    decision = NEEDS_REVIEW
```
- Any exclusion trigger or a "not eligible" flag → hard `NOT_ELIGIBLE`.
- High score + high confidence → `ELIGIBLE`.
- Mid-range → `LIKELY_ELIGIBLE` / `POSSIBLY_ELIGIBLE`.
- Everything else → `NEEDS_REVIEW`.

**Honest-uncertainty short-circuit (a regression fix worth mentioning):**
- If criteria are unavailable (the TrialsMap sentinel string, or all of inclusion/exclusion/raw_text
  empty), the checker **immediately returns `NEEDS_REVIEW` with confidence 0 and match 0** —
  **no LLM call is made**, so no false confidence is fabricated. `physician_notes` explicitly says
  manual review is required.

**Eligibility agent output:** `eligibility_results` (list of `{nct_id, assessment}`) and
`eligible_count` (count of ELIGIBLE/LIKELY/POSSIBLY).

### 9.6 Agent 4 — Drug Safety Agent (`drug_safety_agent.py`)

**Order of operations per eligible trial:**
1. **Rule engine first** (`rule_engine.evaluate(patient, trial)`) — deterministic, <1ms, no network.
   - If `halt_pipeline` → the trial gets `SafetyAssessment(overall_level=CRITICAL, is_safe_to_proceed=False)`
     and is **skipped** (no OpenFDA call).
2. **OpenFDA interaction check** — only if the trial has `intervention_names` and the patient has
   meds. Checks the **first 3 trial drugs** against patient medications concurrently
   (`asyncio.gather`). OpenFDA queries the `/drug/label.json` endpoint and scans
   `drug_interactions`, `warnings`, `boxed_warning`, and `contraindications` text.
3. **Allergy conflict detection** — substring match of each patient allergen against each trial
   intervention name.
4. **Overall level computation**:
   - any CRITICAL interaction → **CRITICAL**, not safe.
   - any WARNING interaction or rule violations → **WARNING**, still safe-to-proceed (requires review).
   - rule engine CAUTION → **CAUTION**.
   - else → **SAFE**.
5. Collects `drug_flags` strings for CRITICAL/WARNING interactions.

**`eligible_nct_ids`** = trials whose decision is *not* `NOT_ELIGIBLE` — an optimization so safety
checks only run on plausible matches.

**Note:** `pipeline_halted` is set to `False` here in all cases (comment: "only halt if ALL trials are
critical") — the halt is per-trial in practice, surfaced via `SafetyAssessment`, and CRITICAL trials
are dropped by the ranker.

### 9.7 Agent 5 — Ranker (`ranker_agent.py`)

**Pure Python, deterministic, no LLM.** See [Section 12](#12-the-scoring-model) for the formula.

**Logic:**
1. Build `trial_map` (nct_id → trial) and `eligibility_map` (nct_id → EligibilityAssessment,
   reconstructing the Pydantic model from the stored dict).
2. For each trial:
   - **Skip if no eligibility assessment** (wasn't evaluated).
   - **Default SAFE** safety assessment if drug safety never ran for it (e.g., ineligible trials).
   - **Hard-exclude `NOT_ELIGIBLE`** — must never surface as a match, even if some `met_criteria`
     were populated (partial hits ≠ eligible). This is a documented regression fix.
   - **Hard-exclude `CRITICAL`** safety.
   - **Keep `NEEDS_REVIEW`/`POSSIBLY_ELIGIBLE`** so uncertain cases surface for physician review
     rather than being silently discarded.
3. Compute `final_score`, build `MatchedTrial`, sort descending, assign `rank = 1..N`.

### 9.8 Agent 6 — Report Generator (`report_generator.py`)

**Model:** `ChatGroq(model=groq_model_complex, temperature=0.1, max_tokens=1500)` — 70B for
professional medical prose.

**Logic:**
1. **No ranked trials** → builds a *deterministic* fallback summary choosing among 4 cases:
   - All `NEEDS_REVIEW` (fallback source lacked criteria) → advise manual review.
   - Dropped by phase only → advise broadening phase preference.
   - Dropped by location only → advise broadening location preference.
   - Both dropped → advise relaxing either.
   - Genuinely nothing found → recommend a research coordinator / manual search.
   This guarantees an honest, useful report even when the pipeline found nothing.
2. **With results** → prepares the **top 3 trials** as text (title, NCT ID, phase, status, score,
   decision, sponsor, reasoning snippet, location, URL, safety note), then prompts the LLM to write
   a physician summary with **strict clinical guardrails**:
   - Must not recommend changing/stopping patient medications.
   - Must not recommend any treatment beyond enrollment guidance.
   - Must not claim higher confidence than the eligibility assessment shows.
   - Must flag `NEEDS_REVIEW` explicitly.
   - Under 250 words, no markdown, ends with the disclaimer.
3. On LLM failure → deterministic fallback summary.

---

## 10. The Safety Rule Engine

File: `rules/safety_rules.py`. **The single most important component.** Pure Python, no I/O.

### Data structures
- **`RuleViolation`** (dataclass): `rule_id`, `severity`, `description`, `recommendation`,
  `halt_pipeline` (bool).
- **`RuleEngineResult`**: `violations[]`, `is_safe`, `halt_pipeline`, `overall_severity`,
  `flags_summary[]`, plus `add_violation()` which:
  - Appends the description to `flags_summary`.
  - Sets `halt_pipeline=True` + `is_safe=False` if the violation is a halt.
  - **Escalates severity only (never de-escalates)** using an ordinal map
    `SAFE(0) < CAUTION(1) < WARNING(2) < CRITICAL(3)`.

### Drug/condition dictionaries (the medical knowledge base)
- `PREGNANCY_DANGEROUS_INTERVENTIONS`: chemotherapy, doxorubicin, cyclophosphamide, methotrexate,
  paclitaxel, cisplatin, carboplatin, radiation, thalidomide, lenalidomide, pomalidomide, warfarin,
  valproate, isotretinoin, ribavirin, live vaccine, experimental, immunotherapy.
- `PEDIATRIC_EXCLUDED_KEYWORDS`: "adults only", "18 years and older", "18 years or older",
  "adult patients", "age 18", "minimum age 18".
- `RENAL_DANGEROUS_DRUGS`: NSAIDs, ibuprofen, naproxen, indomethacin, contrast, gadolinium,
  aminoglycosides, gentamicin, tobramycin, vancomycin, cyclosporine, tacrolimus, metformin.
- `LIVER_DANGEROUS_DRUGS`: acetaminophen/paracetamol, isoniazid, valproate, amiodarone,
  methotrexate, leflunomide, niacin, ketoconazole.
- `CARDIAC_DANGEROUS_DRUGS`: doxorubicin, anthracycline, trastuzumab, sunitinib, bevacizumab,
  5-fluorouracil, capecitabine.
- `AGE_RELATED_CAUTIONS`: children(0–12), adolescents(12–18), elderly/geriatric(65+), pediatric(0–18).

### The rules (each is a `_check_*` method run in order)
| Rule | ID(s) | Severity / Halt? | Logic |
|------|-------|------------------|-------|
| **Status** | `STATUS_001` | CRITICAL / halt | Trial in COMPLETED/TERMINATED/WITHDRAWN/SUSPENDED |
| **Age** | `AGE_001` (too young), `AGE_002` (too old) | CRITICAL / halt | Patient age outside trial's min/max window |
| **Sex** | `SEX_001` (male-only trial, female patient), `SEX_002` (reverse) | CRITICAL / halt | Trial `sex_eligible` mismatch |
| **Pregnancy** | `PREG_001` | CRITICAL / halt | Pregnant/breastfeeding + teratogenic intervention (one critical flag is enough, then returns) |
| | `PREG_002` | WARNING / no halt | Pregnant + "experimental" trial → MFM consult |
| **Allergy** | `ALLERGY_001` | CRITICAL (severe allergy) / halt **or** WARNING | Substring match allergen ↔ trial drug; severity drives severity |
| **Renal** | `RENAL_001` | WARNING / no halt | Renal condition + nephrotoxic drug → nephrology consult |
| **Liver** | `LIVER_001` | WARNING / no halt | Liver condition + hepatotoxic drug → hepatology consult |
| **Cardiac** | `CARDIAC_001` | WARNING / no halt | Cardiac condition + cardiotoxic drug → cardiology eval |
| **Pediatric** | `PEDS_001` | CRITICAL / halt | Patient <18 and adult-only keywords in criteria/title |

**Key properties to state in an interview:**
- **Deterministic** — same input, same output, every time.
- **Auditable** — every violation has a `rule_id`, severity, description, recommendation →
  traceable for regulatory/compliance review.
- **Instant** — pure Python, <1 ms per trial, no network/rate limits.
- **Non-negotiable** — critical violations set `halt_pipeline=True`; the trial is never surfaced
  as a match. The LLM can never override the rule engine.

---

## 11. The External API Clients

File: `utils/api_clients.py`. All three clients share: httpx async, tenacity retries with
exponential backoff, `trust_env=False` (ignore system proxies), and a shared `TIMEOUT =
httpx.Timeout(30.0, connect=10.0)`.

### 11.1 `ClinicalTrialsClient`

- **`FIELDS`** — a whitelist of `protocolSection.*` submodules to request, so responses are smaller.
- **`_normalize_query_terms(terms, limit)`** — trims, dedupes, caps free-text terms.
- **`_build_ctg_search_variants(...)`** — builds **a sequence of increasingly simpler queries**
  (e.g., specific cond+term+sex → cond+term → cond → patient → term). Rationale: CT.gov sometimes
  rejects complex requests (403); the client tries progressively simpler ones.
- **`search_trials(...)`**:
  - Tries each variant; on **403** continues to the next variant.
  - On 403 for *all* variants → falls back to `_search_trials_via_trialsmap()`.
  - Uses `countTotal=true` for total counts; cursor pagination via `nextPageToken` internally.
  - Wrapped in `@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)))`.
- **`parse_trial(raw_study)`** — flattens the deeply nested JSON:
  - Reads each `*Module`, skips trials missing `nctId` or a `briefTitle`.
  - Maps status and phase strings to enums with safe fallbacks.
  - `_parse_eligibility` splits `eligibilityCriteria` text on the "Exclusion Criteria" marker,
    strips the "Inclusion Criteria" header, and parses bullets via `_parse_bullets` (handles `-`, `*`, `•`, numbers).
  - `_parse_age_years`: "18 Years"→18, "6 Months"→0 (floor division by 12), "N/A"→None.
  - `_parse_locations` caps at 10 sites; dedupes countries.
  - Builds `url = f"https://clinicaltrials.gov/study/{nct_id}"`.
  - Any exception → returns `None` (trial skipped), logged as warning.
- **TrialsMap HTML fallback (`_search_trials_via_trialsmap`)** — when CT.gov is blocked:
  1. GET the landing page to scrape a **CSRF token**.
  2. POST the search query with that token.
  3. Paginates up to 5 pages, extracts `<article>` HTML blocks.
  4. `_parse_trialsmap_article` uses regex to pull title, NCT link, status badge, summary, sponsor,
     age range, gender, countries (from an embedded JS array), and contact info.
  5. Eligibility gets the sentinel `raw_text="Eligibility details unavailable from TrialsMap fallback."`
     and empty inclusion/exclusion → which later triggers the NEEDS_REVIEW short-circuit.
  - Returns `{studies: [], parsed_trials: [...], total_count, next_page_token: None}`.

### 11.2 `OpenFDAClient`

- **`get_drug_interactions(drug_name, patient_medications)`**:
  - Queries `${base}/drug/label.json` with `search=openfda.generic_name:"{drug_name}"`, `limit=1`.
  - Reads the top label's `drug_interactions`, `warnings`, `boxed_warning`, `contraindications` text.
  - For each patient medication, if it appears in the interactions text → **WARNING** flag with the
    relevant sentence; if in contraindications text → **CRITICAL** flag.
  - Returns `DrugInteractionFlag[]`; on 404/no results → `[]`.
  - Retry: 3 attempts, exponential 2–8s, only on timeout/connect errors.
- **`get_adverse_events(drug_name, limit=5)`** — queries `/drug/event.json` counting reactions by
  MedDRA preferred term (reactionmeddrapt). Used for physician warnings.

### 11.3 `RxNormClient`

- **`normalize_drug_name(name)`** — brand → generic:
  1. `approximateTerm.json?term={drug}&maxEntries=1` → best candidate's `rxcui`.
  2. `rxcui/{rxcui}/properties.json` → `properties.name` (the generic name).
  3. Any failure → returns the input lower-cased (graceful degradation).
- **`normalize_medications(drug_names)`** — concurrent via `asyncio.gather`; on per-item exception,
  keeps the original lower-cased name.
- **`get_interaction_list(rxcui_list)`** — RxNorm interaction API (`interaction/list.json`,
  joins first 10 RxCUIs with `+`); returns `fullInteractionTypeGroup`.

### Singletons
`clinical_trials_client`, `openfda_client`, `rxnorm_client` — created once at module import and
reused across requests (cheap, no per-request instantiation).

---

## 12. The Scoring Model

**Deterministic, explainable, weighted 0–100 formula** — no LLM involvement.

| Dimension | Weight | Basis |
|-----------|:------:|-------|
| **Eligibility match** | 40% | DSPy `match_score` (0–100) |
| **Safety level** | 30% | SAFE=100 · CAUTION=75 · WARNING=40 · CRITICAL=0 |
| **Trial phase** | 15% | PHASE4=100 · PHASE3=90 · PHASE2=70 · PHASE1=50 · EARLY_PHASE1=30 · NA=60 |
| **Enrollment proximity** | 10% | RECRUITING=100 · NOT_YET_RECRUITING=70 · +10 bonus if enrollment_count > 100 (capped at 100) |
| **Recency** | 5% | started ≤1yr ago=100 · ≤2yr=85 · ≤3yr=70 · else=50 · default=60 |

```python
final_score = (
    eligibility_score * 0.40 +
    safety_score      * 0.30 +
    phase_score       * 0.15 +
    enrollment_score  * 0.10 +
    recency_score     * 0.05
)
return round(final_score, 2)
```

**Recency parsing** tries multiple date formats (`%Y-%m-%d`, `%Y-%m`, `%Y`) and computes years ago
using `days / 365.25`.

**Why explainable?** Because every component maps back to a visible dimension, a physician can see
*why* a trial scored the way it did. Deterministic = auditable (same inputs → same output).

---

## 13. Pagination & Response Contract

- `page` (default 1, `ge=1`) and `page_size` (default 10, `ge=1`, `le=50`, clamped to
  `settings.max_page_size`).
- The pipeline evaluates **up to 20 trials** but ranks all of them; pagination slices the ranked list.
- `PaginationMeta`: `page`, `page_size`, `total_items`, `total_pages` (ceil), `has_next`, `has_previous`.
- Frontend re-issues `POST /match?page=N` when navigating pages (the whole pipeline re-runs because
  results aren't cached/persisted — a known design tradeoff).

---

## 14. Frontend

### 14.1 `main.tsx`
- React 18 root, `React.StrictMode`.
- **TanStack Query** `QueryClient` with `retry: 1` and `staleTime: 5 * 60 * 1000` (5 min) — data is
  considered fresh for 5 minutes (though the match call is a mutation-style POST used via plain axios).

### 14.2 `services/api.ts`
- Axios instance, `baseURL: '/api/v1'` (relative → handled by Vite proxy in dev or the SPA mount in prod),
  `timeout: 120000` (2 min — pipeline can take 30–60s).
- Functions: `matchTrials(patient, page, pageSize)` (POST with query params),
  `getTrial(nctId)`, `checkDrugInteractions(...)`, `normalizeDrug(name)`, `healthCheck()`.

### 14.3 `types/index.ts`
- Mirrors the backend Pydantic contract 1:1: `PatientProfile`, `EligibilityAssessment`,
  `DrugInteraction`, `SafetyAssessment`, `TrialLocation`, `TrialIntervention`,
  `EligibilityCriteria`, `ClinicalTrial`, `MatchedTrial`, `PaginationMeta`, `MatchResponse`.
- This guarantees type safety between the TS UI and the Python API.

### 14.4 `App.tsx` — the view state machine
- **View states:** `'form' | 'loading' | 'results'`.
- **`PIPELINE_STEPS`** — an array of 7 steps shown to the user (note: the UI *shows* 7 steps
  including a separate "Safety Rule Engine" step; the backend has 6 agents with the rule engine
  inside the safety agent — good interview nuance).
- **`handleSubmit`**: sets loading view, starts a cosmetic `setInterval` that advances the
  active step every 6 seconds, calls `matchTrials`, then shows results or an error.
  - Error text pulled from `err.response?.data?.detail` (FastAPI's standard error format).
- **`handlePageChange`**: re-runs `matchTrials(lastPatient, newPage, 10)`, scrolls to top.
- **Results view** renders: header card (search_id, query_summary, processing time), stats grid
  (trials searched / eligible / ranked matches), optional safety-halt alert, physician summary card,
  no-results card, list of `TrialCard`s, and pagination controls (max 7 page buttons).

### 14.5 `components/PatientForm.tsx`
- Multi-section intake form: Demographics → Conditions & Symptoms → Medications & Allergies →
  Lab Values → Search Preferences.
- Controlled inputs + local "add/remove" pattern for list fields.
- **Client-side validation** mirrors the backend: age 0–120, sex required, at least one condition
  or symptom.
- Dynamic lists via `setProfile` spread + filter; phase selector toggles entries in `trial_phases`
  (empty → `undefined` meaning "all phases").

### 14.6 `components/TrialCard.tsx`
- Renders one `MatchedTrial`:
  - **Decision badge** color config map (`DECISION_CONFIG`) for ELIGIBLE/LIKELY/POSSIBLY/
    NOT_ELIGIBLE/NEEDS_REVIEW.
  - **Safety badge** color config map (`SAFETY_CONFIG`) for SAFE/CAUTION/WARNING/CRITICAL.
  - **Rank 1** gets a "Top Match" banner + accent ring.
  - Score circle (final_score /100), NCT ID, phase label, status, sponsor, summary,
    conditions/interventions chips, countries + site count, start date.
  - **Safety warnings**: CRITICAL halt box, drug-interaction box.
  - **Expandable section**: AI eligibility reasoning, met/unmet criteria, raw inclusion/exclusion
    criteria (first 5 each), trial contact info, and "View on ClinicalTrials.gov" link.

### 14.7 Styling (`index.css`, `tailwind.config.js`)
- Tailwind 3 with custom theme: `paper`, `ink` (DEFAULT/muted/faint), `line`, `accent`
  (DEFAULT/hover/soft), Inter + JetBrains Mono fonts, custom shadows.
- Reusable component classes via `@layer components`: `.card`, `.badge`, `.btn-primary`,
  `.btn-secondary`, `.input-field`, `.label`, `.section-title`.

---

## 15. Resilience, Error Handling & Rate Limiting

**Layered resilience:**
1. **HTTP retries** — tenacity on ClinicalTrials.gov search (3 attempts, exp backoff 2–10s),
   OpenFDA (3 attempts, 2–8s), RxNorm (3 attempts, 1–6s).
2. **Query-variant fallbacks** — progressively simpler CT.gov queries on 403.
3. **Alternative source fallback** — TrialsMap HTML scraper when CT.gov is fully blocked.
4. **Graceful per-agent degradation** — RxNorm failure → raw names; LLM keyword extraction failure →
   deterministic fallbacks; LLM report failure → deterministic summary; DSPy per-trial failure →
   NEEDS_REVIEW with error text.
5. **Pipeline-level graceful error** — `run_pipeline` catches exceptions and returns an empty
   `MatchResponse` rather than crashing.
6. **Rate-limit awareness** — slowapi per-IP limits (match 5/min, trial 20/min, drugs/check 10/min,
   normalize 20/min), eligibility batch size 5 + 2s sleep, ≤20 trials evaluated, ≤3 trial drugs
   checked per trial.

**Honesty safeguards (design-level):**
- NEEDS_REVIEW for unavailable criteria — no fabricated confidence.
- NOT_ELIGIBLE and CRITICAL hard-excluded from results.
- Report guardrails (no medication changes, no over-claiming confidence).
- Built-in disclaimers on every response and in the UI.

---

## 16. Testing

All tests run **without network access** (mock data / pure parsing).

### `tests/test_rule_engine.py` (most critical)
Fixtures: `make_patient()` / `make_trial()`.
- `test_safe_patient_passes` — baseline SAFE.
- `test_patient_too_young` / `test_patient_too_old` — AGE_001/AGE_002, halt.
- `test_wrong_sex` — SEX rule, halt.
- `test_pregnancy_with_chemo` — PREG_001, halt.
- `test_allergy_to_trial_drug` — ALLERGY_001 with severe allergy, halt.
- `test_completed_trial_halts` — STATUS_001, halt.
- `test_renal_patient_with_nsaid` — RENAL_001 → WARNING, **no halt**.
- `test_pediatric_patient_adult_trial` — PEDS_001, halt.
- `test_multiple_violations` — multiple violations captured, halt.

### `tests/test_api_clients.py`
- `parse_trial` returns trial, strips HTML, correct status/phase.
- Eligibility text splits into inclusion/exclusion; age parsing; bullets parsing.
- URL format, missing-NCT → None.
- TrialsMap article HTML parsing (title, NCT, status, sponsor, age range, gender, countries, contacts).

### `tests/test_pipeline_fixes.py` (regression tests)
1. Location filter drops non-matching trials / keeps matching.
2. Phase filter is enforced (no silent fallback) / passes matching.
3. Ranker excludes NOT_ELIGIBLE even with met_criteria; keeps NEEDS_REVIEW.
4. Eligibility checker returns NEEDS_REVIEW (conf 0, match 0) without an LLM call when criteria
   are unavailable.
5. `query_summary` reflects phase/location preferences.
6. Drop counters propagate through state (`trials_dropped_by_phase` / `_by_location` preserved by ranker).

### Run commands
```bash
pytest tests/ -v
pytest tests/test_rule_engine.py -v
pytest tests/ -v --cov=. --cov-report=term-missing
```

---

## 17. Deployment & Environment

### Environment variables (from `core/config.py`)
| Variable | Required | Notes |
|----------|:--------:|-------|
| `GROQ_API_KEY` | Yes | free at console.groq.com |
| `DATABASE_URL` | Yes | `postgresql+asyncpg://...` |
| `DATABASE_URL_SYNC` | Yes | for Alembic/tooling |
| `GROQ_MODEL_COMPLEX` / `GROQ_MODEL_FAST` | No | defaults to 70b / 8b |
| `QDRANT_HOST/PORT/COLLECTION` | No | vector DB (optional) |
| `CLINICALTRIALS_BASE_URL` / `OPENFDA_BASE_URL` / `RXNORM_BASE_URL` | No | defaults to the public APIs |
| `APP_ENV/HOST/PORT` | No | dev defaults |
| `SECRET_KEY` | No | **must change in production** |
| `CORS_ORIGINS` | No | comma-separated |
| `DEFAULT_PAGE_SIZE` / `MAX_PAGE_SIZE` | No | 10 / 50 |

### Run locally
```bash
# backend
python -m venv .venv && .venv\Scripts\Activate.ps1
pip install -r requirements.txt
# set .env, start PostgreSQL
uvicorn main:app --reload --port 8000   # → /docs

# frontend
cd frontend && npm install && npm run dev   # → :3000, /api proxied to :8000
```

### Deploy
- Backend: Railway/Render/Docker; managed Postgres; set env vars.
- Frontend: Vercel/Netlify; set `VITE_API_URL`, CORS must include the origin.
- Qdrant: optional, cloud free tier.

---

## 18. Interview Q&A

### Core concepts
**Q: Explain the project in one minute.**
A: It's an AI-powered clinical trial matching platform. Given a patient profile, a 6-agent
LangGraph pipeline normalizes the data, searches ClinicalTrials.gov, evaluates eligibility with a
DSPy/Groq LLM reasoner, applies a deterministic safety rule engine plus OpenFDA drug-interaction
checks, ranks trials with an explainable weighted score, and produces a physician summary. The key
design principle is safety-first: the deterministic rule engine is a hard wall the LLM can never
override.

**Q: Why LangGraph?**
A: It models the pipeline as an explicit directed graph of agents with shared state. Each agent is a
node reading/writing a shared `PipelineState` TypedDict. It gives us conditional routing (e.g., skip
to the report if no trials are found), a single compiled graph, and clean async invocation
(`ainvoke`).

**Q: What is DSPy and why did you use it?**
A: DSPy is a framework for programming LLMs with structured signatures instead of raw prompts. Here
it guarantees typed, validated eligibility output — `is_eligible`, `confidence_score`, `match_score`,
criteria lists, reasoning — so the model can't return free-form text. `ChainOfThought` forces
step-by-step reasoning, which improves accuracy for clinical reasoning.

**Q: Why a deterministic rule engine instead of another LLM?**
A: LLMs hallucinate. A hallucinated "safe" verdict could enroll someone in a dangerous trial. The
rule engine is deterministic, auditable (rule_id/severity/recommendation), instant (<1ms), and
non-negotiable — critical violations set `halt_pipeline=True` and the trial is never surfaced.

**Q: How do the rule engine and LLM cooperate?**
A: They're layered. Rules run first and are hard walls — age, sex, pregnancy, allergy, organ-system
warnings. The LLM (DSPy eligibility checker + report generator) reasons *within* those walls, e.g.,
interpreting free-text inclusion/exclusion criteria. The rule engine's per-trial flags also feed
into the SafetyAssessment, which feeds the ranker.

### Scoring & decisions
**Q: How is a trial scored?**
A: 0–100 weighted formula: eligibility match 40% (from DSPy), safety 30% (SAFE=100/CAUTION=75/
WARNING=40/CRITICAL=0), phase 15% (Phase 3/4 highest), enrollment 10% (recruiting + size bonus),
recency 5%. Deterministic and explainable — no LLM in the ranking.

**Q: How is the eligibility decision derived?**
A: From DSPy's `is_eligible`, `exclusion_triggers`, `match_score`, and `confidence`: any exclusion
trigger or non-eligible → NOT_ELIGIBLE; match ≥80 and confidence ≥0.7 → ELIGIBLE; ≥60/≥0.5 →
LIKELY_ELIGIBLE; ≥40 → POSSIBLY_ELIGIBLE; else NEEDS_REVIEW.

**Q: Why keep NEEDS_REVIEW trials?**
A: They're honest uncertainty. When criteria are missing (e.g., from the TrialsMap fallback) we
never fabricate confidence — we return NEEDS_REVIEW with confidence 0 so the physician manually
reviews. Hard-excluding them would hide potentially relevant trials; presenting them as ELIGIBLE
would be dangerous.

### Resilience & data
**Q: What happens if ClinicalTrials.gov blocks you?**
A: The client builds progressively simpler query variants and retries; if still 403, it falls back
to scraping the TrialsMap HTML mirror, which yields trials but with sparse data (eligibility set to
a sentinel string). Those trials then flow through the pipeline as NEEDS_REVIEW rather than being
fabricated.

**Q: How do you handle rate limits?**
A: Multiple layers: slowapi per-IP endpoint limits; tenacity retries with exponential backoff;
eligibility checks batched 5-at-a-time with 2s sleeps and capped at 20 trials; only the first 3 trial
drugs checked per trial; a 5/min limit on the match endpoint itself (protects Groq free tier).

**Q: Why normalize drug names with RxNorm?**
A: Brand names differ by country and registry; generic names are universal. Normalizing
(brand → generic, e.g., "Tylenol" → "acetaminophen") makes OpenFDA interaction matching reliable
because FDA labels are written against generic names.

**Q: Where does the fallback data come from and how do you avoid hallucination there?**
A: TrialsMap is a public mirror of recruiting trials. Its scraper extracts title, status, sponsor,
age/gender, countries, contact. It has no detailed eligibility text, so eligibility becomes the
sentinel string; the eligibility checker short-circuits to NEEDS_REVIEW and never calls the LLM with
a prompt that implies criteria exist.

### FHIR / models
**Q: What is FHIR and why is it used?**
A: FHIR R4 is the international healthcare data-exchange standard (used by Epic, Cerner, etc.).
The patient schema maps to FHIR Patient/Condition/MedicationStatement resources, and uses standard
coding systems (SNOMED CT for conditions, RxNorm for medications, ICD-10). This makes the system
EHR-integratable.

**Q: What validation does a patient profile go through?**
A: Pydantic v2: age 0–120, sex required, at least one condition or symptom (model_validator),
symptoms normalized, condition display title-cased, medication names lower-cased, optional fields
range-checked (weight 1–500, height 30–250).

### Frontend
**Q: How does the frontend talk to the backend?**
A: Axios against `/api/v1`. In dev, Vite proxies `/api` to `localhost:8000`. In prod, FastAPI mounts
the built SPA (`frontend/dist`) and serves it as static files with a catch-all route. TanStack Query
wraps data fetching with retry/staleness.

**Q: Why does the UI show 7 steps when there are 6 agents?**
A: The UI breaks out "Safety Rule Engine" as its own visual step for clarity, but in the backend the
rule engine is invoked inside the Drug Safety agent (Agent 4). (Also note: `pipeline_state.py`
docstrings reference an older 7-agent layout — the compiled graph is 6 nodes.)

**Q: What happens if the pipeline errors mid-run?**
A: `run_pipeline` catches it, logs it, and returns a valid `MatchResponse` with zero matches and
"Pipeline error — please try again." as the summary. The API maps `ValueError`→422 and other
errors→500. The frontend shows the error detail and returns to the form.

### System design / architecture
**Q: How would you scale this?**
A: Move eligibility checks to a queue (e.g., Celery/Redis) so the request doesn't block for 30–60s;
add caching of normalized trials and eligibility results (the pipeline currently re-runs per page
request); use Qdrant (already configured) for semantic trial search; persist search histories in
Postgres; use DB connection pooling (already configured).

**Q: What are the security/privacy considerations?**
A: No PII is stored (patient_id is auto-generated, demo mode), `.env` is gitignored, `SECRET_KEY`
must be changed in production, CORS is explicit, rate limiting protects the APIs, and `trust_env=False`
on HTTP clients avoids unintended proxy traversal.

**Q: What was the hardest design decision?**
A: The safety architecture: deciding which safety checks must be deterministic (hard walls) vs.
which benefit from LLM reasoning. And the filtering semantics — location is a *soft* preference
(keeps results with a warning if nothing matches) while phase is a *hard* constraint (returns empty
honestly). Regression tests in `test_pipeline_fixes.py` exist specifically because the location and
phase filters were once no-ops/silent fallbacks.

---

## 19. Quick Reference Cheat Sheet

- **Pipeline:** ProfileParser → TrialFetcher → (conditional) EligibilityChecker → DrugSafety → Ranker → ReportGenerator.
- **Conditional edge:** no trials/fetch error → ReportGenerator.
- **Decision ladder:** not eligible/trigger → NOT_ELIGIBLE; ≥80 & ≥0.7 → ELIGIBLE; ≥60 & ≥0.5 →
  LIKELY; ≥40 → POSSIBLY; else NEEDS_REVIEW.
- **Weights:** elig 40% / safety 30% / phase 15% / enrollment 10% / recency 5%.
- **Safety levels:** SAFE < CAUTION < WARNING < CRITICAL (severity only escalates).
- **Hard excludes:** NOT_ELIGIBLE and CRITICAL never surface as matches.
- **Fallbacks:** RxNorm→raw names; LLM extract→heuristics; CT.gov→TrialsMap; DSPy error→NEEDS_REVIEW;
  report error→deterministic text; pipeline error→empty MatchResponse.
- **Rate limits:** match 5/min, trial 20/min, drugs/check 10/min, normalize 20/min;
  ≤20 eligibility checks, batches of 5, 2s gaps, ≤3 trial drugs per OpenFDA check.
- **Test files:** `test_rule_engine.py` (safety), `test_api_clients.py` (parsing/fallback),
  `test_pipeline_fixes.py` (regressions).
