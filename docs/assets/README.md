# README architecture artwork

`project-architecture.svg` is the editable, self-contained overview displayed at the top of the repository README. It uses embedded vector paths, system fonts and an opaque background so it renders without external image dependencies in GitHub light and dark themes. The detailed diagrams in `../02-architecture.md` are unchanged.

Technology logos (Python, Streamlit, FastAPI, SQLite, Microsoft Azure, Docker and GitHub Actions) come from [Devicon v2.17.0](https://github.com/devicons/devicon/tree/v2.17.0/icons). Their MIT license is included in [DEVICON-LICENSE.txt](DEVICON-LICENSE.txt). Product names and marks belong to their respective owners and identify the technologies used; they do not imply endorsement. The Azure logo identifies the Azure runtime, rather than an individual Foundry service icon.

Keep the overview aligned with `src/claims_triage/bootstrap.py`, `service.py`, `runtime.py`, `azure_runtime.py` and the detailed architecture document. Preserve the distinction between verified local behavior, the implemented Azure adapter and pending live/cloud checks.
