# Clinical Trial Matcher — Gap Analysis & Remediation Roadmap

Status date: 2026-11-01
Scope: what is broken today, what "good enough to demo to a client" means, and the
ordered plan to get there. Phases are deliberately small and independently
verifiable so nothing is attempted all at once.

---

## 1. Verified current state

These results were reproduced in this repository on this machine, not copied from
earlier session logs.

| Check | Command | Result |
|---|---|---|
| Lint | `ruff check src tests` | **pass** |
| Types | `mypy src/clinical_trial_matcher` | **pass** (46 files) |
| Tests | `pytest -q` | **pass** (67 tests) |
| Frontend build | `npm run build` (frontend/) | **pass** (259 kB JS) |
| App import / lifespan | `create_app()` + TestClient | **pass** |
| Postgres | direct `SELECT 1` | **up**, Alembic at head `cd051579e2bd` |
| Redis | `ping_redis()` | **down** (dev fallback to in-memory rate limiting) |
| Docker | `docker ps` | **down** (Docker Desktop not running) |
| Ollama | `/api/tags` | **up**, only `llama3.2:3b` installed |
| ClinicalTrials.gov | `search_trials("Type 2 Diabetes Mellitus")` | **20/20 studies parsed**, 878 total |
| End-to-end `/match` | real pipeline run | **not usable**: one eligibility call took **261.7 s** |

So the project is not "failing to start". It starts, lints, type-checks, tests and
builds. The failure is in the **core value path**: a single `/match` request cannot
finish inside the frontend's 120 s timeout.

---

## 2. Gaps, ordered by severity

### P0 — blocks a client demo

1. **Eligibility inference is far too slow.**
   Measured: **261.7 s for one trial** with `llama3.2:3b` on CPU. The agent caps at 6
   trials / 3 worker threads, so a realistic request is 2–3 waves ≈ **9–13 minutes**.
   The frontend aborts at 120 s (`frontend/src/services/api.ts`), so the UI shows a
   timeout and no matches.

2. **Eligibility output is clinically contradictory.**
   Same run returned `match_score = 92.5` together with `is_eligible = false` and
   `decision = NOT_ELIGIBLE`, with reasoning claiming "age 52 is below the threshold of
   35" for a trial whose protocol minimum is 18. A 3B model cannot be trusted with
   free-form eligibility reasoning. Score and decision are inconsistent in the payload
   the client sees.

3. **No latency budget or per-call timeout anywhere.**
   No `asyncio.wait_for`, no pipeline deadline, no per-trial timeout. One slow or hung
   LLM call blocks the entire request. `dspy.LM` uses default retries, so a slow call
   can be retried and become even slower.

4. **Hard protocol facts are sent to the LLM unnecessarily.**
   `EligibilityCriteria` already carries `minimum_age`, `maximum_age` and
   `sex_eligible` parsed deterministically from ClinicalTrials.gov, but the eligibility
   agent ignores them and asks the model to re-derive age/sex eligibility. This is both
   the slowest and the least reliable part of the pipeline, and it is the part that
   produced the contradictory reasoning above.

5. **LLM quality is not matched to the job.**
   `.env` sets `LOCAL_LLM_MODEL=llama3.2:3b` while config/README default to
   `llama3.1:8b`. The 3B model is fast enough for keyword extraction, not for
   eligibility reasoning. Only `llama3.2:3b` is currently pulled.

### P1 — correctness, honesty, operability

6. **Reporting is not honest about coverage.**
   `total_trials_searched` is 878 (all matching trials at the source) but at most 6 are
   evaluated; the response does not distinguish "not eligible" from "not evaluated".
   The UI therefore implies full coverage.

7. **"NEEDS_REVIEW" reasons are conflated.**
   The report generator's fallback text always says criteria were "unavailable (data
   came from a fallback source)". After adding timeouts, this text would be wrong for
   time-budget skips. Each skip reason must be carried through.

8. **Test coverage stops at the edges.**
   67 tests cover API parsing, safety rules, pipeline filters, config, errors, health,
   logging, middleware, models, security. **No test** covers `/auth/login`,
   `/auth/refresh`, an authenticated `/match`, or the eligibility agent's failure
   modes. The two client-facing endpoints have the least coverage.

9. **Redis is down in development.**
   Rate limiting silently falls back to in-memory. Fine for a laptop, but the demo
   environment must state which mode it is in, and production must fail fast.

10. **`TRUSTED_HOSTS` in `.env` omits `testserver`.**
    Running the app against the real `.env` rejects TestClient's default host with
    `400 Invalid host header`, which makes local in-process smoke tests misleading.

### P2 — release hygiene

11. **One huge uncommitted change set.**
    The src-layout migration, auth, database, Docker, CI, Alembic and frontend auth are
    all uncommitted on top of `9148b5e`. There is no clean checkpoint to roll back to.

12. **A Groq API key was written to `.env` and printed in a terminal transcript.**
    `.env` is git-ignored (verified), but the key itself must be treated as leaked and
    rotated. It is not needed for the local-provider deployment.

13. **Deployment path is unverified on this machine.**
    Docker daemon is down, so `docker compose up` and the Dockerfile could not be
    exercised. Compose/Dockerfile contents look coherent but are unproven here.

14. **Documentation overstates guarantees.**
    README claims DSPy "guarantees typed, validated eligibility decisions"; in practice
    the agent needs `_coerce_*` shims because the model returns dicts/strings. README
    also still implies full-trial evaluation.

---

## 3. Target architecture (smallest change that fixes the root cause)

Keep the 6-agent LangGraph pipeline. Change only what the measured failures require:

```
POST /api/v1/match
        │
        ▼
  Profile Parser ─────────────► RxNorm + local LLM (fast model, extraction only)
        │
        ▼
  Trial Fetcher ──────────────► ClinicalTrials.gov (+ TrialsMap fallback)
        │                       new: return ALL candidates, already pre-filtered
        ▼
  Eligibility Gate  ◄── NEW deterministic layer
        │  1. age / sex protocol screen (no LLM, instant, auditable)
        │  2. rank candidates by cheap relevance, take at most N
        │  3. LLM check with per-call timeout + global deadline
        │  4. timeout/deadline ⇒ NEEDS_REVIEW with the exact skip reason
        ▼
  Drug Safety ────────────────► rule engine (hard walls) + OpenFDA
        ▼
  Ranker ─────────────────────► deterministic weighted score
        │                       new: keep NOT_ELIGIBLE out, keep NEEDS_REVIEW visible
        ▼
  Report Generator ───────────► summary that states evaluated vs. found
        ▼
  MatchResponse ──────────────► add evaluation coverage metadata
```

Key architectural decisions:

- **Protocol facts are not model questions.** Age and sex eligibility are decided by
  code from the parsed protocol.
- **Every LLM call has a deadline.** Per-call timeout plus a whole-pipeline budget;
  exceeding either downgrades a trial to `NEEDS_REVIEW` with a stated reason instead of
  hanging the request.
- **Partial results are first-class.** A response that says "evaluated 3 of 20; 17 not
  evaluated within the time budget" is a valid, honest product result. A 10-minute
  request is not.
- **No async job queue yet.** It is the right long-term answer for slow local inference,
  but it is a much larger change. Budgeted synchronous matching fits inside a demo and
  can be replaced later without touching agents.

Model configuration guidance:

- Local CPU: `llama3.2:3b` for extraction, but eligibility must run on `llama3.1:8b`
  (already the documented default) or be accepted as `NEEDS_REVIEW`.
- GPU or hosted dev (`LLM_PROVIDER=groq`): sub-second calls; production validation still
  forbids non-local providers.

---

## 4. Step-by-step plan

### Phase 0 — Safety and checkpoint (do first, ~15 min)

1. Rotate the exposed Groq key and remove it from `.env` (leave `GROQ_API_KEY=` empty).
2. Commit the current refactor as a checkpoint so later fixes are reviewable.
3. Remove stale build caches from the working tree (`.mypy_cache`, `__pycache__`) from
   version control consideration.

**Exit criteria:** clean baseline commit; no live secret in the workspace.

### Phase 1 — Make `/match` finish and tell the truth (P0 + P1.6–7)

1. Add deterministic age/sex eligibility screening before any LLM call.
2. Add `eligibility_timeout_seconds` and `pipeline_budget_seconds` settings; pass
   `timeout` and `num_retries=0` to `dspy.LM`.
3. Wrap each eligibility call in `asyncio.wait_for`; on timeout emit `NEEDS_REVIEW`
   with a machine-readable skip reason (`timeout`, `budget_exhausted`, `criteria_unavailable`,
   `llm_error`).
4. Enforce the global budget across batches; remaining trials are marked skipped, not
   dropped.
5. Reduce local eligibility cap to 3 trials (one worker wave).
6. Surface coverage in the response: evaluated count, skipped count, skip reasons, and
   a `query_summary` that states the limitation.
7. Align the frontend timeout with the budget and show the coverage note in the UI.
8. Update the report generator so skip reasons are not misreported as "fallback source".
9. Add tests: age screen, sex screen, timeout path, budget path, coverage counts.

**Exit criteria:** a real `/match` against local Ollama returns within the configured
budget with ranked results and honest coverage counts; no request exceeds the budget.

### Phase 2 — Clinical output quality (P0.2)

1. Make decision and score consistent: a `NOT_ELIGIBLE` decision cannot report a high
   `match_score`; clamp/recompute before persisting.
2. Move to `llama3.1:8b` (pull locally) or GPU inference for eligibility; benchmark one
   call and record latency in the README.
3. Add a small golden-set evaluation script: 5–10 patient/trial pairs with expected
   decisions, run against each model, report agreement and latency.
4. Cache eligibility results per (patient-profile hash, trial criteria hash) to avoid
   paying for the same comparison twice.

**Exit criteria:** evaluation agreement is measured and documented; no contradictory
assessment reaches the API response.

### Phase 3 — Client-demo readiness (P1)

1. Seed script: one admin, one clinician, and 3 patient personas with expected results.
2. Auth tests for login, refresh rotation, logout, RBAC on `/match`.
3. Frontend: coverage banner, honest empty state, retry affordance, progress copy that
   matches the actual budget.
4. Start Redis locally (or `docker compose up -d redis`) and confirm rate limiting uses
   Redis; document dev fallback.
5. Add `testserver` to dev `TRUSTED_HOSTS` (or run smoke tests with an explicit Host
   header) so in-process smoke tests are trustworthy.

**Exit criteria:** a scripted demo (seed → login → match → results) runs clean on a
fresh machine.

### Phase 4 — Deployment verification (P2)

1. Start Docker Desktop; run `docker compose build` and `up`, then hit
   `/api/v1/health/ready` and one real match.
2. Verify Alembic migration on a clean database and `create_admin` inside the container.
3. Confirm CI (lint, types, tests, frontend build, image build) is green on the
   checkpoint commit.
4. Update README to match measured behaviour (coverage, latency, model requirements).

**Exit criteria:** compose deployment serves a working match end to end; docs match
reality.

---

## 5. What "demo-ready" means here

- `/match` returns in a bounded time (target: under 2 minutes locally, under 10 seconds
  with a hosted/GPU model).
- Ranked matches display with eligibility decision, safety level and reasoning.
- The response never claims more evaluation coverage than actually happened.
- A clinician can log in, run a match, read the physician summary and open a trial.
- No secret, timeout or Docker requirement blocks the demo.
