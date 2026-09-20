"""LangGraph Agent Runtime 的终态事件测试。"""

from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

import cygnusx.application.services.chat.runtimes.langgraph_runtime as lg_module
from cygnusx.application.services.chat.dual_run import (
    assert_equivalent,
    compare_golden_record,
)
from cygnusx.application.services.chat.runtimes.langgraph_runtime import (
    LangGraphChatRuntime,
    _gate_chat_sandbox_approval,
)
from cygnusx.application.services.execution_events import validate_event_sequence
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk

_GOLDEN_ROOT = Path(__file__).parents[2] / "e2e" / "chat_golden"


class _Service:
    def __init__(self, sandbox_meta: dict | None = None) -> None:
        self.update_message_content = AsyncMock()
        self._apply_usage_to_session = AsyncMock()
        self._session = SimpleNamespace(sandbox_meta=sandbox_meta)
        self.get_session = AsyncMock(return_value=self._session)


async def _stream_chunks(
    runtime: LangGraphChatRuntime,
    **overrides: Any,
) -> list[ChatChunk]:
    defaults: dict[str, Any] = {
        "user_id": "user-1",
        "session_id": "session-1",
        "ai_message_id": "message-1",
        "model_config": SimpleNamespace(model="test-model"),
        "llm_messages": [],
        "system_prompt": None,
        "tools": [],
        "temperature": 0.2,
        "max_tokens": 128,
        "deep_thinking": False,
        "active_mcp_servers": [],
        "mcp_client": SimpleNamespace(),
        "tool_context": SimpleNamespace(agent_id="agent-1"),
    }
    defaults.update(overrides)
    return [
        chunk
        async for chunk in runtime._stream_agent_chat_langgraph(**defaults)
    ]


@pytest.mark.asyncio
async def test_langgraph_runtime_error_stream_emits_failed_terminal_and_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingRuntime:
        def __init__(self, *_: Any, **__: Any) -> None:
            self.last_usage = None
            self.last_handoff = None
            self.last_ask_request = None
            self.rounds_exhausted = False

        async def stream(self, _: list[dict[str, Any]]) -> AsyncIterator[ChatChunk]:
            yield ChatChunk(type="error", content="provider unavailable")

    import cygnusx.infrastructure.execution.langgraph_runtime as runtime_module

    monkeypatch.setattr(runtime_module, "LangGraphRuntimeService", _FailingRuntime)
    service = _Service()
    runtime = LangGraphChatRuntime(service)  # type: ignore[arg-type]
    chunks = await _stream_chunks(runtime)

    assert [chunk.type for chunk in chunks] == [
        "agent_turn_started",
        "error",
        "agent_turn_failed",
        "done",
    ]
    validate_event_sequence(chunks)
    service.update_message_content.assert_awaited_once()

    result = await compare_golden_record(
        "langgraph-runtime-error",
        _GOLDEN_ROOT / "langgraph-runtime-error.json",
        lambda: runtime._stream_agent_chat_langgraph(
            user_id="user-1",
            session_id="session-1",
            ai_message_id="message-1",
            model_config=SimpleNamespace(model="test-model"),
            llm_messages=[],
            system_prompt=None,
            tools=[],
            temperature=0.2,
            max_tokens=128,
            deep_thinking=False,
            active_mcp_servers=[],
            mcp_client=SimpleNamespace(),
            tool_context=SimpleNamespace(agent_id="agent-1"),
        ),
    )

    assert_equivalent([result])


@pytest.mark.asyncio
async def test_unhandled_langgraph_handoff_emits_failed_terminal_and_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _HandoffRuntime:
        def __init__(self, *_: Any, **__: Any) -> None:
            self.last_usage = None
            self.last_handoff = {"target_agent_id": "agent-2"}
            self.last_ask_request = None
            self.rounds_exhausted = False

        async def stream(self, _: list[dict[str, Any]]) -> AsyncIterator[ChatChunk]:
            if False:
                yield ChatChunk(type="text")

    import cygnusx.infrastructure.execution.langgraph_runtime as runtime_module

    monkeypatch.setattr(runtime_module, "LangGraphRuntimeService", _HandoffRuntime)
    service = _Service()
    chunks = await _stream_chunks(LangGraphChatRuntime(service))  # type: ignore[arg-type]

    assert [chunk.type for chunk in chunks] == [
        "agent_turn_started",
        "error",
        "agent_turn_failed",
        "done",
    ]
    validate_event_sequence(chunks)
    service.update_message_content.assert_awaited_once()


class _FakeApprovalService:
    """假审批服务：create 返回 pending 记录，wait_resolution 返回预设决议。"""

    def __init__(self, resolution: dict[str, Any]) -> None:
        self.resolution = resolution
        self.created: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> dict[str, Any]:
        record = {"approval_id": "approval-1", "risk_hint": kwargs.get("risk_hint", ""), **kwargs}
        self.created.append(record)
        return record

    async def wait_resolution(
        self, approval_id: str, timeout: int = 300  # noqa: ASYNC109 - 假服务签名对齐真实现
    ) -> dict[str, Any]:
        return self.resolution


def _gate_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "emit": AsyncMock(),
        "user_id": "user-1",
        "session_id": "session-1",
        "tool_call_id": "call-1",
        "args": {"language": "python", "code": "print(1)"},
        "permission_mode": "supervised",
        "always_allow": set(),
    }
    kwargs.update(overrides)
    return kwargs


@pytest.mark.asyncio
async def test_gate_skipped_when_permission_mode_not_supervised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeApprovalService({"action": "approved"})
    monkeypatch.setattr(lg_module, "get_studio_approval_service", lambda: service)

    args, rejection = await _gate_chat_sandbox_approval(
        **_gate_kwargs(permission_mode=None)
    )

    assert rejection is None
    assert service.created == []


@pytest.mark.asyncio
async def test_gate_skipped_when_tool_always_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _FakeApprovalService({"action": "approved"})
    monkeypatch.setattr(lg_module, "get_studio_approval_service", lambda: service)

    _, rejection = await _gate_chat_sandbox_approval(
        **_gate_kwargs(always_allow={"chat_sandbox_execute"})
    )

    assert rejection is None
    assert service.created == []


@pytest.mark.asyncio
async def test_gate_approved_emits_request_and_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeApprovalService({"action": "approved"})
    monkeypatch.setattr(lg_module, "get_studio_approval_service", lambda: service)
    emit = AsyncMock()

    args, rejection = await _gate_chat_sandbox_approval(**_gate_kwargs(emit=emit))

    assert rejection is None
    assert args == {"language": "python", "code": "print(1)"}
    emitted = [c.args[0] for c in emit.await_args_list]
    assert [c.type for c in emitted] == ["approval_request", "approval_resolved"]
    request = emitted[0]
    assert request.metadata["tool_name"] == "chat_sandbox_execute"
    assert request.metadata["timeout_seconds"] == 300
    assert request.metadata["risk_hint"] == "将在沙盒中执行 python 代码"
    assert emitted[1].metadata == {
        "approval_id": "approval-1",
        "tool_call_id": "call-1",
        "action": "approved",
    }
    # 决议工具名/参数与 legacy 一致地写入审批记录
    assert service.created[0]["tool_name"] == "chat_sandbox_execute"
    assert service.created[0]["arguments"] == {"language": "python", "code": "print(1)"}


@pytest.mark.asyncio
async def test_gate_approved_with_always_adds_to_always_allow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeApprovalService({"action": "approved", "always": True})
    monkeypatch.setattr(lg_module, "get_studio_approval_service", lambda: service)
    always_allow: set[str] = set()

    _, rejection = await _gate_chat_sandbox_approval(**_gate_kwargs(always_allow=always_allow))

    assert rejection is None
    assert always_allow == {"chat_sandbox_execute"}


@pytest.mark.asyncio
async def test_gate_edited_replaces_args(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _FakeApprovalService(
        {"action": "edited", "modified_args": {"language": "python", "code": "print(2)"}}
    )
    monkeypatch.setattr(lg_module, "get_studio_approval_service", lambda: service)

    args, rejection = await _gate_chat_sandbox_approval(**_gate_kwargs())

    assert rejection is None
    assert args == {"language": "python", "code": "print(2)"}


@pytest.mark.asyncio
async def test_gate_rejected_returns_rejection_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeApprovalService({"action": "rejected", "reason": "不允许跑这个"})
    monkeypatch.setattr(lg_module, "get_studio_approval_service", lambda: service)
    emit = AsyncMock()

    _, rejection = await _gate_chat_sandbox_approval(**_gate_kwargs(emit=emit))

    assert rejection == {
        "success": False,
        "rejected": True,
        "result": {
            "llm_payload": {"rejected": True, "error": "不允许跑这个"},
            "ui_payload": {"rejected": True, "error": "不允许跑这个"},
        },
    }
    emitted = [c.args[0] for c in emit.await_args_list]
    assert emitted[-1].type == "approval_resolved"
    assert emitted[-1].metadata["action"] == "rejected"


@pytest.mark.asyncio
async def test_gate_timeout_records_audit_and_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeApprovalService({"action": "timeout"})
    monkeypatch.setattr(lg_module, "get_studio_approval_service", lambda: service)
    audits: list[dict[str, Any]] = []
    monkeypatch.setattr(
        lg_module,
        "record_approval_audit",
        AsyncMock(side_effect=lambda **kw: audits.append(kw)),
    )

    _, rejection = await _gate_chat_sandbox_approval(**_gate_kwargs())

    assert rejection is not None
    assert rejection["result"]["llm_payload"]["error"] == "用户未响应（超时）"
    assert audits == [
        {
            "user_id": "user-1",
            "approval_id": "approval-1",
            "session_id": "session-1",
            "tool_name": "chat_sandbox_execute",
            "action": "timeout",
            "resolver": "timeout",
            "arguments": {"language": "python", "code": "print(1)"},
            "method": "EVENT",
        }
    ]


@pytest.mark.asyncio
async def test_gate_bypassed_when_auto_approve(monkeypatch: pytest.MonkeyPatch) -> None:
    """AI 助手页面（auto_approve）：supervised 下也不建审批记录、直接放行。"""
    service = _FakeApprovalService({"action": "approved"})
    monkeypatch.setattr(lg_module, "get_studio_approval_service", lambda: service)

    args, rejection = await _gate_chat_sandbox_approval(
        **_gate_kwargs(auto_approve=True)
    )

    assert rejection is None
    assert service.created == []


@pytest.mark.asyncio
async def test_network_gate_bypassed_when_auto_approve(monkeypatch: pytest.MonkeyPatch) -> None:
    """出网审批同样受 auto_approve 旁路（普通聊天未声明权限模式时本就询问）。"""
    from cygnusx.application.services.chat.runtimes.langgraph_runtime import (
        _gate_network_request_approval,
    )

    service = _FakeApprovalService({"action": "approved"})
    monkeypatch.setattr(lg_module, "get_studio_approval_service", lambda: service)

    args, rejection = await _gate_network_request_approval(
        **_gate_kwargs(
            args={"url": "https://example.com"},
            permission_mode=None,
            auto_approve=True,
        )
    )

    assert rejection is None
    assert service.created == []


@pytest.mark.asyncio
async def test_network_gate_still_asks_without_auto_approve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不传 auto_approve（AI 工作台页面）时出网仍逐次询问，语义不回退。"""
    from cygnusx.application.services.chat.runtimes.langgraph_runtime import (
        _gate_network_request_approval,
    )

    service = _FakeApprovalService({"action": "approved"})
    monkeypatch.setattr(lg_module, "get_studio_approval_service", lambda: service)

    _, rejection = await _gate_network_request_approval(
        **_gate_kwargs(args={"url": "https://example.com"}, permission_mode=None)
    )

    assert rejection is None
    assert len(service.created) == 1
