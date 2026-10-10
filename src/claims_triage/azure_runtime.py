"""Foundry Agent Service adapter pinned to the azure-ai-agents 1.1.0 API.

All service calls are here. Importing/running mock mode never authenticates to Azure.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .domain import AgentError, AppError, Json
from .ingestion import reject_constant, unique_object
from .observability import log
from .ports import AgentReply, Repository, ToolDispatch
from .tools import AGENT_INSTRUCTIONS, ROLE_TOOLS, definitions


def enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


class AzureRuntime:
    mode = "azure"

    def __init__(
        self,
        repository: Repository,
        endpoint: str,
        model: str,
        knowledge_dir: Path,
        knowledge_version: str,
        timeout: float = 60,
        client: Any = None,
        clock: Any = time.monotonic,
        sleep: Any = time.sleep,
    ):
        self.repo, self.endpoint, self.model = repository, endpoint, model
        self.knowledge_dir, self.knowledge_version, self.timeout = knowledge_dir, knowledge_version, timeout
        self.clock, self.sleep = clock, sleep
        self.credential: Any = None
        if client is None:
            from azure.ai.agents import AgentsClient
            from azure.identity import DefaultAzureCredential

            self.credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
            client = AgentsClient(
                endpoint=endpoint,
                credential=self.credential,
                connection_timeout=10,
                read_timeout=20,
                retry_total=0,
            )
        self.client = client

    @property
    def fingerprint(self) -> str:
        content = json.dumps(
            {
                "endpoint": self.endpoint,
                "model": self.model,
                "knowledge": self.knowledge_version,
                "instructions": AGENT_INSTRUCTIONS,
                "tools": {r: definitions(r) for r in ROLE_TOOLS},
            },
            sort_keys=True,
        )
        return hashlib.sha256(content.encode()).hexdigest()

    def provision(self) -> Json:
        """Create four agents programmatically; resume partially completed provisioning."""
        from azure.ai.agents.models import FileSearchTool

        manifest = self.repo.metadata("azure_manifest") or {"fingerprint": self.fingerprint, "agents": {}}
        if manifest["fingerprint"] != self.fingerprint:
            raise AppError(
                "deployment_mismatch",
                "Configuration changed. Use a separate database/profile for a new agent deployment.",
                409,
            )
        try:
            if not manifest.get("file_id"):
                uploaded = self.client.files.upload_and_poll(
                    file_path=str(self.knowledge_dir / "underwriting_rules.md"),
                    purpose="assistants",
                    timeout=self.timeout,
                )
                manifest["file_id"] = uploaded.id
                self.repo.set_metadata("azure_manifest", manifest)
            if not manifest.get("vector_store_id"):
                store = self.client.vector_stores.create_and_poll(
                    file_ids=[manifest["file_id"]], name="synthetic-claims-underwriting", timeout=self.timeout
                )
                if enum_value(store.status) != "completed":
                    raise AgentError("knowledge_index_failed")
                manifest["vector_store_id"] = store.id
                self.repo.set_metadata("azure_manifest", manifest)
            file_search = FileSearchTool(vector_store_ids=[manifest["vector_store_id"]])
            for role in ROLE_TOOLS:
                if role in manifest["agents"]:
                    continue
                tools: list[Any] = list(definitions(role))
                options: Json = {}
                if role == "coverage":
                    tools += file_search.definitions
                    options["tool_resources"] = file_search.resources
                agent = self.client.create_agent(
                    model=self.model,
                    name=f"synthetic-claims-{role}",
                    instructions=AGENT_INSTRUCTIONS[role],
                    tools=tools,
                    metadata={"application": "synthetic-claims-triage", "role": role},
                    **options,
                )
                manifest["agents"][role] = agent.id
                self.repo.set_metadata("azure_manifest", manifest)
                log("agent_provisioned", agent=role)
            return manifest
        except AppError:
            raise
        except Exception as exc:
            log("provision_failed", error_type=type(exc).__name__)
            raise AppError(
                "provision_failed",
                "Foundry provisioning failed. Check endpoint, access, model and quota. Partial resource IDs are saved for retry.",
                503,
            ) from exc

    def invoke(
        self, role: str, session_id: str, tool: str, arguments: Json, dispatch: ToolDispatch
    ) -> AgentReply:
        manifest = self.repo.metadata("azure_manifest")
        if (
            not manifest
            or manifest.get("fingerprint") != self.fingerprint
            or role not in manifest.get("agents", {})
        ):
            raise AgentError("agents_not_provisioned")
        if tool not in ROLE_TOOLS[role]:
            raise AgentError("tool_not_allowed")
        run: Any = None
        thread_id = self.repo.thread(session_id, role)
        start = self.clock()
        output: Json | None = None
        try:
            if not thread_id:
                thread_id = self.client.threads.create().id
                self.repo.set_thread(session_id, role, thread_id)
            self.client.messages.create(
                thread_id=thread_id,
                role="user",
                content=json.dumps(
                    {
                        "task": "Execute the specified tool with these exact context-bound arguments, then summarize its evidence.",
                        "tool": tool,
                        "arguments": arguments,
                        "synthetic": True,
                    }
                ),
            )
            run = self.client.runs.create(
                thread_id=thread_id,
                agent_id=manifest["agents"][role],
                tool_choice={"type": "function", "function": {"name": tool}},
                parallel_tool_calls=False,
                max_completion_tokens=1200,
            )
            tool_rounds = 0
            while True:
                if self.clock() - start >= self.timeout:
                    raise AgentError("agent_timeout")
                status = enum_value(run.status)
                if status == "completed":
                    if output is None:
                        raise AgentError("missing_tool_evidence")
                    # Supplemental model text is kept separate from authoritative tool evidence.
                    narrative = ""
                    for message in self.client.messages.list(thread_id=thread_id, order="desc", limit=10):
                        if (
                            enum_value(message.role) == "assistant"
                            and getattr(message, "run_id", None) == run.id
                        ):
                            narrative = "\n".join(
                                part.text.value for part in message.content if enum_value(part.type) == "text"
                            )
                            break
                    return AgentReply(output, narrative)
                if status in {"failed", "cancelled", "expired", "incomplete"}:
                    raise AgentError(f"agent_{status}")
                if status == "requires_action":
                    tool_rounds += 1
                    if tool_rounds > 6:
                        raise AgentError("tool_call_limit")
                    action = run.required_action
                    if enum_value(action.type) != "submit_tool_outputs":
                        raise AgentError("unsupported_agent_action")
                    calls = action.submit_tool_outputs.tool_calls
                    if not calls or len(calls) > 5:
                        raise AgentError("tool_call_limit")
                    outputs = []
                    for call in calls:
                        if enum_value(call.type) != "function":
                            raise AgentError("tool_not_allowed")
                        try:
                            if len(call.function.arguments) > 4096:
                                raise ValueError("Tool arguments too large")
                            args = json.loads(
                                call.function.arguments,
                                parse_constant=reject_constant,
                                object_pairs_hook=unique_object,
                            )
                        except (ValueError, TypeError, RecursionError) as exc:
                            raise AgentError("invalid_tool_arguments") from exc
                        value = dispatch(call.function.name, args)
                        if call.function.name == tool:
                            output = value
                        outputs.append(
                            {
                                "tool_call_id": call.id,
                                "output": json.dumps(value, default=str, allow_nan=False),
                            }
                        )
                    run = self.client.runs.submit_tool_outputs(
                        thread_id=thread_id, run_id=run.id, tool_outputs=outputs
                    )
                elif status in {"queued", "in_progress", "cancelling"}:
                    self.sleep(min(0.5, max(0, self.timeout - (self.clock() - start))))
                    run = self.client.runs.get(thread_id=thread_id, run_id=run.id)
                else:
                    raise AgentError("unknown_run_state")
        except Exception as exc:
            if run is not None and thread_id:
                try:
                    self.client.runs.cancel(thread_id=thread_id, run_id=run.id)
                except Exception:
                    log("agent_cancel_failed", agent=role, session_id=session_id)
            if isinstance(exc, AgentError):
                raise
            raise AgentError("agent_failed") from exc

    def close(self) -> None:
        self.client.close()
        if self.credential:
            self.credential.close()
