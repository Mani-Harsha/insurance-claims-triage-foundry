from .domain import Json
from .ports import AgentReply, ToolDispatch


class MockRuntime:
    """Only the LLM/service transport is mocked; all tools, storage and retrieval are real."""

    mode = "mock"

    def invoke(
        self, role: str, session_id: str, tool: str, arguments: Json, dispatch: ToolDispatch
    ) -> AgentReply:
        return AgentReply(dispatch(tool, arguments))

    def close(self) -> None:
        pass
