"""Agent 执行闭环的统一事件字段与构造辅助。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from omichub.infrastructure.ai_provider.openai_compatible import ChatChunk

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
    }
)


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
