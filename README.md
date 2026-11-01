<div align="center">

# Clinical Trial Matcher

**AI-Powered Clinical Trial Matching Platform**

An end-to-end system that matches patients to recruiting clinical trials using a **6-agent LangGraph pipeline**, combining LLM reasoning (local-first via an OpenAI-compatible Ollama/vLLM endpoint; Groq development fallback), structured programmatic reasoning (DSPy), deterministic protocol screening, a deterministic clinical safety rule engine, and live data from **ClinicalTrials.gov**, **OpenFDA**, and **RxNorm**. Production configuration rejects non-local model providers, so patient data stays on the host.

Built with a **FastAPI** backend, a **React + TypeScript** frontend, and **FHIR R4**-aligned data models.

```
Patients --> AI Pipeline --> Ranked, Safety-Flagged Trial Matches + Physician Summary
```

</div>

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [How It Works — The 6-Agent Pipeline](#how-it-works--the-6-agent-pipeline)
- [Safety-First Design](#safety-first-design)
- [Evaluation Coverage & Latency Guardrails](#evaluation-coverage--latency-guardrails)
- [Scoring Model](#scoring-model)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [API Reference](#api-reference)
- [Testing](#testing)
- [Deployment](#deployment--docker-compose-on-a-vps)
- [Environment Variables](#environment-variables-reference)
- [Troubleshooting](#troubleshooting)
- [Disclaimer](#disclaimer)

---

## Overview

Finding a suitable clinical trial is notoriously difficult: eligibility criteria are dense clinical text, drug–drug interactions must be cross-checked, and results are spread across fragmented data sources. **Clinical Trial Matcher** automates this workflow.

Given a structured patient profile, the system:

1. **Normalizes** patient data (RxNorm medication standardization + LLM keyword extraction).
2. **Searches** ClinicalTrials.gov for actively recruiting trials (with an automatic fallback source).
3. **Screens and evaluates eligibility** — hard protocol facts (age window and eligible sex) are decided deterministically in code, then the remaining candidates are assessed by an AI reasoner (DSPy + local LLM) inside a per-trial timeout and a whole-request budget.
4. **Checks safety** — a **deterministic rule engine** (age, sex, pregnancy, allergies, renal/liver/cardiac status) plus **OpenFDA** drug-interaction lookups.
5. **Ranks** results with an explainable, weighted scoring formula.
6. **Summarizes** findings into a physician-ready report.

The evaluation is deliberately bounded. Only a capped number of candidates are sent to the LLM, and any trial that cannot be evaluated in time is returned as `NEEDS_REVIEW` with the reason stated — never dropped or presented as a confident match. See [Evaluation Coverage & Latency Guardrails](#evaluation-coverage--latency-guardrails).

The output is a paginated, ranked list of matches with per-trial eligibility reasoning, safety assessments, and an AI-generated physician summary.

---

## Key Features

| Area | Feature |
|------|---------|
| **AI Orchestration** | 6 specialized agents coordinated by a LangGraph state machine with conditional routing |
| **Structured Reasoning** | DSPy `ChainOfThought` structures eligibility reasoning; model output is coerced into typed, validated assessments before it reaches the API |
| **Safety-First** | Pure-Python, deterministic rule engine runs before ranking — its hard walls cannot be overridden by LLM output |
| **Drug Safety** | RxNorm normalization + OpenFDA label/contraindication matching + allergy conflict detection |
| **Resilient Data Fetching** | Retries with exponential backoff, query-variant fallbacks, and an automatic HTML-scraper fallback when ClinicalTrials.gov blocks the request |
| **Resilient Pre-Filtering** | Trials pre-filtered by status, **preferred location**, and **trial phase** before expensive LLM evaluation |
| **Deterministic Protocol Screen** | Age window and eligible sex are parsed from the protocol and enforced in code *before* any trial is sent to the LLM |
| **Bounded Inference** | Per-trial timeout plus a whole-pipeline budget; trials that do not fit are returned as `NEEDS_REVIEW` with an explicit skip reason |
| **Honest Uncertainty** | Trials with unavailable criteria or unfinished evaluation are returned as `NEEDS_REVIEW` — never fabricated as confident matches, and `query_summary` states how many trials were actually evaluated |
| **FHIR R4 Alignment** | Pydantic schemas modeled on FHIR R4 resources (Patient, Condition, MedicationStatement) |
| **Rate-Limit Aware** | SlowAPI throttling (Redis in production) + batched/concurrent agent execution |
| **Security** | Self-hosted JWT auth with Argon2 hashing, RBAC, refresh-token rotation, and an audit-log schema for security events |
| **Observability** | JSON logs with request correlation and secret redaction, health/readiness probes, Prometheus `/metrics` |
| **Production Ready** | Docker Compose deployment, Alembic migrations, async PostgreSQL, CORS, security headers, SPA static serving |

---

## How It Works — The 6-Agent Pipeline

All agents share a single `PipelineState` (a LangGraph `TypedDict`) — a relay baton passed through the graph. Each agent reads, enriches, and writes back to the state.

```
                        ┌─────────────────────────────────────────────────────┐
   Patient Profile      │            LangGraph Orchestration                 │
   (FHIR R4)            │                                                     │
        │               │   ┌────────────────┐    ┌─────────────────────┐    │
        ▼               │   │  Agent 1       │    │  Agent 2            │    │
   POST /api/v1/match ──┼──▶│  Profile        │───▶│  Trial Fetcher      │────┼──▶ ClinicalTrials.gov
        │               │   │  Parser        │    │  (no LLM)           │    │      (+ fallback)
        │               │   │  [LLM fast]     │    │  pre-filter:        │    │
        │               │   └────────────────┘    │  status/location/   │    │
        │               │                         │  phase              │    │
        │               │                         └────────┬────────────┘    │
        │               │                                  ▼                 │
        │               │   ┌────────────────┐    ┌─────────────────────┐    │
        │               │   │  Agent 3       │    │  Agent 4            │    │
        │               │   │  Eligibility   │───▶│  Drug Safety        │────┼──▶ OpenFDA + RxNorm
        │               │   │  Checker       │    │  Rule Engine (hard  │    │
        │               │   │  [screen+DSPy] │    │  walls) + FDA       │    │
        │               │   └────────────────┘    └────────┬────────────┘    │
        │               │                                  ▼                 │
        │               │   ┌────────────────┐    ┌─────────────────────┐    │
        │               │   │  Agent 5       │    │  Agent 6            │    │
        │               │   │  Ranker        │───▶│  Report Generator   │────┼──▶ Physician Summary
        │               │   │  (weighted     │    │  [LLM complex]         │    │
        │               │   │  scoring)      │    └─────────────────────┘    │
        │               │   └────────────────┘                               │
        │               └──────────────────────────┬─────────────────────────┘
        │                                          ▼
        ▼                                Ranked Matches + Safety Flags
   React Frontend ◀─────────────────────── Pagination Meta + Physician Summary
```

### Agent Breakdown

| # | Agent | Module | Model / Tool | Responsibility |
|---|-------|--------|--------------|----------------|
| 1 | **Profile Parser** | `agents/profile_parser.py` | Local LLM (fast) + RxNorm | Normalizes medication names to generics, extracts search-optimized condition keywords, builds a human-readable profile summary |
| 2 | **Trial Fetcher** | `agents/trial_fetcher.py` | ClinicalTrials.gov v2 API (no LLM) | Fetches recruiting trials, parses/cleans them, pre-filters by status, preferred location, and trial phase |
| 3 | **Eligibility Checker** | `agents/eligibility_checker.py` | Deterministic protocol screen + DSPy `ChainOfThought` + local LLM | Applies age/sex protocol facts in code, then evaluates remaining trials under a per-call timeout and request budget; returns a typed decision (`ELIGIBLE` → `NEEDS_REVIEW`), confidence, match score, met/unmet criteria, and reasoning |
| 4 | **Drug Safety** | `agents/drug_safety_agent.py` | Rule engine (deterministic) + OpenFDA | Runs hard-contraindication rules first, then OpenFDA interaction checks; produces per-trial `SafetyAssessment` |
| 5 | **Ranker** | `agents/ranker_agent.py` | Weighted formula (no LLM) | Computes a 0–100 score per trial, sorts, assigns ranks, hard-excludes `NOT_ELIGIBLE` / `CRITICAL` trials |
| 6 | **Report Generator** | `agents/report_generator.py` | Local LLM | Writes a concise physician summary with safety notes, eligibility status, and next steps (with strict clinical guardrails) |

Agent 3 also enforces the inference guardrails: the deterministic age/sex screen runs first (no LLM call), then each remaining trial is evaluated within `ELIGIBILITY_TIMEOUT_SECONDS`, and the evaluation phase respects `PIPELINE_BUDGET_SECONDS`. The number of trials sent to a local model is capped by `LOCAL_LLM_MAX_ELIGIBILITY_TRIALS` (default `3`).

**Conditional routing:** if the trial fetcher returns no trials (or an error), the graph routes directly to the report generator so the patient still receives an honest, actionable summary explaining why.

---

## Safety-First Design

> **Rule Engine = hard walls (never crossed, regardless of LLM confidence)**
> **LLM = intelligent reasoning *within* those hard walls**

The single most important design decision in this project is the deterministic **safety rule engine** (`rules/safety_rules.py`). LLMs can hallucinate — a hallucinated "safe" result could enroll a patient in a dangerous trial. The engine runs after eligibility inference but before ranking, and a critical violation excludes the trial regardless of what the model concluded:

- **Deterministic** — identical inputs always produce identical output.
- **Auditable** — every violation carries a `rule_id`, severity, description, and recommendation, traceable for regulatory/compliance review.
- **Fast** — pure Python with no network calls; latency is negligible next to model inference.
- **Non-negotiable** — a critical violation marks the trial `CRITICAL` and it is never surfaced as a match. Remaining trials are still evaluated, so one unsafe trial does not hide the rest.

Hard protocol facts are also decided in code during eligibility checking: age window and eligible sex are parsed from the trial record and enforced without an LLM call.

### Rule Categories

| Rule ID Prefix | Check | Example |
|----------------|-------|---------|
| `STATUS_*` | Trial is not recruiting | Completed / terminated / withdrawn trials |
| `AGE_*` | Patient age within trial window | 15-year-old vs. 18+ trial |
| `SEX_*` | Biological sex eligibility | Male-only trial for a female patient |
| `PREG_*` | Pregnancy / breastfeeding contraindications | Teratogenic drugs (e.g., doxorubicin, thalidomide, warfarin) |
| `ALLERGY_*` | Documented allergy to trial intervention | Severe anaphylaxis to a trial drug |
| `RENAL_*` | Nephrotoxic drugs for renal patients | NSAIDs, metformin, contrast agents with CKD |
| `LIVER_*` | Hepatotoxic drugs for liver patients | Acetaminophen, methotrexate with liver disease |
| `CARDIAC_*` | Cardiotoxic drugs for cardiac patients | Anthracyclines, trastuzumab with heart failure |
| `PEDS_*` | Adult-only trials for pediatric patients | "18 years and older" criteria |

---

## Evaluation Coverage & Latency Guardrails

Local LLM inference is the slowest part of the pipeline, so the system treats *evaluation as a bounded resource* rather than implying every fetched trial was assessed. A request always finishes, and the response states what was and was not evaluated.

| Mechanism | Setting | Behaviour |
|-----------|---------|-----------|
| Deterministic protocol screen | — | Minimum age, maximum age, and eligible sex come from the parsed protocol. A patient outside the window is `NOT_ELIGIBLE` without any model call. |
| Per-trial timeout | `ELIGIBILITY_TIMEOUT_SECONDS` (90) | One slow or hung inference cannot block the request; that trial becomes `NEEDS_REVIEW`. |
| Whole-pipeline budget | `PIPELINE_BUDGET_SECONDS` (180) | No new batch starts once the budget is exhausted. Remaining trials are returned as `NEEDS_REVIEW`, not dropped. |
| Candidate cap | `LOCAL_LLM_MAX_ELIGIBILITY_TRIALS` (3) | Local models evaluate at most this many candidates per request; the non-local development path caps at 20. |
| Frontend timeout | `frontend/src/services/api.ts` (300 s) | Kept above the backend budget so the UI does not abort while the server is still working. |

`query_summary` and each trial's reasoning distinguish **not eligible** from **not evaluated**. Every skip carries its reason: timeout, exhausted budget, unavailable criteria (for example the TrialsMap fallback), or an unusable model response. "Evaluated 3 of 20 candidates" is an intended, honest result — not an error.

> **Tuning:** raise the budget and candidate cap only after measuring your own model's latency. `ROADMAP.md` records the measured baseline and the remaining remediation phases.

---

## Scoring Model

Each trial is scored 0–100 using a transparent, explainable weighted formula (deterministic — no LLM involved):

| Dimension | Weight | Basis |
|-----------|:------:|-------|
| **Eligibility match** | 40% | DSPy match score (0–100) |
| **Safety level** | 30% | SAFE=100 · CAUTION=75 · WARNING=40 · CRITICAL=0 |
| **Trial phase** | 15% | Phase III/IV scored highest (most evidence) |
| **Enrollment proximity** | 10% | Recruiting status + enrollment size |
| **Recency** | 5% | Trials started within the last 1–2 years |

---

## Tech Stack

### Backend
| Category | Technology |
|----------|-----------|
| Framework | [FastAPI](https://fastapi.tiangolo.com) + Uvicorn |
| Agent Orchestration | [LangGraph](https://langchain-ai.github.io/langgraph/) |
| Structured LLM Reasoning | [DSPy](https://dspy-docs.vercel.app) (`ChainOfThought`) |
| LLM Provider | Local OpenAI-compatible endpoint (Ollama / vLLM); Groq development fallback |
| Validation | Pydantic v2 + pydantic-settings |
| Database | PostgreSQL (async) via SQLAlchemy 2.1 + asyncpg + Alembic |
| Auth | Self-hosted JWT (PyJWT) + Argon2 (`pwdlib`) + RBAC |
| HTTP / Resilience | httpx · aiohttp · tenacity (retries + backoff) |
| Rate Limiting | SlowAPI with Redis storage |
| Observability | Loguru JSON logs + Prometheus metrics |
| Serialization | orjson |

### Frontend
| Category | Technology |
|----------|-----------|
| Framework | React 18 + TypeScript |
| Build | Vite 5 |
| Styling | Tailwind CSS 3 |
| Data Fetching | Axios + TanStack Query |
| Auth | JWT bearer tokens with automatic refresh-token rotation (Axios interceptor) |
| Icons | lucide-react |

### External Data Sources (all free, no API keys)
- **ClinicalTrials.gov v2 API** — trial data (with automatic TrialsMap HTML fallback)
- **OpenFDA** — drug labels, interactions, contraindications, adverse events
- **RxNorm (NLM)** — drug name normalization and RxCUI codes

---

## Project Structure

```
clinical_trial_matcher/
├── src/clinical_trial_matcher/
│   ├── main.py                    # FastAPI app factory, middleware, lifespan
│   ├── agents/                    # The 6-agent LangGraph pipeline
│   │   ├── pipeline_state.py      # Shared TypedDict state
│   │   ├── pipeline.py            # Graph orchestration + conditional routing
│   │   ├── llm.py                 # Provider-aware clients (local endpoint / Groq dev fallback)
│   │   ├── profile_parser.py      # Agent 1: RxNorm + keyword extraction
│   │   ├── trial_fetcher.py       # Agent 2: ClinicalTrials.gov + pre-filtering
│   │   ├── eligibility_checker.py # Agent 3: protocol screen + DSPy evaluation
│   │   ├── drug_safety_agent.py   # Agent 4: Rule engine + OpenFDA
│   │   ├── ranker_agent.py        # Agent 5: Weighted scoring & ranking
│   │   └── report_generator.py    # Agent 6: Physician-ready summary
│   ├── api/
│   │   ├── auth.py                # Register/login/refresh/logout/me
│   │   ├── deps.py                # Principal, JWT dependencies, RBAC guards
│   │   ├── errors.py              # Consistent error envelope
│   │   ├── health.py              # Liveness, readiness, metrics
│   │   ├── middleware.py          # Request ID, body limit, security headers
│   │   └── routes.py              # Match, trial detail, drug checks
│   ├── core/
│   │   ├── config.py              # Pydantic settings + production safety checks
│   │   ├── database.py            # Async SQLAlchemy engine/sessions
│   │   ├── logger.py              # JSON logs, correlation, redaction
│   │   ├── rate_limit.py          # Shared SlowAPI limiter
│   │   ├── redis.py               # Redis client lifecycle
│   │   └── security.py            # Argon2 hashing + JWT issue/verify
│   ├── db/
│   │   ├── base.py                # Declarative base
│   │   ├── enums.py               # Domain enums
│   │   └── models/                # 13 SQLAlchemy models
│   ├── rules/safety_rules.py      # Deterministic clinical safety rules
│   ├── schemas/                   # Pydantic request/response contracts
│   └── utils/api_clients.py       # ClinicalTrials.gov, OpenFDA, RxNorm clients
│
├── main.py                        # Compatibility shim for `uvicorn main:app`
├── alembic.ini                    # Alembic configuration
├── alembic/                       # Schema migrations
├── scripts/
│   ├── create_admin.py            # Admin bootstrap / promotion CLI
│   └── docker-entrypoint.sh       # Migrate + start Uvicorn
├── tests/
│   ├── test_api_clients.py        # ClinicalTrials.gov parsing + TrialsMap fallback
│   ├── test_rule_engine.py        # Deterministic safety rules
│   ├── test_pipeline_fixes.py     # Pre-filtering, ranker exclusion, coverage counters
│   ├── test_eligibility_guardrails.py  # Age/sex screen, timeout and budget degradation
│   └── unit/                      # Auth API, config, errors, health, logging, middleware, models, security
├── frontend/                      # React + TypeScript + Tailwind SPA (auth + results UI)
├── .github/workflows/ci.yml       # Lint, types, migrations, tests, SPA and image builds
├── ROADMAP.md                     # Gap analysis and remediation plan
├── INTERVIEW_GUIDE.md             # File-by-file architecture walkthrough
├── Dockerfile                     # Multi-stage API + SPA image
├── docker-compose.yml             # API, PostgreSQL, Redis, Ollama, optional Qdrant
├── pyproject.toml                 # Dependencies + tooling configuration
├── uv.lock                        # Reproducible dependency lock
└── .env.example                   # Environment template (never commit .env)
```

---

## Getting Started

### Prerequisites

- **Python 3.12** (3.11+ supported)
- **Node.js 20+** (for the frontend)
- **PostgreSQL 16+** (or Docker)
- **Redis 7+** (required in staging/production)
- **Docker + Docker Compose** (recommended deployment path)
- **A local OpenAI-compatible LLM** — Ollama (`llama3.1:8b` by default) or vLLM. Groq is available only as an explicit development fallback; production startup rejects non-local providers.

### 1. Clone & enter the project

```bash
git clone <your-repo-url> clinical_trial_matcher
cd clinical_trial_matcher
```

### 2. Create & activate a Python virtual environment

```bash
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# Mac / Linux
source .venv/bin/activate
```

### 3. Install Python dependencies

With [uv](https://docs.astral.sh/uv/) (recommended, uses the lockfile):

```bash
uv sync --extra dev
```

Or with pip:

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Generate a strong secret and fill in the database credentials:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Key settings:

```env
APP_ENV=development
SECRET_KEY=<generated 48-byte value>
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/clinical_trials
DATABASE_URL_SYNC=postgresql://postgres:postgres@localhost:5432/clinical_trials
REDIS_URL=redis://localhost:6379/0
LLM_PROVIDER=local
LOCAL_LLM_BASE_URL=http://localhost:11434/v1
LOCAL_LLM_MODEL=llama3.1:8b
LOCAL_LLM_MAX_ELIGIBILITY_TRIALS=3
ELIGIBILITY_TIMEOUT_SECONDS=90
PIPELINE_BUDGET_SECONDS=180
AUTH_ENABLED=true
ALLOW_REGISTRATION=false
AUTO_CREATE_TABLES=false
```

See [`.env.example`](.env.example) for the complete list. In production the app refuses to start when `SECRET_KEY` is weak, `AUTO_CREATE_TABLES` is true, registration is open, or `LLM_PROVIDER` is not `local`.

The frontend waits up to 300 s for `/match`, which is longer than the default pipeline budget. If you raise `PIPELINE_BUDGET_SECONDS`, raise the timeout in `frontend/src/services/api.ts` as well.

### 5. Start PostgreSQL and Redis

```bash
docker compose up -d db redis
```

Or point `DATABASE_URL` / `REDIS_URL` at existing local services. Redis is optional in development; rate limiting falls back to in-memory storage.

### 6. Apply migrations and bootstrap an admin

```bash
uv run alembic upgrade head
uv run python scripts/create_admin.py --email admin@example.com
```

`create_admin.py` prompts for a password and creates (or promotes) an administrator. Registration is disabled by default; provision additional accounts through the CLI or your deployment's admin process.

### 7. (Optional) Start Qdrant

```bash
docker compose --profile vector up -d qdrant
```

### 8. Run the backend

```bash
uv run uvicorn clinical_trial_matcher.main:app --reload --port 8000
```

- Interactive API docs (development only): **http://localhost:8000/docs**
- Liveness: **http://localhost:8000/api/v1/health/live**
- Readiness: **http://localhost:8000/api/v1/health/ready**
- Metrics: **http://localhost:8000/metrics**

### 9. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend is served at **http://localhost:3000**. The Vite dev server proxies `/api` requests to the FastAPI backend at `http://localhost:8000`.

Sign in with the admin account created in step 6. The SPA stores the access/refresh token pair and refreshes the access token automatically when it expires.

> **Tip:** to serve the frontend directly from FastAPI (single-server deployment), build it with `npm run build` (outputs to `frontend/dist`). FastAPI automatically mounts the built SPA on restart.

---

## API Reference

All endpoints are prefixed with `/api/v1`. Clinical endpoints require a Bearer access token and are rate limited per client IP (Redis-backed in production). `/match` additionally requires the `admin`, `physician`, or `researcher` role; trial and drug lookups accept any authenticated role. Self-registered accounts receive the `viewer` role and must be promoted before they can run a match.

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/auth/register` | Register a user (disabled in production by default) |
| `POST` | `/auth/login` | Exchange email/password for access + refresh tokens |
| `POST` | `/auth/refresh` | Rotate a refresh token and issue a new access token |
| `POST` | `/auth/logout` | Revoke the submitted refresh token |
| `GET` | `/auth/me` | Current user and role |

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=admin@example.com" \
  --data-urlencode "password=..."
```

### Clinical endpoints

| Method | Endpoint | Description | Rate Limit |
|--------|----------|-------------|:----------:|
| `POST` | `/match` | Run the full 6-agent pipeline and return ranked matches | 5/min |
| `GET` | `/trial/{nct_id}` | Fetch full details for a specific trial | 60/min |
| `GET` | `/drugs/check` | Check drug–drug interactions (`drug1`, `drug2`) | 60/min |
| `GET` | `/drugs/normalize` | Normalize a brand name → generic via RxNorm (`name`) | 60/min |

### Health and observability

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Basic service health (status, version, model, provider, environment, timestamp) |
| `GET` | `/health/live` | Liveness probe |
| `GET` | `/health/ready` | Readiness probe (database + Redis; 503 when a required dependency is down — Redis is optional in development) |
| `GET` | `/metrics` | Prometheus metrics |

### Match a patient with trials

```bash
curl -X POST http://localhost:8000/api/v1/match \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "age": 52,
    "sex": "female",
    "conditions": [
      {"display": "Type 2 Diabetes Mellitus", "is_active": true},
      {"display": "Hypertension", "is_active": true}
    ],
    "symptoms": ["fatigue", "frequent urination"],
    "medications": [
      {"name": "metformin", "dosage": "1000mg", "frequency": "twice daily"},
      {"name": "lisinopril", "dosage": "10mg", "frequency": "once daily"}
    ],
    "allergies": [],
    "lab_values": [{"test_name": "HbA1c", "value": 8.2, "unit": "%"}],
    "smoking_status": "never",
    "is_pregnant": false,
    "is_breastfeeding": false,
    "preferred_locations": ["California"],
    "trial_phases": ["PHASE2", "PHASE3"]
  }'
```

**Key response fields:**

| Field | Description |
|-------|-------------|
| `search_id` | Unique identifier for this pipeline run |
| `query_summary` | Human-readable recap of what was searched, filtered, and actually evaluated (coverage included) |
| `matches[]` | Ranked trials with `final_score`, `rank`, `decision`, eligibility reasoning, and safety assessment |
| `pagination` | Page / page_size / totals / prev-next navigation |
| `total_trials_searched` | Total trials reported by the source (ClinicalTrials.gov, or the TrialsMap fallback) |
| `total_eligible` | Trials with a positive eligibility decision (`ELIGIBLE`, `LIKELY_ELIGIBLE`, or `POSSIBLY_ELIGIBLE`) |
| `physician_summary` | AI-generated report for the referring physician |
| `safety_halt` | Whether the pipeline halted for safety reasons |
| `disclaimer` | Standard informational-use notice returned with every match response |

### Check a drug interaction

```bash
curl "http://localhost:8000/api/v1/drugs/check?drug1=metformin&drug2=contrast%20dye" \
  -H "Authorization: Bearer $TOKEN"
```

### Get a specific trial

```bash
curl http://localhost:8000/api/v1/trial/NCT04892173 -H "Authorization: Bearer $TOKEN"
```

### Pagination

The `/match` endpoint accepts `page` and `page_size` query parameters (`page_size` is accepted up to 50 and further capped by `MAX_PAGE_SIZE`):

```bash
curl -X POST "http://localhost:8000/api/v1/match?page=2&page_size=10" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"age": 52, "sex": "female", "conditions": [{"display": "Type 2 Diabetes Mellitus"}]}'
```

---

## Testing

The suite (82 tests across 12 files) runs **without network access** — external API calls are mocked or tested at the parsing/decision layer. `tests/conftest.py` sets a safe environment before any application module imports `settings`.

```bash
# Run the full suite from the project root (with the venv active)
uv run pytest -q

# Verbose output with coverage
uv run pytest -v --cov=clinical_trial_matcher --cov-report=term-missing

# Run just the safety rule engine tests (most critical)
uv run pytest tests/test_rule_engine.py -v

# Guardrails for the eligibility agent
uv run pytest tests/test_eligibility_guardrails.py -v
```

### Test coverage

- **`test_api_clients.py`** — ClinicalTrials.gov parsing: HTML stripping, status/phase mapping, eligibility splitting, age parsing, query-variant cleanup, and the TrialsMap HTML fallback parser.
- **`test_rule_engine.py`** — Safety rules: age, sex, pregnancy/teratogenic drugs, allergies, non-recruiting statuses, renal/liver warnings, pediatric exclusions, and multi-violation detection.
- **`test_pipeline_fixes.py`** — Pipeline regressions: location pre-filtering, strict phase filtering, `NOT_ELIGIBLE` ranker exclusion, `NEEDS_REVIEW` short-circuiting on unavailable criteria, and filter/coverage counters.
- **`test_eligibility_guardrails.py`** — Deterministic age/sex exclusions without LLM calls, per-trial timeout degradation, and budget exhaustion marking remaining trials as not evaluated.
- **`tests/unit/`** — Application edges: `test_auth_api.py` (HTTP login, refresh-token rotation/revocation, RBAC on `/match`), `test_config.py` (production hardening), `test_errors.py` (error envelope and no detail leakage), `test_health.py` (probes, request IDs, security headers, metrics), `test_logging.py` (secret/PII redaction), `test_middleware.py` (body limit, headers on rejection), `test_models.py` (13 tables + ORM mappers), `test_security.py` (JWT types, RBAC, rate-limit key resolution).

### Code quality

The CI pipeline runs the following; run them locally before opening a PR:

```bash
uv run ruff check src/clinical_trial_matcher tests
uv run ruff format --check src/clinical_trial_matcher tests
uv run mypy src/clinical_trial_matcher
```

---

## Deployment — Docker Compose on a VPS

The image builds the React SPA and serves it from FastAPI, so a single API container exposes the complete application.

```bash
cp .env.example .env
# Set at minimum:
#   APP_ENV=production
#   SECRET_KEY=<48+ random bytes>
#   POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB
#   TRUSTED_HOSTS=your-domain.example
#   CORS_ORIGINS=https://your-domain.example
#   LOCAL_LLM_MODEL=llama3.1:8b

docker compose build
docker compose up -d
docker compose exec ollama ollama pull llama3.1:8b
docker compose exec api python scripts/create_admin.py --email admin@example.com
```

The API runs migrations automatically on startup (`RUN_MIGRATIONS=true`). Verify with:

```bash
curl -fsS http://127.0.0.1:8000/api/v1/health/ready
docker compose logs -f api
```

Operational notes:

- Put a TLS-terminating reverse proxy (Caddy, Traefik, or nginx) in front of port 8000. Set `TRUSTED_PROXY_COUNT` and `FORWARDED_ALLOW_IPS` for your proxy topology.
- PostgreSQL, Redis, and Ollama are internal-only; do not publish their ports.
- Pull the model once per host (or bake it into your deployment process). The API starts before the model finishes downloading, so `/health/ready` can be green while the first match fails — warm the model after pulling.
- Back up the `postgres_data` volume. Logs are written to the `app_logs` volume and stdout.
- Scale `WEB_CONCURRENCY` with CPU; GPU inference is served by the Ollama container (add a GPU reservation override if your VPS has one).
- CI (`.github/workflows/ci.yml`) runs lint, type checks, migrations, tests, a frontend build, and a Docker image build.
- **Local inference is wired end to end.** Every agent selects its client through `agents/llm.py` using `LLM_PROVIDER`; production validation still rejects `LLM_PROVIDER=groq`, so patient data never leaves the host. Pull the configured `LOCAL_LLM_MODEL` before the first request and confirm model quality on your own evaluation data before clinical use.
- **A match is bounded in time and coverage.** `PIPELINE_BUDGET_SECONDS` caps the evaluation phase and `LOCAL_LLM_MAX_ELIGIBILITY_TRIALS` caps how many candidates reach the model. Size both against measured model latency; see [Evaluation Coverage & Latency Guardrails](#evaluation-coverage--latency-guardrails).

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|:--------:|---------|-------------|
| `APP_ENV` | No | `development` | `development` / `staging` / `production` / `test` |
| `APP_HOST` / `APP_PORT` | No | `0.0.0.0` / `8000` | Bind address used by the container entrypoint |
| `DEBUG` | No | `false` | Verbose mode; must be false in production |
| `LOG_LEVEL` / `LOG_JSON` | No | `INFO` / auto | Log level; JSON logs default to on outside development |
| `DOCS_ENABLED` | No | auto | Expose `/docs`, `/redoc`, `/openapi.json`; defaults to off in production |
| `SECRET_KEY` | Production | `change-me-in-production` | JWT signing secret, **≥32 characters in production** |
| `DATABASE_URL` | Yes | — | Async PostgreSQL URL (`postgresql+asyncpg://…`) |
| `DATABASE_URL_SYNC` | Yes | — | Sync PostgreSQL URL (Alembic) |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_ECHO` | No | `10` / `20` / `false` | Async engine pool tuning |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Compose | `ctm` / — / `clinical_trials` | Database container credentials |
| `REDIS_URL` | Production | `redis://localhost:6379/0` | Rate-limit storage |
| `RATE_LIMIT_ENABLED` | No | `true` | Enable SlowAPI throttling (in-memory in development/test) |
| `RATE_LIMIT_DEFAULT` / `RATE_LIMIT_MATCH` / `RATE_LIMIT_READ` / `RATE_LIMIT_AUTH` | No | `120/minute` / `5/minute` / `60/minute` / `10/minute` | Per-route limits |
| `AUTH_ENABLED` | No | `true` | Enable JWT authentication (must be true in production) |
| `ALLOW_REGISTRATION` | No | `false` | Open `/auth/register` (must be false in production) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | `30` | Access-token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | No | `7` | Refresh-token lifetime |
| `JWT_ALGORITHM` / `JWT_ISSUER` / `JWT_AUDIENCE` | No | `HS256` / `clinical-trial-matcher` / `clinical-trial-matcher-api` | JWT signing and claim validation |
| `PASSWORD_MIN_LENGTH` | No | `12` | Minimum password length for registration and bootstrap |
| `MAX_REQUEST_BODY_BYTES` | No | `1000000` | Request body cap enforced by middleware |
| `PATIENT_DATA_ENCRYPTION_KEY` | No | — | Reserved for at-rest patient-data encryption |
| `TRUSTED_HOSTS` | Production | `localhost,127.0.0.1,testserver` | Comma-separated Host allowlist (keep `testserver` for in-process smoke tests) |
| `CORS_ORIGINS` | No | `http://localhost:3000,http://localhost:5173` | Comma-separated allowed origins |
| `TRUSTED_PROXY_COUNT` | No | `0` | Trusted reverse-proxy hops for client IP resolution |
| `AUTO_CREATE_TABLES` | No | `true` | Dev convenience; **must be false in production** |
| `LLM_PROVIDER` | No | `local` | `local` (production) or `groq` (development only) |
| `LOCAL_LLM_BASE_URL` | No | `http://localhost:11434/v1` | OpenAI-compatible local endpoint |
| `LOCAL_LLM_MODEL` | No | `llama3.1:8b` | Local model name |
| `LOCAL_LLM_API_KEY` | No | `local` | Sent as the bearer token to the OpenAI-compatible endpoint |
| `LOCAL_LLM_TIMEOUT_SECONDS` | No | `120` | Timeout for local model requests |
| `LOCAL_LLM_MAX_ELIGIBILITY_TRIALS` | No | `3` | Trials evaluated by the local model per request |
| `ELIGIBILITY_TIMEOUT_SECONDS` | No | `90` | Hard limit for one trial's eligibility inference |
| `PIPELINE_BUDGET_SECONDS` | No | `180` | Total LLM evaluation budget; remaining trials return `NEEDS_REVIEW` |
| `GROQ_API_KEY` / `GROQ_MODEL_*` | Dev only | — | Explicit development fallback; rejected in production |
| `CLINICALTRIALS_BASE_URL` / `OPENFDA_BASE_URL` / `RXNORM_BASE_URL` | No | Public endpoints | Upstream API base URLs |
| `EXTERNAL_API_TIMEOUT_SECONDS` | No | `30` | Timeout for external API clients |
| `QDRANT_HOST` / `QDRANT_PORT` / `QDRANT_COLLECTION` | No | `localhost` / `6333` / `clinical_trials` | Optional vector store |
| `DEFAULT_PAGE_SIZE` / `MAX_PAGE_SIZE` | No | `10` / `50` | Pagination bounds |
| `SENTRY_DSN` / `OTEL_EXPORTER_OTLP_ENDPOINT` | No | — | Optional observability hooks |
| `METRICS_ENABLED` | No | `true` | Expose Prometheus metrics |
| `RUN_MIGRATIONS` | Compose | `true` | Run `alembic upgrade head` on container start |
| `WEB_CONCURRENCY` | Compose | `2` | Uvicorn worker count |
| `FORWARDED_ALLOW_IPS` | Compose | `127.0.0.1` | Proxy header allowlist passed to Uvicorn |

---

## Troubleshooting

**Production refuses to start with a settings error**
Read the validation message. Common causes: `SECRET_KEY` shorter than 32 characters, `AUTO_CREATE_TABLES=true`, `ALLOW_REGISTRATION=true`, or `LLM_PROVIDER=groq`. Production intentionally rejects all of these.

**`Database connection refused`**
Confirm PostgreSQL is running (`docker compose ps`) and that `DATABASE_URL` credentials match the database. Run `uv run alembic upgrade head` before starting the API if `AUTO_CREATE_TABLES=false`.

**Health is green but matching fails**
Ensure the local model is running and pulled: `docker compose exec ollama ollama pull llama3.1:8b`. Note that `/api/v1/health/ready` only covers database/Redis, not model warm-up.

**`/match` is slow or returns fewer evaluated trials than expected**
This is the bounded-inference design, not a bug. Local models evaluate at most `LOCAL_LLM_MAX_ELIGIBILITY_TRIALS` candidates, each bounded by `ELIGIBILITY_TIMEOUT_SECONDS`, within `PIPELINE_BUDGET_SECONDS`; anything unfinished is returned as `NEEDS_REVIEW` with a stated reason. Raise these only after measuring your model, and keep the frontend timeout above the budget.

**`403 Insufficient permissions` on `/match`**
Self-registered accounts receive the `viewer` role. Promote an account with `uv run python scripts/create_admin.py --email <email> --promote`, or sign in as an admin, physician, or researcher.

**401 after restarting the API**
Changing `SECRET_KEY` invalidates existing access/refresh tokens. Log in again.

**`DSPy import error`**
The PyPI package is `dspy-ai`, not `dspy`. Run `pip install dspy-ai`.

**Frontend can't reach the API**
Ensure the backend is running on port 8000. The Vite dev proxy forwards `/api` to `http://localhost:8000` (see `frontend/vite.config.ts`).

**Rate-limit errors from Groq**
The free tier allows ~30 requests/min. The pipeline already batches eligibility checks with delays. If you hit limits, reduce the fetch/evaluation volume in `agents/trial_fetcher.py` (the `FETCH_BUFFER_MULTIPLIER` / hard cap) and `agents/eligibility_checker.py`.

**ClinicalTrials.gov returns HTTP 403**
The client automatically retries progressively simpler queries and, if still blocked, falls back to a public trial-search mirror (TrialsMap). This is logged as a `WARNING` in `logs/app.log`.

---

## Disclaimer

This tool is for **informational and research purposes only** and does **not** constitute medical advice. All trial matches, eligibility determinations, and drug-safety assessments are AI-generated and must be reviewed by a qualified healthcare provider before any enrollment or clinical decision. No patient PII is stored.

---

<div align="center">
  <sub>Built with FastAPI · LangGraph · DSPy · local LLMs · React</sub>
</div>
