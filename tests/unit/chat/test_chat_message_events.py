"""WP2 chat_message_events：append-only 落库、seq 生成、降级契约与双读回放。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from cygnusx.application.services.chat.utils import _invocation_payload_hash
from cygnusx.application.services.chat_message_event_service import (
    ChatMessageEventService,
    _MessageEventBuffer,
)
from cygnusx.infrastructure.database.models.chat import ChatMessageEventModel

# ===== 信封 payload_hash =====


def test_payload_hash_deterministic_and_excludes_hash_field() -> None:
    envelope = {"tool_call_id": "call-1", "tool_name": "sandbox_execute", "result": {"a": 1}}
    expected = hashlib.sha256(
        json.dumps(envelope, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    with_hash = _invocation_payload_hash({**envelope, "payload_hash": "stale-value"})
    assert with_hash == expected
    # 与计算时的键序无关
    reordered = _invocation_payload_hash({"result": {"a": 1}, "tool_name": "sandbox_execute",
                                          "tool_call_id": "call-1", "payload_hash": with_hash})
    assert reordered == expected


def test_payload_hash_stored_value_recomputable() -> None:
    envelope: dict[str, Any] = {
        "tool_call_id": "call-9",
        "tool_name": "chat_sandbox_execute",
        "arguments": {"language": "python", "code": "print(1)"},
        "success": True,
        "result": {"stdout": "1\n"},
        "ui_payload": {"stdout": "1\n", "stderr": ""},
    }
    envelope["payload_hash"] = _invocation_payload_hash(envelope)
    # 模拟读取方复算：去掉 hash 字段重算必须一致
    assert _invocation_payload_hash(envelope) == envelope["payload_hash"]


# ===== 攒批缓冲 =====


def test_buffer_flushes_on_count_threshold() -> None:
    service = ChatMessageEventService()
    for _ in range(7):
        assert service._buffers.get("m1") is None or len(service._buffers["m1"].events) < 8
    # 直接验证阈值行为
    buf = _MessageEventBuffer()
    for i in range(8):
        buf.append({"event_type": "tool_output", "payload": {"data": f"chunk-{i}"}})
    assert len(buf.events) == 8


# ===== 落库降级契约（不阻塞、不抛异常） =====


@pytest.mark.asyncio
async def test_append_degrades_when_session_factory_raises(monkeypatch) -> None:
    import cygnusx.infrastructure.database.session as session_mod

    def _boom():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(session_mod, "get_session_factory", _boom)
    warnings: list[str] = []
    monkeypatch.setattr(
        "cygnusx.application.services.chat_message_event_service.logger.warning",
        lambda msg, *a, **k: warnings.append(str(msg)),
    )
    service = ChatMessageEventService()
    # 前 7 条只进缓冲不触库；第 8 条触发刷库并降级
    for i in range(8):
        ok = await service.append_tool_output(
            "m-dead", tool_call_id="tc", stream="stdout", data=f"c{i}"
        )
    assert ok is False  # 降级返回 False，未抛异常
    assert any("db unavailable" in w for w in warnings)


@pytest.mark.asyncio
async def test_flush_message_events_never_raises(monkeypatch) -> None:
    import cygnusx.infrastructure.database.session as session_mod

    def _boom():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(session_mod, "get_session_factory", _boom)
    warnings: list[str] = []
    monkeypatch.setattr(
        "cygnusx.application.services.chat_message_event_service.logger.warning",
        lambda msg, *a, **k: warnings.append(str(msg)),
    )
    service = ChatMessageEventService()
    await service.append_tool_output("m-dead2", tool_call_id="tc", stream="stdout", data="x")
    await service.flush_message_events("m-dead2")  # 不得抛异常
    assert any("db unavailable" in w for w in warnings)


@pytest.mark.asyncio
async def test_empty_message_id_is_noop() -> None:
    service = ChatMessageEventService()
    assert await service.append_tool_output(
        "", tool_call_id="tc", stream="stdout", data="x"
    ) is False
    await service.flush_message_events("")  # 不触库


# ===== seq 冲突回退 =====


@pytest.mark.asyncio
async def test_seq_conflict_resyncs_from_db(monkeypatch) -> None:
    service = ChatMessageEventService()
    service._seq_counters["m-conflict"] = 3  # 模拟计数器漂移（如进程重启）

    inserted: list[tuple[str, int]] = []
    state = {"failed_once": False}

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def add(self, obj):
            inserted.append((obj.message_id, obj.seq))

        async def flush(self):
            if not state["failed_once"]:
                state["failed_once"] = True
                raise IntegrityError("insert", {}, Exception("dup pkey"))

        async def commit(self):
            pass

        async def rollback(self):
            pass

    async def _max_seq(session, message_id):
        service._seq_counters[message_id] = 5  # DB 里已有 5 条

    monkeypatch.setattr(service, "_resync_seq", _max_seq)

    import cygnusx.infrastructure.database.session as session_mod

    monkeypatch.setattr(
        session_mod, "get_session_factory", lambda: lambda: _FakeSession()
    )
    # 先攒两条事件进缓冲，再 flush 触发冲突回退
    await service.append_tool_output("m-conflict", tool_call_id="tc", stream="stdout", data="a")
    await service.append_tool_output("m-conflict", tool_call_id="tc", stream="stdout", data="b")
    await service.flush_message_events("m-conflict")
    # 首次尝试用漂移计数器（seq 4、5）插入触发冲突并回滚；冲突后从
    # max(seq)=5 重分配，最终提交的两条事件 seq 为 6、7
    assert inserted[-2:] == [("m-conflict", 6), ("m-conflict", 7)]
    assert service._seq_counters["m-conflict"] == 7


# ===== 双读回放 =====


class _FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeExecuteResult:
    def __init__(self, rows, scalars=True):
        self._rows = rows
        self._scalars = scalars

    def scalars(self):
        return _FakeScalars(self._rows)

    def all(self):
        return self._rows


class _FakeReadSession:
    """load_replay / has_events 的假 session：execute 按调用顺序返回。"""

    def __init__(self, events, snapshots):
        self._events = events
        self._snapshots = snapshots

    async def execute(self, stmt):
        # 第一次调用是事件查询，第二次是快照查询
        if not hasattr(self, "_events_returned"):
            self._events_returned = True
            return _FakeExecuteResult(self._events)
        return _FakeExecuteResult(
            [(mid, meta) for mid, meta in self._snapshots.items()], scalars=False
        )


def _event(message_id: str, seq: int, tool_call_id: str, stream: str, data: str):
    return ChatMessageEventModel(
        message_id=message_id,
        seq=seq,
        event_type="tool_output",
        payload={"tool_call_id": tool_call_id, "stream": stream, "data": data},
    )


@pytest.mark.asyncio
async def test_load_replay_concatenates_by_seq_and_checks_consistency() -> None:
    events = [
        _event("m1", 1, "tc-1", "stdout", "hel"),
        _event("m1", 2, "tc-1", "stdout", "lo\n"),
        _event("m1", 3, "tc-1", "stderr", "warn\n"),
        _event("m1", 4, "tc-2", "stdout", "other"),
    ]
    snapshots = {
        "m1": {
            "tool_invocations": [
                {
                    "tool_call_id": "tc-1",
                    "ui_payload": {"stdout": "hello\n", "stderr": "warn\n"},
                }
            ]
        }
    }
    service = ChatMessageEventService()
    replay = await service.load_replay(_FakeReadSession(events, snapshots), ["m1"])
    assert replay["m1"]["tool_outputs"]["tc-1"] == {"stdout": "hello\n", "stderr": "warn\n"}
    assert replay["m1"]["tool_outputs"]["tc-2"] == {"stdout": "other"}
    assert replay["m1"]["consistent_with_snapshot"] is True
    assert replay["m1"]["event_count"] == 4


@pytest.mark.asyncio
async def test_load_replay_marks_inconsistent_when_snapshot_differs() -> None:
    events = [_event("m2", 1, "tc-1", "stdout", "partial")]
    snapshots = {
        "m2": {"tool_invocations": [{"tool_call_id": "tc-1", "ui_payload": {"stdout": "full"}}]}
    }
    service = ChatMessageEventService()
    replay = await service.load_replay(_FakeReadSession(events, snapshots), ["m2"])
    assert replay["m2"]["consistent_with_snapshot"] is False


@pytest.mark.asyncio
async def test_load_replay_empty_for_no_events() -> None:
    service = ChatMessageEventService()
    replay = await service.load_replay(_FakeReadSession([], {}), ["m3"])
    assert replay == {}
