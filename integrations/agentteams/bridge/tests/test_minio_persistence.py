"""MinIO persistence adapter + store integration tests (in-process fake, no real MinIO)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from cygnusx_agentteams_bridge.audit import OPERATIONAL_EVENT_TYPES, AuditStore
from cygnusx_agentteams_bridge.case_store import CaseStore
from cygnusx_agentteams_bridge.minio_store import MinioBridgeStorage
from cygnusx_agentteams_bridge.models import CaseRecord, WorkItemRecord


class NoSuchKey(Exception):  # noqa: N818 - 类名刻意与 minio S3Error 的 code 对齐，供适配层识别
    """Fake counterpart of minio's S3Error(code="NoSuchKey")."""


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
    """In-process fake implementing the minio.Minio subset used by MinioBridgeStorage."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_put = False
        self.fail_get = False
        self.reachable = True

    def bucket_exists(self, _bucket: str) -> bool:
        if not self.reachable:
            raise RuntimeError("injected connectivity failure")
        return True

    def put_object(
        self, _bucket: str, key: str, data: Any, length: int, content_type: str | None = None
    ) -> None:
        if self.fail_put:
            raise RuntimeError("injected put failure")
        payload = data.read()
        assert len(payload) == length
        self.objects[key] = payload

    def get_object(self, _bucket: str, key: str) -> FakeResponse:
        if self.fail_get:
            raise RuntimeError("injected get failure")
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


def make_storage(client: FakeMinioClient | None = None, **kwargs: Any) -> MinioBridgeStorage:
    return MinioBridgeStorage(
        "http://minio:9000",
        "root",
        "secret",
        "agentteams",
        client=client or FakeMinioClient(),
        **kwargs,
    )


def make_case_record(case_id: str = "case-minio-1") -> CaseRecord:
    now = datetime.now(UTC)
    return CaseRecord(
        case_id=case_id,
        project_ref={"kind": "project", "id": "project-1"},
        intent="minio-test",
        requester_ref="user-1",
        team_id="bioops-delivery",
        created_at=now,
        updated_at=now,
    )


def make_event(case_id: str, event_type: str, event_id: str) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "recorded_at": datetime.now(UTC).isoformat(),
        "case_id": case_id,
        "actor": "bioops-manager",
        "event_type": event_type,
        "payload": {"summary": "test"},
    }


# ---------------------------------------------------------------------------
# adapter read/write/rolling/snapshot validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_and_read_events_roundtrip() -> None:
    storage = make_storage()
    for index in range(3):
        await storage.append_event("case-1", make_event("case-1", "case.created", f"evt-{index}"))
    events = storage.read_events("case-1")
    assert [event["event_id"] for event in events] == ["evt-0", "evt-1", "evt-2"]
    assert storage.last_event_id("case-1") == "evt-2"
    assert sorted(storage._client.objects) == ["cases/case-1/events/audit.jsonl"]


@pytest.mark.asyncio
async def test_event_stream_rolls_to_dated_volume() -> None:
    client = FakeMinioClient()
    storage = make_storage(client, max_event_object_bytes=1_100)
    for index in range(10):
        await storage.append_event(
            "case-1", make_event("case-1", "work_item.running", f"evt-{index}")
        )
    keys = sorted(client.objects)
    assert "cases/case-1/events/audit.jsonl" in keys
    assert any("/events/audit-" in key and not key.endswith("/audit.jsonl") for key in keys)
    # 分卷后读回仍按写入顺序完整返回
    events = storage.read_events("case-1")
    assert [event["event_id"] for event in events] == [f"evt-{index}" for index in range(10)]


@pytest.mark.asyncio
async def test_snapshot_roundtrip_and_recovery() -> None:
    storage = make_storage()
    await storage.append_event("case-1", make_event("case-1", "case.created", "evt-1"))
    case = make_case_record("case-1")
    storage.write_snapshot("case-1", case.model_dump(mode="json"))
    recovered = storage.recover_cases()
    assert recovered["case-1"]["case_id"] == "case-1"


def test_corrupt_snapshot_last_event_id_refuses_startup() -> None:
    client = FakeMinioClient()
    storage = make_storage(client)
    # 事件流只有 evt-1，快照却声称 last_event_id=evt-999 → 连续性校验必须拒绝
    client.objects["cases/case-1/events/audit.jsonl"] = (
        json.dumps(make_event("case-1", "case.created", "evt-1")) + "\n"
    ).encode()
    client.objects["cases/case-1/snapshot.json"] = json.dumps(
        {
            "version": 1,
            "case_id": "case-1",
            "saved_at": datetime.now(UTC).isoformat(),
            "last_event_id": "evt-999",
            "case": make_case_record("case-1").model_dump(mode="json"),
        }
    ).encode()
    with pytest.raises(RuntimeError, match="not in the event stream"):
        storage.recover_cases()


def test_snapshot_without_marker_is_a_legal_transient() -> None:
    """写顺序是先快照后事件：marker=None 而事件流非空是合法瞬时态，恢复必须放行。"""
    client = FakeMinioClient()
    storage = make_storage(client)
    client.objects["cases/case-1/events/audit.jsonl"] = (
        json.dumps(make_event("case-1", "case.created", "evt-1")) + "\n"
    ).encode()
    client.objects["cases/case-1/snapshot.json"] = json.dumps(
        {
            "version": 1,
            "case_id": "case-1",
            "saved_at": datetime.now(UTC).isoformat(),
            "last_event_id": None,
            "case": make_case_record("case-1").model_dump(mode="json"),
        }
    ).encode()
    recovered = storage.recover_cases()
    assert recovered["case-1"]["case_id"] == "case-1"


def test_corrupt_event_object_is_rejected() -> None:
    client = FakeMinioClient()
    storage = make_storage(client)
    client.objects["cases/case-1/events/audit.jsonl"] = b"{broken-json\n"
    with pytest.raises(RuntimeError, match="corrupt line"):
        storage.read_events("case-1")


def test_minio_read_failure_raises_fail_fast() -> None:
    client = FakeMinioClient()
    client.fail_get = True
    storage = make_storage(client)
    client.objects["cases/case-1/events/audit.jsonl"] = b"{}\n"
    with pytest.raises(RuntimeError, match="MinIO read failed"):
        storage.read_events("case-1")


def test_health_reports_reachability_and_write_latency() -> None:
    client = FakeMinioClient()
    storage = make_storage(client)
    assert storage.health() == {"reachable": True, "last_write_latency_ms": None}
    storage.write_snapshot("case-1", {"case_id": "case-1"})
    health = storage.health()
    assert health["reachable"] is True
    assert health["last_write_latency_ms"] is not None
    client.reachable = False
    assert storage.health()["reachable"] is False


# ---------------------------------------------------------------------------
# AuditStore: write ordering / operational events / delete semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_minio_failure_leaves_no_ghost_state(tmp_path: Path) -> None:
    client = FakeMinioClient()
    client.fail_put = True
    notified: list[dict[str, Any]] = []
    store = AuditStore(
        str(tmp_path / "audit.jsonl"),
        on_event=notified.append,
        minio_storage=make_storage(client),
    )
    with pytest.raises(RuntimeError, match="MinIO write failed"):
        await store.record(
            case_id="case-1", actor="bioops-manager", event_type="case.created", payload={}
        )
    # MinIO 写失败即操作失败：内存索引与 _notify（room mirror 副作用）都无幽灵成功态
    assert await store.list_events("case-1") == []
    assert notified == []


@pytest.mark.asyncio
async def test_operational_events_are_counted_not_persisted(tmp_path: Path) -> None:
    client = FakeMinioClient()
    store = AuditStore(str(tmp_path / "audit.jsonl"), minio_storage=make_storage(client))
    assert {"worker.inbox_polled", "worker.heartbeat", "room.typing"} <= set(
        OPERATIONAL_EVENT_TYPES
    )
    for event_type in ("worker.inbox_polled", "worker.heartbeat", "room.typing"):
        event_id, recorded_at = await store.record(
            case_id="case-1", actor="agent-code", event_type=event_type, payload={}
        )
        assert event_id and recorded_at is not None
    # 不进持久流、不进内存索引，只进计数
    assert client.objects == {}
    assert await store.list_events("case-1") == []
    assert store._operational_counts == {
        "worker.inbox_polled": 1,
        "worker.heartbeat": 1,
        "room.typing": 1,
    }
    # business 事件照常持久化
    await store.record(
        case_id="case-1", actor="cygnusx-user", event_type="room.user_message", payload={}
    )
    assert [event["event_type"] for event in await store.list_events("case-1")] == [
        "room.user_message"
    ]


@pytest.mark.asyncio
async def test_metrics_expose_operational_event_counts(tmp_path: Path) -> None:
    """operational 聚合计数经 metrics 展平键暴露，供监控面板消费（Part 3.4）。"""
    store = AuditStore(str(tmp_path / "audit.jsonl"), minio_storage=make_storage(FakeMinioClient()))
    for _ in range(3):
        await store.record(
            case_id="case-1", actor="agent-code", event_type="worker.heartbeat", payload={}
        )
    await store.record(
        case_id="case-1", actor="cygnusx-user", event_type="room.user_message", payload={}
    )
    metrics = await store.metrics()
    assert metrics["operational_events__worker.heartbeat"] == 3
    assert metrics["event_count"] == 1  # operational 不计入持久流事件数


@pytest.mark.asyncio
async def test_delete_events_uses_object_delete_semantics(tmp_path: Path) -> None:
    client = FakeMinioClient()
    storage = make_storage(client, max_event_object_bytes=1_100)
    store = AuditStore(str(tmp_path / "audit.jsonl"), minio_storage=storage)
    for index in range(6):
        await store.record(
            case_id="case-1",
            actor="bioops-manager",
            event_type="work_item.running",
            payload={"index": index},
        )
    await store.record(case_id="case-2", actor="bioops-manager", event_type="case.created", payload={})
    removed = await store.delete_events("case-1")
    assert removed == 6
    assert await store.list_events("case-1") == []
    assert not [key for key in client.objects if key.startswith("cases/case-1/events/")]
    assert len(await store.list_events("case-2")) == 1


# ---------------------------------------------------------------------------
# startup recovery across fresh store instances (container rebuild scenario)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stores_recover_state_and_events_from_minio(tmp_path: Path) -> None:
    client = FakeMinioClient()
    storage = make_storage(client)
    case_store = CaseStore(str(tmp_path / "cases.json"), minio_storage=storage)
    audit_store = AuditStore(str(tmp_path / "audit.jsonl"), minio_storage=storage)

    case = make_case_record("case-minio-1")
    await case_store.create(case)
    receipt = {"case_id": "case-minio-1", "omic_task_id": "task-1", "status": "pending"}
    await audit_store.record(
        case_id="case-minio-1",
        actor="workflow-operator",
        event_type="omic_task.submitted",
        payload={"idempotency_key": "minio-key", "receipt": receipt},
    )
    await case_store.transition("case-minio-1", "planning_running")
    # 状态迁移后快照内嵌的 last_event_id 必须指向已落盘的最后一条事件
    envelope = json.loads(client.objects["cases/case-minio-1/snapshot.json"])
    assert envelope["last_event_id"] == storage.last_event_id("case-minio-1")

    # 新实例（模拟容器重建）从同一 MinIO 恢复：状态与事件完整
    restored_cases = CaseStore(
        str(tmp_path / "cases.json"), minio_storage=make_storage(client)
    )
    restored_audit = AuditStore(
        str(tmp_path / "audit.jsonl"), minio_storage=make_storage(client)
    )
    restored_case = await restored_cases.get("case-minio-1")
    assert restored_case.status == "planning_running"
    events = await restored_audit.list_events("case-minio-1")
    assert [event["event_type"] for event in events] == ["omic_task.submitted"]
    assert await restored_audit.get_receipt("minio-key") == receipt


def test_case_store_refuses_corrupt_minio_snapshot(tmp_path: Path) -> None:
    client = FakeMinioClient()
    client.objects["cases/case-1/snapshot.json"] = b"{broken-json"
    with pytest.raises(RuntimeError, match="snapshot"):
        CaseStore(str(tmp_path / "cases.json"), minio_storage=make_storage(client))


def test_audit_store_refuses_corrupt_minio_events(tmp_path: Path) -> None:
    client = FakeMinioClient()
    client.objects["cases/case-1/events/audit.jsonl"] = b"{broken-json\n"
    with pytest.raises(RuntimeError, match="corrupt line"):
        AuditStore(str(tmp_path / "audit.jsonl"), minio_storage=make_storage(client))


# ---------------------------------------------------------------------------
# /healthz extension
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_healthz_reports_minio_fields(tmp_path: Path) -> None:
    from httpx import ASGITransport, AsyncClient
    from cygnusx_agentteams_bridge.app import create_app
    from cygnusx_agentteams_bridge.config import BridgeSettings

    client = FakeMinioClient()
    settings = BridgeSettings(
        audit_log_path=str(tmp_path / "audit.jsonl"),
        case_store_path=str(tmp_path / "cases.json"),
        worker_token_store_path=str(tmp_path / "worker-tokens.json"),
        manifest_dir=str(tmp_path / "manifests"),
        minio_endpoint="http://minio:9000",
        minio_access_key="root",
        minio_secret_key="secret",
        case_gc_days=0,
        work_item_sweep_interval_seconds=0,
    )
    app = create_app(settings, minio_storage=make_storage(client))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["minio_enabled"] is True
    assert body["minio_reachable"] is True
    assert body["minio_last_write_latency_ms"] is None


@pytest.mark.asyncio
async def test_healthz_without_minio_reports_disabled(tmp_path: Path) -> None:
    from httpx import ASGITransport, AsyncClient
    from cygnusx_agentteams_bridge.app import create_app
    from cygnusx_agentteams_bridge.config import BridgeSettings

    settings = BridgeSettings(
        audit_log_path=str(tmp_path / "audit.jsonl"),
        case_store_path=str(tmp_path / "cases.json"),
        worker_token_store_path=str(tmp_path / "worker-tokens.json"),
        manifest_dir=str(tmp_path / "manifests"),
        case_gc_days=0,
        work_item_sweep_interval_seconds=0,
    )
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.get("/healthz")
    assert response.status_code == 200
    assert response.json()["minio_enabled"] is False


# ---------------------------------------------------------------------------
# service-level end-to-end in MinIO mode (service.py call sites unchanged)
# ---------------------------------------------------------------------------


class _FakeCygnusXClient:
    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_service_layer_runs_unchanged_on_minio_backed_stores(tmp_path: Path) -> None:
    from cygnusx_agentteams_bridge.config import BridgeSettings
    from cygnusx_agentteams_bridge.models import (
        CaseCreateRequest,
        ContextRef,
        WorkItemCreateRequest,
    )
    from cygnusx_agentteams_bridge.service import BridgeService

    client = FakeMinioClient()
    settings = BridgeSettings(
        cygnusx_service_token="service-token",
        approval_signing_secret="test-signing-secret",
        identities="bioops-manager:manager,agent-code:code",
        role_agent_map="agent-code:agent-code",
        audit_log_path=str(tmp_path / "audit.jsonl"),
        case_store_path=str(tmp_path / "cases.json"),
        manifest_dir=str(tmp_path / "manifests"),
        case_gc_days=0,
        work_item_sweep_interval_seconds=0,
    )

    def build_service() -> BridgeService:
        return BridgeService(
            settings,
            _FakeCygnusXClient(),
            AuditStore(settings.audit_log_path, minio_storage=make_storage(client)),
            CaseStore(settings.case_store_path, minio_storage=make_storage(client)),
        )

    service = build_service()
    await service.create_case(
        CaseCreateRequest(
            case_id="minio-e2e-case",
            project_ref=ContextRef(kind="project", id="project-1"),
            intent="minio_e2e",
            requester_ref="user-1",
        ),
        "bioops-manager",
    )
    await service.assign_work_item(
        "minio-e2e-case",
        WorkItemCreateRequest(
            work_item_id="code-01",
            target="agent-code",
            objective="Review code.",
            skill_name="code-review",
        ),
        "bioops-manager",
    )

    # 模拟容器重建：同一 MinIO（fake client）上的全新 store/service 实例
    restored = build_service()
    inbox = await restored.list_worker_inbox("agent-code")
    assert [item.work_item.work_item_id for item in inbox.items] == ["code-01"]
    events = await restored.get_case_events("minio-e2e-case", "bioops-manager")
    assert {event["event_type"] for event in events.events} >= {
        "case.created",
        "work_item.assigned",
    }



# ---------------------------------------------------------------------------
# 手册阶段 2 修复 1：persist-then-commit（MinIO 写失败 = 操作失败，无幽灵态）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_minio_write_failure_leaves_no_ghost_case_state(tmp_path: Path) -> None:
    """无 Redis 模式：快照写失败时内存态不推进，恢复后也不会固化幽灵。"""
    client = FakeMinioClient()
    storage = make_storage(client)
    store = CaseStore(str(tmp_path / "cases.json"), minio_storage=storage)
    await store.create(make_case_record("case-ghost-1"))

    client.fail_put = True
    # create：persist 失败即操作失败，后续 get/list 无幽灵
    with pytest.raises(RuntimeError, match="MinIO write failed"):
        await store.create(make_case_record("case-ghost-2"))
    with pytest.raises(HTTPException) as missing:
        await store.get("case-ghost-2")
    assert missing.value.status_code == 404
    assert [case.case_id for case in await store.list()] == ["case-ghost-1"]
    # transition：失败不推进内存态
    with pytest.raises(RuntimeError, match="MinIO write failed"):
        await store.transition("case-ghost-1", "planning_running")
    assert (await store.get("case-ghost-1")).status == "received"

    # 恢复后状态一致且可继续推进
    client.fail_put = False
    updated = await store.transition("case-ghost-1", "planning_running")
    assert updated.status == "planning_running"
    # 全新实例（模拟容器重建）从同一 MinIO 恢复：无幽灵残留
    restored = CaseStore(str(tmp_path / "cases.json"), minio_storage=make_storage(client))
    assert (await restored.get("case-ghost-1")).status == "planning_running"
    with pytest.raises(HTTPException) as restored_missing:
        await restored.get("case-ghost-2")
    assert restored_missing.value.status_code == 404


@pytest.mark.asyncio
async def test_minio_write_failure_rolls_back_claim(tmp_path: Path) -> None:
    """claim 原子性路径：persist 失败后租约/attempt 不推进，可被他者重新认领。"""
    client = FakeMinioClient()
    store = CaseStore(str(tmp_path / "cases.json"), minio_storage=make_storage(client))
    await store.create(make_case_record("case-claim-1"))
    await store.add_work_item(
        "case-claim-1",
        WorkItemRecord(
            work_item_id="wi-1",
            target="agent-code",
            objective="Review code.",
            skill_name="code-review",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
    )

    client.fail_put = True
    with pytest.raises(RuntimeError, match="MinIO write failed"):
        await store.claim_work_item("case-claim-1", "wi-1", "agent-code")
    item = await store.get_work_item("case-claim-1", "wi-1")
    assert item.status == "pending"
    assert item.attempt == 0
    assert item.lease_owner is None

    client.fail_put = False
    claimed = await store.claim_work_item("case-claim-1", "wi-1", "agent-code")
    assert claimed.status == "claimed"
    assert claimed.attempt == 1


@pytest.mark.asyncio
async def test_persist_writes_only_changed_case_snapshots(tmp_path: Path) -> None:
    """顺手优化：_persist 增量写——一次迁移只 PUT 本次变更的 case 快照。"""
    client = FakeMinioClient()
    storage = make_storage(client)
    store = CaseStore(str(tmp_path / "cases.json"), minio_storage=storage)
    await store.create(make_case_record("case-a"))
    await store.create(make_case_record("case-b"))

    written: list[str] = []
    original = storage.write_snapshot

    def spy(case_id: str, payload: dict[str, Any]) -> None:
        written.append(case_id)
        original(case_id, payload)

    storage.write_snapshot = spy  # type: ignore[method-assign]
    await store.transition("case-a", "planning_running")
    assert written == ["case-a"]
    # 未变更的 case-b 快照保持 create 时的版本（未被重写）
    envelope = json.loads(client.objects["cases/case-b/snapshot.json"])
    assert envelope["case"]["status"] == "received"


# ---------------------------------------------------------------------------
# 手册阶段 2 修复 2：幂等 receipt 独立对象入 MinIO，重启直读恢复
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_receipt_recovered_from_minio_without_event_replay(tmp_path: Path) -> None:
    """receipt 写入独立对象；新实例不经过 omic_task.submitted 事件重放即幂等命中。"""
    client = FakeMinioClient()
    store = AuditStore(str(tmp_path / "audit.jsonl"), minio_storage=make_storage(client))
    receipt = {"case_id": "case-1", "omic_task_id": "task-1", "status": "submitted"}
    await store.save_receipt("restart-key", receipt)
    assert "receipts/restart-key.json" in client.objects

    # 全新实例（模拟容器重建）：事件流为空，receipt 从 receipts/ 对象直读恢复
    restored = AuditStore(str(tmp_path / "audit.jsonl"), minio_storage=make_storage(client))
    assert await restored.get_receipt("restart-key") == receipt
    assert await restored.get_receipt("missing-key") is None


@pytest.mark.asyncio
async def test_receipt_save_minio_failure_raises_without_ghost(tmp_path: Path) -> None:
    """receipt 的 MinIO 写失败即操作失败：内存索引不出现幽灵 receipt。"""
    client = FakeMinioClient()
    client.fail_put = True
    store = AuditStore(str(tmp_path / "audit.jsonl"), minio_storage=make_storage(client))
    with pytest.raises(RuntimeError, match="MinIO write failed"):
        await store.save_receipt("ghost-key", {"case_id": "case-1"})
    assert await store.get_receipt("ghost-key") is None
