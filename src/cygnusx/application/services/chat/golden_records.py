"""用于 Chat Runtime 行为基线的 SSE 事件归一化与比较。"""

from __future__ import annotations

from collections.abc import Iterable
import json
from pathlib import Path
from typing import Any

from cygnusx.application.services.execution_events import (
    EventSequenceError,
    validate_event_sequence,
)
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk

_VOLATILE_METADATA_KEYS = frozenset(
    {
        "approval_id",
        "message_id",
        "overdrive_approval_id",
        "run_id",
        "session_id",
        "timestamp",
        "tool_call_id",
    }
)


def _normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _normalize_value(nested_value)
            for key, nested_value in value.items()
            if key not in _VOLATILE_METADATA_KEYS
        }
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_value(item) for item in value]
    return value


def normalize_event(chunk: ChatChunk) -> dict[str, Any]:
    """移除随机标识和时间戳，保留可比较的事件语义。"""
    metadata = _normalize_value(chunk.metadata or {})
    event: dict[str, Any] = {"type": chunk.type}
    if chunk.content:
        event["content"] = chunk.content
    if metadata:
        event["metadata"] = metadata
    return event


def normalize_events(chunks: Iterable[ChatChunk]) -> list[dict[str, Any]]:
    """把一条 SSE 流转为可落盘的稳定 golden record。"""
    return [normalize_event(chunk) for chunk in chunks]


def _validate_golden_event_sequence(events: Iterable[dict[str, Any]], path: Path) -> None:
    """拒绝包含已迁入执行生命周期但违反状态机的落盘记录。"""
    event_list = list(events)
    if any(not isinstance(event.get("type"), str) or not event["type"] for event in event_list):
        raise ValueError(f"golden record events require a non-empty type: {path}")
    try:
        validate_event_sequence(
            [ChatChunk(type=event["type"]) for event in event_list]
        )
    except EventSequenceError as exc:
        raise ValueError(f"invalid golden event sequence: {path}: {exc}") from exc


def save_events(path: Path, chunks: Iterable[ChatChunk]) -> list[dict[str, Any]]:
    """归一化 SSE 事件并以稳定 JSON 格式写入 golden record。"""
    events = normalize_events(chunks)
    _validate_golden_event_sequence(events, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(events, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return events


def load_events(path: Path) -> list[dict[str, Any]]:
    """读取并校验已归一化的 golden record。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(event, dict) for event in payload):
        raise ValueError(f"golden record must be a JSON array of events: {path}")
    _validate_golden_event_sequence(payload, path)
    return payload


def diff_normalized_events(
    expected_events: Iterable[dict[str, Any]], actual_events: Iterable[dict[str, Any]]
) -> list[str]:
    """返回两个已归一化记录的逐事件语义差异。"""
    expected_list = list(expected_events)
    actual_list = list(actual_events)
    differences: list[str] = []
    max_length = max(len(expected_list), len(actual_list))
    for index in range(max_length):
        expected_event = expected_list[index] if index < len(expected_list) else None
        actual_event = actual_list[index] if index < len(actual_list) else None
        if expected_event != actual_event:
            differences.append(
                f"event[{index}] expected={expected_event!r} actual={actual_event!r}"
            )
    return differences


def diff_events(expected: Iterable[ChatChunk], actual: Iterable[ChatChunk]) -> list[str]:
    """返回逐事件差异；空列表表示行为序列等价。"""
    return diff_normalized_events(normalize_events(expected), normalize_events(actual))
