"""ChatRuntime 通用生命周期事件构造测试。"""

from collections.abc import AsyncIterator
from types import SimpleNamespace

from cygnusx.application.services.chat.runtimes.base import ChatRuntime, ChatRuntimeRequest
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk


class _Runtime(ChatRuntime):
    async def run(self, request: ChatRuntimeRequest) -> AsyncIterator[ChatChunk]:
        del request
        yield ChatChunk(type="done")


def _context() -> SimpleNamespace:
    return SimpleNamespace(
        session_id="session-1",
        run_id="run-1",
        agent=SimpleNamespace(agent_id="agent-1"),
        round_number=2,
        execution_path="chat_runtime",
    )


def test_runtime_builds_ask_user_and_handoff_events_with_execution_metadata() -> None:
    runtime = _Runtime()
    context = _context()

    ask_user = runtime._build_ask_user(context, "请选择下一步")
    handoff = runtime._build_handoff(context, "agent-2")

    assert ask_user.type == "ask_user"
    assert ask_user.content == "请选择下一步"
    assert ask_user.metadata["run_id"] == "run-1"
    assert handoff.type == "handoff"
    assert handoff.metadata["target_agent_id"] == "agent-2"
