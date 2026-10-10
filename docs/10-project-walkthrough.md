# 10. Project walkthrough and design FAQ

This guide covers the project architecture, design tradeoffs, code-reading order and a reproducible demonstration. The [implementation guide](12-implementation-guide.md) provides additional technical detail; the [requirement coverage checklist](11-coverage.md) maps behavior to verification evidence.

The later Streamlit addition has a [step-by-step UI showcase guide](13-streamlit-showcase.md). You can now demonstrate uploads, review, conversation, retrieved evidence and the requirements dashboard through that frontend; the CLI walkthrough below remains useful for explaining the underlying code.

## A concise project overview

"This is a synthetic insurance claims triage assistant with four roles: a supervisor, intake validator, coverage/anomaly specialist, and adjuster briefing specialist. The supervisor follows a visible sequence instead of asking a model to invent a workflow. Each specialist calls a constrained tool. Coverage decisions use retrieved underwriting rules, and briefings use earlier persisted claim history. Every output is a recommendation awaiting an adjuster's decision. The same application runs offline through a deterministic mock or through Azure AI Foundry Agent Service."

The business benefit is consistent preparation of an adjuster's review: missing information, coverage problems, review indicators, explanations, and earlier context are presented together. A review indicator is not a fraud accusation. The application does not pay claims or represent synthetic policies as real customers.

## Architecture explanation

```text
CLI / authenticated HTTP
          |
          v
Supervisor application service
          |
          +--> intake --> validate --> validation checkpoint
          |                                  |
          |                                  v
          +-------------------- coverage/anomalies --> briefing
                                                       |
                                                       v
                                               pending human review

Tools --> pure domain rules <-- retrieved, versioned knowledge
   |                              |
   +--> SQLite session/history    +--> local retrieval / Azure file search

Agent runtime boundary --> deterministic mock OR Azure Agent Service
```

The application owns ordering and transitions. The runtime owns model interaction and remote thread/run handling. Domain functions own input validity, coverage checks and recommendation precedence. Persistence owns sessions, durable evidence and atomic review recording. This separation lets tests replace the runtime without replacing the business behavior being tested.

Explain the distinction between *routing* and *authority*: the supervisor identifies the requested task and dispatches specialists, but neither free text nor a remote tool-call argument can grant approval authority. The application validates role, schema and execution context before running a tool. Human review has its own interface and persistence operation.

## Design decisions and tradeoffs

| Decision | Why it was chosen | Cost or limitation |
|---|---|---|
| Explicit routine over unrestricted agent planning | Predictable order, checkpoints and an inspectable audit trail | Adding a new workflow requires code and tests |
| Four specialist roles behind one runtime port | Clear responsibilities; tools can be restricted per role | Extra Azure calls and thread management compared with a single agent |
| Exact decimal monetary comparisons | Correct cent-level comparisons and threshold boundaries | Values must be validated and serialized deliberately |
| Rules retrieved from versioned knowledge files | Evidence can cite the actual rule text; thresholds are inspectable data | Knowledge updates need validation and regression tests |
| Deterministic findings govern recommendations | Model prose cannot override invalid inputs or safety gates | This does not demonstrate an autonomous underwriting model |
| SQLite for session, history and evidence | Simple reproducible local deployment; durable transactions and persisted session leases | Single-host/local-disk operating scope; no distributed database |
| Session conversation plus cross-session history | Separates conversational context from durable prior-loss evidence | Requires clear scope, ordering and exclusion rules |
| Pending human review for all outcomes | Makes responsibility and review status explicit | `auto_approve` is a proposed action rather than automatic settlement |
| Optional Azure adapter; offline default | Runs without credentials while retaining real SDK integration | Mock output cannot establish live model quality or cloud readiness |
| Single-tenant bearer authentication | Small, testable protected API appropriate to this synthetic exercise | Enterprise user identity, role mapping and tenant isolation require further work |

## Important code walkthrough

Use the actual repository files in this order; locate the named symbols with VS Code's workspace search if a module has moved.

1. Open `projectdetails.txt`, then `docs/01-requirements.md`. Explain how source requirements became acceptance criteria before implementation.
2. Open `src/claims_triage/domain.py`. Walk through `validate_claim`, `money`, `check_coverage`, `build_brief`, and `route_request`. Explain why `Decimal` is used, how multiple row issues accumulate, and why future/self history is excluded.
3. Open `knowledge/rules.json` and `knowledge/underwriting_rules.md`. Pick inception and near-limit rules. Trace retrieval into the coverage check and then into output citations. Do not describe placing all rules in a model instruction as retrieval.
4. Find the application routine. Show named states, explicit validation checkpoint, specialist execution, degraded-service handling, persisted events, and pending human review. Show the exact code that prevents unsafe approval.
5. Find tool schemas and dispatch. Demonstrate one JSON schema, the owning role and context validation before execution. Explain that a well-formed schema alone cannot authorize access to a different claim.
6. Open the Azure adapter. Show four programmatic creations, tool registration, hosted file-search resources, per-role threads, tool-output submission, bounded polling and timeout cleanup. Identify what is mocked in tests.
7. Open `src/claims_triage/repository.py` and `docs/03-database.md`. Explain the batch transaction, history lookup and single-review constraint. Show lease-token and expiry checks at renewal and commit: a worker that loses ownership cannot commit a batch. Show that an earlier conversation is persisted rather than kept only in a Python list.
8. Open tests for a rule boundary, session restart, invalid approval and failed runtime. Explain the behavioral oracle before reading the assertion.

## Challenges solved

**Useful invalid-row processing.** A well-formed batch may contain invalid claims. Intake records field issues without pretending the row is eligible for coverage evaluation. The batch can still produce an adjuster-facing documentation recommendation for that row.

**Avoiding incorrect historical evidence.** The same synthetic policy may have several claims, some submitted out of chronological order. History must use loss dates, exclude the current claim and future events, and match policy/peril before it can support a repeat-loss finding.

**Maintaining consistent outcomes during agent failure.** Tool errors, failed runs and timeouts are explicit service issues. Deterministic findings remain inspectable, but incomplete agent execution cannot produce an automatic approval recommendation. Azure mode does not silently become mock mode.

**Combining grounding with reliable controls.** Retrieval returns the applicable evidence with rule identities and a version. Generic code evaluates the retrieved parameters. This preserves auditable business logic while keeping underwriting thresholds outside prompt instructions.

**Preserving evidence through review.** The initial findings remain available after an adjuster records a decision. Review is an additional record, not an edit that erases why the recommendation was produced.

## Ten-minute VS Code demonstration

Before running the demo, install the project and development extras using the README, select the virtual environment as the Python interpreter, and run the local checks. Start in mock mode unless a live Azure project is intentionally configured. Use only the checked-in synthetic fixtures. The VS Code tasks include initialization, triage and test commands; the debugger launches the module directly.

| Time | Screen/action | Explanation |
|---|---|---|
| 0:00-1:00 | Requirement matrix and architecture | Four roles, explicit routine, retrieval, two forms of memory, human gate |
| 1:00-2:30 | Initialize and triage starter fixture | Mixed outcomes and synthetic labeling |
| 2:30-4:00 | Explain C-2031 and contextual follow-up | Short-term context, prior-loss evidence and citations |
| 4:00-5:00 | Restart command and explain again | Durable session/history rather than process-local memory |
| 5:00-6:00 | Domain checks and knowledge files | Exact boundaries and data-driven rules |
| 6:00-7:00 | Supervisor and tool schemas | Inspectable order, role restrictions and human review gate |
| 7:00-8:00 | Azure adapter | Programmatic agents, file search, per-role threads and run handling |
| 8:00-9:00 | Selected tests and audit output | Positive/negative boundaries and service-failure handling |
| 9:00-10:00 | Limitations and next steps | Single-instance scope, cloud evidence, identity and operational work |

Example PowerShell sequence from the repository root:

```powershell
python -m claims_triage init
python -m claims_triage triage data/claims.json --synthetic
# Copy the actual returned session identifier into this variable.
$demoSession = 'SESSION_FROM_TRIAGE_OUTPUT'
python -m claims_triage chat $demoSession 'Why was claim C2031 flagged?'
python -m claims_triage chat $demoSession 'Explain its recommendation'
# Each command starts a separate process: persisted context is reused.
python -m claims_triage chat $demoSession 'Why was it flagged?'
python -m pytest -q --basetemp=.pytest-local-tmp
```

Use the batch identifier and row index returned by triage for the `review` command; consult `python -m claims_triage review --help` for the accepted decision values. Review a clean row, then repeat to demonstrate conflict handling. Avoid repeatedly triaging the same fixture in the same session unless intentionally demonstrating duplicate detection. Do not screen-share `.env` contents, credential caches or bearer tokens.

## Design FAQ

**Why four agents rather than one?** The requirement calls for a supervisor plus three specialists. Their tools and responsibilities differ, so separation also makes role restrictions and failure attribution explicit. A single deterministic service would be simpler if multiagent behavior were not a requirement.

**What makes this a multiagent implementation rather than four prompts?** There are four programmatic Agent Service definitions with role instructions and registered tools. The application dispatches them through an explicit routine and maintains role-specific conversation threads. In mock mode the same roles/tools execute locally without model calls.

**Where does the LLM add value?** The Azure adapter supports model-driven function calls and collects supplemental explanatory language. The application currently returns the deterministic tool result; it does not display the adapter's supplemental `narrative` as the final brief. In mock mode no LLM is called. This demonstrates constrained agent integration, but does not establish that an LLM improves decision accuracy or user-facing explanation quality. Surfacing validated model prose would be a separate enhancement.

**How do you prove grounding?** Inspect the retrieval result and stored citations: source, rule ID, text and version accompany the coverage findings. Inspect Azure provisioning for the file-search resource. A model claiming it used a document is not sufficient proof.

**How are conversation memory and long-term memory different?** Conversation memory is ordered messages plus last-claim context and remote thread references within a session. Long-term memory is durable prior-claim history used after process restarts and across sessions when policy/peril/date filters permit it.

**Why does C-2032 not use C-1900 as an earlier claim?** C-2032 has a 2026-02-10 loss date; C-1900 is dated 2026-02-15. The seed exists in storage but happened later, so using it as earlier-loss evidence would be incorrect.

**Does an anomaly mean fraud?** No. It is a review indicator. The application routes the evidence to an investigator and does not accuse a synthetic policyholder of wrongdoing.

**What happens at exactly the policy limit?** The amount is within coverage, but it triggers the retrieved near-limit review pattern. Coverage validity and review risk are separate dimensions.

**Why is an auto-approval still pending?** The requirement asks for a recommended next action suitable for adjuster review and explicit human gates. The software records a recommendation; an authorized reviewer records the decision separately.

**How do you address prompt injection?** Treat descriptions, documents and model arguments as untrusted. Tools are schema validated, allowlisted by role and bound to the current request context. Models cannot invoke a settlement or approval tool. Authentication and deterministic checks sit outside model reasoning.

**What if Azure times out midway?** Polling is bounded, cancellation is attempted, the failure is audited, and the affected evidence is marked incomplete. The recommendation requires documentation/human review; the runtime does not quietly switch to a mock and report cloud success.

**What are the most valuable tests?** Threshold boundaries, invalid-row behavior, duplicate handling, exclusion of future history, cross-process persistence, session isolation, tool authorization, review conflicts and service failures. Those catch behaviors a happy-path screenshot cannot establish.

**Can this run with many replicas?** The delivered SQLite and persisted session-lease design is scoped to a single host using a local disk. Multiple replicas need shared transactional storage and distributed concurrency control, plus appropriate queueing/idempotency and identity design.

**What would you change before processing real claims?** Establish a separately authorized product scope, tenant/user identity, actual policy integrations, retention/privacy controls, governed rule updates, load/recovery tests, and independent security/model evaluations. This repository intentionally uses synthetic data; a declaration is not a PII detector.

**How do you report what you verified?** Separate local unit/integration results, fake SDK contract checks and actual cloud smoke results. Name the exact commands and outcomes recorded in the coverage document, and clearly say when Azure execution has not been performed.
