"""HTTP integration tests use the real service, SQLite, retrieval and mock agents."""

import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from claims_triage.api import create_app
from claims_triage.bootstrap import create_service
from claims_triage.config import Settings
from claims_triage.domain import AppError
from claims_triage.ingestion import MAX_BYTES

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "synthetic-test-token-0123456789"


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        mode="mock",
        database=tmp_path / "api.db",
        data_dir=ROOT / "data",
        knowledge_dir=ROOT / "knowledge",
        api_token=TOKEN,
        _env_file=None,
    )
    service = create_service(settings)
    service.today = lambda: date(2026, 10, 9)
    with TestClient(create_app(settings, service), raise_server_exceptions=False) as connection:
        connection.headers["Authorization"] = f"Bearer {TOKEN}"
        yield connection


@pytest.fixture
def claims():
    return json.loads((ROOT / "data/claims.json").read_text())


def session(client):
    response = client.post("/sessions")
    assert response.status_code == 201
    return response.json()["session_id"]


def batch(client, sid, claims):
    response = client.post(f"/sessions/{sid}/batches", json={"synthetic": True, "claims": claims})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("POST", "/sessions", None),
        ("GET", "/sessions/missing/messages", None),
        ("POST", "/sessions/missing/batches", {"synthetic": True, "claims": [{}]}),
        ("POST", "/sessions/missing/uploads?format=json&synthetic=true", None),
        ("GET", "/sessions/missing/batches/missing", None),
        ("POST", "/sessions/missing/chat", {"message": "hello"}),
        ("POST", "/sessions/missing/batches/missing/reviews/0", {"decision": "approve", "note": "reviewed"}),
    ],
)
@pytest.mark.parametrize("authorization", [None, "Bearer incorrect", "Basic wrong"])
def test_all_data_routes_require_authentication(client, method, path, payload, authorization):
    client.headers.pop("Authorization")
    headers = {"Authorization": authorization} if authorization else {}
    response = client.request(method, path, json=payload, headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.headers["www-authenticate"] == "Bearer"


def test_health_and_openapi_contract(client):
    client.headers.pop("Authorization")
    assert client.get("/health").json() == {"status": "ok", "mode": "mock", "synthetic": True}
    schema = client.get("/openapi.json").json()
    assert "HTTPBearer" in schema["components"]["securitySchemes"]
    for path, methods in schema["paths"].items():
        if path != "/health":
            for operation in methods.values():
                assert operation["security"] == [{"HTTPBearer": []}]


def test_weak_api_token_refuses_startup():
    with pytest.raises(AppError) as caught:
        create_app(Settings(api_token="weak", _env_file=None))
    assert caught.value.code == "api_token_required"


@pytest.mark.parametrize("media_type,file_format", [("application/json", "json"), ("text/csv", "csv")])
def test_swagger_upload_examples_execute(client, media_type, file_format):
    schema = client.get("/openapi.json").json()
    content = schema["paths"]["/sessions/{session_id}/uploads"]["post"]["requestBody"]["content"]
    example = content[media_type]["example"]
    response = client.post(
        f"/sessions/{session(client)}/uploads?format={file_format}&synthetic=true",
        content=json.dumps(example) if file_format == "json" else example,
        headers={"Content-Type": media_type},
    )
    assert response.status_code == 201, response.text
    assert response.json()["state"] == "HUMAN_REVIEW_PENDING"
    assert all(not row["service_issues"] for row in response.json()["results"])


def test_swagger_starter_and_conversation_examples_execute(client, claims):
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    example = paths["/sessions/{session_id}/batches"]["post"]["requestBody"]["content"]["application/json"]["examples"]["starter"]["value"]
    assert example["claims"] == claims
    sid = session(client)
    response = client.post(f"/sessions/{sid}/batches", json=example)
    assert response.status_code == 201
    examples = paths["/sessions/{session_id}/chat"]["post"]["requestBody"]["content"]["application/json"]["examples"]
    for name in ("explain", "followup"):
        answer = client.post(f"/sessions/{sid}/chat", json=examples[name]["value"])
        assert answer.status_code == 200
        assert answer.json()["claim_id"] == "C-2031"
        assert "C-1900" in answer.json()["answer"]


def test_complete_batch_chat_and_human_review(client, claims):
    sid = session(client)
    result = batch(client, sid, claims)
    assert result["state"] == "HUMAN_REVIEW_PENDING"
    assert all(row["brief"]["review_status"] == "pending" for row in result["results"])
    answer = client.post(f"/sessions/{sid}/chat", json={"message": "Why was claim C2031 flagged?"})
    assert answer.status_code == 200
    assert answer.json()["claim_id"] == "C-2031"
    assert "C-1900" in answer.json()["answer"]
    followup = client.post(f"/sessions/{sid}/chat", json={"message": "Explain its recommendation"})
    assert followup.json()["claim_id"] == "C-2031"
    assert len(client.get(f"/sessions/{sid}/messages").json()["messages"]) == 6
    review_path = f"/sessions/{sid}/batches/{result['id']}/reviews"
    denied = client.post(f"{review_path}/0", json={"decision": "approve", "note": "Checked evidence"})
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "unsafe_approval"
    for index, decision in enumerate(["investigate", "approve", "investigate", "request_documentation"]):
        response = client.post(
            f"{review_path}/{index}", json={"decision": decision, "note": "Checked synthetic evidence"}
        )
        assert response.status_code == 200
        assert response.json()["reviewer"] == "api-adjuster"
    reviewed = client.get(f"/sessions/{sid}/batches/{result['id']}").json()
    assert reviewed["state"] == "REVIEWED"
    assert all(row["brief"]["review_status"] == "reviewed" for row in reviewed["results"])
    duplicate = client.post(f"{review_path}/1", json={"decision": "approve", "note": "Again"})
    assert duplicate.status_code == 409


def test_session_evidence_isolation(client, claims):
    sid, other = session(client), session(client)
    result = batch(client, sid, claims)
    assert client.get(f"/sessions/{other}/batches/{result['id']}").status_code == 404
    assert client.get(f"/sessions/{other}/messages").json()["messages"] == []
    explanation = client.post(f"/sessions/{other}/chat", json={"message": "Why was C2031 flagged?"})
    assert explanation.json()["evidence"] == []
    assert (
        client.post(
            f"/sessions/{other}/batches/{result['id']}/reviews/1",
            json={"decision": "approve", "note": "Wrong session"},
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"synthetic": True, "claims": []},
        {"synthetic": "true", "claims": [{}]},
        {"synthetic": 1, "claims": [{}]},
        {"synthetic": True, "claims": [1]},
        {"synthetic": True, "claims": [{}] * 101},
        {"synthetic": True, "claims": [{}], "extra": "forbidden"},
    ],
)
def test_batch_schema_validation(client, payload):
    response = client.post(f"/sessions/{session(client)}/batches", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_synthetic_opt_in_all_ingestion_routes(client, claims):
    sid = session(client)
    responses = [
        client.post(f"/sessions/{sid}/batches", json={"synthetic": False, "claims": claims}),
        client.post(f"/sessions/{sid}/chat", json={"message": "triage this batch", "claims": claims}),
        client.post(f"/sessions/{sid}/uploads?format=json", content=json.dumps(claims)),
    ]
    for response in responses:
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "synthetic_required"


@pytest.mark.parametrize("format", ["json", "csv"])
def test_raw_file_upload(client, format):
    sid = session(client)
    response = client.post(
        f"/sessions/{sid}/uploads?format={format}&synthetic=true",
        content=(ROOT / f"data/claims.{format}").read_bytes(),
        headers={"Content-Type": "application/json" if format == "json" else "text/csv"},
    )
    assert response.status_code == 201
    assert len(response.json()["results"]) == 4


@pytest.mark.parametrize(
    "content", [b"{invalid", b'{"synthetic":true,"synthetic":false}', b'{"claims":[NaN]}', b"\xff"]
)
def test_malformed_or_ambiguous_json_rejected(client, content):
    response = client.post(
        f"/sessions/{session(client)}/batches", content=content, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "malformed_input"


def test_oversized_body_rejected_even_without_content_length(client):
    sid = session(client)
    response = client.post(
        f"/sessions/{sid}/uploads?format=json&synthetic=true",
        content=iter([b"x" * (MAX_BYTES // 2), b"x" * (MAX_BYTES // 2 + 1)]),
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "input_too_large"


def test_unknown_session_and_invalid_review_contract(client):
    assert client.get("/sessions/missing/messages").status_code == 404
    sid = session(client)
    for payload in [
        {"decision": "pay", "note": "Reviewed"},
        {"decision": "approve", "note": "x"},
        {"decision": "approve", "note": "Reviewed", "reviewer": "spoofed"},
    ]:
        assert client.post(f"/sessions/{sid}/batches/missing/reviews/0", json=payload).status_code == 422


def test_unexpected_error_is_sanitized(client, monkeypatch):
    def fail():
        raise RuntimeError("SECRET should never leave the server")

    monkeypatch.setattr(client.app.state.service.repo, "create_session", fail)
    response = client.post("/sessions")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "SECRET" not in response.text
