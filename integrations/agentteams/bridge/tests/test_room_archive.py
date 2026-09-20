"""房间命名空间事件流归档/恢复（协作室房间事件GC与归档口径 §2）的 Bridge 侧测试。

覆盖：归档后在线卷清空且冷存可读、归档后 business 写入被显式拒绝、
unarchive 后审计链完整可重放（含 room.archived / room.unarchived）、
重复归档幂等、自动扫描只归档超龄命名空间、非 MinIO 模式显式拒绝。
MinIO 一律用进程内 fake（与 test_minio_persistence.py / test_room_namespace.py 同做法）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import HTTPException
from cygnusx_agentteams_bridge.app import create_app
from cygnusx_agentteams_bridge.audit import AuditStore
from cygnusx_agentteams_bridge.case_store import CaseStore
from cygnusx_agentteams_bridge.config import BridgeSettings
from cygnusx_agentteams_bridge.minio_store import MinioBridgeStorage
from cygnusx_agentteams_bridge.models import CaseCreateRequest, EvidenceRequest
from cygnusx_agentteams_bridge.service import BridgeService


class FakeCygnusXClient:
    async def aclose(self) -> None:
        return None

    async def get_task(self, task_id: str) -> dict:
        return {"id": task_id, "status": "success"}

    async def get_agentteams_capabilities(self) -> dict:
        return {
            "allowed_flow_ids": [],
            "flow_agent_map": {},
            "flow_quality_gate_map": {},
            "role_agent_map": {},
            "worker_profiles": {},
        }


class NoSuchKey(Exception):  # noqa: N818 - 与 minio S3Error 的 code 对齐
    pass


class FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self, *_args: Any) -> bytes:
        return self._data

    def close(self) -> None:
        return None

    def release_conn(self) -> None:
        return None


class FakeMinioClient:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def bucket_exists(self, _bucket: str) -> bool:
        return True

    def put_object(
        self, _bucket: str, key: str, data: Any, length: int, content_type: str | None = None
    ) -> None:
        payload = data.read()
        assert len(payload) == length
        self.objects[key] = payload

    def get_object(self, _bucket: str, key: str) -> FakeResponse:
        if key not in self.objects:
            raise NoSuchKey(key)
        return FakeResponse(self.objects[key])

    def list_objects(self, _bucket: str, prefix: str = "", recursive: bool = True) -> list[Any]:
        return [
            SimpleNamespace(object_name=key)
            for key in sorted(self.objects)
            if key.startswith(prefix)
        ]

    def remove_object(self, _bucket: str, key: str) -> None:
        self.objects.pop(key, None)


def make_settings(tmp_path: Path, **overrides: Any) -> BridgeSettings:
    values = {
        "cygnusx_service_token": "service-token",
        "approval_signing_secret": "test-signing-secret",
        "identities": "bioops-manager:manager,approval-authority:approval,data-steward:steward",
        "audit_log_path": str(tmp_path / "audit.jsonl"),
        "case_store_path": str(tmp_path / "cases.json"),
        "manifest_dir": str(tmp_path / "manifests"),
    }
    values.update(overrides)
    return BridgeSettings(**values)


def make_minio_service(
    tmp_path: Path, fake: FakeMinioClient, **overrides: Any
) -> tuple[BridgeService, MinioBridgeStorage, AuditStore, BridgeSettings]:
    settings = make_settings(tmp_path, **overrides)
    storage = MinioBridgeStorage("http://minio:9000", "ak", "sk", "agentteams", client=fake)
    audit = AuditStore(settings.audit_log_path, minio_storage=storage)
    cases = CaseStore(settings.case_store_path, minio_storage=storage)
    service = BridgeService(settings, FakeCygnusXClient(), audit, cases)
    return service, storage, audit, settings


def namespace_request(case_id: str) -> CaseCreateRequest:
    return CaseCreateRequest(
        case_id=case_id,
        record_kind="room_namespace",
        intent="协作室房间会话：归档测试",
        requester_ref="user-1",
    )


def room_message(content: str) -> EvidenceRequest:
    return EvidenceRequest(
        work_item_id="case",
        event_type="room.user_message",
        summary=content,
        payload={"actor": "user-1", "content": content},
    )


async def seed_room(service: BridgeService, room_id: str, *messages: str) -> None:
    await service.create_case(namespace_request(f"room-{room_id}"), "bioops-manager")
    for content in messages:
        await service.record_evidence(f"room-{room_id}", room_message(content), "bioops-manager")


def cold_volume_lines(fake: FakeMinioClient, room_id: str, volume: str = "audit.jsonl") -> list[dict]:
    raw = fake.objects[f"archive/rooms/{room_id}/events/{volume}"]
    return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]


def age_online_events(fake: FakeMinioClient, case_id: str, *, days: int) -> None:
    """把在线事件卷里全部事件的 recorded_at 改老（自动扫描超龄判定用）。"""
    key = f"cases/{case_id}/events/audit.jsonl"
    old = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    events = [
        json.loads(line) for line in fake.objects[key].decode("utf-8").splitlines() if line.strip()
    ]
    for event in events:
        event["recorded_at"] = old
    fake.objects[key] = "".join(
        json.dumps(event, ensure_ascii=False) + "\n" for event in events
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# 归档：事件卷迁冷存、在线读不到、快照连续性不破坏重启恢复
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archive_moves_event_volumes_to_cold_prefix(tmp_path: Path) -> None:
    fake = FakeMinioClient()
    service, storage, audit, settings = make_minio_service(tmp_path, fake)
    await seed_room(service, "abc123", "今天吃什么", "scRNA-seq 怎么整合")

    result = await service.archive_room_namespace("abc123", "bioops-manager", "测试归档")

    assert result["archived"] is True
    assert result["already_archived"] is False
    assert result["event_count"] == 3  # room.namespace_created + 2 条 room.user_message
    assert result["archive_prefix"] == "archive/rooms/abc123/events/"
    # 在线事件卷清空，冷存卷齐全；命名空间记录快照保持在线（房间本身不删除）。
    assert not any(key.startswith("cases/room-abc123/events/") for key in fake.objects)
    assert "archive/rooms/abc123/events/audit.jsonl" in fake.objects
    assert "cases/room-abc123/snapshot.json" in fake.objects
    # 在线审计链查询不再加载：read_events / get_case_events 均为空。
    assert storage.read_events("room-abc123") == []
    page = await service.get_case_events("room-abc123", "bioops-manager")
    assert page.events == []
    assert audit.room_namespace_archived("abc123")
    # room.archived 审计事件写在归档前事件流末尾，随冷存一并保留（口径 §2.3）。
    archived_event = cold_volume_lines(fake, "abc123")[-1]
    assert archived_event["event_type"] == "room.archived"
    assert archived_event["actor"] == "bioops-manager"
    assert archived_event["payload"]["reason"] == "测试归档"
    assert archived_event["payload"]["archive_prefix"] == "archive/rooms/abc123/events/"
    assert archived_event["payload"]["event_count"] == 3
    # 指标：已归档房间不计在线命名空间，单列 archived 计数。
    metrics = await service.metrics()
    assert metrics["room_namespace_count"] == 0
    assert metrics["room_namespace_archived_count"] == 1
    # 模拟容器重建：快照 last_event_id 已重置，recover_cases 连续性校验通过，
    # 命名空间记录仍在线可读（归档 ≠ 删除）。
    recovered_cases = CaseStore(settings.case_store_path, minio_storage=storage)
    record = await recovered_cases.get("room-abc123")
    assert record.record_kind == "room_namespace"
    recovered_audit = AuditStore(settings.audit_log_path, minio_storage=storage)
    assert recovered_audit.room_namespace_archived("abc123")
    assert await recovered_audit.list_events("room-abc123") == []


@pytest.mark.asyncio
async def test_archived_namespace_rejects_business_writes(tmp_path: Path) -> None:
    fake = FakeMinioClient()
    service, _storage, _audit, _settings = make_minio_service(tmp_path, fake)
    await seed_room(service, "abc123", "归档前的消息")
    await service.archive_room_namespace("abc123", "bioops-manager", "只读验证")

    with pytest.raises(HTTPException) as exc_info:
        await service.record_evidence("room-abc123", room_message("归档后的消息"), "bioops-manager")
    assert exc_info.value.status_code == 409

    # 瞬态 stream 事件不受影响（不进持久卷，口径 §2.2 只拦截 business 写入）。
    response = await service.record_evidence(
        "room-abc123",
        EvidenceRequest(
            work_item_id="case",
            event_type="room.agent_stream",
            summary="打字机增量",
            payload={"stream_id": "s1", "channel": "content", "delta": "你"},
        ),
        "bioops-manager",
    )
    assert response.event_id


@pytest.mark.asyncio
async def test_unarchive_restores_full_event_chain(tmp_path: Path) -> None:
    fake = FakeMinioClient()
    service, storage, _audit, settings = make_minio_service(tmp_path, fake)
    await seed_room(service, "abc123", "消息一", "消息二")
    await service.archive_room_namespace("abc123", "bioops-manager", "阶段收尾")

    result = await service.unarchive_room_namespace("abc123", "bioops-manager")

    assert result["unarchived"] is True
    assert result["restored_from"] == "archive/rooms/abc123/events/"
    # 冷存清空、在线卷恢复；审计链完整：归档前事件 + room.archived + room.unarchived。
    assert not any(key.startswith("archive/rooms/") for key in fake.objects)
    events = storage.read_events("room-abc123")
    assert [event["event_type"] for event in events] == [
        "room.namespace_created",
        "room.user_message",
        "room.user_message",
        "room.archived",
        "room.unarchived",
    ]
    assert events[-1]["payload"]["room_id"] == "abc123"
    assert not storage.room_namespace_archived("abc123")
    # 恢复后可继续写 business 事件，链条继续增长。
    await service.record_evidence("room-abc123", room_message("恢复后的消息"), "bioops-manager")
    events = storage.read_events("room-abc123")
    assert events[-1]["event_type"] == "room.user_message"
    assert events[-1]["payload"]["payload"]["content"] == "恢复后的消息"
    # 模拟容器重建：恢复后的事件链从 MinIO 完整重放（persist-then-commit 同口径）。
    recovered_audit = AuditStore(settings.audit_log_path, minio_storage=storage)
    replayed = await recovered_audit.list_events("room-abc123")
    assert [event["event_type"] for event in replayed] == [event["event_type"] for event in events]
    metrics = await recovered_audit.metrics()
    assert metrics["room_namespace_archived_count"] == 0
    assert metrics["room_namespace_count"] == 1


@pytest.mark.asyncio
async def test_archive_is_idempotent(tmp_path: Path) -> None:
    fake = FakeMinioClient()
    service, storage, _audit, _settings = make_minio_service(tmp_path, fake)
    await seed_room(service, "abc123", "只有一条")
    first = await service.archive_room_namespace("abc123", "bioops-manager", "首次归档")

    second = await service.archive_room_namespace("abc123", "bioops-manager", "重复归档")

    assert second["archived"] is True
    assert second["already_archived"] is True
    # 不重复写 room.archived，冷存卷不翻倍。
    archived_types = [event["event_type"] for event in cold_volume_lines(fake, "abc123")]
    assert archived_types.count("room.archived") == 1
    assert len(second.get("migrated_objects", [])) == 0
    # 恢复后链条里同样只有一条 room.archived。
    await service.unarchive_room_namespace("abc123", "bioops-manager")
    events = storage.read_events("room-abc123")
    assert [event["event_type"] for event in events].count("room.archived") == 1
    assert first["event_count"] == 2  # room.namespace_created + 1 条 room.user_message


@pytest.mark.asyncio
async def test_unarchive_requires_archived_namespace(tmp_path: Path) -> None:
    fake = FakeMinioClient()
    service, _storage, _audit, _settings = make_minio_service(tmp_path, fake)
    await seed_room(service, "abc123", "未归档")

    with pytest.raises(HTTPException) as exc_info:
        await service.unarchive_room_namespace("abc123", "bioops-manager")
    assert exc_info.value.status_code == 409

    with pytest.raises(HTTPException) as exc_info:
        await service.archive_room_namespace("missing", "bioops-manager", None)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_archive_requires_minio_persistence(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    service = BridgeService(
        settings,
        FakeCygnusXClient(),
        AuditStore(settings.audit_log_path),
        CaseStore(settings.case_store_path),
    )
    await seed_room(service, "abc123", "本地模式")

    with pytest.raises(HTTPException) as exc_info:
        await service.archive_room_namespace("abc123", "bioops-manager", None)
    assert exc_info.value.status_code == 501


# ---------------------------------------------------------------------------
# 自动扫描：只归档超过 room_archive_days 无 business 活动的命名空间
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_scan_archives_only_stale_namespaces(tmp_path: Path) -> None:
    fake = FakeMinioClient()
    service, storage, audit, _settings = make_minio_service(tmp_path, fake, room_archive_days=30)
    await seed_room(service, "old-room", "很久以前的闲聊")
    await seed_room(service, "new-room", "刚刚还在聊")
    age_online_events(fake, "room-old-room", days=45)

    summary = await service.archive_stale_room_namespaces("bioops-manager")

    assert summary["archive_enabled"] is True
    assert summary["scanned"] == 2
    assert summary["archived"] == 1
    assert summary["skipped"] == 1
    assert summary["failed"] == 0
    assert audit.room_namespace_archived("old-room")
    assert not audit.room_namespace_archived("new-room")
    archived_event = cold_volume_lines(fake, "old-room")[-1]
    assert archived_event["event_type"] == "room.archived"
    assert archived_event["payload"]["reason"] == "inactive_for_30d(auto)"
    # 第二轮扫描：已归档的跳过，不重复归档。
    second = await service.archive_stale_room_namespaces("bioops-manager")
    assert second["archived"] == 0
    assert second["skipped"] == 2
    assert storage.room_namespace_archived("old-room")


@pytest.mark.asyncio
async def test_auto_scan_disabled_when_days_zero(tmp_path: Path) -> None:
    fake = FakeMinioClient()
    service, _storage, audit, _settings = make_minio_service(tmp_path, fake, room_archive_days=0)
    await seed_room(service, "old-room", "再老也不归档")
    age_online_events(fake, "room-old-room", days=3650)

    summary = await service.archive_stale_room_namespaces("bioops-manager")

    assert summary == {
        "archive_enabled": False,
        "days": 0,
        "scanned": 0,
        "archived": 0,
        "skipped": 0,
        "failed": 0,
    }
    assert not audit.room_namespace_archived("old-room")


# ---------------------------------------------------------------------------
# 路由：POST /v1/rooms/{room_id}/archive|unarchive（鉴权与 case_gc 一致）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_room_archive_endpoints(tmp_path: Path) -> None:
    fake = FakeMinioClient()
    storage = MinioBridgeStorage("http://minio:9000", "ak", "sk", "agentteams", client=fake)
    settings = make_settings(tmp_path)
    app = create_app(settings, FakeCygnusXClient(), minio_storage=storage)
    manager = {"X-Bridge-Identity": "bioops-manager", "X-Bridge-Token": "manager"}
    steward = {"X-Bridge-Identity": "data-steward", "X-Bridge-Token": "steward"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://bridge.test"
    ) as client:
        created = await client.post(
            "/v1/cases",
            json={
                "case_id": "room-abc123",
                "record_kind": "room_namespace",
                "intent": "协作室房间会话：路由测试",
                "requester_ref": "user-1",
            },
            headers=manager,
        )
        assert created.status_code == 201
        evidenced = await client.post(
            "/v1/cases/room-abc123/evidence",
            json={
                "work_item_id": "case",
                "event_type": "room.user_message",
                "summary": "路由层消息",
                "payload": {"actor": "user-1", "content": "路由层消息"},
            },
            headers=manager,
        )
        assert evidenced.status_code == 201

        archived = await client.post(
            "/v1/rooms/abc123/archive", params={"reason": "路由归档"}, headers=manager
        )
        assert archived.status_code == 200
        assert archived.json()["archived"] is True
        assert archived.json()["archive_prefix"] == "archive/rooms/abc123/events/"

        # 归档后 evidence 写入被显式拒绝（409）。
        rejected = await client.post(
            "/v1/cases/room-abc123/evidence",
            json={
                "work_item_id": "case",
                "event_type": "room.user_message",
                "summary": "归档后的消息",
                "payload": {"actor": "user-1", "content": "归档后的消息"},
            },
            headers=manager,
        )
        assert rejected.status_code == 409

        # 非管理角色无权归档/恢复（与 case_gc 同口径的 bioops-manager 限定）。
        forbidden = await client.post("/v1/rooms/abc123/unarchive", headers=steward)
        assert forbidden.status_code == 403

        unarchived = await client.post("/v1/rooms/abc123/unarchive", headers=manager)
        assert unarchived.status_code == 200
        assert unarchived.json()["unarchived"] is True

        events = await client.get("/v1/cases/room-abc123/events", headers=manager)
        assert events.status_code == 200
        assert [event["event_type"] for event in events.json()["events"]] == [
            "room.namespace_created",
            "room.user_message",
            "room.archived",
            "room.unarchived",
        ]
