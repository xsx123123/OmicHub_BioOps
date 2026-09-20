"""Studio Agent 单轮工具调用循环护栏。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

from cygnusx.application.services.execution_events import execution_metadata
from cygnusx.infrastructure.config.studio_loader import StudioLoopControlConfig
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk


@dataclass(frozen=True)
class LoopGuardTrigger:
    """触发熔断时回传给 SSE 层的结构化原因。"""

    reason: str
    tool_calls: int
    consecutive_failures: int
    tool_name: str | None = None
    error_type: str | None = None


@dataclass(frozen=True)
class StudioLoopGuardOutcome:
    """循环护栏处理后的权限状态与统一 SSE 事件。"""

    permission_mode: str
    event: ChatChunk


async def handle_loop_guard_trigger(
    trigger: LoopGuardTrigger,
    *,
    permission_mode: str,
    auto_downgrade_to_supervised: bool,
    session_id: str,
    user_id: str,
    run_id: str,
    agent_id: str,
    round_number: int,
    execution_path: str,
    get_session: Callable[[str, str], Awaitable[Any | None]],
    flush: Callable[[], Awaitable[Any]],
) -> StudioLoopGuardOutcome:
    """在循环熔断时持久化权限降级，并生成统一执行事件。"""
    downgraded = False
    next_permission_mode = permission_mode
    if permission_mode == "auto" and auto_downgrade_to_supervised:
        session = await get_session(session_id, user_id)
        if session is not None:
            sandbox_meta = dict(session.sandbox_meta or {})
            permissions = dict(sandbox_meta.get("permissions") or {})
            permissions["mode"] = "supervised"
            sandbox_meta["permissions"] = permissions
            session.sandbox_meta = sandbox_meta
            session.updated_at = datetime.now(UTC)
            await flush()
            next_permission_mode = "supervised"
            downgraded = True

    return StudioLoopGuardOutcome(
        permission_mode=next_permission_mode,
        event=ChatChunk(
            type="loop_guard_triggered",
            metadata=execution_metadata(
                "agent_loop_guard_triggered",
                session_id=session_id,
                run_id=run_id,
                agent_id=agent_id,
                round_number=round_number,
                execution_path=execution_path,
                reason=trigger.reason,
                tool_calls=trigger.tool_calls,
                consecutive_failures=trigger.consecutive_failures,
                tool_name=trigger.tool_name,
                error_type=trigger.error_type,
                downgraded_to_supervised=downgraded,
            ),
        ),
    )


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
