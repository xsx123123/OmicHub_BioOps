"""Matrix 反向同步测试：回投、回声过滤、cursor 推进、终态清理、降级与锁。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from omichub.application.services.agentteams_room_sync_service import (
    ROOM_SYNC_CURSOR_KEY_PREFIX,
    AgentTeamsRoomSyncService,
    record_room_binding,
)
from omichub.core.exceptions import BusinessError, NotFoundError


class FakeRedis:
    def __init__(self, *, acquired: bool = True, bindings: dict[str, str] | None = None) -> None:
        self.acquired = acquired
        self.hash: dict[str, str] = dict(bindings or {})
        self.values: dict[str, str] = {}
        self.release_calls = 0

    async def set(self, key, value, **kwargs):
        self.values[key] = value
        return self.acquired

    async def get(self, key):
        return self.values.get(key)

    async def hset(self, name, key, value):
        self.hash[key] = value

    async def hgetall(self, name):
        return dict(self.hash)

    async def hdel(self, name, key):
        self.hash.pop(key, None)

    async def eval(self, *_args):
        self.release_calls += 1
        return 1


class FakeGateway:
    def __init__(
        self,
        events: list[dict] | None = None,
        *,
        error: Exception | None = None,
        available: bool = True,
    ) -> None:
        self._events = events or []
        self._error = error
        self.available = available
        self.streams: list[tuple[str, str | None]] = []

    def stream_room_events(self, room_id: str, *, since: str | None = None):
        self.streams.append((room_id, since))
        return self._gen()

    async def _gen(self):
        if self._error is not None:
            raise RuntimeError("gateway down")
        for event in self._events:
            yield event


def _agentteams(status: str = "executing") -> SimpleNamespace:
    return SimpleNamespace(
        get_case=AsyncMock(return_value={"case_id": "bioops_1", "status": status}),
        post_case_evidence=AsyncMock(return_value={"event_id": "evt-x"}),
    )


def _service(
    *,
    agentteams: SimpleNamespace,
    gateway: FakeGateway,
    redis: FakeRedis,
    responder: MagicMock | None = None,
) -> AgentTeamsRoomSyncService:
    return AgentTeamsRoomSyncService(
        agentteams,
        gateway=gateway,
        redis_getter=lambda: redis,
        responder=responder or MagicMock(),
    )


BINDING = {"bioops_1": "!room:test|user-a"}


@pytest.mark.asyncio
async def test_external_message_reprojected_and_responder_dispatched() -> None:
    events = [
        {
            "event_id": "$m1",
            "origin": "external",
            "sender_identity": None,
            "sender_matrix_id": "@alice:matrix",
            "content": "Element 里的问题",
        },
        {"next_batch": "token-2"},
    ]
    agentteams = _agentteams()
    gateway = FakeGateway(events)
    redis = FakeRedis(bindings=BINDING)
    responder = MagicMock()

    stats = await _service(
        agentteams=agentteams, gateway=gateway, redis=redis, responder=responder
    ).run(watch_seconds=5)

    assert stats["status"] == "ok"
    assert stats["messages"] == 1
    kwargs = agentteams.post_case_evidence.await_args.kwargs
    assert kwargs["event_type"] == "room.user_message"
    assert kwargs["work_item_id"] == "case"
    assert kwargs["payload"]["content"] == "Element 里的问题"
    assert kwargs["payload"]["via"] == "matrix"
    assert kwargs["payload"]["matrix_event_id"] == "$m1"
    assert kwargs["payload"]["actor"] == "@alice:matrix"
    responder.assert_called_once_with("bioops_1", "user-a", "Element 里的问题")
    assert redis.values[f"{ROOM_SYNC_CURSOR_KEY_PREFIX}bioops_1"] == "token-2"
    assert redis.release_calls == 1


@pytest.mark.asyncio
async def test_echo_messages_filtered() -> None:
    events = [
        {"event_id": "$m1", "origin": "omichub", "sender_identity": "omichub-user", "content": "平台镜像消息"},
        {"event_id": "$m2", "origin": "external", "sender_matrix_id": "@alice:matrix", "content": "真人发言"},
    ]
    agentteams = _agentteams()
    redis = FakeRedis(bindings=BINDING)

    stats = await _service(agentteams=agentteams, gateway=FakeGateway(events), redis=redis).run(
        watch_seconds=5
    )

    assert stats["messages"] == 1
    assert agentteams.post_case_evidence.await_args.kwargs["payload"]["matrix_event_id"] == "$m2"


@pytest.mark.asyncio
async def test_duplicate_external_event_is_projected_once() -> None:
    event = {
        "event_id": "$same-event",
        "origin": "external",
        "sender_matrix_id": "@alice:matrix",
        "content": "同一条用户回复",
    }
    agentteams = _agentteams()
    redis = FakeRedis(bindings=BINDING)
    responder = MagicMock()

    stats = await _service(
        agentteams=agentteams,
        gateway=FakeGateway([event, event, {"next_batch": "token-3"}]),
        redis=redis,
        responder=responder,
    ).run(watch_seconds=5)

    assert stats["messages"] == 1
    assert agentteams.post_case_evidence.await_count == 1
    responder.assert_called_once_with("bioops_1", "user-a", "同一条用户回复")
    assert redis.values[f"{ROOM_SYNC_CURSOR_KEY_PREFIX}bioops_1"] == "token-3"


@pytest.mark.asyncio
async def test_duplicate_external_message_without_event_id_is_projected_once() -> None:
    event = {
        "origin": "external",
        "sender_matrix_id": "@alice:matrix",
        "content": "无事件 ID 的重复回复",
    }
    agentteams = _agentteams()
    redis = FakeRedis(bindings=BINDING)
    responder = MagicMock()

    stats = await _service(
        agentteams=agentteams,
        gateway=FakeGateway([event, dict(event), {"next_batch": "token-4"}]),
        redis=redis,
        responder=responder,
    ).run(watch_seconds=5)

    assert stats["messages"] == 1
    assert agentteams.post_case_evidence.await_count == 1
    responder.assert_called_once_with("bioops_1", "user-a", "无事件 ID 的重复回复")


@pytest.mark.asyncio
async def test_sync_resumes_from_persisted_cursor() -> None:
    agentteams = _agentteams()
    gateway = FakeGateway([])
    redis = FakeRedis(bindings=BINDING)
    redis.values[f"{ROOM_SYNC_CURSOR_KEY_PREFIX}bioops_1"] = "token-old"

    await _service(agentteams=agentteams, gateway=gateway, redis=redis).run(watch_seconds=5)

    assert gateway.streams == [("!room:test", "token-old")]


@pytest.mark.asyncio
async def test_room_failure_does_not_break_other_rooms() -> None:
    agentteams = _agentteams()
    gateway = FakeGateway(error=RuntimeError("gateway down"))
    redis = FakeRedis(bindings=BINDING)

    stats = await _service(agentteams=agentteams, gateway=gateway, redis=redis).run(
        watch_seconds=5
    )

    assert stats["failed"] == 1
    assert redis.release_calls == 1


@pytest.mark.asyncio
async def test_terminal_case_binding_removed_without_streaming() -> None:
    agentteams = _agentteams(status="closed")
    gateway = FakeGateway([])
    redis = FakeRedis(bindings=BINDING)

    stats = await _service(agentteams=agentteams, gateway=gateway, redis=redis).run(
        watch_seconds=5
    )

    assert stats["messages"] == 0
    assert gateway.streams == []
    assert redis.hash == {}


@pytest.mark.asyncio
async def test_missing_case_binding_removed_without_repeated_failure() -> None:
    agentteams = _agentteams()
    agentteams.get_case = AsyncMock(side_effect=NotFoundError("协作案例不存在"))
    gateway = FakeGateway([])
    redis = FakeRedis(bindings=BINDING)

    stats = await _service(agentteams=agentteams, gateway=gateway, redis=redis).run(
        watch_seconds=5
    )

    assert stats["failed"] == 0
    assert gateway.streams == []
    assert redis.hash == {}


@pytest.mark.asyncio
async def test_bridge_not_found_case_binding_removed_without_repeated_failure() -> None:
    agentteams = _agentteams()
    agentteams.get_case = AsyncMock(side_effect=BusinessError("协作案例不存在"))
    gateway = FakeGateway([])
    redis = FakeRedis(bindings=BINDING)

    stats = await _service(agentteams=agentteams, gateway=gateway, redis=redis).run(
        watch_seconds=5
    )

    assert stats["failed"] == 0
    assert gateway.streams == []
    assert redis.hash == {}


@pytest.mark.asyncio
async def test_run_skipped_when_gateway_unavailable() -> None:
    redis = FakeRedis(bindings=BINDING)

    stats = await _service(
        agentteams=_agentteams(), gateway=FakeGateway(available=False), redis=redis
    ).run(watch_seconds=5)

    assert stats["status"] == "skipped_unavailable"


@pytest.mark.asyncio
async def test_run_skipped_when_lock_held() -> None:
    redis = FakeRedis(acquired=False, bindings=BINDING)

    stats = await _service(
        agentteams=_agentteams(), gateway=FakeGateway([]), redis=redis
    ).run(watch_seconds=5)

    assert stats["status"] == "skipped_locked"
    assert redis.release_calls == 0


@pytest.mark.asyncio
async def test_record_room_binding_writes_hash() -> None:
    redis = FakeRedis()

    await record_room_binding("bioops_1", "!room:test", "user-a", redis_getter=lambda: redis)

    assert redis.hash == {"bioops_1": "!room:test|user-a"}


@pytest.mark.asyncio
async def test_record_room_binding_failure_only_logs() -> None:
    class BrokenRedis:
        async def hset(self, *_args):
            raise RuntimeError("redis down")

    await record_room_binding("bioops_1", "!room:test", "user-a", redis_getter=BrokenRedis)


def test_celery_task_delegates_to_async_impl(monkeypatch) -> None:
    import omichub.infrastructure.celery_app.tasks.agentteams as task_module

    async def fake_impl() -> dict[str, object]:
        return {"status": "ok"}

    monkeypatch.setattr(task_module, "_sync_case_rooms", fake_impl)

    assert task_module.sync_case_rooms() == {"status": "ok"}


@pytest.mark.asyncio
async def test_sync_task_skipped_when_gateway_unavailable(monkeypatch) -> None:
    import omichub.infrastructure.celery_app.tasks.agentteams as task_module

    class UnavailableGateway:
        @property
        def available(self) -> bool:
            return False

    monkeypatch.setattr(
        "omichub.application.services.agentteams_room_gateway_service.AgentTeamsRoomGatewayService",
        UnavailableGateway,
    )

    result = await task_module._sync_case_rooms_with_factory(lambda: lambda: None)

    assert result == {"status": "skipped_unavailable"}
