# Complete implementation study guide and additional interview answers

Read this for a detailed understanding of the implemented project, then rehearse the [short presentation and screen-share guide](10-interview.md). The [requirement analysis](01-requirements.md) and [coverage checklist](11-coverage.md) provide the formal source-to-code-to-test mapping. Sample answers describe the checked-in implementation; adapt them to your own understanding and experience rather than claiming something you cannot demonstrate.

**Later addition:** a Streamlit frontend and requirements dashboard were added at the user's request. Follow the [UI showcase guide](13-streamlit-showcase.md). The original assignment did not demand a graphical frontend, but one is now available and calls the same authenticated backend.

## 1. Your project introduction

### Thirty-second answer

> This is a synthetic insurance claims triage backend with a supervisor and three specialists: intake validation, coverage and anomaly checks, and adjuster briefing. The supervisor follows a fixed, auditable workflow. Coverage uses retrieved underwriting rules, and briefings reference persisted earlier claims. A human records the final decision. The local workflow is tested; the real Azure Agent Service adapter is included, but live Azure execution still needs verification.

### Two-minute answer

> The input is a JSON or CSV batch of synthetic property or auto claims. First, the intake specialist checks required fields, dates, amounts, policy numbers and duplicate claim IDs. Invalid rows remain visible with documentation requests rather than disappearing from the batch.
>
> Valid claims proceed to coverage and anomaly checks. The application loads the matching synthetic policy and retrieves underwriting rules. It checks covered perils, policy limits and active dates, then applies review patterns such as reporting shortly after inception, near-limit amounts and similar earlier flagged losses. Coverage results include rule citations and a knowledge version.
>
> The briefing specialist produces a natural-language summary and a constrained next action. SQLite stores messages, evidence, history and human decisions. That supports both conversational follow-ups and historical context across separate runs.
>
> The host application owns the sequence and authorization checks. The Azure adapter creates four agents and registers their tools in code. Local mode mocks only the LLM/service transport while actual validation, retrieval, persistence and API operations run. The last recorded verification was 223 passing tests with 96.02 percent statement coverage; the live Azure test was skipped. I can demonstrate the local system and explain the Azure integration without claiming a deployed cloud system.

## 2. Requirements translated into implementation

The R numbers below refer to the complete 35-group matrix. This table groups them for a spoken explanation.

| Requirement | What we implemented | How to explain it | Where to show it |
|---|---|---|---|
| Synthetic JSON/CSV property/auto input, R01–R02/R26 | Starter JSON/CSV, additive auto records, explicit synthetic declaration | “Both formats reach the same workflow; no actual policyholder data is used.” | `data/`, `ingestion.py`, upload tests |
| Intake validation, R03–R07 | Required fields, strict dates, policy syntax/existence, duplicates, amount checks; validation tool | “A valid batch envelope can contain invalid rows. Each row retains its issues.” | `domain.validate_claim`, `tools.py` |
| Coverage, R08–R10 | Covered peril, per-claim limit, inclusive active period | “A claim can be covered but still have review indicators.” | `domain.check_coverage`, UW01–UW03 |
| Grounded knowledge, R11–R13 | Eight retrieved rule records, TF-IDF vectors, source/version citations; Azure file-search registration | “Thresholds come from retrieved data, not copied prompt text.” | `knowledge.py`, `knowledge/`, SDK tests |
| Adjuster briefing, R14–R15 | Natural-language tool summary, three possible recommendations, earlier-loss references | “The brief combines intake, coverage and eligible history without inventing missing facts.” | `domain.build_brief`, C-2031 output |
| Supervisor/routine, R16–R18 | Routing, six stages, validation checkpoint, human decision gate | “The host enforces order. The model cannot skip validation or approve a claim.” | `service.py`, `ROUTINE`, review tests |
| Memory, R19/R23 | Messages, last-claim pointer, history table, role-specific Azure thread IDs | “Session context resolves follow-ups; durable history supplies prior facts.” | `repository.py`, restart/CLI tests |
| Azure agents/tools, R20–R22 | Pinned SDK adapter, four agent definitions, five custom function contracts | “Instructions and registrations are in code, not just configured in the portal.” | `azure_runtime.provision`, `tools.definitions` |
| Failures/observability, R24–R25/R27 | Bounded runs, cancellation attempts, degraded outcomes, structured logs, explicit mock mode | “An outage remains visible and closes the auto-approval recommendation path.” | Failure/timeout tests, console logs |
| Documentation and quality, R28–R35 | VS Code tasks, CLI/API, architecture/schema/docs, tests and interview material | “Every requirement maps to implementation and verification evidence.” | README, docs 01–11, `verification.json` |

The source does **not** explicitly require a graphical frontend, payment processing, a particular SQL engine, or a specific Azure model deployment. CLI/API access, SQLite, identifier formats, batch limits and single-tenant bearer authentication are documented design choices. The requirement asks for human checkpoints; the exact restriction on approving a flagged row is our implementation choice.

## 3. Explain the complete workflow

```text
JSON/CSV or HTTP request
  -> bounded decoding and synthetic declaration
  -> session lease and Supervisor route_request
  -> INTAKE: identify batch and duplicates
  -> VALIDATE: Intake validate_claim for every row
  -> VALIDATION_CHECKPOINT: invalid rows cannot enter coverage
  -> COVERAGE_AND_ANOMALIES: valid rows in loss-date order
       policy lookup + retrieved rules + eligible earlier history
  -> BRIEF: build_brief for every row, including invalid rows
  -> HUMAN_REVIEW_PENDING: commit evidence, events and history
  -> adjuster records approve / investigate / request_documentation
  -> REVIEWED after every row has a decision
```

These are application stages, not six agents. Transport decoding happens before `INTAKE`; specialist validation occurs in `VALIDATE`. `FAILED` is the failure state and `HUMAN_DECISION` is a review audit event.

Coverage processes valid claims by loss date so later losses can reference eligible earlier findings. The response preserves original input order and `row_index`, giving every result an unambiguous review target even if IDs are duplicated.

### Explain the sample results

| Claim | Reasoning | Recommendation |
|---|---|---|
| C-2031 | Water damage is covered; 8,500 is below 50,000; loss is in the active period. Earlier synthetic C-1900 on 2026-02-15 is a flagged water-damage event within the repeat window. | Route to investigator |
| C-2032 | Covered loss on 2026-02-10. C-1900 occurred on 2026-02-15, so it cannot count as an earlier loss. | Auto approve, pending human review |
| C-2033 | Theft is covered; amount equals the limit. Report is three days after inception and amount triggers the near-limit pattern. Equality passes coverage but warrants review. | Route to investigator |
| C-2034 | Loss date is absent and amount is zero. Coverage is skipped; the system must not invent a loss date even though the policy is expired. | Request more documentation |

All recommendations await a human decision. Approval records a review; it does not transfer money or settle a real claim. Original evidence remains intact after review.

## 4. RAG and grounding: the precise explanation

RAG combines retrieval of external evidence with generation. The tested offline path here is **retrieval-grounded deterministic reasoning and template-based briefing**. It does not call a generative model. The Azure adapter supports LLM tool calls and supplemental prose, but the application currently returns the tool-derived brief rather than that supplemental prose.

### Local retrieval, step by step

1. Load eight structured rules from `knowledge/rules.json` and read the markdown companion.
2. Validate rule kinds, fields, thresholds and corresponding markdown rule IDs. This does not prove complete semantic equivalence between the markdown and JSON.
3. Compute a SHA-256 knowledge version from both files.
4. Tokenize rule kind, title and text, then build normalized sparse TF-IDF vectors in memory.
5. Vectorize a query describing claim type, coverage category and rule topics. Rank records by cosine similarity.
6. Retrieve **all eight** rules for coverage evaluation, so similarity ranking cannot omit a mandatory policy check.
7. Apply deterministic evaluators and retain rule ID, title, text, source and version in coverage evidence.

The local vector index rebuilds at startup. Files persist knowledge; SQLite persists claim memory. No neural embedding deployment or hosted Azure AI Search index is used locally. Vector search does not necessarily mean dense neural embeddings.

Rule operators and recommendation precedence remain code. Thresholds and peril mappings are retrieved parameters. An arbitrary new rule kind requires code, catalog validation and tests; writing another markdown sentence does not make it executable business logic.

### Azure retrieval configuration

Provisioning uploads the underwriting markdown, creates a hosted vector store and attaches `FileSearchTool` to the Coverage agent. That role also owns `check_coverage` and `search_knowledge`. The required `check_coverage` call itself performs local retrieval and returns grounded evidence.

Registration alone is **not proof that hosted file search executed**. The routine requires a context-bound function call; it does not force a separate hosted search on every run. Configuration is contract-tested, while live hosted search usage and retrieval quality still need service traces and evaluation.

### A defensible spoken answer

> I implemented retrieval over a small versioned underwriting catalog. Locally it uses TF-IDF and cosine similarity, with rule evidence attached to coverage results. I retrieve all eight records to preserve mandatory checks. The Azure adapter also configures hosted file search, but that live path is not verified. The offline summary is deterministic, so I describe it as retrieval-grounded processing rather than claim live LLM generation.

## 5. Code-reading order

| Order | File/symbols | What you should explain |
|---|---|---|
| 1 | `ingestion.py`: `parse_claims`, `validate_batch` | Whole-request rejection versus row validation |
| 2 | `domain.py`: `validate_claim`, `money` | Required fields, dates, duplicates and exact money |
| 3 | `knowledge.py`: `_vector`, `search`, `applicable_rules` | Indexing, ranking, complete rule retrieval and citations |
| 4 | `domain.py`: `check_coverage`, `build_brief` | Coverage, anomaly indicators and action precedence |
| 5 | `service.py`: `_triage`, `_agent`, `chat`, `review` | Ordering, degraded results, conversation and human gate |
| 6 | `tools.py`: `ROLE_TOOLS`, `definitions`, `bound_dispatch` | Schemas, role restrictions and exact context binding |
| 7 | `repository.py`: `session_lock`, `save_batch`, `review` | Transactions, stale workers, persistent memory and double-review prevention |
| 8 | `azure_runtime.py`: `provision`, `invoke` | Actual SDK calls, manifest, threads, runs and timeouts |
| 9 | `ports.py`, `bootstrap.py`, `config.py` | Dependency injection and runtime substitution |
| 10 | `api.py`, `cli.py`, `tests/` | Entry points and evidence of behavior |

## 6. Thirty-six additional interviewer questions and sample answers

These extend the 15 questions in the short guide. First-person wording is practice language; use it only for work and understanding you can substantiate.

### Scope and architecture

**Q01. How did you ensure requirement completeness?**

> I mapped the source into 35 requirement groups before implementation. Each has implementation tasks and verification evidence. I re-read the source after implementation and explicitly separated delivered code from live cloud behavior that has not been verified.

**Q02. Was a frontend required, and what is available now?**

> The original document did not require a graphical dashboard. The initial delivery used CLI/API access, and a Streamlit frontend was subsequently added for showcasing. It uses the same API for uploads, claim review, conversation and persistence, and includes a requirements dashboard. It remains a local single-tenant showcase, not a multi-user production portal.

**Q03. Is the supervisor an autonomous planner?**

> No. The host routes recognized requests through a deterministic tool and runs a fixed sequence. In Azure mode a Supervisor Agent participates through that tool. The model cannot invent or reorder the business workflow.

**Q04. Why not use LangGraph?**

> The flow is small enough to express clearly as named application stages, and no orchestration framework was required. I would reconsider when branching, resumable jobs or workflow complexity justified the dependency.

**Q05. What is the difference between an agent, a tool, a routine and memory?**

> An agent is a role with instructions and permitted tools. A tool is a function with an input contract. A routine defines execution order. Memory stores conversation context or earlier facts. Creating an agent alone does not provide deterministic orchestration or durable memory.

**Q06. Where are clean architecture and SOLID visible?**

> Domain functions do not depend on FastAPI or Azure. Runtime, repository and knowledge protocols let the application depend on abstractions. The composition root supplies adapters, allowing tests to replace service transport while retaining real business logic and storage.

### Retrieval and LLM behavior

**Q07. Where are your embeddings stored?**

> The local representation is sparse TF-IDF, stored in memory and rebuilt from knowledge files. No neural embedding model is called. Azure provisioning creates a separate hosted file-search vector store; I do not equate that configuration with a verified live retrieval result.

**Q08. How do you chunk the documents?**

> Each structured rule is a local retrieval unit. There are only eight short rules, so arbitrary text-size chunking is unnecessary. The Azure path uploads markdown and relies on service ingestion; custom hosted chunking was not implemented or evaluated.

**Q09. Why retrieve all eight rules instead of top three?**

> Similarity ranks relevance but should not exclude a mandatory policy check. Exhaustive retrieval is cheap for eight records. At larger scale I would select mandatory rules through structured applicability and use semantic retrieval for supporting evidence.

**Q10. Is this a rules engine disguised as RAG?**

> Decision logic is deliberately a deterministic rules evaluator. It retrieves external records and cites them, so grounding is real, but I would not claim sophisticated semantic RAG from the local path. The design combines retrieval, auditable evaluation and constrained agent integration.

**Q11. Are all underwriting rules outside code?**

> No. Peril mappings and thresholds are retrieved parameters; rule meanings and recommendation precedence are code. A new operator needs implementation and tests. This is not an engine that safely executes arbitrary natural-language rules.

**Q12. How would you evaluate retrieval quality?**

> Current tests verify citations, completeness and changed behavior when parameters change. For a larger corpus, I would label claim-to-required-rule pairs and measure whether all mandatory rules are retrieved. I would separately evaluate explanation faithfulness. The current coverage percentage is not a retrieval metric.

**Q13. Does a citation prove correctness?**

> No. The correct applicable rule must be retrieved and evaluated correctly, and the source itself must be valid. Citations and versions support auditability; boundary tests and rule governance support correctness.

**Q14. How are knowledge updates handled?**

> Update and review JSON and markdown together, run knowledge and rule tests, and inspect changed outcomes. The version hash and Azure fingerprint change. Current checks validate corresponding IDs, not complete semantic consistency; generating the markdown from structured records would improve that.

**Q15. Is generated model language shown to the user?**

> The adapter collects a supplemental narrative, but the application returns the deterministic `build_brief` result. Displaying model prose with grounding and consistency checks would be an additional feature. I would not describe the current user-facing summary as LLM-generated.

**Q16. If the model is constrained, why use it at all?**

> The assignment requires agent-service integration, and this implements roles, tool calling and threads. The deterministic workflow can operate without an LLM. I have not measured an accuracy advantage from model use; I would expand its role only for a demonstrated need and evaluate it.

### Validation, memory and claim behavior

**Q17. Which errors reject a batch versus flag a row?**

> Malformed files, invalid envelopes and size/count violations reject ingestion. Missing dates or invalid policy fields inside an object are row-level findings. Invalid rows skip coverage and still receive documentation briefs, while valid rows continue.

**Q18. Why validate money beyond checking that it is numeric?**

> Booleans, zero, negatives, non-finite numbers and excess precision are not acceptable amounts. Decimal preserves cent-level comparisons. A documented upper bound is enforced and valid amounts are normalized to decimal strings.

**Q19. How do you handle duplicate IDs?**

> Every same-batch occurrence is flagged. A previously processed ID in the same session is also flagged after restart. Independent sessions can reuse synthetic fixtures. Batch plus row index identifies a result, so duplicate IDs never overwrite each other.

**Q20. Can the chat understand arbitrary language?**

> No. The router supports a limited set of triage and explanation patterns. It normalizes C2031 to C-2031 and uses the last discussed claim for supported follow-ups. Unsupported requests get guidance; this is not a general semantic intent classifier.

**Q21. What exactly is long-term memory?**

> SQLite history stores policy, claim, peril, date, flag, note and source across runs. Similar-loss logic matches policy/peril, excludes the same claim and non-earlier dates, and applies a retrieved lookback window. This is prior-indicator memory, not a paid-claims ledger.

**Q22. Why sort by loss date?**

> Input order may differ from historical order. Chronological evaluation lets earlier eligible findings inform later losses without using future events. Output keeps the original row indexes so review targets remain stable.

**Q23. What if a claim has both anomaly and documentation issues?**

> Implemented precedence prioritizes documentation for invalid intake, agent failures and late reports. Otherwise coverage/anomaly findings route to investigation; clean evidence receives an auto-approve recommendation. This is a documented and tested design choice.

**Q24. Can the adjuster override a flagged claim and approve?**

> Not in this version. Approval requires a stored clean recommendation. A flagged row can be investigated or sent for documentation. Corrected evidence can be submitted in a new session, but a versioned reopen/override process with higher authorization is not implemented.

### Security, persistence and errors

**Q25. What prevents a model from changing claim data?**

> The tool argument identifies the bound row rather than supplying replacement claim fields. Dispatch checks schema, role and exact expected arguments. The operation uses application-held context, so a model cannot silently substitute an amount or access another row.

**Q26. What do prompt-injection defenses guarantee?**

> The stronger boundary is code: strict tools, context binding, no arbitrary execution and no model-callable approval operation. Instructions also treat text as data. This limits available actions; it does not prove that every possible prompt injection is solved.

**Q27. Is this multi-user or multi-tenant authorization?**

> No. One bearer credential represents one trusted tenant. Queries scope batch evidence to the supplied session, but the token does not establish ownership per individual user. Long-term policy history is shared inside that tenant. Enterprise identity and per-user permissions are future work.

**Q28. How do you prevent double review and concurrent corruption?**

> Reviews use an immediate transaction and a unique batch/row key. Session operations acquire an expiring lease token; renewal and batch commit validate ownership. An expired worker cannot commit after replacement. This targets one host with local SQLite storage.

**Q29. Does every failure roll back everything?**

> Results, batch events and history commit together. Session creation/messages are separate transactions, and Azure operations are remote side effects. There is no distributed transaction across them. A crash may leave messages or remote resources without a completed local batch.

**Q30. Are submissions exactly once or fully idempotent?**

> No client idempotency-key API is implemented. Same-session duplicates are flagged and bound tool results are cached within an invocation, but that is not exactly-once batch processing. Durable request IDs and job/result lookup would be needed for stronger retry guarantees.

**Q31. What happens when a tool or Azure call fails?**

> The failure is recorded and deterministic processing is attempted to preserve inspectable evidence. Any agent service issue forces documentation review. If deterministic work fails too, the batch follows its failure path. Runs and tool rounds are bounded, cancellation is attempted, and Azure mode never silently reports mock execution as cloud success.

**Q32. How does provisioning resume?**

> Successful resource IDs are progressively saved in a manifest and reused for matching configuration. A crash between remote creation and local persistence can still create an orphan, so inspection may be required. Provisioning should not run concurrently; changed fingerprints require a new profile.

### Testing and deployment

**Q33. What does 96.02 percent coverage mean?**

> It is statement coverage from the recorded local run, not model accuracy, security assurance or cloud compatibility. The meaningful evidence is behavior: thresholds, future-history exclusions, approval restrictions and failure paths. The report records 223 passes and one skipped live test.

**Q34. What is mocked and what is real in tests?**

> Mock mode replaces LLM/service transport. Validation, file retrieval, SQLite, API handlers and CLI subprocesses execute real code. SDK tests use a fake client plus installed SDK contracts. They cannot establish subscription access, quota, regional support or remote model quality.

**Q35. How would you scale to thousands of claims?**

> The current limit is 100 rows per batch with synchronous processing. Azure calls can make a batch slow, and throughput has not been benchmarked. I would add durable jobs, queueing, progress APIs and idempotency, then migrate shared storage/concurrency before adding replicas. Parallelism must preserve historical ordering semantics.

**Q36. What remains before claiming production deployment?**

> Configure a compatible Foundry project/model, verify access, provision and run the live smoke, then inspect actual tool/retrieval traces. Build and run the image, validate persistence and recovery, and complete deployment-specific identity, ingress, monitoring and load checks. The local synthetic implementation is tested; live cloud and container execution are not yet verified.

## 7. Practical demonstration with explanations

Run from the repository root after README setup. These commands use explicit mock mode and a separate persistent interview database. They do not create Azure resources.

```powershell
$py = '.\.venv\Scripts\python.exe'
$env:TRIAGE_MODE = 'mock'
$env:TRIAGE_DATABASE = 'var/interview.db'

$batch = & $py -m claims_triage triage data/claims.json --synthetic | ConvertFrom-Json
$batch.results | ForEach-Object {
    [PSCustomObject]@{
        Claim = $_.claim_id
        Action = $_.brief.recommended_action
        Review = $_.brief.review_status
    }
} | Format-Table

# Show evidence, not only a recommendation.
$batch.results[0].coverage.citations | Format-Table id,title,source
$batch.results[0].coverage.history | Format-Table claim_id,loss_date,flagged
$batch.events | Format-Table state

# Each call starts a separate process; the same session survives.
& $py -m claims_triage chat $batch.session_id 'Why was claim C2031 flagged?'
& $py -m claims_triage chat $batch.session_id 'Explain its recommendation'

# Clean C-2032 is row 1. This records a decision, not a payment.
& $py -m claims_triage review $batch.session_id $batch.id 1 approve --note 'Reviewed synthetic evidence'
& $py -m claims_triage show $batch.session_id $batch.id

# Expected refusal: C-2031 has a review indicator.
& $py -m claims_triage review $batch.session_id $batch.id 0 approve --note 'Demonstrate approval gate'
```

The last command intentionally returns an error; explain why before running it. JSON goes to stdout and diagnostics to stderr, so the pipeline reads the result. A new triage invocation creates a new session by default. Do not erase a database mid-demonstration just to hide prior results.

For HTTP, follow README token/serve instructions and open `/docs`. Explain that Swagger is an API explorer, not a custom dashboard. Avoid displaying credentials. Use README test commands and the [scenario catalog](07-test-scenarios.md) to demonstrate a specific behavior.

## 8. Rehearsal checklist

- Start with the business problem before naming frameworks.
- Name the four roles and their tools.
- Trace one claim through input, retrieval, history, briefing and review.
- Explain why C-2032 excludes C-1900 and why C-2033 is covered but flagged.
- Describe TF-IDF accurately; do not claim neural embeddings or semantic retrieval metrics.
- Distinguish hosted search registration from observed retrieval execution.
- Show where deterministic tool evidence reaches the user instead of model prose.
- Demonstrate a persisted follow-up and rejected unsafe approval.
- Distinguish session scoping from per-user authorization.
- Explain the test results, skipped live test and pending container verification.
- Identify which decisions came from the source and which are documented assumptions.
- Describe one improvement and its tradeoff without presenting it as implemented.

When asked about something outside scope, say: “That is not implemented in this version. The current behavior is X. To add Y, I would change Z and verify it with these tests.” An accurate limitation is easier to defend than an unsupported claim.
