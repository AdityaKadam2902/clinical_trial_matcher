<div align="center">

# Clinical Trial Matcher

**AI-Powered Clinical Trial Matching Platform**

An end-to-end system that matches patients to recruiting clinical trials using a **6-agent LangGraph pipeline**, combining LLM reasoning (local-first via an OpenAI-compatible Ollama/vLLM endpoint; Groq development fallback), structured programmatic reasoning (DSPy), a deterministic clinical safety rule engine, and live data from **ClinicalTrials.gov**, **OpenFDA**, and **RxNorm**. Production configuration rejects non-local model providers; the agent-level local migration is tracked in Phase 3.

Built with a **FastAPI** backend, a **React + TypeScript** frontend, and **FHIR R4**-aligned data models.

```
Patients --> AI Pipeline --> Ranked, Safety-Flagged Trial Matches + Physician Summary
```

</div>

---

## Table of Contents

- [Overview](#-overview)
- [Key Features](#-key-features)
- [How It Works — The 6-Agent Pipeline](#-how-it-works--the-6-agent-pipeline)
- [Safety-First Design](#-safety-first-design)
- [Scoring Model](#-scoring-model)
- [Tech Stack](#-tech-stack)
- [Project Structure](#-project-structure)
- [Getting Started](#-getting-started)
- [API Reference](#-api-reference)
- [Testing](#-testing)
- [Deployment](#-deployment)
- [Environment Variables](#-environment-variables)
- [Troubleshooting](#-troubleshooting)
- [Disclaimer](#-disclaimer)

---

## Overview

Finding a suitable clinical trial is notoriously difficult: eligibility criteria are dense clinical text, drug–drug interactions must be cross-checked, and results are spread across fragmented data sources. **Clinical Trial Matcher** automates this workflow.

Given a structured patient profile, the system:

1. **Normalizes** patient data (RxNorm medication standardization + LLM keyword extraction).
2. **Searches** ClinicalTrials.gov for actively recruiting trials (with an automatic fallback source).
3. **Evaluates eligibility** — an AI reasoner (DSPy + local LLM) assesses each trial's inclusion/exclusion criteria against the patient.
4. **Checks safety** — a **deterministic rule engine** (age, sex, pregnancy, allergies, renal/liver/cardiac status) plus **OpenFDA** drug-interaction lookups.
5. **Ranks** results with an explainable, weighted scoring formula.
6. **Summarizes** findings into a physician-ready report.

The output is a paginated, ranked list of matches with per-trial eligibility reasoning, safety assessments, and an AI-generated physician summary.

---

## Key Features

| Area | Feature |
|------|---------|
| **AI Orchestration** | 6 specialized agents coordinated by a LangGraph state machine with conditional routing |
| **Structured Reasoning** | DSPy `ChainOfThought` guarantees typed, validated eligibility decisions (no free-form hallucination) |
| **Safety-First** | Pure-Python, deterministic rule engine runs *before* any LLM output — hard medical walls the LLM can never override |
| **Drug Safety** | RxNorm normalization + OpenFDA label/contraindication matching + allergy conflict detection |
| **Resilient Data Fetching** | Retries with exponential backoff, query-variant fallbacks, and an automatic HTML-scraper fallback when ClinicalTrials.gov blocks the request |
| **Resilient Pre-Filtering** | Trials pre-filtered by status, **preferred location**, and **trial phase** before expensive LLM evaluation |
| **Honest Uncertainty** | Trials with unavailable criteria are returned as `NEEDS_REVIEW` — never fabricated as confident matches |
| **FHIR R4 Alignment** | Pydantic schemas modeled on FHIR R4 resources (Patient, Condition, MedicationStatement) |
| **Rate-Limit Aware** | SlowAPI throttling (Redis in production) + batched/concurrent agent execution |
| **Security** | Self-hosted JWT auth with Argon2 hashing, RBAC, refresh-token rotation, immutable audit log |
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
        │               │   │  [DSPy + LLM]  │    │  walls) + FDA       │    │
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
| 3 | **Eligibility Checker** | `agents/eligibility_checker.py` | DSPy `ChainOfThought` + local LLM | Determines eligibility per trial, returns typed decision (`ELIGIBLE` → `NEEDS_REVIEW`), confidence, match score, met/unmet criteria, and reasoning |
| 4 | **Drug Safety** | `agents/drug_safety_agent.py` | Rule engine (deterministic) + OpenFDA | Runs hard-contraindication rules first, then OpenFDA interaction checks; produces per-trial `SafetyAssessment` |
| 5 | **Ranker** | `agents/ranker_agent.py` | Weighted formula (no LLM) | Computes a 0–100 score per trial, sorts, assigns ranks, hard-excludes `NOT_ELIGIBLE` / `CRITICAL` trials |
| 6 | **Report Generator** | `agents/report_generator.py` | Local LLM | Writes a concise physician summary with safety notes, eligibility status, and next steps (with strict clinical guardrails) |

**Conditional routing:** if the trial fetcher returns no trials (or an error), the graph routes directly to the report generator so the patient still receives an honest, actionable summary explaining why.

---

## Safety-First Design

> **Rule Engine = hard walls (never crossed, regardless of LLM confidence)**
> **LLM = intelligent reasoning *within* those hard walls**

The single most important design decision in this project is the deterministic **safety rule engine** (`rules/safety_rules.py`). LLMs can hallucinate — a hallucinated "safe" result could enroll a patient in a dangerous trial. Therefore:

- **Deterministic** — identical inputs always produce identical output.
- **Auditable** — every violation carries a `rule_id`, severity, description, and recommendation, traceable for regulatory/compliance review.
- **Instant** — pure Python, no network calls, runs in <1 ms per trial.
- **Non-negotiable** — critical violations set `halt_pipeline=True` and the trial is never surfaced as a match.

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
│   │   ├── profile_parser.py      # Agent 1: RxNorm + keyword extraction
│   │   ├── trial_fetcher.py       # Agent 2: ClinicalTrials.gov + pre-filtering
│   │   ├── eligibility_checker.py # Agent 3: DSPy eligibility evaluation
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
├── alembic/                       # Schema migrations
├── scripts/
│   ├── create_admin.py            # Admin bootstrap / promotion CLI
│   └── docker-entrypoint.sh       # Migrate + start Uvicorn
├── tests/                         # Unit and regression tests
├── frontend/                      # React + TypeScript + Tailwind SPA
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
AUTH_ENABLED=true
ALLOW_REGISTRATION=false
AUTO_CREATE_TABLES=false
```

See [`.env.example`](.env.example) for the complete list. In production the app refuses to start when `SECRET_KEY` is weak, `AUTO_CREATE_TABLES` is true, registration is open, or `LLM_PROVIDER` is not `local`.

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

> **Tip:** to serve the frontend directly from FastAPI (single-server deployment), build it with `npm run build` (outputs to `frontend/dist`). FastAPI automatically mounts the built SPA on restart.

---

## API Reference

All endpoints are prefixed with `/api/v1`. Clinical endpoints require a Bearer access token and are rate limited per client IP (Redis-backed in production).

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
| `GET` | `/health` | Basic service health (version, environment, uptime) |
| `GET` | `/health/live` | Liveness probe |
| `GET` | `/health/ready` | Readiness probe (503 when dependencies are down) |
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
| `query_summary` | Human-readable recap of what was searched and filtered |
| `matches[]` | Ranked trials with `final_score`, `rank`, `decision`, eligibility reasoning, and safety assessment |
| `pagination` | Page / page_size / totals / prev-next navigation |
| `total_trials_searched` | Total trials found on ClinicalTrials.gov |
| `total_eligible` | Trials that passed eligibility evaluation |
| `physician_summary` | AI-generated report for the referring physician |
| `safety_halt` | Whether the pipeline halted for safety reasons |

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

Both the `/match` endpoint accept `page` and `page_size` query parameters (`page_size` capped at `MAX_PAGE_SIZE`):

```bash
curl -X POST "http://localhost:8000/api/v1/match?page=2&page_size=10" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"age": 52, "sex": "female", "conditions": [{"display": "Type 2 Diabetes Mellitus"}]}'
```

---

## Testing

The test suite is designed to run **without network access** — all API calls are mocked or unit-tested at the parsing/decision layer.

```bash
# Run the full suite from the project root (with venv activated)
pytest tests/ -v

# With coverage report
pytest tests/ -v --cov=. --cov-report=term-missing

# Run just the safety rule engine tests (most critical)
pytest tests/test_rule_engine.py -v
```

### Test coverage

- **`test_api_clients.py`** — ClinicalTrials.gov parsing: HTML stripping, status/phase mapping, eligibility splitting, age parsing, and the TrialsMap HTML fallback parser.
- **`test_rule_engine.py`** — Safety rules: age, sex, pregnancy/teratogenic drugs, allergies, non-recruiting statuses, renal/liver warnings, pediatric exclusions, and multi-violation detection.
- **`test_pipeline_fixes.py`** — Regression tests for recent pipeline fixes: location pre-filtering, strict phase filtering, `NOT_ELIGIBLE` ranker exclusion, `NEEDS_REVIEW` short-circuiting on unavailable criteria, and filter-reason propagation.

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

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|:--------:|---------|-------------|
| `APP_ENV` | No | `development` | `development` / `staging` / `production` / `test` |
| `SECRET_KEY` | Production | `change-me-in-production` | JWT signing secret, **≥32 characters in production** |
| `DATABASE_URL` | Yes | — | Async PostgreSQL URL (`postgresql+asyncpg://…`) |
| `DATABASE_URL_SYNC` | Yes | — | Sync PostgreSQL URL (Alembic) |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Compose | `ctm` / — / `clinical_trials` | Database container credentials |
| `REDIS_URL` | Production | `redis://localhost:6379/0` | Rate-limit storage |
| `AUTH_ENABLED` | No | `true` | Enable JWT authentication (must be true in production) |
| `ALLOW_REGISTRATION` | No | `false` | Open `/auth/register` (must be false in production) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | `30` | Access-token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | No | `7` | Refresh-token lifetime |
| `TRUSTED_HOSTS` | Production | `localhost,127.0.0.1,testserver` | Comma-separated Host allowlist |
| `CORS_ORIGINS` | No | `http://localhost:3000,http://localhost:5173` | Comma-separated allowed origins |
| `TRUSTED_PROXY_COUNT` | No | `0` | Trusted reverse-proxy hops for client IP resolution |
| `AUTO_CREATE_TABLES` | No | `true` | Dev convenience; **must be false in production** |
| `LLM_PROVIDER` | No | `local` | `local` (production) or `groq` (development only) |
| `LOCAL_LLM_BASE_URL` | No | `http://localhost:11434/v1` | OpenAI-compatible local endpoint |
| `LOCAL_LLM_MODEL` | No | `llama3.1:8b` | Local model name |
| `LOCAL_LLM_TIMEOUT_SECONDS` | No | `120` | Timeout for local model requests |
| `LOCAL_LLM_MAX_ELIGIBILITY_TRIALS` | No | `3` | Trials evaluated by the local model per request |
| `ELIGIBILITY_TIMEOUT_SECONDS` | No | `90` | Hard limit for one trial's eligibility inference |
| `PIPELINE_BUDGET_SECONDS` | No | `180` | Total LLM evaluation budget; remaining trials return `NEEDS_REVIEW` |
| `GROQ_API_KEY` / `GROQ_MODEL_*` | Dev only | — | Explicit development fallback; rejected in production |
| `QDRANT_HOST` / `QDRANT_PORT` / `QDRANT_COLLECTION` | No | `localhost` / `6333` / `clinical_trials` | Optional vector store |
| `DEFAULT_PAGE_SIZE` / `MAX_PAGE_SIZE` | No | `10` / `50` | Pagination bounds |
| `SENTRY_DSN` / `OTEL_EXPORTER_OTLP_ENDPOINT` | No | — | Optional observability hooks |
| `METRICS_ENABLED` | No | `true` | Expose Prometheus metrics |

---

## Troubleshooting

**Production refuses to start with a settings error**
Read the validation message. Common causes: `SECRET_KEY` shorter than 32 characters, `AUTO_CREATE_TABLES=true`, `ALLOW_REGISTRATION=true`, or `LLM_PROVIDER=groq`. Production intentionally rejects all of these.

**`Database connection refused`**
Confirm PostgreSQL is running (`docker compose ps`) and that `DATABASE_URL` credentials match the database. Run `uv run alembic upgrade head` before starting the API if `AUTO_CREATE_TABLES=false`.

**Health is green but matching fails**
Ensure the local model is running and pulled: `docker compose exec ollama ollama pull llama3.1:8b`. Check `/api/v1/health/ready` only covers database/Redis, not model warm-up.

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
