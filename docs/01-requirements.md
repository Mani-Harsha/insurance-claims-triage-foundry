# 1. Requirement analysis and pre-implementation checklist

Source: `projectdetails.txt`, read in full before implementation. The supplied Word file is an alternate attachment; the explicitly identified text file is the authoritative specification. All fixtures and outputs describe synthetic claims only.

## Scope and assumptions

The deliverable is a Python application with a CLI and authenticated HTTP API. No graphical UI, database engine, HTTP routes, currency, authentication scheme, or cloud subscription was specified. A CLI, OpenAPI explorer, SQLite, a single-tenant API token, and a configurable Foundry Agent Service adapter are documented implementation choices. No real-world claim settlement or payment is performed. “Auto approve” is a recommendation that still requires an adjuster's recorded decision.

Use the explicitly allowed offline LLM mock by default because no Foundry endpoint/model/credentials were supplied. Keep the real `azure-ai-agents` SDK integration executable and test its contracts separately. Cloud creation and live inference require the user's Azure configuration. The local database supports a single deployment on a persistent local disk; multi-replica deployment requires a shared database and distributed concurrency control.

Required fields are all seven fields in the sample. Claim IDs use `C-<digits>` and policy numbers use `POL-<digits>`; `C2031` in conversation normalizes to `C-2031`. Amounts are positive decimal currency values with at most two fractional digits, with a documented upper bound. Dates are ISO calendar dates; loss cannot exceed report date; future dates are invalid. Policy periods and the 7-day/2% thresholds are inclusive. Coverage categories, thresholds, and historical review patterns live in retrieved knowledge records, not model instructions. Repeat history is limited to earlier events, never future events or the same claim. Duplicate IDs in one batch invalidate every occurrence; previously processed IDs in a session are flagged. Independent sessions may triage the same synthetic fixture for demonstrations.

## Traceability matrix / implementation plan

Every row was inventoried and mapped before source code generation. Status and executed evidence are recorded in `11-coverage.md`; this file preserves the original plan.

| ID | Source requirement / acceptance criterion | Type | Implementation task | Verification plan |
|---|---|---|---|---|
| R01 | Property/auto claims batch from JSON or CSV | Functional | Input parser; property and auto fixtures; CLI/API | JSON/CSV ingestion and auto coverage tests |
| R02 | Synthetic data only; never imply real policyholders | Business | Synthetic declaration, fixtures, prompts, output label | Reject absent/false declaration; inspect fixtures |
| R03 | Intake specialist validates required fields | Functional/validation | Intake tool with row-level issues | Every missing field; mixed valid/invalid batch |
| R04 | Inconsistent dates flagged | Validation | Strict ISO parsing and chronological checks | Invalid, future, reversed dates |
| R05 | Invalid policy numbers flagged | Validation | Syntax and policy catalog existence checks | Malformed/unknown policy |
| R06 | Duplicate claim IDs flagged | Validation | Batch counts and persisted session lookup | Same-batch and cross-batch duplicate tests |
| R07 | Intake validation exposed as a tool | Integration | `validate_claim` JSON schema and dispatch | Registration and argument validation tests |
| R08 | Coverage specialist confirms claim type | Business | Retrieved coverage mapping and policy lookup | Covered, excluded, unknown claim types |
| R09 | Coverage specialist checks policy limit | Business | Exact decimal comparison | Below/equal/above limit |
| R10 | Coverage specialist checks active policy dates | Business | Inclusive active period | Both boundaries and outside period |
| R11 | Knowledge grounding via retrieval | Integration | Local file vector retrieval and Azure file search | Retrieved citations; missing/corrupt knowledge fails safely |
| R12 | 5–10 underwriting/fraud rules in markdown/JSON | Data | Eight structured, cited knowledge rules plus markdown | Rule catalog validation; threshold behavior |
| R13 | Policy-inception and near-limit patterns | Business | Retrieved thresholds and deterministic evaluator | 7/8 days, 98%/97.99%, above-limit cases |
| R14 | Briefing specialist creates natural-language summary and next action | Functional | Briefing tool, three constrained recommendations | All three outcomes; evidence present |
| R15 | Briefing references earlier session/persisted history | Functional | Policy history and seeded six-month synthetic event | Prior event included; future/self excluded |
| R16 | Supervisor routes triage and explanation requests | Functional | Explicit intent router; follow-up claim context | Triage, why C2031, pronoun follow-up, unsupported intent |
| R17 | Explicit intake → validate → coverage/anomalies → briefing routine | Functional | Named states and durable audit events | Exact sequence and failure-state tests |
| R18 | Defined checkpoints/HITL gates | Business | Validation checkpoint, pending human review, authenticated decisions | Cannot finalize without decision; invalid approvals blocked |
| R19 | Multiturn conversation preserves context | Functional | Session messages, last-claim pointer, Azure thread IDs | Same-session follow-up; session isolation |
| R20 | Azure Foundry project + Agent Service Python SDK | Platform | Real `AgentsClient`, Entra credentials, setup CLI | SDK import/signatures; mocked protocol; opt-in live smoke |
| R21 | At least four programmatically created agents | Integration | Supervisor/intake/coverage/briefing definitions and provisioning | Four creations, instructions, ownership, restart reuse |
| R22 | At least three function tools with JSON schemas assigned correctly | Integration | Router, validation, coverage, briefing and retrieval tools | Strict schemas; role allowlist; bad arguments |
| R23 | Short-term conversation and long-term cross-run memory | Data | Messages/threads plus durable SQLite history | Reopen DB; new-session history; thread reuse |
| R24 | Graceful malformed input/tool failure/timeout handling | Nonfunctional | Typed application errors, bounded runs, fallback evidence | Malformed files, failed tool, terminal run, timeout |
| R25 | Log agent decisions and tool calls | Observability | Structured redacted logs and per-batch event trail | Correlation IDs; no raw claim/token logs |
| R26 | Include supplied starter claims and coverage records | Data | Exact starter fields; additive auto example and memory | Fixture regression outcomes |
| R27 | Mock allowed for quota/access issues; explain mock and why | Documentation | Explicit mock/azure modes; no silent mode switch | README; offline runs; Azure failure disclosure |
| R28 | VS Code preferred; screen-share walkthrough | Workflow | Launch/tasks settings and timed demonstration guide | Walkthrough commands run locally |
| R29 | Detailed requirements, traceability, mapped implementation tasks before code | Deliverable | This analysis and coverage matrix | Source-to-deliverable review |
| R30 | Architecture, components, folders, DB, APIs, security, errors, logging | Deliverable | Design documents and schema | Design-to-source review |
| R31 | Complete clean/SOLID reusable implementation with validation/errors/edge cases | Quality | Domain/application/adapter separation and dependency injection | Unit/integration tests, lint/type checks |
| R32 | Unit/integration/positive/negative tests and scenarios | Quality | pytest suites and scenario catalog | Executed report with limitations |
| R33 | README/setup/run/deployment/API/architecture/assumptions | Deliverable | README and linked numbered documents | Run documented local commands |
| R34 | Project overview/decisions/tradeoffs/challenges/code walkthrough/FAQ | Deliverable | Project walkthrough and demo guide | Document review |
| R35 | Final full source re-scan and coverage/missing-item remediation | Quality | Final audit and explicit residual verification limits | `11-coverage.md` |

## Additional interface, database, and operational contracts

These are chosen designs, not hidden source requirements: bounded batch/file sizes; strict tool arguments; generated opaque session/batch identifiers; transactional batch persistence; stable row indexes for duplicate IDs; immutable evidence with an append-only human review record; parameterized SQL; no arbitrary tool execution; single-tenant authentication on all data endpoints; liveness endpoint without data; OpenAPI docs; deterministic recommendations authoritative over LLM prose; errors and incomplete agent runs never produce automatic approval recommendations; no cloud deployment claimed without a live smoke test.

Pre-code checkpoint: all source paragraphs, technical table rows, sample records, and closing notes are mapped above. No source requirement was intentionally omitted. Implementation may start.
