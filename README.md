# MultiAgent Insurance Claims Triage Assistant on Azure AI Foundry

**For interviewers:** start with the [five-minute reviewer guide](docs/00-reviewer-start-here.md), [architecture](docs/02-architecture.md), and [requirement evidence](docs/11-coverage.md). For a screen-share, follow the [ten-minute demonstration](docs/10-interview.md) or [Streamlit walkthrough](docs/13-streamlit-showcase.md).

A runnable synthetic property/auto claims assistant with a supervisor, three specialist agents, explicit triage checkpoints, retrieved underwriting knowledge, persistent memory and an adjuster review gate. Python 3.11–3.13; developed and tested with Python 3.12.

**Default: local mock LLM mode.** The actual validation, coverage tools, vector retrieval, orchestration, API and SQLite persistence run locally. Only the LLM/Foundry transport is mocked. The assignment permits this; no Azure project endpoint, model deployment or credentials were supplied. Azure Developer CLI was also unavailable in the implementation environment. The real `azure-ai-agents==1.1.0` adapter is included and contract-tested, but a live Azure deployment is not claimed. See [verification and coverage](docs/11-coverage.md).

All supplied fixtures, history, summaries and decisions are **synthetic**. “Auto approve” is an adjuster recommendation, not a settlement/payment action. Every claim remains pending until a human records a decision.

## Streamlit showcase and requirements dashboard

A Streamlit frontend is now included as a user-requested addition. It calls the authenticated API for triage, uploads, chat, evidence and human review. Its **Requirements dashboard** covers all 35 original groups, shows implementation/test references and distinguishes observed UI behavior from pending live Azure checks.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ui.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
$env:TRIAGE_MODE = 'mock'
.\.venv\Scripts\python.exe tools/run_showcase.py --api-port 8011 --ui-port 8511
```

Open **http://127.0.0.1:8511**. If the showcase is already running, simply open it. The launcher starts both services and handles their shared token. Use **New session** to begin. Follow the [step-by-step showcase guide](docs/13-streamlit-showcase.md) for the full demonstration, including RAG evidence, memory, validation edge cases, human gates and the requirements dashboard. Setup from an empty environment is also covered there.

## Quick start — PowerShell

Run from this repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m claims_triage triage data/claims.json --synthetic
```

The response includes `session_id`, batch `id`, per-row evidence, citations, recommendations and six routine events. Logs go to stderr; JSON goes to stdout. Use the IDs from the response:

```powershell
.\.venv\Scripts\python.exe -m claims_triage chat <session-id> "why was claim C2031 flagged?"
.\.venv\Scripts\python.exe -m claims_triage chat <session-id> "explain why it was flagged"
.\.venv\Scripts\python.exe -m claims_triage review <session-id> <batch-id> 1 approve --note "Synthetic evidence reviewed and accepted"
.\.venv\Scripts\python.exe -m claims_triage show <session-id> <batch-id>
.\.venv\Scripts\python.exe -m claims_triage triage data/claims_auto.csv --synthetic
```

Angle-bracket values above are placeholders: replace them, including brackets. Each `triage` creates a new session unless `--session` is supplied. Data persists in `var/claims.db`. Reprocessing the same ID in the same session is a duplicate. To demonstrate independent batches without this flag, use a new session. Persisted policy history remains shared in this explicitly single-tenant application.

On Linux/macOS use `.venv/bin/python`. As an alternative to the frozen lock files, install the declared ranges with `python -m pip install -e '.[dev,azure]'`. Runtime-only deployments use `requirements.lock`. The locks freeze the tested dependency set; review updates before changing them.

## Expected starter results

| Claim | Recommendation | Why |
|---|---|---|
| C-2031 | route_to_investigator | Earlier synthetic flagged water-damage event C-1900 on 2026-02-15 |
| C-2032 | auto_approve, pending human | Valid covered loss, no earlier flagged event as of its loss date |
| C-2033 | route_to_investigator | Report 3 days after inception; amount equals the limit |
| C-2034 | request_more_documentation | Missing loss date and zero amount; coverage is explicitly skipped |

The expired POL-4410 policy cannot be evaluated against an absent loss date. After correcting input in a new session, its loss date would be compared to the policy period. Neither description text nor a model may supply that missing date.

## Run the API

```powershell
$env:TRIAGE_API_TOKEN = .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
.\.venv\Scripts\python.exe -m claims_triage serve
```

Visit `http://127.0.0.1:8000/docs`, select **Authorize**, and enter the token. Create a session, then submit a batch using `{"synthetic":true,"claims":[...]}`. The API binds to loopback by default. Do not expose it directly to the internet; see the deployment guide for TLS and ingress requirements. `/health`, `/docs`, `/redoc` and `/openapi.json` contain no claim data and are public; every claim/session operation requires the token.

For configuration, copy `.env.example` to `.env` and supply values, or set `TRIAGE_*` environment variables. Real Azure calls use `TRIAGE_MODE=azure`, `TRIAGE_AZURE_ENDPOINT`, and `TRIAGE_AZURE_MODEL`; see [Azure setup](docs/09-deployment.md). Run `python -m claims_triage provision` once to create the four agents, their JSON-schema tools, and file-search vector store. Provisioning resumes from saved resource IDs. Invocation never silently changes from Azure mode to mock mode.

## Verify

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp=.pytest-local-tmp --cov=claims_triage --cov-report=term-missing
.\.venv\Scripts\python.exe -m ruff check src tests tools
.\.venv\Scripts\python.exe -m mypy src
```

The live Azure smoke test is skipped unless `TRIAGE_RUN_LIVE=1` and a provisioned Azure profile are configured. Tests with fake SDK clients validate code behavior, not subscription access or model availability. VS Code launch configurations and tasks are included. See the [10-minute interview demonstration](docs/10-interview.md).

## Deliverables, in requested order

1. [Requirement analysis and traceability](docs/01-requirements.md)
2. [Architecture, components, security, errors and logging](docs/02-architecture.md)
3. [Database design](docs/03-database.md)
4. [API design and examples](docs/04-api.md)
5. [Folder structure](docs/05-folder-structure.md)
6. [Source code guide](docs/06-source-code.md), with implementation in `src/claims_triage/`
7. [Test cases and scenarios](docs/07-test-scenarios.md), with executable tests in `tests/`
8. [README and setup/run instructions](README.md)
9. [Deployment guide and operating limits](docs/09-deployment.md)
10. [Interview explanation, walkthrough and questions](docs/10-interview.md)
11. [Final requirement coverage checklist and verification evidence](docs/11-coverage.md)

For interview study, read the [complete implementation explanation and 36 additional Q&As](docs/12-implementation-and-interview-study-guide.md), then rehearse the shorter [screen-share guide](docs/10-interview.md). The study guide covers requirement mapping, RAG, sample results, technical tradeoffs and verification limits.

## Deliberate boundaries

SQLite and the token model target a single tenant on one host with persistent local storage. Streamlit was added after the original backend assignment at the user's request. No payment integration, multi-tenant identity system, policy administration integration, or real fraud determination is implemented. Configuration and assumptions are listed in the requirement analysis. Horizontal scaling needs a shared transactional database, distributed concurrency control, identity/RBAC and a background job queue. Cloud readiness also depends on actual Azure smoke testing and deployment-specific operations checks.
