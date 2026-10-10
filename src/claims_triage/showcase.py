"""HTTP-only presentation adapter and evidence mapping for the showcase dashboard."""

import re
from pathlib import Path
from typing import Any

import httpx

from .domain import AppError, Json


class ShowcaseClient:
    def __init__(self, base_url: str, token: str, timeout: float = 600):
        self.base_url, self.token, self.timeout = base_url.rstrip("/"), token, timeout

    def request(self, method: str, path: str, **kwargs: Any) -> Json:
        try:
            response = httpx.request(
                method,
                self.base_url + path,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=httpx.Timeout(self.timeout, connect=5),
                follow_redirects=False,
                trust_env=False,
                **kwargs,
            )
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise AppError(
                "request_timeout",
                "The request timed out. Processing may continue. Refresh batches before submitting again.",
                504,
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise AppError(
                "backend_unavailable",
                "Cannot reach the claims API. Start the showcase launcher or check the API connection.",
                503,
            ) from exc
        if response.is_error:
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            raise AppError(
                error.get("code", "api_error"),
                error.get("message", "The API rejected this request."),
                response.status_code,
            )
        if not isinstance(payload, dict):
            raise AppError("invalid_response", "The API returned an unexpected response.", 502)
        return payload


def requirement_rows(root: Path, demonstrated: set[str]) -> list[Json]:
    """Read the authoritative checked-in matrix; never present source inspection as a live test."""
    planned: dict[str, str] = {}
    for line in (root / "docs/01-requirements.md").read_text(encoding="utf-8").splitlines():
        if re.match(r"\| R\d{2} \|", line):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            planned[cells[0]] = cells[1]
    rows = []
    for line in (root / "docs/11-coverage.md").read_text(encoding="utf-8").splitlines():
        if re.match(r"\| R\d{2} \|", line):
            rid, status, implementation, verification = [cell.strip() for cell in line.strip("|").split("|")]
            rows.append(
                {
                    "ID": rid,
                    "Requirement": planned[rid],
                    "Recorded status": status,
                    "Current showcase": "Observed" if rid in demonstrated else "Not observed yet",
                    "Implementation": implementation.replace("`", ""),
                    "Evidence / test": verification.replace("`", ""),
                }
            )
    return rows


def demonstrated_by_batch(batch: Json) -> set[str]:
    """Only mark behaviors actually evidenced by a completed response."""
    rows = batch.get("results", [])
    if not rows:
        return set()
    seen = {"R01", "R02", "R07", "R14", "R17"}
    issues = {
        issue["code"]
        for row in rows
        for source in ("intake", "coverage")
        for issue in row[source].get("issues", [])
    }
    for code, rid in {
        "missing_required": "R03",
        "date_order": "R04",
        "invalid_date": "R04",
        "future_date": "R04",
        "unknown_policy": "R05",
        "invalid_identifier": "R05",
        "duplicate_claim": "R06",
        "peril_not_covered": "R08",
        "over_limit": "R09",
        "policy_inactive": "R10",
        "early_claim": "R13",
        "near_limit": "R13",
    }.items():
        if code in issues:
            seen.add(rid)
    if any(row["coverage"].get("citations") for row in rows):
        seen.update({"R08", "R09", "R10", "R11", "R12"})
    if any(row["coverage"].get("history") for row in rows):
        seen.add("R15")
    if any(row.get("review") for row in rows):
        seen.add("R18")
    if any(row.get("service_issues") for row in rows):
        seen.add("R24")
    return seen
