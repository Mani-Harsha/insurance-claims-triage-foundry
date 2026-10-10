# 6. Source code guide

The complete implementation is in `src/claims_triage`; this is an installable application, not pseudocode. `python -m claims_triage` and `claims-triage` share the same entry point.

| Component | Responsibility / important entry points |
|---|---|
| `domain.py` | `validate_claim`, `check_coverage`, `build_brief`, `route_request`; pure functions with explicit inputs, no SDK/network state |
| `ports.py` | Structural protocols let the application depend on abstractions and tests inject faulty runtimes/repositories |
| `service.py` | `TriageService.triage/chat/review`; ordered routine, validation checkpoint, chronological history, error gates |
| `tools.py` | Five JSON-schema function tools across four agents, strict schema validation and binding to the exact trusted row/request |
| `knowledge.py` | Validates rule catalog and loads a sparse TF-IDF cosine index; every applicable rule is retrieved with source/version evidence |
| `repository.py` | SQLite schema, SQL parameters, transactions, fenced session leases, immutable review evidence and persisted threads |
| `azure_runtime.py` | Four `create_agent` calls; coverage FileSearchTool/vector store; explicit run polling, function execution and bounded cancellation |
| `runtime.py` | Mock transport that executes the same validated tools locally |
| `api.py`, `cli.py` | Thin presentation adapters; the same service enforces business policy for both |
| `bootstrap.py`, `config.py` | Composition root and configuration; no Azure import/authentication in default mode |

SOLID is applied through one domain concern per function, separate presentation/infrastructure modules, substitutable runtime adapters, narrow protocols, and dependency injection. Further abstraction for every SDK operation would obscure a small project; SDK details remain in one adapter instead.

The local retriever ranks all eight records, rather than using a low top-k that might omit a mandatory coverage check. This is real vector retrieval with explicit citations, but not a semantic embedding model. The Azure coverage agent additionally registers hosted file search over markdown. Decision thresholds and peril mappings come from retrieved JSON records; evaluator branches implement rule semantics. Missing/invalid knowledge prevents startup. When updating knowledge, edit both human-readable and structured files, test their consistency, and provision a fresh Azure profile because the deployment fingerprint changes.

The host constrains function arguments to the current row. A model cannot ask an intake tool to approve, inspect another session, execute code, or modify memory. Runs are cancellable and bounded; output from a completed tool survives a service failure only with explicit degraded status and a closed approval path. Supplemental model prose does not replace authoritative deterministic findings.

SDK compatibility was chosen deliberately: this assignment names `azure-ai-agents`, so the adapter targets its pinned 1.1.0 Agent Service threads/runs API. It does not mix `azure-ai-projects` 2.x Responses types into that contract. A future migration is isolated behind `AgentRuntime` and needs its own live verification. Reference: [Microsoft Azure AI Agents SDK documentation](https://learn.microsoft.com/en-us/python/api/overview/azure/ai-agents-readme?view=azure-python), [run operations](https://learn.microsoft.com/en-us/python/api/azure-ai-agents/azure.ai.agents.operations.runsoperations?view=azure-python).
