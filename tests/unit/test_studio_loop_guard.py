"""Studio 单轮工具循环护栏测试。"""

import pytest

from omichub.application.services.studio_loop_guard import StudioLoopGuard
from omichub.infrastructure.config.studio_loader import StudioLoopControlConfig


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
