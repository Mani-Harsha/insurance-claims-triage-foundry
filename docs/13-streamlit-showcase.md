# Streamlit showcase: setup, requirements dashboard and step-by-step demonstration

The frontend is a later user-requested addition to the original assignment. It calls the authenticated FastAPI backend over HTTP. It does not duplicate business rules or directly edit SQLite. Local mock mode executes the actual validators, knowledge retrieval, persistence and human-decision gates; only LLM/Foundry transport is mocked.

## Start the showcase

From the project root, using Python 3.12 as the tested environment:

```powershell
# If the virtual environment does not already exist:
python -m venv .venv

# Install the frozen UI/runtime dependencies and the package:
.\.venv\Scripts\python.exe -m pip install -r requirements-ui.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .

# Explicitly select the offline demonstration:
$env:TRIAGE_MODE = 'mock'
.\.venv\Scripts\python.exe tools/run_showcase.py --api-port 8011 --ui-port 8511
```

Open **http://127.0.0.1:8511** when the terminal says “Showcase ready”. If a showcase is already running there, open it instead of starting a second copy. Keep the launcher terminal/process running. Ctrl+C stops both services started by that launcher. The equivalent PowerShell wrapper is `tools/start-showcase.ps1 --api-port 8011 --ui-port 8511`.

The launcher creates a random API token when none is configured, shares it privately between the two processes, and binds both to loopback. No token needs to be copied into the UI. The default database is `var/showcase.db`; a configured `TRIAGE_DATABASE` overrides it. Restarting preserves evidence. Logs are under `var/showcase-<api-port>/`. If a port is in use, choose different `--api-port` and `--ui-port` values; do not stop an unrelated service.

Both services are intended for a trusted local demonstration. The UI's server-side API token is not individual-user authentication. Do not expose Streamlit publicly without an authenticated deployment boundary. Azure mode still needs the existing project configuration, provisioning and live acceptance checks documented in [deployment](09-deployment.md).

## What is on each screen

| Screen | Purpose | Evidence to point out |
|---|---|---|
| Sidebar | New session, resume by ID, select saved batch, refresh | Persistent session ID, current runtime, saved batch states |
| 1 · Triage | Choose a prepared scenario or upload JSON/CSV | Synthetic declaration, input preview and download, batch result |
| 2 · Claims & review | Inspect recommendations and record human decisions | Intake issues, coverage findings, prior history, retrieved citations, immutable review |
| 3 · Conversation | Ask about a claim and ask follow-up questions | Saved messages, normalized claim ID, earlier memory |
| 4 · Evidence & routine | Inspect actual executed steps and export evidence | Ordered states, runtime, knowledge hash, complete audit JSON |
| 5 · Requirements dashboard | Show all 35 original requirement groups | Recorded implementation/tests, observed behaviors, pending Azure checks, downloadable matrix |

The dashboard's “Recorded passing tests” and coverage figures come from `docs/verification.json`. Opening the dashboard does not execute a test suite. “Observed in this showcase” is a narrower indicator that some relevant behavior was seen through this UI; it is not proof of every edge case or complete acceptance of that requirement. Its counters accumulate in the current browser session, including across new claim sessions. Reloading a new browser session resets these counters; resuming a saved batch reconstructs observable batch evidence.

## Fifteen-minute demonstration

### Agent functions to point out

Open **Evidence & routine** to expand the four agent cards and inspect their registered JSON-schema functions. The catalog is visible before running a batch and does not claim those tools have executed.

| Agent | Functions | Showcase evidence |
|---|---|---|
| Supervisor | `route_request` | Submit a batch; ask why C2031 was flagged; ask a follow-up |
| Intake & Validation | `validate_claim` | C-2034 missing fields; Validation edge cases; duplicate detection |
| Anomaly & Coverage | `check_coverage`, `search_knowledge` | Policy checks, retrieved UW rules/citations, C-1900 history, Coverage edge cases |
| Adjuster Briefing | `build_brief` | Per-claim summaries and the three recommendations; pending human review |

The mock workflow executes `route_request`, `validate_claim`, `check_coverage` and `build_brief`. Retrieval runs inside `check_coverage`. `search_knowledge` is an additional registered function available to the Azure coverage agent; it is not separately invoked by the mock routine. Hosted file search and live model/tool selection require Azure verification. Human decisions are authenticated application operations, not model tools.

### Swagger alternative

For a demo where you also want to use Swagger, generate a token in the launching terminal before starting the services:

```powershell
$env:TRIAGE_API_TOKEN = .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
# Copy this value into Swagger's Authorize dialog; do not include the Bearer prefix:
$env:TRIAGE_API_TOKEN
.\.venv\Scripts\python.exe tools/run_showcase.py --api-port 8011 --ui-port 8511
```

Open **http://127.0.0.1:8011/docs** or the UI sidebar's **Swagger API showcase** link. Click **Authorize**, enter the token, and close the dialog. For each operation, click **Try it out**, enter the fields, then **Execute**:

1. `POST /sessions`: copy `session_id` from the response.
2. `POST /sessions/{session_id}/batches`: enter that ID and use the ready-made **starter** example. Copy response `id` as `batch_id`. All four agents participate; expected actions are investigate, approve recommendation, investigate, and documentation.
3. `POST /sessions/{session_id}/chat`: execute **explain**, then **followup**. Both should refer to C-2031 and C-1900.
4. `POST /sessions/{session_id}/batches/{batch_id}/reviews/{row_index}`: use **investigate** for rows 0 and 2, **approve** for row 1, and **documentation** for row 3. Each example includes a valid note. Approving row 0 before reviewing it returns `409 unsafe_approval`.
5. `GET /sessions/{session_id}/batches/{batch_id}`: verify all four reviews and final `state: REVIEWED`. Use `/messages` and the batch-list endpoint to inspect persisted conversation and saved batches.
6. In a fresh session, try `/uploads`: select `application/json` with `format=json`, or `text/csv` with `format=csv`, and set `synthetic=true`. The body editor contains a working example. This is raw content, not multipart upload.
7. Paste the same session ID into the Streamlit sidebar's **Resume a saved session** form. The UI shows the evidence and decisions created through Swagger.

The Swagger introduction also lists all five registered functions and the demonstration sequence. Agent functions run inside the supervised workflow; they are not independent HTTP endpoints.

### Step 1 — Frame the problem and scope (one minute)

Say: “This prepares synthetic insurance claims for adjuster review. Four agent roles coordinate through a visible routine, with retrieval-grounded policy evidence and persistent memory. Today I am demonstrating local mock mode, not claiming live Azure execution.”

Point to the runtime label and synthetic banner. Open **Requirements dashboard** and show 35 groups with implementation/test references. Explain the distinction between recorded tests and observed UI behavior.

### Step 2 — Triage the starter property batch (two minutes)

1. Click **New session** in the sidebar.
2. Save the displayed session ID in a note; it is needed for the restart demonstration.
3. In **Triage**, select **Starter property claims**.
4. Expand **Preview submitted data** and show the four provided records.
5. Check **I confirm these submissions are synthetic.**
6. Click **Run triage**. Wait until the batch state appears.
7. Open **Claims & review**.

Expected recommendations:

| Claim | Outcome | Explanation |
|---|---|---|
| C-2031 | Investigator review | Covered claim with an earlier similar flagged C-1900 event |
| C-2032 | Auto approve recommendation | Valid coverage; C-1900 occurred after this claim's loss date and is excluded |
| C-2033 | Investigator review | Report three days after inception and amount exactly at policy limit |
| C-2034 | More documentation | Missing loss date and zero amount; coverage is skipped |

Say: “These are recommendations. All four start pending human review.”

### Step 3 — Demonstrate grounding and memory (two minutes)

1. Select **Row 0 · C-2031** under **Inspect claim**.
2. Show the natural-language brief and the **Earlier policy history** table with C-1900.
3. Show **Retrieved underwriting rules and citations**, especially UW06.
4. Select **Row 1 · C-2032** and explain why the later C-1900 event is not earlier history for that loss.
5. Select **Row 2 · C-2033** and point to `early_claim` and `near_limit`.

Say: “The local index uses sparse TF-IDF retrieval. Coverage evaluates retrieved parameters and includes citations. The Azure adapter also registers hosted file search, but registration alone does not prove a live search occurred.”

### Step 4 — Show the human gate (two minutes)

1. Select **C-2032**, choose **approve**, and enter a note such as “Reviewed synthetic coverage evidence”.
2. Click **Record human decision**. The UI shows the stored decision and note; the editable form disappears for that row.
3. Select **C-2031**, deliberately choose **approve**, enter a valid note, and submit.
4. Show the expected `unsafe_approval` error. This is the backend rejecting the operation, not only a disabled frontend control.
5. Change the decision to **investigate** and submit with a note. It should succeed.
6. Optionally review C-2033 as **investigate** and C-2034 as **request_documentation**. Once all four are reviewed, the batch state becomes `REVIEWED`.

Say: “A recommendation does not authorize payment. The backend records one human decision per row and preserves original evidence.”

### Step 5 — Demonstrate conversation (one minute)

1. Open **Conversation**.
2. Submit “Why was claim C2031 flagged?”
3. Submit “Explain its recommendation”.
4. Show that the follow-up retains C-2031 context and references earlier stored evidence.

Say: “The current router supports defined triage and explanation patterns; this is not an unrestricted general-purpose chatbot.” Batch submission is easiest from the Triage screen; a chat-only request cannot invent missing batch rows.

### Step 6 — Show the explicit routine and export (one minute)

Open **Evidence & routine**. Point to `INTAKE`, `VALIDATE`, `VALIDATION_CHECKPOINT`, `COVERAGE_AND_ANOMALIES`, `BRIEF` and `HUMAN_REVIEW_PENDING`. If reviewed, additional `HUMAN_DECISION` events appear.

Show the knowledge hash and **Download full evidence JSON**. Say: “The workflow is application-controlled and inspectable. The model cannot skip these checkpoints.”

### Step 7 — Demonstrate negative cases and auto coverage (three minutes)

Use **New session** for each independent scenario so duplicate detection does not obscure the intended example.

| Prepared source | What to demonstrate | Expected result |
|---|---|---|
| Validation edge cases | Both duplicate C-4001 rows; C-4002 reversed dates and unknown policy; C-4003 missing date, invalid policy and zero amount | Every row requests documentation, with explicit intake issues |
| Coverage edge cases | C-5001 exceeds limit; C-5002 loss outside active period; C-5003 auto peril excluded; C-5004 late report | First three route to investigator; late report requests documentation |
| Auto claims (CSV) | CSV ingestion and covered versus excluded auto peril | Collision gets auto-approve recommendation; fire routes to investigator |
| Upload JSON / CSV | Upload `data/claims.csv` or `data/claims.json` | Same backend validation and workflow as prepared fixtures |

For a malformed-input demonstration, upload a small `.json` file containing `not-json`. Expect `malformed_input`. No successful batch should be created for that upload. For same-session duplicates, run the same fixture twice in one session and inspect the second batch's duplicate findings.

### Step 8 — Prove persistence (two minutes)

1. Save the starter session ID from Step 2.
2. Open a new browser session/tab or restart the launcher with the same database configuration.
3. In the sidebar, expand **Resume a saved session**.
4. Paste the saved ID and click **Resume session**.
5. Select its saved batch. Prior human decisions and audit evidence should reappear.
6. Open **Conversation** and show saved messages; submit another explanation request.

Do not delete `var/showcase.db`. SQLite persistence is what makes this demonstration meaningful. Session context is scoped; policy history is shared inside this single-tenant demo workspace.

### Step 9 — Finish with the requirement dashboard (one minute)

1. Open **Requirements dashboard**.
2. Filter **Observed in this showcase** to show behaviors demonstrated through the screens.
3. Filter **Azure / live verification** and explicitly discuss pending live checks.
4. Download **requirement evidence** and show that every original group has code and test references.
5. Download the implementation guide for technical details.

Do not try to make every “Not observed yet” cell turn green: documentation, code-driven provisioning and live Azure behaviors need different evidence. A truthful requirements dashboard is more useful than a blanket completion badge.

## Verification and reproducible checks

```powershell
# Developer/test dependencies:
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock

# Streamlit controls against the real backend application and database:
.\.venv\Scripts\python.exe -m pytest tests/test_streamlit_ui.py -q --basetemp=.pytest-ui-tmp

# Starts real servers, checks HTTP, and drives Streamlit widgets over real HTTP:
.\.venv\Scripts\python.exe tools/run_showcase.py --smoke --api-port 8012 --ui-port 8512

# Full regression suite:
.\.venv\Scripts\python.exe -m pytest --basetemp=.pytest-showcase-tmp --cov=claims_triage --cov-report=term-missing
.\.venv\Scripts\python.exe -m ruff check src ui tests tools
.\.venv\Scripts\python.exe -m mypy src
```

The smoke command stops the services it starts. Use different ports from an active demonstration. Streamlit AppTest drives actual widget logic but does not verify browser pixel layout; the separate HTTP checks prove real network communication. Live Azure remains its own opt-in verification, not implied by a passing mock showcase.

## UI extension requirements

| ID | Requested capability | Implementation | Verification |
|---|---|---|---|
| U01 | Streamlit frontend | `ui/app.py`, theme and launcher | Streamlit AppTest and service startup |
| U02 | Frontend uses backend end to end | `ShowcaseClient` calls authenticated HTTP API | Real HTTP smoke and UI/API integration tests |
| U03 | Requirements dashboard | 35 original groups, evidence, observed filter and live-check distinction | Dashboard count/filter/non-Azure-claim tests |
| U04 | Showcase inputs and edge cases | JSON/CSV uploads and four prepared scenarios | Upload, malformed-input and scenario tests |
| U05 | Show memory, citations, routine and review | Claim workbench, conversation, audit export and resume | UI workflow, unsafe approval and restart/resume tests |
| U06 | Step-by-step demonstration guide | This document plus downloadable in-app guides | Paths and documented commands checked |

## Troubleshooting

- **Run triage disabled:** create/resume a session, supply a file/scenario and confirm synthetic input.
- **401 unauthorized:** API and UI must use the same token. The launcher handles this. For separate terminals, explicitly set the same `TRIAGE_API_TOKEN` in both.
- **Backend unavailable:** ensure the launcher is still running; read its port-specific logs.
- **Port unavailable:** use another pair of ports rather than killing unrelated processes.
- **Request timeout:** processing may still finish. Click **Refresh batches** and inspect saved results before resubmitting.
- **Unexpected duplicates:** use a new session for independent fixture demonstrations.
- **Wrong batch visible:** select the intended saved batch in the sidebar; IDs and states are shown.
- **Agent service issues in Azure mode:** inspect the issue codes and project configuration. Do not report the degraded result as successful live inference.
- **Fresh browser has no session:** use the saved session ID to resume. The browser is not the durable database.
