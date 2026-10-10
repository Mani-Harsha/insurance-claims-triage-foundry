# 7. Test cases and verification scenarios

This catalog maps acceptance scenarios to the requirement IDs in [01-requirements.md](01-requirements.md). It describes expected behavior, not an assertion that every scenario has been executed. The final executed checks and remaining verification limits belong in [11-coverage.md](11-coverage.md). All input is synthetic.

## Test layers

Unit tests exercise domain rules with a fixed reference date and exact decimal amounts. Integration tests connect the application service to a temporary SQLite database, real local retrieval, the mock runtime, and the HTTP test client. SDK contract tests use a fake Azure client to inspect provisioning and run handling without allocating Azure resources. A live smoke test requires an explicitly configured project, deployment, and credentials and must be reported separately from mock tests.

Run the checked-in suite from the repository root after installing the development extras:

```powershell
python -m pytest -q --basetemp=.pytest-local-tmp
python -m pytest --basetemp=.pytest-local-tmp --cov=claims_triage --cov-report=term-missing
python -m ruff check src tests
python -m mypy src/claims_triage
```

Do not interpret line coverage as proof of correct thresholds, adequate security, or cloud compatibility. The boundary cases below are the acceptance oracle.

## Positive and negative acceptance cases

| Case | Requirements | Setup/input | Expected result |
|---|---|---|---|
| T01 | R01, R26 | Read starter JSON with an explicit synthetic declaration | Four rows preserved in their original order; results identify each row |
| T02 | R01, R08 | Read the auto CSV fixture | CSV values normalize into domain input; auto covered perils are retrieved from knowledge |
| T03 | R02 | Missing or false synthetic declaration | Request rejected before triage; no successful batch persisted |
| T04 | R03 | Remove each of the seven required fields in turn; repeat with null/blank text | Field-specific missing-required issue; recommendation requests documentation |
| T05 | R04 | Invalid calendar date, non-ISO date, future date, loss after report | Validation issue; coverage checks do not treat invalid input as a valid claim |
| T06 | R05 | Malformed policy identifier and validly formed absent policy | Distinct identifier/catalog issues; no invented coverage |
| T07 | R06 | Same claim ID occurs twice in one batch | Both occurrences flagged, with distinct stable row indexes |
| T08 | R06, R23 | Submit a previously processed ID in the same session after reopening the database | Duplicate flagged; no silent overwrite of prior evidence |
| T09 | R03, R31 | Amount is zero, negative, boolean, NaN/infinity, over the configured bound, or has a nonzero third decimal digit | Invalid amount issue, never an approval recommendation |
| T10 | R03, R31 | Valid integer/string decimal amount and maximum allowed two-decimal value | Exact normalized decimal representation, without binary floating-point threshold drift |
| T11 | R08 | Covered homeowners/auto peril; unsupported peril; valid peril on wrong coverage category | Only the applicable retrieved coverage mapping passes |
| T12 | R09, R13 | Amount below, equal to, and one cent above policy limit | Equal is covered but near-limit flagged; above fails coverage |
| T13 | R10 | Loss on active-from, on active-to, one day before/after | Endpoints covered; outside dates fail coverage |
| T14 | R13 | Report at inception +7 days and +8 days, with no other indicators | Day 7 flagged; day 8 does not trigger inception rule |
| T15 | R13 | Amount exactly 98% of limit and one cent below threshold | Exact threshold flagged; lower amount does not trigger near-limit rule |
| T16 | R11, R12 | Retrieve rules for a coverage check | Evidence includes rule identifiers, source, text, and version; rules originate in retrieval files |
| T17 | R11, R24 | Missing, malformed, incomplete, or inconsistent knowledge/configuration | Initialization fails clearly; no default assumption that a claim is covered |
| T18 | R14, R18 | Clean valid covered claim outside anomaly thresholds | Natural-language brief with `auto_approve` recommendation and pending human review |
| T19 | R14, R18 | Valid claim with coverage/anomaly findings | Investigator recommendation; human review remains pending |
| T20 | R14, R18 | Invalid intake, incomplete agent service, or reporting delay >30 days | Documentation recommendation; no approval |
| T21 | R15, R23 | Seed C-1900 on POL-5521, then triage C-2031 | Earlier synthetic water-damage history referenced and repeat review indicator produced |
| T22 | R15 | History contains same claim, a future loss, another policy, and another peril | Those records cannot create a similar-earlier-loss finding |
| T23 | R15 | Similar flagged loss 365 versus 366 days earlier | Inclusive 365-day review window; older event does not trigger repeat rule |
| T24 | R16, R19 | Ask why C2031 was flagged, then ask why it was flagged again | Identifier normalized to C-2031; follow-up uses the session's last claim context |
| T25 | R16 | Ask to triage a batch without attaching/providing rows; unsupported request | Helpful route-specific response; no invented batch or claim |
| T26 | R19, R23 | Restart application, reopen same session, then open a new session | Conversation persists for original session; new session has separate conversation but eligible long-term history |
| T27 | R17, R25 | Run full mixed batch | Audit trail records intake, validation, validation checkpoint, coverage/anomalies, briefing, pending human review in explicit order |
| T28 | R18 | Review clean row once; review it again | One recorded decision only; duplicate review rejected |
| T29 | R18 | Attempt approval on invalid or flagged evidence | Unsafe approval rejected; model text cannot bypass the human gate |
| T30 | R20, R21 | Provision with a fake SDK client; provision again using stored manifest | Four distinct role agents created with instructions; successful manifest reused |
| T31 | R22 | Inspect tool registration and invoke with extra fields, wrong type, wrong role, or mismatched row | Schemas and role/context allowlists reject invalid execution |
| T32 | R11, R20 | Inspect coverage-agent provisioning | Hosted file-search tool has the uploaded underwriting knowledge/vector-store resource |
| T33 | R24 | Malformed JSON, wrong envelope, unsupported extension, empty/oversized input, inconsistent CSV | Stable application error; no misleading successful result |
| T34 | R24, R27 | Tool failure, terminal failed run, timeout, excessive tool loop | Bounded execution, explicit service issue, documentation recommendation; no silent Azure-to-mock switch |
| T35 | R25 | Observe logs for successful and failed processing | Correlation/role/tool/status available; secrets and raw descriptions absent |
| T36 | R30, R31 | Missing, malformed, or incorrect HTTP bearer token | Data endpoint denies access; liveness exposes no claim data |
| T37 | R30, R31 | Valid token with malformed body, unknown session/batch/row, invalid review decision | Stable appropriate error response; no traceback or database internals |
| T38 | R23, R31 | Reopen SQLite after committed batch; simulate failure before batch commit | Complete committed evidence survives; transaction failure leaves no partial successful batch |
| T39 | R19, R31 | Interleave requests for one session and for separate sessions | Per-session operations do not corrupt last-claim context; one session cannot explain another's unshared batch |
| T40 | R28, R33 | Follow README in fresh virtual environment, then use VS Code task/launch | Documented module commands, fixture paths, and debugger entry resolve |

## Starter fixture oracle

Use a reference date on or after 2026-08-30 and the supplied memory seed. Tests should inject their date rather than depend on the workstation clock.

| Claim | Expected principal evidence | Recommendation |
|---|---|---|
| C-2031 | Valid covered water damage; earlier flagged C-1900 loss on 2026-02-15 | `route_to_investigator` |
| C-2032 | Valid covered loss on 2026-02-10; C-1900 happened later and must not count as earlier memory | `auto_approve`, pending human review |
| C-2033 | Theft covered; report three days after inception; amount equals policy limit | `route_to_investigator` |
| C-2034 | Missing loss date and nonpositive amount | `request_more_documentation`; do not infer an actual loss date to establish coverage |

## Manual walkthrough and cloud checks

1. Use a fresh synthetic demo session, run the starter batch, and retain its session/batch identifiers.
2. Explain C-2031, then use a contextual follow-up; inspect messages and cited rule evidence.
3. Stop the process, start a new process, and explain the same result to demonstrate persistence.
4. Record an authorized clean-row review; repeat the review to demonstrate the conflict response.
5. Run a deliberately invalid row and show that its outcome stays pending documentation review.
6. If Azure is configured, provision the agents and run an equivalent batch in Azure mode. Inspect the actual four agent IDs, hosted retrieval configuration, per-role thread reuse, function execution and final run status. Record endpoint region/model version and observed errors separately from local results.

Cloud testing may incur charges and depends on external access/quota. A fake SDK test demonstrates application behavior against the expected interface; it does not demonstrate a reachable deployed service, adequate quota, Azure RBAC correctness, or model quality. Load testing, recovery drills, penetration testing, and multi-replica behavior require a separately scoped operational environment.
