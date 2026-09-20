"""阶段 0 安全止血回归测试（审查报告 B1/B2/B3 + D#2）。

覆盖：
- B1：approval-authority 等平台身份不可被铸造为 Worker token；审批 token 绑定
  plan_hash，计划修订后旧 token 一律 403。
- B2：evidence 写入的身份白名单、target 绑定、平台保留命名空间封禁、
  因果锚点（Worker 强制/回填，平台身份 validate-when-present）。
- B3/B1：立项确认卡的 confirm_token 在事件流出口一律脱敏（含 pending 卡；
  token 只存主后端房间行 DB 字段，不经事件流分发）。
- D#2：room.agent_stream 不进 MinIO 持久卷但仍可经 list_events 读回；
  重建后消失；room mirror 不再镜像到 Matrix。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from cygnusx_agentteams_bridge.audit import AuditStore
from cygnusx_agentteams_bridge.config import BridgeSettings
from cygnusx_agentteams_bridge.room_mirror import AuditRoomMirror
from test_bridge_contract import (
    LoopLocalASGIClient,
    create_case,
    create_flow_case,
    headers,
)
from test_minio_persistence import FakeMinioClient, make_storage
from test_room_mirror import FakeGatewayClient


@pytest.fixture
def settings(tmp_path):
    return BridgeSettings(
        cygnusx_base_url="http://omic.test",
        cygnusx_service_token="service-token",
        approval_signing_secret="test-signing-secret",
        identities=(
            "approval-authority:approval,bioops-manager:manager,data-steward:steward,"
            "workflow-operator:operator,quality-auditor:auditor,delivery-reporter:reporter,"
            "agent-code:code,agent-viz:viz,agent-scrna:scrna,agent-atacseq:atacseq,"
            "analysis-worker:analysis"
        ),
        allowed_flow_ids="rna_seq",
        role_agent_map="data-steward:agent-data,quality-auditor:agent-qc,delivery-reporter:agent-delivery,agent-code:agent-code,agent-viz:agent-viz,agent-scrna:agent-scrna,agent-rnaseq:agent-rnaseq,agent-atacseq:agent-atacseq",
        audit_log_path=str(tmp_path / "audit.jsonl"),
        case_store_path=str(tmp_path / "cases.json"),
        worker_token_store_path=str(tmp_path / "tokens.json"),
        manifest_dir=str(tmp_path / "manifests"),
    )


@pytest.fixture
def client(settings):
    calls: list = []
    return LoopLocalASGIClient(settings, calls), calls


# ---------------------------------------------------------------------------
# B1：approval-authority 不可铸造 + plan_hash 绑定
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manager_cannot_mint_platform_identity_worker_tokens(client) -> None:
    request_client, _ = client
    for platform_identity in ("approval-authority", "bioops-manager"):
        response = await request_client.post(
            "/v1/worker-tokens",
            headers=headers("bioops-manager", "manager"),
            json={"identity": platform_identity},
        )
        assert response.status_code == 403
        assert "Platform identities" in response.json()["detail"]


@pytest.mark.asyncio
async def test_manager_mints_external_worker_token_but_not_unknown_identity(client) -> None:
    request_client, _ = client
    minted = await request_client.post(
        "/v1/worker-tokens",
        headers=headers("bioops-manager", "manager"),
        json={"identity": "agent-code"},
    )
    assert minted.status_code == 201
    assert minted.json()["record"]["identity"] == "agent-code"

    unknown = await request_client.post(
        "/v1/worker-tokens",
        headers=headers("bioops-manager", "manager"),
        json={"identity": "ghost"},
    )
    assert unknown.status_code == 422


async def _preflight_to_approval_pending(request_client) -> None:
    await create_flow_case(request_client, "bioops_001")
    preflight = await request_client.post(
        "/v1/projects/project-1/preflight",
        headers=headers("data-steward", "steward"),
        json={
            "case_id": "bioops_001",
            "flow_id": "rna_seq",
            "sample_sheet": [{"sample": "S01"}],
        },
    )
    assert preflight.status_code == 200
    assert preflight.json()["status"] == "passed"


async def _issue_approval_token(request_client) -> str:
    approval = await request_client.post(
        "/v1/approvals",
        headers=headers("approval-authority", "approval"),
        json={"case_id": "bioops_001", "action": "submit_task", "flow_id": "rna_seq"},
    )
    assert approval.status_code == 201
    return approval.json()["token"]


def _submit_payload(token: str, task: dict[str, Any]) -> dict[str, Any]:
    # 流程 Case 的提交任务必须与冻结计划（proposed_submission）逐字段相等。
    return {
        "case_id": "bioops_001",
        "idempotency_key": "bioops-001-rna-v1",
        "approval_token": token,
        "task": task,
    }


async def _frozen_submission(request_client) -> dict[str, Any]:
    case = await request_client.get(
        "/v1/cases/bioops_001", headers=headers("bioops-manager", "manager")
    )
    return case.json()["proposed_submission"]


@pytest.mark.asyncio
async def test_approval_chain_with_static_authority_key_still_works(client) -> None:
    """B1 回归：approval-authority 静态密钥签发的 token 仍可完成任务提交。"""
    request_client, _ = client
    await _preflight_to_approval_pending(request_client)
    token = await _issue_approval_token(request_client)

    submitted = await request_client.post(
        "/v1/tasks",
        headers=headers("workflow-operator", "operator"),
        json=_submit_payload(token, await _frozen_submission(request_client)),
    )

    assert submitted.status_code == 201
    assert submitted.json()["omic_task_id"] == "task-001"


@pytest.mark.asyncio
async def test_approval_token_is_bound_to_plan_hash(client) -> None:
    """B1：计划修订改变 plan_hash 后，旧审批 token 提交一律 403；重签后恢复。"""
    request_client, _ = client
    await _preflight_to_approval_pending(request_client)
    stale_token = await _issue_approval_token(request_client)
    case = await request_client.get(
        "/v1/cases/bioops_001", headers=headers("bioops-manager", "manager")
    )
    plan_hash = case.json()["plan_hash"]

    revised = await request_client.post(
        "/v1/cases/bioops_001/plan/revise",
        headers=headers("bioops-manager", "manager"),
        json={
            "expected_plan_hash": plan_hash,
            "parameters": {"note": "revised-after-approval"},
            "reason": "审批后修订计划参数",
        },
    )
    assert revised.status_code == 200
    assert revised.json()["plan_hash"] != plan_hash

    stale = await request_client.post(
        "/v1/tasks",
        headers=headers("workflow-operator", "operator"),
        json=_submit_payload(stale_token, await _frozen_submission(request_client)),
    )
    assert stale.status_code == 403
    assert stale.json()["detail"] == "Approval scope mismatch"

    fresh_token = await _issue_approval_token(request_client)
    submitted = await request_client.post(
        "/v1/tasks",
        headers=headers("workflow-operator", "operator"),
        json=_submit_payload(fresh_token, await _frozen_submission(request_client)),
    )
    assert submitted.status_code == 201


# ---------------------------------------------------------------------------
# B2：evidence 身份白名单 + 租约/target 绑定 + 因果锚点 + 命名空间封禁
# ---------------------------------------------------------------------------


async def _create_worker_case(request_client, case_id: str = "bioops_evidence") -> None:
    await create_case(request_client, case_id)
    assigned = await request_client.post(
        f"/v1/cases/{case_id}/work-items",
        headers=headers("bioops-manager", "manager"),
        json={
            "work_item_id": "analysis-01",
            "target": "agent-code",
            "objective": "run analysis",
            "skill_name": "analysis",
        },
    )
    assert assigned.status_code == 201


def _evidence_payload(event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "work_item_id": "analysis-01",
        "event_type": event_type,
        "summary": "worker evidence",
        "payload": payload or {},
    }


@pytest.mark.asyncio
async def test_unbound_worker_cannot_record_evidence(client) -> None:
    request_client, _ = client
    await _create_worker_case(request_client)

    denied = await request_client.post(
        "/v1/cases/bioops_evidence/evidence",
        headers=headers("agent-viz", "viz"),
        json=_evidence_payload("worker.preflight_failed"),
    )

    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_target_worker_evidence_gets_causal_anchor_backfilled(client) -> None:
    request_client, _ = client
    await _create_worker_case(request_client)

    recorded = await request_client.post(
        "/v1/cases/bioops_evidence/evidence",
        headers=headers("agent-code", "code"),
        json=_evidence_payload("worker.preflight_failed"),
    )
    assert recorded.status_code == 201

    events = await request_client.get(
        "/v1/cases/bioops_evidence/events", headers=headers("bioops-manager", "manager")
    )
    stream = events.json()["events"]
    assigned_event = next(
        event
        for event in stream
        if event["event_type"] == "work_item.assigned"
        and event["payload"].get("work_item_id") == "analysis-01"
    )
    worker_event = next(
        event for event in stream if event["event_type"] == "worker.preflight_failed"
    )
    inner = worker_event["payload"]["payload"]
    assert inner["causation_event_id"] == assigned_event["event_id"]


@pytest.mark.asyncio
async def test_worker_cannot_record_platform_reserved_event_types(client) -> None:
    request_client, _ = client
    await _create_worker_case(request_client)

    for event_type in ("room.user_message", "approval.granted", "case.created"):
        denied = await request_client.post(
            "/v1/cases/bioops_evidence/evidence",
            headers=headers("agent-code", "code"),
            json=_evidence_payload(event_type),
        )
        assert denied.status_code == 403, event_type


@pytest.mark.asyncio
async def test_worker_evidence_with_forged_causal_anchor_is_rejected(client) -> None:
    request_client, _ = client
    await _create_worker_case(request_client)

    forged = await request_client.post(
        "/v1/cases/bioops_evidence/evidence",
        headers=headers("agent-code", "code"),
        json=_evidence_payload(
            "worker.preflight_failed", {"causation_event_id": "evt-does-not-exist"}
        ),
    )

    assert forged.status_code == 422


@pytest.mark.asyncio
async def test_platform_identity_with_dangling_anchor_is_rejected(client) -> None:
    request_client, _ = client
    await _create_worker_case(request_client)

    dangling = await request_client.post(
        "/v1/cases/bioops_evidence/evidence",
        headers=headers("bioops-manager", "manager"),
        json=_evidence_payload(
            "room.user_message", {"causation_event_id": "evt-ghost-anchor"}
        ),
    )

    assert dangling.status_code == 422


@pytest.mark.asyncio
async def test_manager_case_level_room_event_without_anchor_still_works(client) -> None:
    """B2 回归：bioops-manager 的 Case 级 room.* 事件（无锚点根事件）不受影响。"""
    request_client, _ = client
    await create_case(request_client)

    recorded = await request_client.post(
        "/v1/cases/bioops_001/evidence",
        headers=headers("bioops-manager", "manager"),
        json={
            "work_item_id": "case",
            "event_type": "room.user_message",
            "summary": "用户发言",
            "payload": {"actor": "user-1", "content": "你好"},
        },
    )

    assert recorded.status_code == 201


@pytest.mark.asyncio
async def test_approval_authority_cannot_record_evidence(client) -> None:
    """B2：evidence 端点身份白名单——approval-authority 不在其列。"""
    request_client, _ = client
    await create_case(request_client)

    denied = await request_client.post(
        "/v1/cases/bioops_001/evidence",
        headers=headers("approval-authority", "approval"),
        json={
            "work_item_id": "case",
            "event_type": "room.user_message",
            "summary": "越权写入",
            "payload": {},
        },
    )

    assert denied.status_code == 403


# ---------------------------------------------------------------------------
# B1：立项确认卡 confirm_token 写入后即全出口脱敏（不再区分 pending/已消费）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_proposal_card_token_is_redacted_pending_and_consumed(client) -> None:
    request_client, _ = client
    await create_case(request_client)
    card = await request_client.post(
        "/v1/cases/bioops_001/evidence",
        headers=headers("bioops-manager", "manager"),
        json={
            "work_item_id": "case",
            "event_type": "room.proposal_confirm",
            "summary": "立项确认卡",
            "payload": {"proposal_id": "p-1", "confirm_token": "secret-token"},
        },
    )
    assert card.status_code == 201
    card_event_id = card.json()["event_id"]

    events = await request_client.get(
        "/v1/cases/bioops_001/events", headers=headers("bioops-manager", "manager")
    )
    card_event = next(
        event for event in events.json()["events"] if event["event_id"] == card_event_id
    )
    # pending 卡同样脱敏：token 只存主后端房间行 DB 字段，不经事件流分发。
    assert card_event["payload"]["payload"]["confirm_token"] is None

    bound = await request_client.post(
        "/v1/cases/bioops_001/evidence",
        headers=headers("bioops-manager", "manager"),
        json={
            "work_item_id": "case",
            "event_type": "room.case_bound",
            "summary": "确认立项",
            "payload": {"answer_to_event_id": card_event_id},
        },
    )
    assert bound.status_code == 201

    events = await request_client.get(
        "/v1/cases/bioops_001/events", headers=headers("bioops-manager", "manager")
    )
    card_event = next(
        event for event in events.json()["events"] if event["event_id"] == card_event_id
    )
    assert card_event["payload"]["payload"]["confirm_token"] is None


# ---------------------------------------------------------------------------
# D#2：room.agent_stream 出 MinIO 持久流 / Matrix 镜像
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_stream_skips_minio_but_stays_readable(tmp_path) -> None:
    minio_client = FakeMinioClient()
    storage = make_storage(minio_client)
    audit = AuditStore(str(tmp_path / "audit.jsonl"), minio_storage=storage)

    await audit.record(
        case_id="case-1",
        actor="bioops-manager",
        event_type="room.agent_stream",
        payload={"summary": "打字机增量", "payload": {"chunk": "你"}},
    )
    await audit.record(
        case_id="case-1",
        actor="bioops-manager",
        event_type="room.agent_message",
        payload={"summary": "终态回复"},
    )

    persisted_keys = sorted(minio_client.objects)
    assert persisted_keys == ["cases/case-1/events/audit.jsonl"]
    persisted = minio_client.objects[persisted_keys[0]].decode()
    assert "room.agent_stream" not in persisted
    assert "room.agent_message" in persisted

    listed = await audit.list_events("case-1")
    assert {event["event_type"] for event in listed} == {
        "room.agent_stream",
        "room.agent_message",
    }


@pytest.mark.asyncio
async def test_agent_stream_is_gone_after_store_rebuild(tmp_path) -> None:
    minio_client = FakeMinioClient()
    storage = make_storage(minio_client)
    audit = AuditStore(str(tmp_path / "audit.jsonl"), minio_storage=storage)
    await audit.record(
        case_id="case-1",
        actor="bioops-manager",
        event_type="room.agent_stream",
        payload={"summary": "打字机增量"},
    )
    await audit.record(
        case_id="case-1",
        actor="bioops-manager",
        event_type="room.agent_message",
        payload={"summary": "终态回复"},
    )

    rebuilt = AuditStore(str(tmp_path / "audit-rebuild.jsonl"), minio_storage=storage)
    relisted = await rebuilt.list_events("case-1")

    assert [event["event_type"] for event in relisted] == ["room.agent_message"]


@pytest.mark.asyncio
async def test_room_mirror_skips_agent_stream() -> None:
    gateway = FakeGatewayClient()
    mirror = AuditRoomMirror(gateway)
    mirror.observe(
        {
            "case_id": "bioops_1",
            "actor": "bioops-manager",
            "event_type": "room.created",
            "payload": {"payload": {"room_id": "!room:test"}},
        }
    )

    mirror.observe(
        {
            "case_id": "bioops_1",
            "actor": "bioops-manager",
            "event_type": "room.agent_stream",
            "payload": {"summary": "打字机增量", "payload": {"chunk": "你"}},
        }
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert gateway.sent == []
