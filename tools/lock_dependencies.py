"""Freeze the currently installed and tested distributions without network resolution.

Run after dependency upgrades and tests. Includes transitive runtime extras and the
current platform's optional dependencies (portable packages such as colorama).
"""

from importlib.metadata import distribution, distributions
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOTS = [
    "fastapi",
    "uvicorn",
    "pydantic",
    "pydantic-settings",
    "jsonschema",
    "azure-ai-agents",
    "azure-identity",
]


def collect(roots: list[str]) -> dict[str, str]:
    pending = [(name, "") for name in roots]
    seen: set[tuple[str, str]] = set()
    pins = {}
    while pending:
        name, extra = pending.pop()
        name = canonicalize_name(name)
        if (name, extra) in seen:
            continue
        seen.add((name, extra))
        package = distribution(name)
        pins[name] = package.version
        for raw in package.requires or []:
            requirement = Requirement(raw)
            if requirement.marker is None or requirement.marker.evaluate({"extra": extra}):
                pending.append((requirement.name, ""))
                pending.extend((requirement.name, item) for item in requirement.extras)
    return pins


def main() -> None:
    pins = collect(ROOTS)
    header = "# Frozen tested distributions; regenerate with tools/lock_dependencies.py after updates.\n"
    Path("requirements.lock").write_text(
        header + "".join(f"{name}=={version}\n" for name, version in sorted(pins.items())), encoding="utf-8"
    )
    dev = {
        canonicalize_name(d.metadata["Name"]): d.version
        for d in distributions()
        if canonicalize_name(d.metadata["Name"]) not in {"claims-triage", "pip", "setuptools"}
    }
    Path("requirements-dev.lock").write_text(
        header + "".join(f"{name}=={version}\n" for name, version in sorted(dev.items())), encoding="utf-8"
    )
    ui = collect([*ROOTS, "streamlit", "httpx"])
    Path("requirements-ui.lock").write_text(
        header + "".join(f"{name}=={version}\n" for name, version in sorted(ui.items())), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
