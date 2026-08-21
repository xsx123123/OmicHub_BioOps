"""房间命名空间记录（会话-工单解耦 Part 2 方案 b）的 Bridge 侧测试。

覆盖：命名空间记录创建与隐藏（列表/配额/GC）、房间级事件读写、
MinIO 持久化与恢复、指标排除、入参校验。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from omichub_agentteams_bridge.audit import AuditStore
from omichub_agentteams_bridge.case_store import CaseStore
from omichub_agentteams_bridge.config import BridgeSettings
from omichub_agentteams_bridge.minio_store import MinioBridgeStorage
from omichub_agentteams_bridge.models import (
    CaseCreateRequest,
    EvidenceRequest,
    is_room_namespace_case_id,
)
from omichub_agentteams_bridge.service import BridgeService
from pydantic import ValidationError


class FakeOmicHubClient:
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


def make_settings(tmp_path, **overrides) -> BridgeSettings:
    values = {
        "omichub_service_token": "service-token",
        "approval_signing_secret": "test-signing-secret",
        "identities": "bioops-manager:manager,approval-authority:approval",
        "audit_log_path": str(tmp_path / "audit.jsonl"),
        "case_store_path": str(tmp_path / "cases.json"),
        "manifest_dir": str(tmp_path / "manifests"),
    }
    values.update(overrides)
    return BridgeSettings(**values)


def make_service(tmp_path, **overrides) -> BridgeService:
    settings = make_settings(tmp_path, **overrides)
    return BridgeService(
        settings,
        FakeOmicHubClient(),
        AuditStore(settings.audit_log_path),
        CaseStore(settings.case_store_path),
    )


def namespace_request(case_id: str = "room-abc123") -> CaseCreateRequest:
    return CaseCreateRequest(
        case_id=case_id,
        record_kind="room_namespace",
        intent="协作室房间会话：测试",
        requester_ref="user-1",
    )


# ---------------------------------------------------------------------------
# 入参校验
# ---------------------------------------------------------------------------


def test_room_namespace_requires_prefixed_case_id() -> None:
    with pytest.raises(ValidationError):
        CaseCreateRequest(
            case_id="bioops_abc",
            record_kind="room_namespace",
            intent="协作室房间会话",
            requester_ref="user-1",
        )


def test_room_namespace_rejects_flow_fields() -> None:
    with pytest.raises(ValidationError):
        CaseCreateRequest(
            case_id="room-abc123",
            record_kind="room_namespace",
            intent="协作室房间会话",
            requester_ref="user-1",
            flow_id="rna_seq",
        )


def test_is_room_namespace_case_id() -> None:
    assert is_room_namespace_case_id("room-abc123")
    assert not is_room_namespace_case_id("bioops_abc123")


# ---------------------------------------------------------------------------
# 创建 / 列表隐藏 / 配额豁免 / GC 豁免
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_room_namespace_hidden_from_case_list(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    await service.create_case(namespace_request(), "bioops-manager")

    listed = await service.list_cases("user-1")

    assert listed.items == []
    assert listed.total == 0
    # 记录本身仍可按 id 读取（房间事件流读写依赖它）。
    record = await service.get_case("room-abc123", "bioops-manager")
    assert record.record_kind == "room_namespace"
    assert record.status == "received"
    assert record.work_items == []


@pytest.mark.asyncio
async def test_room_namespace_exempt_from_requester_quota(tmp_path: Path) -> None:
    service = make_service(tmp_path, max_active_cases_per_requester=1)
    await service.create_case(namespace_request(), "bioops-manager")

    case = await service.create_case(
        CaseCreateRequest(
            case_id="bioops_real1",
            context_refs=[{"kind": "workspace", "id": "user-1"}],
            intent="真实分析工单",
            requester_ref="user-1",
        ),
        "bioops-manager",
    )

    # 命名空间记录不占配额：真实 Case 不应被排队。
    assert case.status == "received"


@pytest.mark.asyncio
async def test_room_namespace_excluded_from_gc(tmp_path: Path) -> None:
    service = make_service(tmp_path, case_gc_days=30)
    await service.create_case(namespace_request(), "bioops-manager")
    await service.create_case(
        CaseCreateRequest(
            case_id="bioops_old1",
            context_refs=[{"kind": "workspace", "id": "user-1"}],
            intent="待清理的旧工单",
            requester_ref="user-1",
        ),
        "bioops-manager",
    )
    await service.cancel_case(
        "bioops_old1",
        SimpleNamespace(reason="测试清理"),
        "bioops-manager",
    )
    # 把两条记录都老化到 GC 窗口内；命名空间记录即便到终态也不得被 GC。
    stale = datetime.now(UTC) - timedelta(days=60)
    for case_id in ("room-abc123", "bioops_old1"):
        async with service._cases._local_lock:
            record = service._cases._cases[case_id]
            service._cases._cases[case_id] = record.model_copy(update={"updated_at": stale})

    summary = await service.gc_cases("bioops-manager")

    assert summary["deleted_cases"] == 1
    record = await service.get_case("room-abc123", "bioops-manager")
    assert record.case_id == "room-abc123"


# ---------------------------------------------------------------------------
# 房间级事件读写（五字段 schema 不变）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_room_namespace_evidence_roundtrip(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    await service.create_case(namespace_request(), "bioops-manager")

    response = await service.record_evidence(
        "room-abc123",
        EvidenceRequest(
            work_item_id="case",
            event_type="room.user_message",
            summary="scRNA-seq 的整合方法有哪些",
            payload={"actor": "user-1", "content": "scRNA-seq 的整合方法有哪些"},
        ),
        "bioops-manager",
    )

    page = await service.get_case_events("room-abc123", "bioops-manager")
    assert len(page.events) == 2  # room.namespace_created + room.user_message
    event = page.events[-1]
    assert set(event) == {"event_id", "recorded_at", "case_id", "actor", "event_type", "payload"}
    assert event["event_id"] == response.event_id
    assert event["case_id"] == "room-abc123"
    assert event["event_type"] == "room.user_message"
    assert event["payload"]["payload"]["content"] == "scRNA-seq 的整合方法有哪些"


# ---------------------------------------------------------------------------
# MinIO 持久化：房间命名空间事件与记录同样落盘、可恢复，且不进指标
# ---------------------------------------------------------------------------


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


@pytest.mark.asyncio
async def test_room_namespace_minio_persistence_and_recovery(tmp_path: Path) -> None:
    fake = FakeMinioClient()
    storage = MinioBridgeStorage("http://minio:9000", "ak", "sk", "agentteams", client=fake)
    settings = make_settings(tmp_path)
    audit = AuditStore(settings.audit_log_path, minio_storage=storage)
    cases = CaseStore(settings.case_store_path, minio_storage=storage)
    service = BridgeService(settings, FakeOmicHubClient(), audit, cases)

    await service.create_case(namespace_request(), "bioops-manager")
    await service.record_evidence(
        "room-abc123",
        EvidenceRequest(
            work_item_id="case",
            event_type="room.proposal_confirm",
            summary="立项确认：分析 matrix.csv",
            payload={"objective": "分析 matrix.csv", "options": ["confirm", "modify", "cancel"]},
        ),
        "bioops-manager",
    )

    # 对象布局与 Part 1 一致：房间命名空间同样在 cases/{id}/... 下。
    assert "cases/room-abc123/events/audit.jsonl" in fake.objects
    assert "cases/room-abc123/snapshot.json" in fake.objects

    # 模拟容器重建：用同一 MinIO 重新构造存储层，命名空间记录与事件完整恢复。
    recovered_audit = AuditStore(settings.audit_log_path, minio_storage=storage)
    recovered_cases = CaseStore(settings.case_store_path, minio_storage=storage)
    recovered_service = BridgeService(settings, FakeOmicHubClient(), recovered_audit, recovered_cases)
    record = await recovered_service.get_case("room-abc123", "bioops-manager")
    assert record.record_kind == "room_namespace"
    page = await recovered_service.get_case_events("room-abc123", "bioops-manager")
    assert [event["event_type"] for event in page.events] == [
        "room.namespace_created",
        "room.proposal_confirm",
    ]

    # 命名空间不进 Case 运营指标。
    metrics = await recovered_service.metrics()
    assert metrics["case_count"] == 0
    await recovered_service.create_case(
        CaseCreateRequest(
            case_id="bioops_real2",
            context_refs=[{"kind": "workspace", "id": "user-1"}],
            intent="真实分析工单",
            requester_ref="user-1",
        ),
        "bioops-manager",
    )
    metrics = await recovered_service.metrics()
    assert metrics["case_count"] == 1


# ---------------------------------------------------------------------------
# C1 观测项：房间事件量指标（business 与瞬态 stream 分开，按命名空间展平）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_room_namespace_event_metrics_local_mode(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    await service.create_case(namespace_request(), "bioops-manager")
    await service.record_evidence(
        "room-abc123",
        EvidenceRequest(
            work_item_id="case",
            event_type="room.user_message",
            summary="闲聊：今天吃什么",
            payload={"actor": "user-1", "content": "闲聊：今天吃什么"},
        ),
        "bioops-manager",
    )
    await service.record_evidence(
        "room-abc123",
        EvidenceRequest(
            work_item_id="case",
            event_type="room.agent_stream",
            summary="Manager 正在回复",
            payload={"stream_id": "s1", "channel": "content", "delta": "你好"},
        ),
        "bioops-manager",
    )

    metrics = await service.metrics()

    assert metrics["room_namespace_count"] == 1
    # room.namespace_created + room.user_message 计入 business；打字机增量单列。
    assert metrics["room_events__room-abc123"] == 2
    assert metrics["room_stream_events__room-abc123"] == 1
    # 房间命名空间仍不进 Case 运营指标。
    assert metrics["case_count"] == 0


@pytest.mark.asyncio
async def test_room_namespace_event_metrics_minio_mode_survive_recovery(tmp_path: Path) -> None:
    fake = FakeMinioClient()
    storage = MinioBridgeStorage("http://minio:9000", "ak", "sk", "agentteams", client=fake)
    settings = make_settings(tmp_path)
    audit = AuditStore(settings.audit_log_path, minio_storage=storage)
    service = BridgeService(settings, FakeOmicHubClient(), audit, CaseStore(settings.case_store_path, minio_storage=storage))
    await service.create_case(namespace_request(), "bioops-manager")
    await service.record_evidence(
        "room-abc123",
        EvidenceRequest(
            work_item_id="case",
            event_type="room.user_message",
            summary="你好",
            payload={"actor": "user-1", "content": "你好"},
        ),
        "bioops-manager",
    )

    # 模拟容器重建：指标来自启动恢复填充的内存索引，不经 MinIO 全量扫描。
    recovered_audit = AuditStore(settings.audit_log_path, minio_storage=storage)
    metrics = await recovered_audit.metrics()

    assert metrics["room_namespace_count"] == 1
    assert metrics["room_events__room-abc123"] == 2
    assert metrics["case_count"] == 0
