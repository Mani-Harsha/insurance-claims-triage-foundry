"""Azure contract tests use the installed SDK models and a deterministic fake service."""

import inspect
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from jsonschema import Draft202012Validator

from claims_triage.azure_runtime import AzureRuntime
from claims_triage.domain import AgentError, AppError
from claims_triage.repository import SQLiteRepository
from claims_triage.tools import ROLE_TOOLS, bound_dispatch, definitions

ROOT = Path(__file__).resolve().parents[1]
pytest.importorskip("azure.ai.agents")


def run(status, *, name="validate_claim", arguments='{"row_index":0}', calls=None):
    result = NS(id="run-1", status=status)
    if status == "requires_action":
        result.required_action = NS(
            type="submit_tool_outputs",
            submit_tool_outputs=NS(
                tool_calls=calls
                or [NS(id="call-1", type="function", function=NS(name=name, arguments=arguments))]
            ),
        )
    return result


class FakeClient:
    def __init__(self):
        self.files = NS(upload_and_poll=Mock(return_value=NS(id="file-1")))
        self.vector_stores = NS(create_and_poll=Mock(return_value=NS(id="vector-1", status="completed")))
        self.create_agent = Mock(side_effect=lambda **kwargs: NS(id=f"agent-{kwargs['metadata']['role']}"))
        self.threads = NS(create=Mock(side_effect=[NS(id=f"thread-{i}") for i in range(10)]))
        self.messages = NS(
            create=Mock(),
            list=Mock(
                return_value=[
                    NS(role="assistant", run_id="old-run", content=[NS(type="text", text=NS(value="stale"))]),
                    NS(
                        role="assistant",
                        run_id="run-1",
                        content=[NS(type="text", text=NS(value="Synthetic summary"))],
                    ),
                ]
            ),
        )
        self.runs = NS(
            create=Mock(return_value=run("requires_action")),
            submit_tool_outputs=Mock(return_value=run("completed")),
            get=Mock(return_value=run("completed")),
            cancel=Mock(),
        )
        self.close = Mock()


@pytest.fixture
def runtime(tmp_path):
    return AzureRuntime(
        SQLiteRepository(tmp_path / "azure.db"),
        "https://example.services.ai.azure.com/api/projects/synthetic",
        "gpt-test",
        ROOT / "knowledge",
        "test-knowledge-version",
        client=FakeClient(),
    )


def dispatch(operation=None, role="intake", tool="validate_claim", args=None):
    return bound_dispatch(
        role,
        tool,
        args or {"row_index": 0},
        operation or (lambda: {"valid": True}),
        lambda query: [{"id": "UW-01", "text": query}],
        "session-test",
    )


def invoke(runtime, handler=None):
    runtime.provision()
    sid = runtime.repo.create_session()
    return runtime.invoke("intake", sid, "validate_claim", {"row_index": 0}, handler or dispatch())


def test_programmatic_four_agent_provision_and_real_sdk_serialization(runtime):
    from azure.ai.agents import AgentsClient
    from azure.ai.agents.models import FunctionToolDefinition

    manifest = runtime.provision()
    assert set(manifest["agents"]) == set(ROLE_TOOLS)
    assert runtime.client.create_agent.call_count == 4
    assert runtime.client.files.upload_and_poll.call_args.kwargs["file_path"].endswith(
        "underwriting_rules.md"
    )
    assert runtime.client.vector_stores.create_and_poll.call_args.kwargs["file_ids"] == ["file-1"]
    for call in runtime.client.create_agent.call_args_list:
        kwargs = call.kwargs
        inspect.signature(AgentsClient.create_agent).bind(None, **kwargs)
        role = kwargs["metadata"]["role"]
        functions = [
            item for item in kwargs["tools"] if isinstance(item, dict) and item["type"] == "function"
        ]
        assert functions == definitions(role)
        for definition in functions:
            assert FunctionToolDefinition(definition).as_dict() == definition
            Draft202012Validator.check_schema(definition["function"]["parameters"])
        assert kwargs["model"] == "gpt-test"
        assert "SYNTHETIC" in kwargs["instructions"]
        if role == "coverage":
            assert any(getattr(item, "type", None) == "file_search" for item in kwargs["tools"])
            assert kwargs["tool_resources"].as_dict() == {"file_search": {"vector_store_ids": ["vector-1"]}}
        else:
            assert "tool_resources" not in kwargs
    assert runtime.provision() == manifest
    assert runtime.client.create_agent.call_count == 4
    runtime.client.files.upload_and_poll.assert_called_once()


def test_provision_resumes_after_partial_failure(runtime):
    runtime.client.create_agent.side_effect = [NS(id="supervisor-existing"), RuntimeError("quota")]
    with pytest.raises(AppError) as caught:
        runtime.provision()
    assert caught.value.code == "provision_failed"
    saved = runtime.repo.metadata("azure_manifest")
    assert saved["agents"] == {"supervisor": "supervisor-existing"}
    runtime.client.create_agent.side_effect = lambda **kwargs: NS(id=f"agent-{kwargs['metadata']['role']}")
    completed = runtime.provision()
    assert len(completed["agents"]) == 4
    assert completed["agents"]["supervisor"] == "supervisor-existing"
    runtime.client.files.upload_and_poll.assert_called_once()
    runtime.client.vector_stores.create_and_poll.assert_called_once()


@pytest.mark.parametrize(
    "attribute,value",
    [
        ("model", "different-model"),
        ("knowledge_version", "changed"),
        ("endpoint", "https://different.example/api/projects/test"),
    ],
)
def test_configuration_mismatch_fails_closed(runtime, attribute, value):
    runtime.provision()
    setattr(runtime, attribute, value)
    with pytest.raises(AppError) as caught:
        runtime.provision()
    assert caught.value.code == "deployment_mismatch"
    assert runtime.client.create_agent.call_count == 4


def test_failed_knowledge_index_never_creates_agents(runtime):
    runtime.client.vector_stores.create_and_poll.return_value.status = "failed"
    with pytest.raises(AgentError) as caught:
        runtime.provision()
    assert caught.value.code == "knowledge_index_failed"
    runtime.client.create_agent.assert_not_called()


def test_tool_output_submission_thread_reuse_and_fresh_narrative(runtime):
    from azure.ai.agents.operations import MessagesOperations, RunsOperations

    runtime.provision()
    sid = runtime.repo.create_session()
    operation = Mock(return_value={"valid": True, "issues": []})
    for _ in range(2):
        reply = runtime.invoke("intake", sid, "validate_claim", {"row_index": 0}, dispatch(operation))
        assert reply.output == {"valid": True, "issues": []}
        assert reply.narrative == "Synthetic summary"
    assert operation.call_count == 2
    runtime.client.threads.create.assert_called_once()
    assert runtime.repo.thread(sid, "intake") == "thread-0"
    submitted = runtime.client.runs.submit_tool_outputs.call_args.kwargs
    assert submitted["thread_id"] == "thread-0"
    assert submitted["tool_outputs"][0]["tool_call_id"] == "call-1"
    assert json.loads(submitted["tool_outputs"][0]["output"]) == reply.output
    inspect.signature(RunsOperations.create).bind(None, **runtime.client.runs.create.call_args.kwargs)
    inspect.signature(RunsOperations.submit_tool_outputs).bind(None, **submitted)
    inspect.signature(MessagesOperations.create).bind(None, **runtime.client.messages.create.call_args.kwargs)
    runtime.client.runs.cancel.assert_not_called()


@pytest.mark.parametrize("status", ["failed", "cancelled", "expired", "incomplete"])
def test_terminal_failure_status_is_surfaced(runtime, status):
    runtime.client.runs.create.return_value = run(status)
    with pytest.raises(AgentError) as caught:
        invoke(runtime)
    assert caught.value.code == f"agent_{status}"
    runtime.client.runs.cancel.assert_called_once()


def test_completed_without_tool_evidence_is_rejected(runtime):
    runtime.client.runs.create.return_value = run("completed")
    with pytest.raises(AgentError) as caught:
        invoke(runtime)
    assert caught.value.code == "missing_tool_evidence"


def test_timeout_cancels_remote_run_without_real_sleep(runtime):
    now = [0.0]
    runtime.clock = lambda: now[0]
    runtime.sleep = lambda seconds: now.__setitem__(0, now[0] + seconds)
    runtime.timeout = 1
    runtime.client.runs.create.return_value = run("queued")
    runtime.client.runs.get.return_value = run("in_progress")
    with pytest.raises(AgentError) as caught:
        invoke(runtime)
    assert caught.value.code == "agent_timeout"
    assert runtime.client.runs.get.call_count == 2
    runtime.client.runs.cancel.assert_called_once()


@pytest.mark.parametrize(
    "name,arguments,code",
    [
        ("build_brief", '{"row_index":0}', "tool_not_allowed"),
        ("validate_claim", '{"row_index":1}', "tool_context_mismatch"),
        ("validate_claim", '{"row_index":0,"claim_amount":1}', "invalid_tool_arguments"),
        ("validate_claim", '{"row_index":true}', "invalid_tool_arguments"),
        ("validate_claim", '{"row_index":-1}', "invalid_tool_arguments"),
        ("validate_claim", '{"row_index":99,"row_index":0}', "invalid_tool_arguments"),
        ("validate_claim", '{"row_index":NaN}', "invalid_tool_arguments"),
        ("validate_claim", "not-json", "invalid_tool_arguments"),
    ],
)
def test_malicious_or_invalid_tool_arguments_never_execute(runtime, name, arguments, code):
    runtime.client.runs.create.return_value = run("requires_action", name=name, arguments=arguments)
    operation = Mock(return_value={"valid": True})
    with pytest.raises(AgentError) as caught:
        invoke(runtime, dispatch(operation))
    assert caught.value.code == code
    operation.assert_not_called()
    runtime.client.runs.submit_tool_outputs.assert_not_called()
    runtime.client.runs.cancel.assert_called_once()


def test_tool_rounds_are_bounded_and_operation_idempotent(runtime):
    runtime.client.runs.submit_tool_outputs.return_value = run("requires_action")
    operation = Mock(return_value={"valid": True})
    with pytest.raises(AgentError) as caught:
        invoke(runtime, dispatch(operation))
    assert caught.value.code == "tool_call_limit"
    operation.assert_called_once()
    assert runtime.client.runs.submit_tool_outputs.call_count == 6


def test_too_many_simultaneous_calls_rejected(runtime):
    calls = [
        NS(id=f"call-{i}", type="function", function=NS(name="validate_claim", arguments='{"row_index":0}'))
        for i in range(6)
    ]
    runtime.client.runs.create.return_value = run("requires_action", calls=calls)
    with pytest.raises(AgentError) as caught:
        invoke(runtime)
    assert caught.value.code == "tool_call_limit"
    runtime.client.runs.submit_tool_outputs.assert_not_called()


def test_unprovisioned_invocation_and_wrong_requested_tool(runtime):
    sid = runtime.repo.create_session()
    with pytest.raises(AgentError) as caught:
        runtime.invoke("intake", sid, "validate_claim", {"row_index": 0}, dispatch())
    assert caught.value.code == "agents_not_provisioned"
    runtime.provision()
    with pytest.raises(AgentError) as caught:
        runtime.invoke("intake", sid, "build_brief", {"row_index": 0}, dispatch())
    assert caught.value.code == "tool_not_allowed"
    runtime.client.threads.create.assert_not_called()


def test_tool_failure_and_cancel_failure_do_not_leak_exception(runtime):
    runtime.client.runs.cancel.side_effect = RuntimeError("credential-secret")
    with pytest.raises(AgentError) as caught:
        invoke(runtime, dispatch(Mock(side_effect=RuntimeError("tool-secret"))))
    assert caught.value.code == "agent_failed"
    assert "secret" not in str(caught.value)


def test_close_releases_client_and_credential(runtime):
    runtime.credential = Mock()
    runtime.close()
    runtime.client.close.assert_called_once()
    runtime.credential.close.assert_called_once()


def test_real_sdk_enum_statuses_are_supported(runtime):
    from azure.ai.agents.models import MessageRole, RunStatus, VectorStoreStatus

    runtime.client.vector_stores.create_and_poll.return_value.status = VectorStoreStatus.COMPLETED
    runtime.client.runs.create.return_value.status = RunStatus.REQUIRES_ACTION
    runtime.client.runs.submit_tool_outputs.return_value.status = RunStatus.COMPLETED
    runtime.client.messages.list.return_value[-1].role = MessageRole.AGENT
    reply = invoke(runtime)
    assert reply.output == {"valid": True}
    assert reply.narrative == "Synthetic summary"
