# Reviewer guide

This project turns a synthetic claims batch into evidence-backed recommendations for a human adjuster. It demonstrates a supervisor and three specialists, constrained function tools, retrieved underwriting rules, conversation context, durable prior-claim memory, and an explicit human review gate.

**Verified scope:** the application runs locally with a deterministic mock of the LLM/Foundry transport. Validation, retrieval, SQLite persistence, HTTP endpoints, Streamlit controls, and human review execute real application code. The Azure Agent Service adapter is implemented and SDK-contract-tested; live Azure provisioning and inference remain unverified. This follows the mock fallback permitted by [the assignment](../projectdetails.txt).

**Local evidence (10 October 2026):** 237 tests passed, one opt-in Azure test skipped, 95.32% statement coverage; lint, typing and API/Streamlit smoke passed. GitHub CI was attempted, but an account-level runner restriction prevented execution. See [verification details](verification.json).

## A five-minute review

| Time | Open | What to inspect |
|---|---|---|
| 1 minute | [Architecture](02-architecture.md) | Four roles, runtime boundary, retrieval and memory, human authority |
| 1 minute | [Expected starter results](../README.md#expected-starter-results) | Four distinct claims, reasons, and pending human status |
| 1 minute | [Supervisor service](../src/claims_triage/service.py) and [tool definitions](../src/claims_triage/tools.py) | Explicit steps, schemas, role and argument restrictions |
| 1 minute | [Azure adapter](../src/claims_triage/azure_runtime.py) | Programmatic agent creation, file-search registration, threads, bounded runs |
| 1 minute | [Requirement evidence](11-coverage.md) and [verification report](verification.json) | Requirement-to-test mapping and clearly stated verification limits |

## Run the demo without Azure credentials

From a fresh checkout, using Python 3.12 and PowerShell:

```powershell
git clone https://github.com/Mani-Harsha/insurance-claims-triage-foundry.git
cd insurance-claims-triage-foundry
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-ui.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
$env:TRIAGE_MODE = 'mock'
.\.venv\Scripts\python.exe tools/run_showcase.py --api-port 8011 --ui-port 8511
```

Open **http://127.0.0.1:8511**. The launcher starts the API and UI and generates their shared server-side token. This address works on the machine running the project; this repository does not provide a hosted public application.

1. Create a **New session**, confirm the data is synthetic, and triage the starter fixture.
2. Inspect C-2031: the recommendation cites an earlier synthetic water-damage event C-1900.
3. Ask `Why was C2031 flagged?`, then `Explain its recommendation` to demonstrate conversation context.
4. Inspect C-2033: the inception and near-limit rules come from retrieved knowledge with citations.
5. Inspect C-2034: missing input prevents coverage evaluation and requires documentation.
6. Approve the clean C-2032 with a review note. Other rows remain pending their own human decisions.
7. Open the requirements dashboard and distinguish recorded evidence from behavior observed in this session.

Use the [full UI guide](13-streamlit-showcase.md) for uploads, restart/persistence, edge cases and troubleshooting. Use a new session for a fresh batch: replaying the same IDs in one session intentionally triggers duplicate detection.

## What makes the design inspectable

- **Explicit orchestration:** the application fixes ordering and checkpoints; the model cannot invent an approval path.
- **Grounding:** versioned rule files supply parameters and citations. Local retrieval uses TF-IDF vectors, not neural embeddings; Azure mode also registers hosted file search.
- **Two memory scopes:** conversation messages and last-claim context support follow-ups; SQLite claim history survives restarts and supplies chronologically eligible earlier losses.
- **Constrained tools:** five custom function tools have role-specific schemas and context checks. Model prose does not override deterministic evidence.
- **Human authority:** `auto_approve` is a recommendation. Every claim starts pending review; unsafe approvals are rejected. No settlement or payment is executed.
- **Failure behavior:** malformed input, timeouts and tool failures are tested; an Azure failure does not silently switch to mock mode.

## Discussion and next steps

Read the [ten-minute walkthrough and tradeoffs](10-project-walkthrough.md) or the [detailed implementation guide](12-implementation-guide.md). The [database](03-database.md), [API](04-api.md), [test scenarios](07-test-scenarios.md), and [deployment guide](09-deployment.md) support a deeper review.

Before a production rollout, validate live Azure access/model behavior, deploy identity and RBAC, replace single-host SQLite for distributed operation, add operational monitoring and recovery exercises, and perform domain-specific evaluation. No cloud deployment, throughput benchmark, fraud-detection accuracy, or production certification is claimed here.
