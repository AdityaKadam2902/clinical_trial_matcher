<div align="center">

# Clinical Trial Matcher

**AI-Powered Clinical Trial Matching Platform**

An end-to-end system that matches patients to recruiting clinical trials using a **6-agent LangGraph pipeline**, combining LLM reasoning (Groq), structured programmatic reasoning (DSPy), a deterministic clinical safety rule engine, and live data from **ClinicalTrials.gov**, **OpenFDA**, and **RxNorm**.

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
3. **Evaluates eligibility** — an AI reasoner (DSPy + Groq 70B) assesses each trial's inclusion/exclusion criteria against the patient.
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
| **Rate-Limit Aware** | SlowAPI endpoint throttling + batched/concurrent agent execution tuned for Groq free-tier limits |
| **Observability** | Loguru structured logging (rotating console + file + error logs), request timing headers, per-pipeline telemetry |
| **Production Ready** | Async PostgreSQL (SQLAlchemy 2.0 + asyncpg), CORS, SPA static serving, pagination |

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
        │               │   │  [Groq 8B]     │    │  pre-filter:        │    │
        │               │   └────────────────┘    │  status/location/   │    │
        │               │                         │  phase              │    │
        │               │                         └────────┬────────────┘    │
        │               │                                  ▼                 │
        │               │   ┌────────────────┐    ┌─────────────────────┐    │
        │               │   │  Agent 3       │    │  Agent 4            │    │
        │               │   │  Eligibility   │───▶│  Drug Safety        │────┼──▶ OpenFDA + RxNorm
        │               │   │  Checker       │    │  Rule Engine (hard  │    │
        │               │   │  [DSPy + 70B]  │    │  walls) + FDA       │    │
        │               │   └────────────────┘    └────────┬────────────┘    │
        │               │                                  ▼                 │
        │               │   ┌────────────────┐    ┌─────────────────────┐    │
        │               │   │  Agent 5       │    │  Agent 6            │    │
        │               │   │  Ranker        │───▶│  Report Generator   │────┼──▶ Physician Summary
        │               │   │  (weighted     │    │  [Groq 70B]         │    │
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
| 1 | **Profile Parser** | `agents/profile_parser.py` | Groq 8B (fast) + RxNorm | Normalizes medication names to generics, extracts search-optimized condition keywords, builds a human-readable profile summary |
| 2 | **Trial Fetcher** | `agents/trial_fetcher.py` | ClinicalTrials.gov v2 API (no LLM) | Fetches recruiting trials, parses/cleans them, pre-filters by status, preferred location, and trial phase |
| 3 | **Eligibility Checker** | `agents/eligibility_checker.py` | DSPy `ChainOfThought` + Groq 70B | Determines eligibility per trial, returns typed decision (`ELIGIBLE` → `NEEDS_REVIEW`), confidence, match score, met/unmet criteria, and reasoning |
| 4 | **Drug Safety** | `agents/drug_safety_agent.py` | Rule engine (deterministic) + OpenFDA | Runs hard-contraindication rules first, then OpenFDA interaction checks; produces per-trial `SafetyAssessment` |
| 5 | **Ranker** | `agents/ranker_agent.py` | Weighted formula (no LLM) | Computes a 0–100 score per trial, sorts, assigns ranks, hard-excludes `NOT_ELIGIBLE` / `CRITICAL` trials |
| 6 | **Report Generator** | `agents/report_generator.py` | Groq 70B | Writes a concise physician summary with safety notes, eligibility status, and next steps (with strict clinical guardrails) |

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
| LLM Provider | Groq (`llama-3.3-70b-versatile` complex / `llama-3.1-8b-instant` fast) via `langchain-groq` |
| Validation | Pydantic v2 + pydantic-settings |
| Database | PostgreSQL (async) via SQLAlchemy 2.0 + asyncpg |
| HTTP / Resilience | httpx · aiohttp · tenacity (retries + backoff) |
| Rate Limiting | slowapi |
| Logging | Loguru |
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
├── main.py                        # FastAPI entry point (lifespan, CORS, rate limits, SPA serving)
├── requirements.txt               # Python dependencies
├── .env                           # Local environment configuration (never commit secrets)
│
├── agents/                        # The 6-agent LangGraph pipeline
│   ├── pipeline_state.py          # Shared TypedDict state (relay baton between agents)
│   ├── pipeline.py                # Graph orchestration + conditional routing
│   ├── profile_parser.py          # Agent 1: RxNorm normalization + LLM keyword extraction
│   ├── trial_fetcher.py           # Agent 2: ClinicalTrials.gov search + pre-filtering
│   ├── eligibility_checker.py     # Agent 3: DSPy ChainOfThought eligibility evaluation
│   ├── drug_safety_agent.py       # Agent 4: Rule engine + OpenFDA interaction checks
│   ├── ranker_agent.py            # Agent 5: Weighted scoring & ranking
│   └── report_generator.py        # Agent 6: Physician-ready summary
│
├── api/
│   └── routes.py                  # REST endpoints (match, trial detail, drug checks)
│
├── core/
│   ├── config.py                  # Centralized Pydantic-settings configuration
│   ├── database.py                # Async PostgreSQL engine / sessions / table creation
│   └── logger.py                  # Loguru setup (console + rotating files)
│
├── rules/
│   └── safety_rules.py            # Deterministic clinical safety rule engine
│
├── schemas/
│   ├── patient.py                 # FHIR R4-aligned patient schemas
│   └── trial.py                   # Cleaned trial, assessment, and response schemas
│
├── utils/
│   └── api_clients.py             # ClinicalTrials.gov, OpenFDA, RxNorm HTTP clients
│
├── tests/
│   ├── test_api_clients.py        # API parsing unit tests (no network)
│   ├── test_rule_engine.py        # Safety rule engine tests (most critical)
│   └── test_pipeline_fixes.py     # Regression tests for pipeline fixes
│
└── frontend/                      # React + TypeScript + Tailwind SPA
    ├── index.html
    ├── vite.config.ts             # Dev server on :3000, proxies /api → :8000
    ├── tailwind.config.js
    ├── package.json
    └── src/
        ├── App.tsx                # Form → pipeline-progress → results views
        ├── main.tsx               # React root + QueryClient provider
        ├── index.css
        ├── services/api.ts        # Axios client for backend endpoints
        ├── types/index.ts         # Full TypeScript contract for API responses
        └── components/
            ├── PatientForm.tsx    # Multi-section patient intake form
            └── TrialCard.tsx      # Ranked trial card with eligibility + safety details
```

---

## Getting Started

### Prerequisites

- **Python 3.11+**
- **Node.js 18+** (for the frontend)
- **PostgreSQL 14+** (or Docker)
- **Docker** (optional — for PostgreSQL/Qdrant)
- **Groq API key** — free at [console.groq.com](https://console.groq.com)

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

```bash
pip install -r requirements.txt
```

> **Note:** the DSPy package is published as `dspy-ai` (not `dspy`). If you hit an import error, run `pip install dspy-ai`.

### 4. Configure environment variables

Create a `.env` file in the project root (a copy of the block below) and fill in your values:

```env
# ── LLM (required) ────────────────────────────────────────────
GROQ_API_KEY=gsk_your_key_here                 # Get free at console.groq.com
GROQ_MODEL_COMPLEX=llama-3.3-70b-versatile     # Complex reasoning (eligibility, reports)
GROQ_MODEL_FAST=llama-3.1-8b-instant           # Fast extraction (profile parser)

# ── Database (required) ───────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/clinical_trials
DATABASE_URL_SYNC=postgresql://postgres:postgres@localhost:5432/clinical_trials

# ── Vector DB (optional) ──────────────────────────────────────
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=clinical_trials

# ── External APIs (all free, no keys) ─────────────────────────
CLINICALTRIALS_BASE_URL=https://clinicaltrials.gov/api/v2
OPENFDA_BASE_URL=https://api.fda.gov/drug
RXNORM_BASE_URL=https://rxnav.nlm.nih.gov/REST

# ── App ───────────────────────────────────────────────────────
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8000
SECRET_KEY=change-me-in-production
CORS_ORIGINS=http://localhost:3000,http://localhost:5173

# ── Pagination ────────────────────────────────────────────────
DEFAULT_PAGE_SIZE=10
MAX_PAGE_SIZE=50
```

### 5. Start PostgreSQL

**Option A — Docker (recommended):**

```bash
docker run -d \
  --name clinical_trials_db \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=clinical_trials \
  -p 5432:5432 \
  postgres:16
```

**Option B — Local PostgreSQL:**

```sql
CREATE DATABASE clinical_trials;
CREATE USER postgres WITH PASSWORD 'postgres';
GRANT ALL PRIVILEGES ON DATABASE clinical_trials TO postgres;
```

### 6. (Optional) Start Qdrant

```bash
docker run -d --name qdrant -p 6333:6333 qdrant/qdrant
```

### 7. Run the backend

```bash
uvicorn main:app --reload --port 8000
```

You should see:

```
INFO   Clinical Trial Matcher API — Starting...
INFO   Environment: development
SUCCESS  Database tables created/verified.
SUCCESS  Application ready.
```

- Interactive API docs (Swagger UI): **http://localhost:8000/docs**
- Health check: **http://localhost:8000/api/v1/health**

### 8. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend is served at **http://localhost:3000**. The Vite dev server proxies `/api` requests to the FastAPI backend at `http://localhost:8000`.

> **Tip:** to serve the frontend directly from FastAPI (single-server deployment), build it with `npm run build` (outputs to `frontend/dist`). FastAPI automatically mounts the built SPA on restart.

---

## API Reference

All endpoints are prefixed with `/api/v1`. Rate limits are enforced per IP address.

| Method | Endpoint | Description | Rate Limit |
|--------|----------|-------------|:----------:|
| `GET` | `/health` | Service health, version, active model, environment | — |
| `POST` | `/match` | Run the full 6-agent pipeline and return ranked matches | 5/min |
| `GET` | `/trials/{nct_id}` | Fetch full details for a specific trial | 20/min |
| `GET` | `/drugs/check` | Check drug–drug interactions (`drug1`, `drug2`) | 10/min |
| `GET` | `/drugs/normalize` | Normalize a brand name → generic via RxNorm (`name`) | 20/min |

### Match a patient with trials

```bash
curl -X POST http://localhost:8000/api/v1/match \
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
curl "http://localhost:8000/api/v1/drugs/check?drug1=metformin&drug2=contrast%20dye"
```

### Get a specific trial

```bash
curl http://localhost:8000/api/v1/trials/NCT04892173
```

### Pagination

Both the `/match` endpoint accept `page` and `page_size` query parameters (`page_size` capped at `MAX_PAGE_SIZE`):

```bash
curl -X POST "http://localhost:8000/api/v1/match?page=2&page_size=10" \
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

## Deployment

### Backend — Railway / Render / any Docker host

```bash
# Railway CLI
npm install -g @railway/cli
railway login
railway init
railway up
```

Set all environment variables from the [Environment Variables](#-environment-variables) section in your host's dashboard. Point `DATABASE_URL` and `DATABASE_URL_SYNC` at a managed PostgreSQL instance.

### Frontend — Vercel / Netlify

```bash
cd frontend
npm install -g vercel
vercel --prod
```

Set `VITE_API_URL` to your deployed backend URL and ensure CORS includes the frontend origin.

### Qdrant Cloud (free tier)

1. Create a free cluster at [cloud.qdrant.io](https://cloud.qdrant.io).
2. Update `QDRANT_HOST` (and port/API key) in your environment.

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|:--------:|---------|-------------|
| `GROQ_API_KEY` | Yes | — | Groq API key (free at console.groq.com) |
| `DATABASE_URL` | Yes | — | Async PostgreSQL connection string (`postgresql+asyncpg://…`) |
| `DATABASE_URL_SYNC` | Yes | — | Sync PostgreSQL string (for tooling such as Alembic) |
| `GROQ_MODEL_COMPLEX` | No | `llama-3.3-70b-versatile` | Complex reasoning model (eligibility, reports) |
| `GROQ_MODEL_FAST` | No | `llama-3.1-8b-instant` | Fast extraction model (profile parser) |
| `QDRANT_HOST` | No | `localhost` | Qdrant vector DB host |
| `QDRANT_PORT` | No | `6333` | Qdrant port |
| `QDRANT_COLLECTION` | No | `clinical_trials` | Qdrant collection name |
| `CLINICALTRIALS_BASE_URL` | No | `https://clinicaltrials.gov/api/v2` | ClinicalTrials.gov API base URL |
| `OPENFDA_BASE_URL` | No | `https://api.fda.gov/drug` | OpenFDA base URL |
| `RXNORM_BASE_URL` | No | `https://rxnav.nlm.nih.gov/REST` | RxNorm base URL |
| `APP_ENV` | No | `development` | `development` / `production` |
| `APP_HOST` | No | `0.0.0.0` | Bind address |
| `APP_PORT` | No | `8000` | Bind port |
| `SECRET_KEY` | No | `change-me-in-production` | App secret — **must change in production** |
| `CORS_ORIGINS` | No | `http://localhost:3000` | Comma-separated allowed frontend origins |
| `DEFAULT_PAGE_SIZE` | No | `10` | Default results per page |
| `MAX_PAGE_SIZE` | No | `50` | Upper bound on page size |

---

## Troubleshooting

**`GROQ_API_KEY not set` / app won't start**
Make sure `.env` exists in the project root and contains a valid key. Restart the terminal after creating/editing the file.

**`Database connection refused`**
Confirm PostgreSQL is running (`docker ps` if using Docker) and that `DATABASE_URL` credentials match the database.

**`DSPy import error`**
The PyPI package is `dspy-ai`, not `dspy`. Run `pip install dspy-ai`.

**Frontend can't reach the API**
Ensure the backend is running on port 8000. The Vite dev proxy forwards `/api` to `http://localhost:8000` (see `frontend/vite.config.ts`).

**Rate-limit errors from Groq**
The free tier allows ~30 requests/min. The pipeline already batches eligibility checks with delays. If you hit limits, reduce the fetch/evaluation volume in `agents/trial_fetcher.py` (the `FETCH_BUFFER_MULTIPLIER` / hard cap) and `agents/eligibility_checker.py`.

**ClinicalTrials.gov returns HTTP 403**
The client automatically retries progressively simpler queries and, if still blocked, falls back to a public trial-search mirror (TrialsMap). This is logged as a `WARNING` in `logs/clinical_trial_matcher.log`.

---

## Disclaimer

This tool is for **informational and research purposes only** and does **not** constitute medical advice. All trial matches, eligibility determinations, and drug-safety assessments are AI-generated and must be reviewed by a qualified healthcare provider before any enrollment or clinical decision. No patient PII is stored.

---

<div align="center">
  <sub>Built with FastAPI · LangGraph · DSPy · Groq · React</sub>
</div>
