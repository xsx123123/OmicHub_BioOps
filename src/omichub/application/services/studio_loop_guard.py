"""Studio Agent 单轮工具调用循环护栏。"""

from __future__ import annotations

from dataclasses import dataclass

from omichub.infrastructure.config.studio_loader import StudioLoopControlConfig


@dataclass(frozen=True)
class LoopGuardTrigger:
    """触发熔断时回传给 SSE 层的结构化原因。"""

    reason: str
    tool_calls: int
    consecutive_failures: int
    tool_name: str | None = None
    error_type: str | None = None


class StudioLoopGuard:
    """仅在一个用户消息发起的工具执行轮内累计状态。"""

    def __init__(self, config: StudioLoopControlConfig) -> None:
        self._config = config
        self.tool_calls = 0
        self._last_failure: tuple[str, str] | None = None
        self._consecutive_failures = 0

    def record_call(self) -> LoopGuardTrigger | None:
        self.tool_calls += 1
        if self.tool_calls <= self._config.max_tool_calls_per_turn:
            return None
        return LoopGuardTrigger(
            reason="max_tool_calls_per_turn",
            tool_calls=self.tool_calls,
            consecutive_failures=self._consecutive_failures,
        )

    def record_result(
        self, tool_name: str, success: bool, error_type: str | None = None
    ) -> LoopGuardTrigger | None:
        if success:
            self._last_failure = None
            self._consecutive_failures = 0
            return None

        signature = (tool_name, error_type or "unknown_error")
        if signature == self._last_failure:
            self._consecutive_failures += 1
        else:
            self._last_failure = signature
            self._consecutive_failures = 1

        if self._consecutive_failures < self._config.max_consecutive_failures:
            return None
        return LoopGuardTrigger(
            reason="max_consecutive_failures",
            tool_calls=self.tool_calls,
            consecutive_failures=self._consecutive_failures,
            tool_name=tool_name,
            error_type=signature[1],
        )
