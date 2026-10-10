"""Streamlit widgets -> HTTP client -> real API/service/retrieval/SQLite via ASGI transport."""

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from claims_triage.api import create_app
from claims_triage.bootstrap import create_service
from claims_triage.config import Settings
from claims_triage.domain import AppError
from claims_triage.showcase import ShowcaseClient, requirement_rows

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "ui-test-synthetic-token-0123456789"


@pytest.fixture
def ui_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIAGE_API_TOKEN", TOKEN)
    monkeypatch.setenv("TRIAGE_MODE", "mock")
    settings = Settings(
        mode="mock",
        database=tmp_path / "ui.db",
        data_dir=ROOT / "data",
        knowledge_dir=ROOT / "knowledge",
        api_token=TOKEN,
        _env_file=None,
    )
    service = create_service(settings)
    service.today = lambda: date(2026, 10, 9)
    with TestClient(create_app(settings, service)) as api:

        def request(self, method, path, **kwargs):
            response = api.request(method, path, headers={"Authorization": f"Bearer {self.token}"}, **kwargs)
            if response.is_error:
                error = response.json()["error"]
                raise AppError(error["code"], error["message"], response.status_code)
            return response.json()

        monkeypatch.setattr(ShowcaseClient, "request", request)
        yield api


def app():
    result = AppTest.from_file(str(ROOT / "ui/app.py"), default_timeout=45).run()
    assert not result.exception
    return result


def button(ui, label):
    return next(item for item in ui.button if item.label == label)


def triage(ui, source="Starter property claims"):
    ui.button(key="new_session").click().run()
    ui.radio(key="claim_source").set_value(source)
    ui.checkbox(key="synthetic_confirm").check().run()
    ui.button(key="run_triage").click().run()
    assert not ui.exception
    assert not ui.error
    return ui.session_state["active_batch"]


def test_dashboard_starts_with_all_35_requirements(ui_environment):
    ui = app()
    assert len(requirement_rows(ROOT, set())) == 35
    assert next(m.value for m in ui.metric if m.label == "Requirement groups") == "35"
    assert next(m.value for m in ui.metric if m.label == "Observed in this showcase") == "0"
    assert ui.button(key="run_triage").disabled
    for role, names in {
        "Supervisor": "route_request", "Intake": "validate_claim",
        "Coverage": "check_coverage, search_knowledge", "Briefing": "build_brief",
    }.items():
        assert any(item.label == f"{role} agent · {names}" for item in ui.expander)
    assert any("not a tool execution log" in item.value for item in ui.caption)


def test_full_ui_triage_grounding_chat_review_and_dashboard(ui_environment):
    ui = app()
    batch = triage(ui)
    assert [r["brief"]["recommended_action"] for r in batch["results"]] == [
        "route_to_investigator",
        "auto_approve",
        "route_to_investigator",
        "request_more_documentation",
    ]
    assert any("UW06" in m.value for m in ui.markdown)
    assert {"R11", "R15", "R17"} <= ui.session_state["observed"]
    button(ui, "Ask supervisor").click().run()
    assert "C-1900" in ui.session_state["last_answer"]["answer"]
    ui.text_input(key="question").set_value("Explain its recommendation")
    button(ui, "Ask supervisor").click().run()
    assert ui.session_state["last_answer"]["claim_id"] == "C-2031"
    ui.selectbox(key=f"claim_{batch['id']}").select(1).run()
    ui.text_area(key=f"note_{batch['id']}_1").set_value("Reviewed synthetic evidence")
    button(ui, "Record human decision").click().run()
    assert not ui.exception
    assert ui.session_state["active_batch"]["results"][1]["review"]["decision"] == "approve"
    assert {"R16", "R18", "R19"} <= ui.session_state["observed"]
    ui.selectbox(key="requirement_filter").select("Observed in this showcase").run()
    assert not ui.exception


def test_unsafe_approval_and_invalid_note_are_visible(ui_environment):
    ui = app()
    batch = triage(ui)
    ui.selectbox(key=f"decision_{batch['id']}_0").select("approve")
    ui.text_area(key=f"note_{batch['id']}_0").set_value("Intentional guard demonstration")
    button(ui, "Record human decision").click().run()
    assert any("unsafe_approval" in error.value for error in ui.error)
    assert not ui.exception
    ui.selectbox(key=f"decision_{batch['id']}_0").select("investigate")
    ui.text_area(key=f"note_{batch['id']}_0").set_value("x")
    button(ui, "Record human decision").click().run()
    assert ui.error


@pytest.mark.parametrize(
    "source,count", [("Auto claims (CSV)", 2), ("Validation edge cases", 4), ("Coverage edge cases", 4)]
)
def test_prepared_scenarios(ui_environment, source, count):
    ui = app()
    batch = triage(ui, source)
    assert len(batch["results"]) == count
    if source == "Validation edge cases":
        assert {"R03", "R04", "R05", "R06"} <= ui.session_state["observed"]
    if source == "Coverage edge cases":
        codes = {issue["code"] for row in batch["results"] for issue in row["coverage"]["issues"]}
        assert {"over_limit", "policy_inactive", "peril_not_covered", "late_report"} <= codes


def test_uploaded_json_and_malformed_upload(ui_environment):
    ui = app()
    ui.button(key="new_session").click().run()
    ui.radio(key="claim_source").set_value("Upload JSON / CSV").run()
    ui.file_uploader(key="claim_file").set_value(
        ("claims.json", (ROOT / "data/claims.json").read_bytes(), "application/json")
    )
    ui.checkbox(key="synthetic_confirm").check().run()
    ui.button(key="run_triage").click().run()
    assert not ui.exception
    assert len(ui.session_state["active_batch"]["results"]) == 4
    ui.file_uploader(key="claim_file").set_value(("bad.json", b"not-json", "application/json")).run()
    ui.button(key="run_triage").click().run()
    assert any("malformed_input" in error.value for error in ui.error)


def test_new_browser_session_restores_saved_evidence_and_conversation(ui_environment):
    ui = app()
    batch = triage(ui)
    sid = ui.session_state["session_id"]
    button(ui, "Ask supervisor").click().run()
    restored = app()
    restored.text_input(key="resume_id").set_value(sid)
    button(restored, "Resume session").click().run()
    assert not restored.exception
    assert restored.session_state["active_batch"]["id"] == batch["id"]
    assert any("C-1900" in text.value for text in restored.text)
    assert "R23" in restored.session_state["observed"]


def test_batch_list_authentication_and_session_scope(ui_environment):
    api = ui_environment
    assert api.get("/sessions/missing/batches").status_code == 401
    headers = {"Authorization": f"Bearer {TOKEN}"}
    sid = api.post("/sessions", headers=headers).json()["session_id"]
    assert api.get(f"/sessions/{sid}/batches", headers=headers).json() == {"batches": []}
    assert api.get("/sessions/missing/batches", headers=headers).status_code == 404


def test_http_adapter_errors_are_sanitized(monkeypatch):
    import httpx

    def unavailable(*args, **kwargs):
        raise httpx.ConnectError("secret credential details")

    monkeypatch.setattr(httpx, "request", unavailable)
    with pytest.raises(AppError, match="Cannot reach"):
        ShowcaseClient("http://localhost", TOKEN).request("GET", "/health")


def test_dashboard_does_not_claim_live_azure_from_mock(ui_environment):
    ui = app()
    triage(ui)
    assert not {"R20", "R21"} & ui.session_state["observed"]
    ui.selectbox(key="requirement_filter").select("Azure / live verification").run()
    assert any("require separate verification" in item.value for item in ui.warning)
    assert "SYNTHETIC" in ui.caption[0].value
