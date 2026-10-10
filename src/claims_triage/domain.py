"""Pure business rules. Thresholds and peril mappings arrive from retrieved knowledge."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

Json = dict[str, Any]
FIELDS = (
    "claim_id",
    "policy_number",
    "claim_type",
    "loss_date",
    "report_date",
    "claim_amount",
    "description",
)


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class AgentError(AppError):
    def __init__(self, code: str = "agent_failed"):
        super().__init__(code, "Agent execution unavailable; evidence requires human review.", 503)


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    field: str | None = None
    rule_id: str | None = None


@dataclass
class IntakeResult:
    claim: Json | None
    issues: list[Issue] = field(default_factory=list)

    def to_dict(self) -> Json:
        return {"claim": self.claim, "issues": [asdict(i) for i in self.issues], "valid": not self.issues}


def parse_date(value: Any) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Expected ISO date")
    return date.fromisoformat(value)


def money(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError("Invalid money")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or not Decimal("0") < amount <= Decimal("1000000000000"):
            raise ValueError("Amount out of bounds")
        if amount != amount.quantize(Decimal("0.01")):
            raise ValueError("At most two decimal places")
        return amount
    except InvalidOperation as exc:
        raise ValueError("Invalid amount") from exc


def validate_claim(
    raw: Json, policies: dict[str, Json], duplicate_ids: set[str], today: date
) -> IntakeResult:
    issues: list[Issue] = []
    clean: Json = {}
    for name in FIELDS:
        value = raw.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            issues.append(Issue("missing_required", f"{name} is required.", name))
        else:
            clean[name] = value.strip() if isinstance(value, str) else value
    for name, pattern in (("claim_id", r"C-\d{1,20}"), ("policy_number", r"POL-\d{1,20}")):
        if name in clean and (not isinstance(clean[name], str) or not re.fullmatch(pattern, clean[name])):
            issues.append(Issue("invalid_identifier", f"Invalid {name} format.", name))
    policy_number = clean.get("policy_number")
    if (
        isinstance(policy_number, str)
        and re.fullmatch(r"POL-\d{1,20}", policy_number)
        and policy_number not in policies
    ):
        issues.append(
            Issue("unknown_policy", "Policy number does not exist in the synthetic catalog.", "policy_number")
        )
    claim_id = clean.get("claim_id")
    if isinstance(claim_id, str) and claim_id in duplicate_ids:
        issues.append(
            Issue("duplicate_claim", "Claim ID is duplicated in this batch or session.", "claim_id")
        )
    dates: dict[str, date] = {}
    for name in ("loss_date", "report_date"):
        if name in clean:
            try:
                dates[name] = parse_date(clean[name])
                if dates[name] > today:
                    issues.append(Issue("future_date", f"{name} cannot be in the future.", name))
            except ValueError:
                issues.append(Issue("invalid_date", f"{name} must be a valid YYYY-MM-DD date.", name))
    if len(dates) == 2 and dates["loss_date"] > dates["report_date"]:
        issues.append(Issue("date_order", "Loss date cannot follow report date.", "loss_date"))
    if "claim_amount" in clean:
        try:
            clean["claim_amount"] = str(money(clean["claim_amount"]).quantize(Decimal("0.01")))
        except ValueError:
            issues.append(
                Issue(
                    "invalid_amount",
                    "Amount must be positive, at most 1 trillion, with at most two decimal places.",
                    "claim_amount",
                )
            )
    for name, limit in (("claim_type", 50), ("description", 2000)):
        if name in clean and (not isinstance(clean[name], str) or len(clean[name]) > limit):
            issues.append(
                Issue("invalid_text", f"{name} must be text no longer than {limit} characters.", name)
            )
    if isinstance(clean.get("claim_type"), str) and not re.fullmatch(r"[a-z_]+", clean["claim_type"]):
        issues.append(
            Issue(
                "invalid_claim_type", "Claim type must use lowercase letters and underscores.", "claim_type"
            )
        )
    unknown = set(raw) - set(FIELDS)
    if unknown:
        issues.append(Issue("unknown_fields", "Submission contains unsupported fields."))
    return IntakeResult(clean if not issues else None, issues)


def check_coverage(claim: Json, policy: Json, rules: list[Json], history: list[Json]) -> Json:
    issues: list[Issue] = []
    loss, reported = parse_date(claim["loss_date"]), parse_date(claim["report_date"])
    start, end = parse_date(policy["active_from"]), parse_date(policy["active_to"])
    amount, limit = money(claim["claim_amount"]), money(policy["policy_limit"])
    similar = [
        h
        for h in history
        if h["claim_id"] != claim["claim_id"]
        and h["policy_number"] == claim["policy_number"]
        and h["claim_type"] == claim["claim_type"]
        and parse_date(h["loss_date"]) < loss
    ]
    for rule in rules:
        kind, params, rid = rule["kind"], rule["parameters"], rule["id"]
        code, message = "", ""
        if kind == "coverage_types" and claim["claim_type"] not in params.get(policy["coverage_type"], []):
            code, message = "peril_not_covered", "Claim type is outside the policy's covered perils."
        elif kind == "limit" and amount > limit:
            code, message = "over_limit", "Claim amount exceeds the policy limit."
        elif kind == "active_period" and not start <= loss <= end:
            code, message = "policy_inactive", "Loss date is outside the active policy period."
        elif kind == "inception" and (reported - start).days <= params["days"]:
            code, message = (
                "early_claim",
                "Report is at/before the retrieved policy-inception review threshold.",
            )
        elif kind == "near_limit" and limit * (1 - Decimal(str(params["percent"])) / 100) <= amount <= limit:
            code, message = "near_limit", "Amount is within the retrieved near-limit review threshold."
        elif kind == "repeat" and any(
            h["flagged"] and (loss - parse_date(h["loss_date"])).days <= params["days"] for h in similar
        ):
            code, message = (
                "similar_history",
                "An earlier similar flagged synthetic loss requires review; this is not proof of fraud.",
            )
        elif kind == "late_report" and (reported - loss).days > params["days"]:
            code, message = "late_report", "Reporting delay exceeds the retrieved documentation threshold."
        if code:
            issues.append(Issue(code, message, rule_id=rid))
    failed = {"peril_not_covered", "over_limit", "policy_inactive"}
    return {
        "covered": not any(i.code in failed for i in issues),
        "issues": [asdict(i) for i in issues],
        "citations": [{k: r[k] for k in ("id", "title", "text", "source", "version")} for r in rules],
        "history": similar,
        "policy": policy,
    }


def build_brief(claim_id: str, intake: Json, coverage: Json, service_issues: list[str]) -> Json:
    findings = intake["issues"] + coverage.get("issues", [])
    if intake["issues"] or service_issues or any(i["code"] == "late_report" for i in findings):
        action = "request_more_documentation"
    elif findings:
        action = "route_to_investigator"
    else:
        action = "auto_approve"
    reasons = (
        " ".join(i["message"] for i in findings)
        or "Intake and retrieved coverage checks passed without review indicators."
    )
    memory = coverage.get("history", [])
    memory_text = " ".join(
        f"Earlier synthetic {h['claim_type']} claim {h['claim_id']} on {h['loss_date']} was {'flagged' if h['flagged'] else 'not flagged'}."
        for h in memory[:10]
    )
    if service_issues:
        reasons += " Agent service evidence is incomplete and requires human review."
    return {
        "summary": f"Synthetic claim {claim_id}: {reasons} {memory_text}".strip(),
        "recommended_action": action,
        "review_status": "pending",
        "synthetic": True,
    }


def route_request(message: str, last_claim_id: str | None = None) -> Json:
    text = message.lower().strip()
    match = re.search(r"\bc-?(\d{1,20})\b", text)
    if re.search(r"\b(triage|process|validate)\b", text) and re.search(r"\b(batch|claims)\b", text):
        return {"intent": "triage", "claim_id": None}
    if re.search(r"\b(why|explain|flagged|summary|recommendation)\b", text):
        return {"intent": "explain", "claim_id": f"C-{match.group(1)}" if match else last_claim_id}
    return {"intent": "help", "claim_id": None}
