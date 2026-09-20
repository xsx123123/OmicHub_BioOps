"""Chat SSE golden record 工具测试。"""

from pathlib import Path

import pytest

from cygnusx.application.services.chat.golden_records import (
    diff_events,
    diff_normalized_events,
    load_events,
    normalize_events,
    save_events,
)
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk


def test_normalize_events_ignores_volatile_identifiers() -> None:
    events = normalize_events(
        [
            ChatChunk(
                type="agent_turn_started",
                metadata={"run_id": "run-a", "timestamp": "now", "round": 1},
            )
        ]
    )

    assert events == [{"type": "agent_turn_started", "metadata": {"round": 1}}]


def test_normalize_events_ignores_nested_tool_call_identifiers() -> None:
    events = normalize_events(
        [
            ChatChunk(
                type="tool_result",
                metadata={
                    "tool_call_id": "top-level-call",
                    "result": {
                        "tool_call_id": "nested-call",
                        "payload": [{"run_id": "nested-run", "value": 42}],
                    },
                },
            )
        ]
    )

    assert events == [
        {
            "type": "tool_result",
            "metadata": {"result": {"payload": [{"value": 42}]}},
        }
    ]


def test_diff_events_reports_semantic_differences() -> None:
    expected = [ChatChunk(type="text", content="answer"), ChatChunk(type="done")]
    actual = [ChatChunk(type="text", content="different"), ChatChunk(type="done")]

    assert diff_events(expected, actual) == [
        "event[0] expected={'type': 'text', 'content': 'answer'} "
        "actual={'type': 'text', 'content': 'different'}"
    ]


def test_golden_record_round_trip_and_normalized_diff(tmp_path) -> None:
    path = tmp_path / "direct-chat.json"

    saved = save_events(
        path,
        [ChatChunk(type="text", content="answer", metadata={"run_id": "run-1"})],
    )

    assert load_events(path) == saved == [{"type": "text", "content": "answer"}]
    assert diff_normalized_events(saved, load_events(path)) == []


def test_load_events_rejects_non_event_arrays(tmp_path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text('{"type": "text"}', encoding="utf-8")

    with pytest.raises(ValueError, match="JSON array of events"):
        load_events(path)


def test_load_events_rejects_invalid_execution_lifecycle(tmp_path) -> None:
    path = tmp_path / "invalid-lifecycle.json"
    path.write_text(
        '[{"type": "agent_turn_started"}, {"type": "done"}]',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid golden event sequence"):
        load_events(path)


def test_load_events_rejects_missing_event_type(tmp_path) -> None:
    path = tmp_path / "missing-type.json"
    path.write_text("[{}]", encoding="utf-8")

    with pytest.raises(ValueError, match="require a non-empty type"):
        load_events(path)


def test_all_committed_golden_records_are_valid() -> None:
    golden_root = Path(__file__).parents[2] / "e2e" / "chat_golden"

    for golden_path in sorted(golden_root.glob("*.json")):
        assert load_events(golden_path), golden_path
