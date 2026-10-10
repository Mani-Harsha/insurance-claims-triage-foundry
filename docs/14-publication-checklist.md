# Repository contents and publication checks

The GitHub repository is intended for public technical review using synthetic data only.

## Included

- Python application and Streamlit UI; supervisor, specialist tools and Azure adapter.
- Synthetic claims, policies and memory seeds; versioned underwriting knowledge.
- Automated tests, dependency locks, CI workflow, Docker and Compose definitions.
- Safe environment template, editor launch/tasks and Streamlit display configuration.
- Text assignment, requirement mapping, architecture, database/API design, setup and project guides.
- A sanitized verification summary. Runtime output and session state remain local.

## Excluded

- `.env` and other private environment files; credentials, keys and Streamlit secrets.
- `.venv`, caches, coverage scratch files, local test directories and build outputs.
- `var/`, SQLite databases, logs, persisted conversations, uploaded inputs and Azure resource manifests.
- Local cloud/agent/editor-assistant state and generated archives.
- The original Word assignment attachment, which may carry document metadata; the supplied text requirements are retained.

The ignore rules are preventive controls, not proof that arbitrary future content is safe. Inspect the staged diff before every push, including synthetic data and documentation.

## Repeatable checks

```powershell
git status --short
git diff --cached --stat
git diff --cached --check
git ls-files
.\.venv\Scripts\python.exe -m ruff check src ui tests tools
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m pytest --basetemp=.pytest-local-tmp --cov=claims_triage
```

The application remains a local demo unless separately deployed. Public repository access lets a reviewer inspect and clone the project; it does not grant access to the developer's computer, Azure resources or local data.
