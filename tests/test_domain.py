from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from claims_triage.domain import FIELDS, build_brief, check_coverage, money, route_request, validate_claim
from claims_triage.knowledge import FileVectorKnowledge, load_policies

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 9)


@pytest.fixture
def claim():
    return {
        "claim_id": "C-9000",
        "policy_number": "POL-5521",
        "claim_type": "water_damage",
        "loss_date": "2026-08-15",
        "report_date": "2026-08-16",
        "claim_amount": "8500.00",
        "description": "Synthetic pipe burst",
    }


@pytest.fixture
def policies():
    return load_policies(ROOT / "data/policy_coverage.json")


@pytest.fixture
def rules():
    return FileVectorKnowledge(ROOT / "knowledge").search("coverage review", 8)


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("missing", [None, "", "   "])
def test_each_required_field_rejects_empty(claim, policies, field, missing):
    claim[field] = missing
    result = validate_claim(claim, policies, set(), TODAY)
    assert result.claim is None
    assert any(issue.code == "missing_required" and issue.field == field for issue in result.issues)


@pytest.mark.parametrize("field", FIELDS)
def test_each_required_field_rejects_absence(claim, policies, field):
    del claim[field]
    assert any(
        issue.field == field and issue.code == "missing_required"
        for issue in validate_claim(claim, policies, set(), TODAY).issues
    )


@pytest.mark.parametrize(
    "value", [0, -1, True, False, "NaN", "Infinity", "-Infinity", "1.001", "1000000000000.01", {}, [], "n/a"]
)
def test_invalid_money_rejected(value):
    with pytest.raises(ValueError):
        money(value)


@pytest.mark.parametrize(
    "value,expected",
    [
        (1, "1"),
        ("0.01", "0.01"),
        ("1.230", "1.230"),
        (Decimal("99.99"), "99.99"),
        ("1000000000000", "1000000000000"),
    ],
)
def test_exact_money_boundaries(value, expected):
    assert money(value) == Decimal(expected)


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"loss_date": "2026-02-30"}, "invalid_date"),
        ({"loss_date": "15/08/2026"}, "invalid_date"),
        ({"loss_date": 20260815}, "invalid_date"),
        ({"report_date": "2026-10-10"}, "future_date"),
        ({"loss_date": "2026-08-17"}, "date_order"),
        ({"policy_number": "5521"}, "invalid_identifier"),
        ({"policy_number": "POL-99999999"}, "unknown_policy"),
        ({"claim_id": "C9000"}, "invalid_identifier"),
        ({"claim_type": "WaterDamage"}, "invalid_claim_type"),
        ({"description": "x" * 2001}, "invalid_text"),
        ({"description": []}, "invalid_text"),
        ({"extra": "ignored?"}, "unknown_fields"),
    ],
)
def test_intake_negative_cases(claim, policies, changes, code):
    claim.update(changes)
    result = validate_claim(claim, policies, set(), TODAY)
    assert code in {issue.code for issue in result.issues}
    assert result.claim is None


def test_intake_normalizes_whitespace_and_decimal_without_mutating_input(claim, policies):
    claim.update(claim_id=" C-9000 ", claim_amount=12, description="  Synthetic  ")
    result = validate_claim(claim, policies, set(), TODAY)
    assert not result.issues
    assert result.claim["claim_amount"] == "12.00"
    assert result.claim["description"] == "Synthetic"
    assert claim["claim_id"] == " C-9000 "


@pytest.mark.parametrize(
    "amount,expected",
    [
        ("48999.99", set()),
        ("49000.00", {"near_limit"}),
        ("50000", {"near_limit"}),
        ("50000.01", {"over_limit"}),
    ],
)
def test_limit_and_near_limit_boundaries(claim, policies, rules, amount, expected):
    claim["claim_amount"] = amount
    result = check_coverage(claim, policies[claim["policy_number"]], rules, [])
    assert {issue["code"] for issue in result["issues"]} == expected
    assert result["covered"] is ("over_limit" not in expected)


@pytest.mark.parametrize("offset,flagged", [(-1, True), (0, True), (7, True), (8, False)])
def test_inception_boundary(claim, policies, rules, offset, flagged):
    policy = dict(policies["POL-5521"], active_from="2026-08-01")
    claim["report_date"] = claim["loss_date"] = (date(2026, 8, 1) + timedelta(days=offset)).isoformat()
    codes = {i["code"] for i in check_coverage(claim, policy, rules, [])["issues"]}
    assert ("early_claim" in codes) is flagged


@pytest.mark.parametrize(
    "loss,covered", [("2024-12-31", False), ("2025-01-01", True), ("2026-12-31", True), ("2027-01-01", False)]
)
def test_policy_period_inclusive(claim, policies, rules, loss, covered):
    claim["loss_date"] = claim["report_date"] = loss
    assert check_coverage(claim, policies["POL-5521"], rules, [])["covered"] is covered


@pytest.mark.parametrize(
    "peril,category,covered",
    [
        ("fire", "homeowners", True),
        ("collision", "auto", True),
        ("collision", "homeowners", False),
        ("flood", "auto", False),
    ],
)
def test_retrieved_peril_mapping(claim, policies, rules, peril, category, covered):
    claim["claim_type"] = peril
    policy = dict(policies["POL-5521"], coverage_type=category)
    assert check_coverage(claim, policy, rules, [])["covered"] is covered


@pytest.mark.parametrize("days,flagged", [(30, False), (31, True)])
def test_reporting_delay_boundary(claim, policies, rules, days, flagged):
    claim["report_date"] = (date.fromisoformat(claim["loss_date"]) + timedelta(days=days)).isoformat()
    codes = {i["code"] for i in check_coverage(claim, policies["POL-5521"], rules, [])["issues"]}
    assert ("late_report" in codes) is flagged


@pytest.mark.parametrize("days,flagged", [(365, True), (366, False)])
def test_repeat_window_and_history_exclusions(claim, policies, rules, days, flagged):
    prior = {
        "claim_id": "C-100",
        "policy_number": claim["policy_number"],
        "claim_type": claim["claim_type"],
        "loss_date": (date.fromisoformat(claim["loss_date"]) - timedelta(days=days)).isoformat(),
        "flagged": True,
    }
    excluded = [
        dict(prior, claim_id=claim["claim_id"]),
        dict(prior, policy_number="POL-0000"),
        dict(prior, claim_type="fire"),
        dict(prior, loss_date="2026-09-01"),
    ]
    result = check_coverage(claim, policies["POL-5521"], rules, [prior, *excluded])
    assert result["history"] == [prior]
    assert ("similar_history" in {i["code"] for i in result["issues"]}) is flagged


@pytest.mark.parametrize(
    "intake,coverage,service,expected",
    [
        ([], [], [], "auto_approve"),
        ([], [{"code": "near_limit", "message": "Near limit"}], [], "route_to_investigator"),
        ([{"code": "missing_required", "message": "Missing"}], [], [], "request_more_documentation"),
        ([], [{"code": "late_report", "message": "Delayed"}], [], "request_more_documentation"),
        ([], [], ["briefing:timeout"], "request_more_documentation"),
    ],
)
def test_brief_precedence_and_human_gate(intake, coverage, service, expected):
    result = build_brief("C-1", {"issues": intake}, {"issues": coverage}, service)
    assert result["recommended_action"] == expected
    assert result["review_status"] == "pending"
    assert result["synthetic"] is True
    assert "Synthetic claim C-1" in result["summary"]


def test_router_normalization_context_and_unsupported_intent():
    assert route_request("Why was C2031 flagged?") == {"intent": "explain", "claim_id": "C-2031"}
    assert route_request("Explain it", "C-2031")["claim_id"] == "C-2031"
    assert route_request("triage this batch of claims")["intent"] == "triage"
    assert route_request("Transfer money")["intent"] == "help"
