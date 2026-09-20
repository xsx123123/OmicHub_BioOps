"""统一 Agent 执行事件契约测试。"""

from cygnusx.application.services.execution_events import (
    EXECUTION_EVENT_TYPES,
    execution_chunk,
    execution_metadata,
)


def test_execution_metadata_has_stable_correlation_fields() -> None:
    metadata = execution_metadata(
        "agent_context_reinjected",
        session_id="session-1",
        run_id="run-1",
        agent_id="agent-code",
        round_number=2,
        execution_path="chat_legacy",
        tool_call_id="tool-1",
        optional_value=None,
    )

    assert metadata == {
        "event_type": "agent_context_reinjected",
        "session_id": "session-1",
        "run_id": "run-1",
        "agent_id": "agent-code",
        "round": 2,
        "execution_path": "chat_legacy",
        "tool_call_id": "tool-1",
        "timestamp": metadata["timestamp"],
    }
    assert metadata["timestamp"].endswith("+00:00")


def test_execution_chunk_keeps_event_type_and_sse_compatible_shape() -> None:
    chunk = execution_chunk(
        "agent_final_result",
        session_id="session-1",
        run_id="run-1",
        agent_id="agent-general",
        round_number=3,
        execution_path="chat_langgraph",
        content="完成",
        status="completed",
    )

    assert chunk.type == "agent_final_result"
    assert chunk.content == "完成"
    assert chunk.metadata["event_type"] == "agent_final_result"
    assert chunk.metadata["execution_path"] == "chat_langgraph"
    assert chunk.metadata["timestamp"].endswith("+00:00")
    assert {"agent_reasoning_delta", "agent_tool_call", "agent_tool_started", "agent_tool_result"} <= EXECUTION_EVENT_TYPES
    assert "agent_loop_guard_triggered" in EXECUTION_EVENT_TYPES
