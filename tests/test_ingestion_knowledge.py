import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from claims_triage.domain import AppError, check_coverage
from claims_triage.ingestion import MAX_BYTES, parse_claims, validate_batch
from claims_triage.knowledge import FileVectorKnowledge, load_policies

ROOT = Path(__file__).resolve().parents[1]


def test_starter_json_and_auto_csv():
    claims = parse_claims((ROOT / "data/claims.json").read_bytes(), "json")
    assert [row["claim_id"] for row in claims] == ["C-2031", "C-2032", "C-2033", "C-2034"]
    auto = parse_claims((ROOT / "data/claims_auto.csv").read_bytes(), "csv")
    assert auto and any(row["claim_type"] == "collision" for row in auto)


def test_json_decimal_and_utf8_bom_preserved():
    rows = parse_claims(b'\xef\xbb\xbf[{"claim_amount": 0.01}]', "json")
    assert rows[0]["claim_amount"] == Decimal("0.01")


@pytest.mark.parametrize(
    "content,format",
    [
        (b"{", "json"),
        (b"\xff", "json"),
        (b'[{"x":1,"x":2}]', "json"),
        (b'[{"x":NaN}]', "json"),
        (b'[{"x":Infinity}]', "json"),
        (b"[]", "xml"),
        (b"claim_id,claim_id\na,b", "csv"),
        (b"claim_id,policy_number,claim_type,loss_date,report_date,claim_amount,description\na,b", "csv"),
        (
            b"claim_id,policy_number,claim_type,loss_date,report_date,claim_amount,description\na,b,c,d,e,f,g,h",
            "csv",
        ),
    ],
)
def test_malformed_input_rejected(content, format):
    with pytest.raises(AppError) as caught:
        parse_claims(content, format)
    assert caught.value.code == "malformed_input"


@pytest.mark.parametrize("rows", [None, {}, [], [1], [None], [{}] * 101, [{"x": float("nan")}]])
def test_invalid_batch_envelopes(rows):
    with pytest.raises(AppError) as caught:
        validate_batch(rows)
    assert caught.value.code == "invalid_batch"


def test_input_size_boundary():
    with pytest.raises(AppError) as caught:
        parse_claims(b" " * (MAX_BYTES + 1), "json")
    assert caught.value.status == 413
    with pytest.raises(AppError) as caught:
        validate_batch([{"description": "x" * MAX_BYTES}])
    assert caught.value.status == 413
    assert len(validate_batch([{}] * 100)) == 100


def test_knowledge_grounding_has_ranked_versioned_citations():
    knowledge = FileVectorKnowledge(ROOT / "knowledge")
    matches = knowledge.search("near limit amount", 3)
    assert len(matches) == 3
    assert matches[0]["id"] == "UW05"
    assert len(knowledge.version) == 64
    assert all(
        row["source"].startswith("knowledge/rules.json#") and row["version"] == knowledge.version
        for row in matches
    )
    policies = load_policies(ROOT / "data/policy_coverage.json")
    claim = parse_claims((ROOT / "data/claims.json").read_bytes(), "json")[0]
    rules = knowledge.applicable_rules(claim, policies[claim["policy_number"]])
    assert {rule["id"] for rule in rules} == {f"UW{i:02d}" for i in range(1, 9)}
    assert len(check_coverage(claim, policies[claim["policy_number"]], rules, [])["citations"]) == 8


def test_rule_change_changes_behavior_and_knowledge_version(tmp_path):
    directory = tmp_path / "knowledge"
    shutil.copytree(ROOT / "knowledge", directory)
    original = FileVectorKnowledge(directory)
    rows = json.loads((directory / "rules.json").read_text())
    next(r for r in rows if r["kind"] == "inception")["parameters"]["days"] = 2
    (directory / "rules.json").write_text(json.dumps(rows), encoding="utf-8")
    changed = FileVectorKnowledge(directory)
    claim = parse_claims((ROOT / "data/claims.json").read_bytes(), "json")[2]
    policy = load_policies(ROOT / "data/policy_coverage.json")[claim["policy_number"]]
    before = check_coverage(claim, policy, original.applicable_rules(claim, policy), [])
    after = check_coverage(claim, policy, changed.applicable_rules(claim, policy), [])
    assert original.version != changed.version
    assert "early_claim" in {i["code"] for i in before["issues"]}
    assert "early_claim" not in {i["code"] for i in after["issues"]}


@pytest.mark.parametrize("damage", ["missing", "json", "incomplete", "duplicate", "threshold", "markdown"])
def test_invalid_knowledge_fails_closed(tmp_path, damage):
    directory = tmp_path / "knowledge"
    shutil.copytree(ROOT / "knowledge", directory)
    path = directory / "rules.json"
    rows = json.loads(path.read_text())
    if damage == "missing":
        path.unlink()
    elif damage == "json":
        path.write_text("{")
    elif damage == "markdown":
        (directory / "underwriting_rules.md").write_text("No rule headings")
    else:
        if damage == "incomplete":
            rows.pop()
        elif damage == "duplicate":
            rows[1]["id"] = rows[0]["id"]
        else:
            next(r for r in rows if r["kind"] == "inception")["parameters"]["days"] = -1
        path.write_text(json.dumps(rows))
    with pytest.raises(AppError) as caught:
        FileVectorKnowledge(directory)
    assert caught.value.code == "invalid_knowledge"


@pytest.mark.parametrize("damage", ["empty", "duplicate", "period", "limit", "category"])
def test_invalid_policy_configuration(tmp_path, damage):
    rows = json.loads((ROOT / "data/policy_coverage.json").read_text())
    if damage == "empty":
        rows = []
    elif damage == "duplicate":
        rows.append(rows[0])
    else:
        key, value = {
            "period": ("active_from", "2030-01-01"),
            "limit": ("policy_limit", -1),
            "category": ("coverage_type", "unsupported"),
        }[damage]
        rows[0][key] = value
    path = tmp_path / "policies.json"
    path.write_text(json.dumps(rows))
    with pytest.raises(AppError) as caught:
        load_policies(path)
    assert caught.value.code == "invalid_policies"
