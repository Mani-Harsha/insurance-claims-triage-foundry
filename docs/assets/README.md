# Architecture artwork

`project-architecture.svg` is the editable, self-contained overview displayed at the top of the repository README. It uses embedded vector paths, system fonts and an opaque background so it renders without external image dependencies in GitHub light and dark themes.

`architecture-flow.mmd` and `production-architecture.mmd` preserve the detailed application and proposed production diagrams. Long labels have explicit line breaks. The shared `mermaid-config.json` uses native SVG text instead of HTML labels, padded nodes and ELK connector routing. The documents embed checked, high-resolution PNGs so Markdown viewers cannot recalculate and clip the labels; each image links to a scalable SVG and its editable source. These are display fixes; the original nodes, connections and architectural meaning are preserved.

To regenerate either diagram, use Mermaid CLI 11.12.0 with the shared configuration (replace `architecture-flow` with `production-architecture` for the second diagram):

```powershell
npx --yes --package @mermaid-js/mermaid-cli@11.12.0 mmdc -i docs/assets/architecture-flow.mmd -o docs/assets/architecture-flow.svg -c docs/assets/mermaid-config.json -b white
npx --yes --package @mermaid-js/mermaid-cli@11.12.0 mmdc -i docs/assets/architecture-flow.mmd -o docs/assets/architecture-flow.png -c docs/assets/mermaid-config.json -b white -s 2
```

If using an existing Chrome installation, pass `-p` with a local Puppeteer JSON config containing its `executablePath` and `"headless": true`. Rendering tools are optional documentation tooling, not application dependencies. After editing, check every label and connector in the generated images before committing both formats with their source. The current images were also checked in headless Chrome for labels exceeding their node or canvas bounds.

Technology logos (Python, Streamlit, FastAPI, SQLite, Microsoft Azure, Docker and GitHub Actions) come from [Devicon v2.17.0](https://github.com/devicons/devicon/tree/v2.17.0/icons). Their MIT license is included in [DEVICON-LICENSE.txt](DEVICON-LICENSE.txt). Product names and marks belong to their respective owners and identify the technologies used; they do not imply endorsement. The Azure logo identifies the Azure runtime, rather than an individual Foundry service icon.

Keep the overview aligned with `src/claims_triage/bootstrap.py`, `service.py`, `runtime.py`, `azure_runtime.py` and the detailed architecture document. Preserve the distinction between verified local behavior, the implemented Azure adapter and pending live/cloud checks.
