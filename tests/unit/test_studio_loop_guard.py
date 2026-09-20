"""Studio 单轮工具循环护栏测试。"""

from types import SimpleNamespace

import pytest

from cygnusx.application.services.studio_loop_guard import (
    LoopGuardTrigger,
    StudioLoopGuard,
    handle_loop_guard_trigger,
)
from cygnusx.infrastructure.config.studio_loader import StudioLoopControlConfig


@pytest.mark.unit
def test_stops_after_configured_tool_call_limit():
    guard = StudioLoopGuard(StudioLoopControlConfig(max_tool_calls_per_turn=2))

    assert guard.record_call() is None
    assert guard.record_call() is None
    trigger = guard.record_call()

    assert trigger is not None
    assert trigger.reason == "max_tool_calls_per_turn"
    assert trigger.tool_calls == 3


@pytest.mark.unit
def test_stops_after_same_tool_same_error_repeats():
    guard = StudioLoopGuard(StudioLoopControlConfig(max_consecutive_failures=3))

    assert guard.record_result("sandbox_execute", False, "SyntaxError") is None
    assert guard.record_result("sandbox_execute", False, "SyntaxError") is None
    trigger = guard.record_result("sandbox_execute", False, "SyntaxError")

    assert trigger is not None
    assert trigger.reason == "max_consecutive_failures"
    assert trigger.tool_name == "sandbox_execute"
    assert trigger.error_type == "SyntaxError"
    assert trigger.consecutive_failures == 3


@pytest.mark.unit
def test_success_or_different_failure_resets_consecutive_counter():
    guard = StudioLoopGuard(StudioLoopControlConfig(max_consecutive_failures=2))

    assert guard.record_result("sandbox_execute", False, "SyntaxError") is None
    assert guard.record_result("workspace_edit", False, "SyntaxError") is None
    assert guard.record_result("workspace_edit", True) is None
    assert guard.record_result("workspace_edit", False, "SyntaxError") is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_guard_trigger_downgrades_auto_permissions_and_emits_execution_event():
    session = SimpleNamespace(sandbox_meta={"permissions": {"mode": "auto"}}, updated_at=None)
    flush_calls = 0

    async def get_session(session_id: str, user_id: str):
        assert (session_id, user_id) == ("session-1", "user-1")
        return session

    async def flush() -> None:
        nonlocal flush_calls
        flush_calls += 1

    outcome = await handle_loop_guard_trigger(
        LoopGuardTrigger(
            reason="max_tool_calls_per_turn",
            tool_calls=4,
            consecutive_failures=0,
        ),
        permission_mode="auto",
        auto_downgrade_to_supervised=True,
        session_id="session-1",
        user_id="user-1",
        run_id="run-1",
        agent_id="agent-1",
        round_number=2,
        execution_path="chat_studio",
        get_session=get_session,
        flush=flush,
    )

    assert outcome.permission_mode == "supervised"
    assert session.sandbox_meta["permissions"]["mode"] == "supervised"
    assert session.updated_at is not None
    assert flush_calls == 1
    assert outcome.event.type == "loop_guard_triggered"
    assert outcome.event.metadata == {
        "event_type": "agent_loop_guard_triggered",
        "session_id": "session-1",
        "run_id": "run-1",
        "agent_id": "agent-1",
        "round": 2,
        "execution_path": "chat_studio",
        "reason": "max_tool_calls_per_turn",
        "tool_calls": 4,
        "consecutive_failures": 0,
        "downgraded_to_supervised": True,
        "timestamp": outcome.event.metadata["timestamp"],
    }
