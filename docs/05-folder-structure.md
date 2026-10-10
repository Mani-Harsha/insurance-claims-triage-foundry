# 5. Folder structure

```text
projectdetails.txt                  authoritative supplied requirements (unchanged)
MultiAgent_Insurance_...docx         original alternate attachment (unchanged)
README.md                           setup, running, results, deliverable index
pyproject.toml                      package, extras, CLI, pytest/lint/type settings
requirements.lock                   frozen runtime + Azure dependencies
requirements-dev.lock               frozen test/development dependencies
requirements-ui.lock                frozen UI/runtime dependencies
ui/app.py                           Streamlit HTTP frontend and requirements dashboard
.streamlit/config.toml              loopback binding, upload limit and theme
.env.example                        documented configuration without credentials
.vscode/                            debugger and task configurations
.github/workflows/ci.yml            lint, type, test and container-build checks
Dockerfile                          non-root application image
compose.yaml                        single-host persistent local volume deployment
.dockerignore                       excludes secrets, fixtures output and caches
data/                               synthetic starter JSON, auto CSV, policy/history
knowledge/                          eight markdown + structured retrieval rules
src/claims_triage/
  domain.py                         pure validation, coverage, routing and briefing
  ports.py                          runtime, repository, knowledge interfaces
  service.py                        explicit supervisor routine and HITL policy
  tools.py                          schemas, instructions, role/context allowlists
  ingestion.py                      bounded JSON/CSV decoding
  knowledge.py                      file TF-IDF vector retrieval + catalog loading
  repository.py                     transactional SQLite, messages/history/reviews
  runtime.py                        local mock LLM/service adapter
  azure_runtime.py                  real SDK creation, threads, runs, function calls
  bootstrap.py                      dependency composition and synthetic seed
  config.py                         typed environment configuration
  observability.py                  redacted structured console logs
  showcase.py                       HTTP presentation client and requirement evidence mapping
  api.py                            authenticated HTTP transport and OpenAPI
  cli.py / __main__.py               command-line transport
tests/                              unit, integration, SDK contracts, opt-in live test
tools/                              reproducible lock and OpenAPI snapshot helpers
docs/                               numbered deliverables and verification report
var/                                ignored mutable SQLite runtime data
```
