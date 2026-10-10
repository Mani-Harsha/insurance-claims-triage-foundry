import json
import sqlite3
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest

from claims_triage.domain import AgentError, AppError
from claims_triage.ingestion import parse_claims
from claims_triage.knowledge import FileVectorKnowledge, load_policies
from claims_triage.ports import AgentReply
from claims_triage.repository import SQLiteRepository
from claims_triage.runtime import MockRuntime
from claims_triage.service import ROUTINE, TriageService

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 9)


def make_service(path, runtime=None):
    repo = SQLiteRepository(path)
    repo.seed_history(json.loads((ROOT / "data/memory_seed.json").read_text()))
    return TriageService(
        repo,
        load_policies(ROOT / "data/policy_coverage.json"),
        FileVectorKnowledge(ROOT / "knowledge"),
        runtime or MockRuntime(),
        lambda: TODAY,
    )


@pytest.fixture
def service(tmp_path):
    return make_service(tmp_path / "claims.db")


@pytest.fixture
def claims():
    return parse_claims((ROOT / "data/claims.json").read_bytes(), "json")


@pytest.fixture
def clean(claims):
    return deepcopy(claims[1])


def test_starter_batch_exact_outcomes_and_routine(service, claims):
    session = service.repo.create_session()
    batch = service.triage(session, claims, True)
    assert [r["brief"]["recommended_action"] for r in batch["results"]] == [
        "route_to_investigator",
        "auto_approve",
        "route_to_investigator",
        "request_more_documentation",
    ]
    assert tuple(event["state"] for event in batch["events"]) == ROUTINE
    assert [row["row_index"] for row in batch["results"]] == [0, 1, 2, 3]
    assert all(row["brief"]["review_status"] == "pending" for row in batch["results"])
    assert "C-1900" in batch["results"][0]["brief"]["summary"]
    assert "C-1900" not in batch["results"][1]["brief"]["summary"]
    assert batch["results"][3]["coverage"]["status"] == "skipped_invalid_intake"
    assert service.repo.batch(session, batch["id"])["results"] == batch["results"]


@pytest.mark.parametrize("synthetic", [False, None, 1, "true"])
def test_synthetic_declaration_is_explicit(service, clean, synthetic):
    session = service.repo.create_session()
    with pytest.raises(AppError) as caught:
        service.triage(session, [clean], synthetic)
    assert caught.value.code == "synthetic_required"
    assert not service.repo.seen_ids(session)


def test_duplicate_all_occurrences_and_cross_batch(service, clean):
    session = service.repo.create_session()
    second = dict(clean, claim_id=" C-2032 ")
    batch = service.triage(session, [clean, second], True)
    assert len(batch["results"]) == 2
    assert all("duplicate_claim" in {i["code"] for i in row["intake"]["issues"]} for row in batch["results"])
    again = service.triage(session, [clean], True)
    assert again["results"][0]["intake"]["issues"][0]["code"] == "duplicate_claim"
    other = service.triage(service.repo.create_session(), [clean], True)
    assert other["results"][0]["intake"]["valid"]


def test_restart_conversation_and_cross_session_history(service, claims):
    session = service.repo.create_session()
    batch = service.triage(session, claims, True)
    first = service.chat(session, "Why was claim C2031 flagged?")
    reopened = make_service(service.repo.path)
    followup = reopened.chat(session, "Explain its recommendation")
    assert followup["claim_id"] == "C-2031"
    assert followup["answer"] == first["answer"]
    assert len(reopened.repo.messages(session)) == 6
    assert reopened.repo.batch(session, batch["id"])["id"] == batch["id"]
    other = reopened.repo.create_session()
    assert reopened.chat(other, "Why was C2031 flagged?")["evidence"] == []
    with pytest.raises(AppError) as caught:
        reopened.repo.batch(other, batch["id"])
    assert caught.value.status == 404
    new_claim = dict(claims[0], claim_id="C-9999", loss_date="2026-09-01", report_date="2026-09-02")
    new_batch = reopened.triage(other, [new_claim], True)
    assert "C-2031" in new_batch["results"][0]["brief"]["summary"]


def test_within_batch_history_is_chronological_and_preserves_input_order(service, clean):
    earlier = dict(
        clean, claim_id="C-701", loss_date="2026-03-01", report_date="2026-03-02", claim_amount=50000
    )
    later = dict(clean, claim_id="C-702", loss_date="2026-04-01", report_date="2026-04-02")
    batch = service.triage(service.repo.create_session(), [later, earlier], True)
    assert [row["claim_id"] for row in batch["results"]] == ["C-702", "C-701"]
    assert "C-701" in {h["claim_id"] for h in batch["results"][0]["coverage"]["history"]}
    assert "C-702" not in {h["claim_id"] for h in batch["results"][1]["coverage"]["history"]}


def test_human_review_preserves_original_evidence_and_completes_batch(service, clean):
    session = service.repo.create_session()
    batch = service.triage(session, [clean], True)
    before = service.repo.claim_results(session, clean["claim_id"])
    decision = service.review(session, batch["id"], 0, "approve", "Evidence checked", "test-adjuster")
    assert decision["reviewer"] == "test-adjuster"
    stored = service.repo.batch(session, batch["id"])
    assert stored["state"] == "REVIEWED"
    assert stored["results"][0]["brief"]["review_status"] == "reviewed"
    assert stored["events"][-1]["state"] == "HUMAN_DECISION"
    assert service.repo.claim_results(session, clean["claim_id"]) == before
    with pytest.raises(AppError) as caught:
        service.review(session, batch["id"], 0, "investigate", "Second decision")
    assert caught.value.code == "already_reviewed"


def test_unsafe_approval_and_cross_session_review_rejected(service, claims):
    session = service.repo.create_session()
    batch = service.triage(session, claims, True)
    for row in [0, 2, 3]:
        with pytest.raises(AppError) as caught:
            service.review(session, batch["id"], row, "approve", "Try unsafe approval")
        assert caught.value.code == "unsafe_approval"
    with pytest.raises(AppError) as caught:
        service.review(service.repo.create_session(), batch["id"], 1, "approve", "Wrong session")
    assert caught.value.status == 404
    service.review(session, batch["id"], 1, "approve", "Clean evidence")
    assert service.repo.batch(session, batch["id"])["state"] == "HUMAN_REVIEW_PENDING"


@pytest.mark.parametrize(
    "row,decision,note,code",
    [
        (-1, "approve", "valid note", "invalid_row"),
        (True, "approve", "valid note", "invalid_row"),
        (0, "pay", "valid note", "invalid_decision"),
        (0, "approve", " ", "invalid_note"),
        (0, "approve", "x" * 2001, "invalid_note"),
    ],
)
def test_review_input_validation(service, row, decision, note, code):
    with pytest.raises(AppError) as caught:
        service.review("irrelevant", "irrelevant", row, decision, note)
    assert caught.value.code == code


class FailingRuntime(MockRuntime):
    mode = "azure"

    def __init__(self, failing_role, after_dispatch=False):
        self.failing_role = failing_role
        self.after_dispatch = after_dispatch

    def invoke(self, role, session_id, tool, arguments, dispatch):
        if role == self.failing_role:
            if self.after_dispatch:
                dispatch(tool, arguments)
            raise AgentError("agent_timeout")
        return super().invoke(role, session_id, tool, arguments, dispatch)


@pytest.mark.parametrize("role", ["supervisor", "intake", "coverage", "briefing"])
@pytest.mark.parametrize("after_dispatch", [False, True])
def test_agent_failure_never_auto_approves(service, clean, role, after_dispatch):
    service.runtime = FailingRuntime(role, after_dispatch)
    batch = service.triage(service.repo.create_session(), [clean], True)
    row = batch["results"][0]
    assert batch["mode"] == "azure"
    assert row["brief"]["recommended_action"] == "request_more_documentation"
    assert f"{role}:agent_timeout" in row["service_issues"]
    assert row["intake"]["valid"]
    assert row["coverage"]["citations"]


def test_explanation_failure_is_exposed_and_closes_approval_path(service, clean):
    session = service.repo.create_session()
    service.triage(session, [clean], True)
    service.runtime = FailingRuntime("briefing", after_dispatch=True)
    answer = service.chat(session, "Why was C2032 flagged?")
    assert answer["recommended_action"] == "request_more_documentation"
    assert "briefing:agent_timeout" in answer["service_issues"]


def test_runtime_cannot_replace_authoritative_evidence(service, clean):
    class LyingRuntime(MockRuntime):
        def invoke(self, role, session_id, tool, arguments, dispatch):
            dispatch(tool, arguments)
            return AgentReply({"recommended_action": "auto_approve", "invented": True})

    service.runtime = LyingRuntime()
    row = service.triage(service.repo.create_session(), [clean], True)["results"][0]
    assert row["brief"]["recommended_action"] == "request_more_documentation"
    assert any("agent_evidence_mismatch" in issue for issue in row["service_issues"])


def test_batch_transaction_rolls_back_all_rows(service):
    session = service.repo.create_session()
    invalid = {
        "id": "bad-batch",
        "session_id": session,
        "state": "HUMAN_REVIEW_PENDING",
        "mode": "mock",
        "knowledge_version": "test",
        "results": [{"row_index": 0, "claim_id": "C-1"}] * 2,
        "events": [],
    }
    with service.repo.session_lock(session), pytest.raises(sqlite3.IntegrityError):
        service.repo.save_batch(invalid, [])
    assert not service.repo.seen_ids(session)
    with pytest.raises(AppError):
        service.repo.batch(session, "bad-batch")


def test_history_seed_idempotence_and_flag_preservation(service, clean):
    original = service.repo.history("POL-5521")
    service.repo.seed_history(json.loads((ROOT / "data/memory_seed.json").read_text()))
    assert service.repo.history("POL-5521") == original
    replay = dict(clean, claim_id="C-1900", loss_date="2026-02-15", report_date="2026-02-16")
    row = service.triage(service.repo.create_session(), [replay], True)["results"][0]
    assert row["brief"]["recommended_action"] == "auto_approve"
    assert next(h for h in service.repo.history("POL-5521") if h["claim_id"] == "C-1900")["flagged"]


def test_session_lease_blocks_second_repository_and_releases(service):
    session = service.repo.create_session()
    other = SQLiteRepository(service.repo.path)
    with service.repo.session_lock(session):
        with pytest.raises(AppError) as caught, other.session_lock(session):
            pytest.fail("Competing lease acquired")
        assert caught.value.code == "session_busy"
        service.repo.renew_lease(session)
    with other.session_lock(session):
        assert other.session(session)["id"] == session


def test_expired_lease_owner_cannot_renew_replacement(service):
    session = service.repo.create_session()
    with service.repo.session_lock(session):
        with service.repo.connection() as db:
            db.execute("UPDATE sessions SET lease_token='replacement', lease_until=0 WHERE id=?", (session,))
        with pytest.raises(AppError) as caught:
            service.repo.renew_lease(session)
        assert caught.value.status == 409
    with service.repo.connection() as db:
        assert (
            db.execute("SELECT lease_token FROM sessions WHERE id=?", (session,)).fetchone()[0]
            == "replacement"
        )


@pytest.mark.parametrize("state", ["absent", "expired", "replaced"])
def test_batch_commit_requires_current_unexpired_lease(service, state):
    session = service.repo.create_session()
    batch = {
        "id": "lease-test",
        "session_id": session,
        "state": "HUMAN_REVIEW_PENDING",
        "mode": "mock",
        "knowledge_version": "test",
        "results": [],
        "events": [],
    }
    if state == "absent":
        with pytest.raises(AppError) as caught:
            service.repo.save_batch(batch, [])
        assert caught.value.code == "lease_lost"
    else:
        with service.repo.session_lock(session):
            with service.repo.connection() as db:
                if state == "expired":
                    db.execute("UPDATE sessions SET lease_until=0 WHERE id=?", (session,))
                else:
                    db.execute("UPDATE sessions SET lease_token='replacement' WHERE id=?", (session,))
            with pytest.raises(AppError) as caught:
                service.repo.save_batch(batch, [])
            assert caught.value.code == "lease_lost"
    with pytest.raises(AppError):
        service.repo.batch(session, batch["id"])


def test_thread_metadata_and_message_context_persist(service):
    session = service.repo.create_session()
    service.repo.set_thread(session, "coverage", "thread-coverage")
    service.repo.set_thread(session, "intake", "thread-intake")
    service.repo.set_metadata("deployment", {"supervisor": "agent-1"})
    for index in range(105):
        service.repo.add_message(session, "user", str(index))
    reopened = SQLiteRepository(service.repo.path)
    assert reopened.thread(session, "coverage") == "thread-coverage"
    assert reopened.thread(session, "intake") == "thread-intake"
    assert reopened.metadata("deployment") == {"supervisor": "agent-1"}
    assert [row["content"] for row in reopened.messages(session)] == [str(i) for i in range(5, 105)]


def test_schema_mismatch_fails_closed(service):
    with service.repo.connection() as db:
        db.execute("INSERT INTO schema_version VALUES (99)")
    with pytest.raises(AppError) as caught:
        SQLiteRepository(service.repo.path)
    assert caught.value.code == "schema_mismatch"


def test_chat_triage_and_unsupported_requests(service, clean):
    session = service.repo.create_session()
    assert "Submit" in service.chat(session, "hello")["answer"]
    batch = service.chat(session, "triage this batch of claims", [clean], True)
    assert batch["results"][0]["claim_id"] == clean["claim_id"]
    for message in ["", "   ", "x" * 2001]:
        with pytest.raises(AppError) as caught:
            service.chat(session, message)
        assert caught.value.code == "invalid_message"
