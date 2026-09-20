"""聊天 Runtime 事件状态机测试。"""

import pytest

from cygnusx.application.services.chat.chat_event_service import ChatEventService
from cygnusx.application.services.execution_events import (
    EventSequenceError,
    must_precede_done,
    validate_event_sequence,
)
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk


def test_execution_event_sequence_accepts_tool_reinjection_loop() -> None:
    events = [
        "agent_turn_started",
        "text",
        "tool_call",
        "tool_result",
        "agent_context_reinjected",
        "agent_turn_continued",
        "text",
        "agent_final_result",
        "done",
    ]

    validate_event_sequence(events)
    assert must_precede_done(events)


def test_execution_event_sequence_accepts_ask_user_terminal_branch() -> None:
    events = [
        "agent_turn_started",
        "ask_user",
        "agent_final_result",
        "done",
    ]

    validate_event_sequence(events)


def test_execution_event_sequence_accepts_ask_request_after_tool_reinjection() -> None:
    validate_event_sequence(
        [
            "agent_turn_started",
            "tool_result",
            "agent_context_reinjected",
            "ask_request",
            "agent_final_result",
            "done",
        ]
    )


def test_ask_user_requires_immediate_final_event() -> None:
    with pytest.raises(EventSequenceError, match="ask_user/ask_request 后必须紧接"):
        validate_event_sequence(
            [
                "agent_turn_started",
                "ask_user",
                "text",
                "agent_final_result",
                "done",
            ]
        )


def test_sse_exit_accepts_ask_user_terminal_branch() -> None:
    service = ChatEventService(enforcement="raise")

    service.before_send(ChatChunk(type="agent_turn_started"))
    service.before_send(ChatChunk(type="ask_user"))
    service.before_send(ChatChunk(type="agent_final_result"))
    service.before_send(ChatChunk(type="done"))
    service.after_stream()


def test_handoff_requires_final_then_done() -> None:
    validate_event_sequence(
        [
            "agent_turn_started",
            "agent_final_result",
            "handoff",
            "done",
        ]
    )

    with pytest.raises(EventSequenceError, match="handoff 后必须紧接 done"):
        validate_event_sequence(
            [
                "agent_turn_started",
                "agent_final_result",
                "handoff",
                "handoff",
                "done",
            ]
        )


def test_handoff_starts_a_new_execution_turn() -> None:
    validate_event_sequence(
        [
            "agent_turn_started",
            "handoff",
            "agent_turn_started",
            "agent_final_result",
            "done",
        ]
    )

    with pytest.raises(EventSequenceError, match="handoff 后必须以新的"):
        validate_event_sequence(
            [
                "agent_turn_started",
                "handoff",
                "text",
                "agent_final_result",
                "done",
            ]
        )


def test_handoff_after_tool_reinjection_starts_a_new_execution_turn() -> None:
    validate_event_sequence(
        [
            "agent_turn_started",
            "tool_result",
            "agent_context_reinjected",
            "agent_turn_continued",
            "handoff",
            "agent_turn_started",
            "agent_final_result",
            "done",
        ]
    )


def test_done_rejects_missing_execution_terminal_event() -> None:
    with pytest.raises(EventSequenceError, match="done 前"):
        validate_event_sequence(["agent_turn_started", "text", "done"])


def test_reinjection_requires_tool_result() -> None:
    with pytest.raises(EventSequenceError, match="工具结果回灌"):
        validate_event_sequence(
            ["agent_turn_started", "agent_context_reinjected", "agent_final_result", "done"]
        )


def test_tool_result_requires_immediate_reinjection() -> None:
    with pytest.raises(EventSequenceError, match="工具结果回灌后必须紧接"):
        validate_event_sequence(
            [
                "agent_turn_started",
                "tool_result",
                "text",
                "agent_context_reinjected",
                "agent_turn_continued",
                "agent_final_result",
                "done",
            ]
        )


def test_reinjection_requires_immediate_continuation() -> None:
    with pytest.raises(EventSequenceError, match="agent_context_reinjected 后必须紧接"):
        validate_event_sequence(
            [
                "agent_turn_started",
                "tool_result",
                "agent_context_reinjected",
                "text",
                "agent_turn_continued",
                "agent_final_result",
                "done",
            ]
        )


def test_tool_batch_allows_next_tool_before_single_continuation() -> None:
    validate_event_sequence(
        [
            "agent_turn_started",
            "tool_call",
            "tool_result",
            "agent_context_reinjected",
            "tool_call",
            "tool_result",
            "agent_context_reinjected",
            "agent_turn_continued",
            "agent_final_result",
            "done",
        ]
    )


def test_sse_exit_raises_before_sending_out_of_order_event() -> None:
    service = ChatEventService(enforcement="raise")
    service.before_send(ChatChunk(type="agent_turn_started"))

    with pytest.raises(EventSequenceError, match="done 前"):
        service.before_send(ChatChunk(type="done"))


def test_sse_exit_rejects_execution_stream_that_ends_without_done() -> None:
    service = ChatEventService(enforcement="raise")
    service.before_send(ChatChunk(type="agent_turn_started"))
    service.before_send(ChatChunk(type="agent_final_result"))

    with pytest.raises(EventSequenceError, match="以 done 事件收尾"):
        service.after_stream()


def test_execution_stream_rejects_text_after_terminal_event() -> None:
    with pytest.raises(EventSequenceError, match="终态事件后不能发送 text"):
        validate_event_sequence(
            [
                "agent_turn_started",
                "agent_final_result",
                "text",
                "done",
            ]
        )


def test_legacy_stream_remains_compatible_until_runtime_migration() -> None:
    validate_event_sequence(["text", "tool_call", "tool_result", "done"])
