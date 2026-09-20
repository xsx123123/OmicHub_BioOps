"""Agent 执行闭环的统一事件字段、构造辅助和状态转移校验。"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk

EXECUTION_EVENT_TYPES = frozenset(
    {
        "agent_turn_started",
        "agent_reasoning_delta",
        "agent_tool_call",
        "agent_tool_started",
        "agent_tool_result",
        "agent_context_reinjected",
        "agent_turn_continued",
        "agent_final_result",
        "agent_turn_failed",
        "agent_loop_guard_triggered",
        "ask_user",
        "ask_request",
        "handoff",
    }
)


class EventSequenceError(ValueError):
    """SSE 执行生命周期不符合公共状态机时抛出。"""


_TERMINAL_EVENT_TYPES = frozenset({"agent_final_result", "agent_turn_failed"})
_TOOL_ACTIVITY_EVENT_TYPES = frozenset(
    {"tool_call", "agent_tool_call", "tool_result", "agent_tool_result"}
)
_TOOL_CALL_EVENT_TYPES = frozenset({"tool_call", "agent_tool_call", "agent_tool_started"})
_ASK_USER_EVENT_TYPES = frozenset({"ask_user", "ask_request"})


def _event_type(event: str | ChatChunk) -> str:
    return event if isinstance(event, str) else event.type


def must_precede_done(event_types: Iterable[str | ChatChunk]) -> bool:
    """返回 ``done`` 前是否已有执行流的终态事件。

    不包含 ``agent_turn_started`` 的传统聊天流保持兼容；一旦进入执行生命周期，
    必须以 ``agent_final_result`` 或 ``agent_turn_failed`` 收尾。
    """
    seen_execution_lifecycle = False
    terminal_seen = False
    for event in event_types:
        event_type = _event_type(event)
        seen_execution_lifecycle = seen_execution_lifecycle or event_type == "agent_turn_started"
        terminal_seen = terminal_seen or event_type in _TERMINAL_EVENT_TYPES
        if event_type == "done":
            return not seen_execution_lifecycle or terminal_seen
    return True


def validate_event_sequence(
    event_types: Iterable[str | ChatChunk], *, require_completion: bool = True
) -> None:
    """校验单个 SSE 流的执行生命周期顺序。

    传统 ``text/tool_call/tool_result/done`` 流尚未迁入 Runtime 时不在此处阻断；
    但任何已经发送 ``agent_turn_started`` 的流都必须遵守统一状态机。
    """
    started = False
    terminal = False
    terminal_event_type: str | None = None
    awaiting_reinjection = False
    awaiting_continuation = False
    ask_user_pending_final = False
    handoff_pending_done = False
    handoff_requires_new_turn = False
    done = False

    for position, event in enumerate(event_types, start=1):
        event_type = _event_type(event)
        if done:
            raise EventSequenceError(f"第 {position} 个事件 {event_type} 出现在 done 之后")

        if event_type == "agent_turn_started":
            if started and not handoff_requires_new_turn:
                raise EventSequenceError("agent_turn_started 只能在单个 SSE 流中发送一次")
            started = True
            handoff_requires_new_turn = False
            continue

        if not started:
            continue

        if handoff_requires_new_turn:
            raise EventSequenceError("handoff 后必须以新的 agent_turn_started 继续")

        if ask_user_pending_final and event_type != "agent_final_result":
            raise EventSequenceError("ask_user/ask_request 后必须紧接 agent_final_result")

        if handoff_pending_done and event_type != "done":
            raise EventSequenceError("handoff 后必须紧接 done")

        if awaiting_reinjection and event_type not in {
            "tool_result",
            "agent_tool_result",
            "agent_context_reinjected",
        }:
            raise EventSequenceError("工具结果回灌后必须紧接 agent_context_reinjected")

        if awaiting_continuation:
            if event_type in _TOOL_CALL_EVENT_TYPES:
                awaiting_continuation = False
            elif event_type in _ASK_USER_EVENT_TYPES:
                awaiting_continuation = False
            elif event_type != "agent_turn_continued":
                raise EventSequenceError(
                    "agent_context_reinjected 后必须紧接 agent_turn_continued 或下一工具调用"
                )

        if terminal and event_type not in {"handoff", "done"}:
            raise EventSequenceError(f"终态事件后不能发送 {event_type}")

        if event_type in _TOOL_ACTIVITY_EVENT_TYPES:
            if event_type in {"tool_result", "agent_tool_result"}:
                awaiting_reinjection = True
            continue

        if event_type == "agent_context_reinjected":
            if terminal or not awaiting_reinjection:
                raise EventSequenceError("agent_context_reinjected 必须紧随工具结果回灌")
            awaiting_reinjection = False
            awaiting_continuation = True
            continue

        if event_type == "agent_turn_continued":
            if terminal or not awaiting_continuation:
                raise EventSequenceError(
                    "agent_turn_continued 必须在 agent_context_reinjected 后发送"
                )
            awaiting_continuation = False
            continue

        if event_type in _TERMINAL_EVENT_TYPES:
            if terminal:
                raise EventSequenceError("单个 SSE 流只能发送一个执行终态事件")
            if awaiting_reinjection:
                raise EventSequenceError("工具结果回灌后必须发送 agent_context_reinjected")
            terminal = True
            terminal_event_type = event_type
            ask_user_pending_final = False
            continue

        if event_type in _ASK_USER_EVENT_TYPES:
            ask_user_pending_final = True
            continue

        if event_type == "handoff":
            if terminal_event_type == "agent_final_result":
                handoff_pending_done = True
            elif terminal:
                raise EventSequenceError("agent_turn_failed 后不能发送 handoff")
            else:
                handoff_requires_new_turn = True
            continue

        if event_type == "done":
            if not terminal:
                raise EventSequenceError(
                    "执行生命周期的 done 前必须发送 agent_final_result 或 agent_turn_failed"
                )
            done = True
            continue

    if require_completion and started and not done:
        raise EventSequenceError("执行生命周期必须以 done 事件收尾")


def execution_metadata(
    event_type: str,
    *,
    session_id: str,
    run_id: str,
    agent_id: str,
    round_number: int,
    execution_path: str,
    **payload: Any,
) -> dict[str, Any]:
    """构造可直接合并到 SSE metadata 的稳定事件载荷。"""
    metadata: dict[str, Any] = {
        "event_type": event_type,
        "session_id": session_id,
        "run_id": run_id,
        "agent_id": agent_id,
        "round": round_number,
        "execution_path": execution_path,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    metadata.update({key: value for key, value in payload.items() if value is not None})
    return metadata


def execution_chunk(
    event_type: str,
    *,
    session_id: str,
    run_id: str,
    agent_id: str,
    round_number: int,
    execution_path: str,
    content: str = "",
    **payload: Any,
) -> ChatChunk:
    return ChatChunk(
        type=event_type,
        content=content,
        metadata=execution_metadata(
            event_type,
            session_id=session_id,
            run_id=run_id,
            agent_id=agent_id,
            round_number=round_number,
            execution_path=execution_path,
            **payload,
        ),
    )
