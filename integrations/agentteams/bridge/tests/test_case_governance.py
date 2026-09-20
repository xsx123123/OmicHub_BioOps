from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from cygnusx_agentteams_bridge.app import case_gc_autorun_enabled, create_app
from cygnusx_agentteams_bridge.audit import AuditStore
from cygnusx_agentteams_bridge.case_store import CaseStore
from cygnusx_agentteams_bridge.config import BridgeSettings
from cygnusx_agentteams_bridge.models import (
    CaseCancelRequest,
    CaseCreateRequest,
    ContextRef,
    WorkItemCreateRequest,
    WorkItemUpdateRequest,
)
from cygnusx_agentteams_bridge.service import BridgeService


class FakeCygnusXClient:
    def __init__(self, task_status: str = "success") -> None:
        self.task_status = task_status

    async def aclose(self) -> None:
        return None

    async def get_task(self, task_id: str) -> dict:
        return {"id": task_id, "status": self.task_status}

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
        "cygnusx_service_token": "service-token",
        "approval_signing_secret": "test-signing-secret",
        "identities": (
            "approval-authority:approval,bioops-manager:manager,data-steward:steward,"
            "workflow-operator:operator,quality-auditor:auditor,delivery-reporter:reporter,"
            "agent-code:code,agent-viz:viz,agent-scrna:scrna,agent-rnaseq:rnaseq"
        ),
        "role_agent_map": (
            "data-steward:agent-data,quality-auditor:agent-qc,"
            "delivery-reporter:agent-delivery,agent-code:agent-code,"
            "agent-viz:agent-viz,agent-scrna:agent-scrna,agent-rnaseq:agent-rnaseq"
        ),
        "audit_log_path": str(tmp_path / "audit.jsonl"),
        "case_store_path": str(tmp_path / "cases.json"),
        "manifest_dir": str(tmp_path / "manifests"),
    }
    values.update(overrides)
    return BridgeSettings(**values)


def make_service(tmp_path, task_status: str = "success", **overrides) -> BridgeService:
    settings = make_settings(tmp_path, **overrides)
    return BridgeService(
        settings,
        FakeCygnusXClient(task_status),
        AuditStore(settings.audit_log_path),
        CaseStore(settings.case_store_path),
    )


async def create_case(service: BridgeService, case_id: str) -> None:
    await service.create_case(
        CaseCreateRequest(
            case_id=case_id,
            project_ref=ContextRef(kind="project", id="project-1"),
            intent="governance-test",
            requester_ref="user-1",
        ),
        "bioops-manager",
    )


async def create_flow_case(service: BridgeService, case_id: str) -> None:
    await service.create_case(
        CaseCreateRequest(
            case_id=case_id,
            project_ref=ContextRef(kind="project", id="project-1"),
            intent="governance-flow-test",
            requester_ref="user-1",
            flow_id="rna_seq",
        ),
        "bioops-manager",
    )


async def assign_and_claim(
    service: BridgeService, case_id: str, work_item_id: str, target: str = "data-steward"
) -> None:
    await service.assign_work_item(
        case_id,
        WorkItemCreateRequest(
            work_item_id=work_item_id,
            target=target,
            objective="Produce a governance test artifact.",
            skill_name="project-preflight",
        ),
        "bioops-manager",
    )
    await service.claim_work_item(case_id, work_item_id, target)


async def move_case_to_executing(service: BridgeService, case_id: str, task_id: str) -> None:
    # Auto-created plan-01 would block auto-reconcile; accept it so downstream
    # executing tests can focus on task-level reconciliation.
    case = await service._cases.get(case_id)
    plan_item = next(
        (item for item in case.work_items if item.work_item_id == "plan-01" and item.status == "pending"),
        None,
    )
    if plan_item is not None:
        await service.claim_work_item(case_id, "plan-01", plan_item.target)
        await service.update_work_item(
            case_id,
            "plan-01",
            WorkItemUpdateRequest(status="completed", summary="plan accepted"),
            plan_item.target,
        )
    for target_status in ("planning_running", "approval_pending", "approved", "executing"):
        case = await service._cases.get(case_id)
        if case.status == target_status:
            continue
        await service._cases.transition(case_id, target_status)
    await service._cases.attach_task(case_id, task_id)


async def backdate_case(service: BridgeService, case_id: str, days: int) -> None:
    case = await service._cases.get(case_id)
    stale = case.model_copy(
        update={"updated_at": datetime.now(UTC) - timedelta(days=days)}
    )
    service._cases._cases[case_id] = stale
    await service._cases._persist()


@pytest.mark.asyncio
async def test_auto_reconcile_skips_chat_case_without_flow_id(tmp_path) -> None:
    service = make_service(tmp_path)
    case_id = "gc-reconcile-received"
    await create_case(service, case_id)
    await assign_and_claim(service, case_id, "adhoc-01")

    await service.update_work_item(
        case_id, "adhoc-01", WorkItemUpdateRequest(status="completed", summary="done"), "data-steward"
    )

    case = await service._cases.get(case_id)
    assert case.status == "received"
    assert not any(item.work_item_id == "plan-01" for item in case.work_items)


@pytest.mark.asyncio
async def test_auto_reconcile_moves_executing_case_to_delivery_after_task_success(tmp_path) -> None:
    service = make_service(tmp_path, task_status="success")
    case_id = "gc-reconcile-executing"
    await create_flow_case(service, case_id)
    await assign_and_claim(service, case_id, "interpret-01")
    await move_case_to_executing(service, case_id, "task-1")

    await service.update_work_item(
        case_id,
        "interpret-01",
        WorkItemUpdateRequest(status="completed", summary="interpreted"),
        "data-steward",
    )

    case = await service._cases.get(case_id)
    assert case.status == "delivery_ready"
    delivery = next(item for item in case.work_items if item.work_item_id == "delivery-01")
    assert delivery.status == "pending"


@pytest.mark.asyncio
async def test_auto_reconcile_is_idempotent_for_terminal_case(tmp_path) -> None:
    service = make_service(tmp_path)
    case_id = "gc-reconcile-idempotent"
    await create_case(service, case_id)
    await assign_and_claim(service, case_id, "adhoc-01")
    await service.update_work_item(
        case_id, "adhoc-01", WorkItemUpdateRequest(status="completed", summary="done"), "data-steward"
    )
    first = await service._cases.get(case_id)
    assert first.status == "received"

    # Chat cases without flow_id must not be advanced by repeated reconcile.
    await service._auto_reconcile(case_id)
    second = await service._cases.get(case_id)
    assert second.status == "received"

    await service.cancel_case(case_id, CaseCancelRequest(reason="no longer needed"), "bioops-manager")
    await service._auto_reconcile(case_id)
    terminal = await service._cases.get(case_id)
    assert terminal.status == "cancelled"


@pytest.mark.asyncio
async def test_auto_reconcile_skips_case_with_in_flight_omic_task(tmp_path) -> None:
    service = make_service(tmp_path, task_status="running")
    case_id = "gc-reconcile-inflight"
    await create_flow_case(service, case_id)
    await assign_and_claim(service, case_id, "interpret-01")
    await move_case_to_executing(service, case_id, "task-1")

    await service.update_work_item(
        case_id,
        "interpret-01",
        WorkItemUpdateRequest(status="completed", summary="interpreted"),
        "data-steward",
    )

    case = await service._cases.get(case_id)
    assert case.status == "executing"
    assert not any(item.work_item_id == "delivery-01" for item in case.work_items)


@pytest.mark.asyncio
async def test_auto_reconcile_skips_failed_work_item_with_retry_budget(tmp_path) -> None:
    service = make_service(tmp_path)
    case_id = "gc-reconcile-retry"
    await create_flow_case(service, case_id)
    await assign_and_claim(service, case_id, "adhoc-01")
    await move_case_to_executing(service, case_id, "task-1")

    await service.update_work_item(
        case_id, "adhoc-01", WorkItemUpdateRequest(status="failed", summary="boom"), "data-steward"
    )

    case = await service._cases.get(case_id)
    assert case.status == "executing"
    retried = next(item for item in case.work_items if item.work_item_id == "adhoc-01")
    assert retried.status == "failed"
    assert retried.retry_not_before is not None


@pytest.mark.asyncio
async def test_case_gc_deletes_stale_terminal_cases_and_their_audit_events(tmp_path) -> None:
    service = make_service(tmp_path)
    for case_id in ("gc-stale-cancelled", "gc-stale-failed"):
        await create_case(service, case_id)
    await service.cancel_case(
        "gc-stale-cancelled", CaseCancelRequest(reason="stale"), "bioops-manager"
    )
    await move_case_to_executing(service, "gc-stale-failed", "task-1")
    await service._cases.transition("gc-stale-failed", "execution_failed")
    await create_case(service, "gc-recent-cancelled")
    await service.cancel_case(
        "gc-recent-cancelled", CaseCancelRequest(reason="recent"), "bioops-manager"
    )
    await create_case(service, "gc-active")
    await backdate_case(service, "gc-stale-cancelled", days=10)
    await backdate_case(service, "gc-stale-failed", days=10)

    assert await service._audit.list_events("gc-stale-cancelled")

    summary = await service.gc_cases("bioops-manager")

    assert summary["gc_enabled"] is True
    assert summary["deleted_cases"] == 2
    assert summary["deleted_events"] > 0
    for deleted in ("gc-stale-cancelled", "gc-stale-failed"):
        with pytest.raises(Exception) as excinfo:
            await service._cases.get(deleted)
        assert getattr(excinfo.value, "status_code", None) == 404
        assert await service._audit.list_events(deleted) == []
    for retained in ("gc-recent-cancelled", "gc-active"):
        assert (await service._cases.get(retained)).case_id == retained
        assert await service._audit.list_events(retained)
    audit_text = Path(service._settings.audit_log_path).read_text(encoding="utf-8")
    assert "gc-stale-cancelled" not in audit_text
    assert "gc-recent-cancelled" in audit_text


@pytest.mark.asyncio
async def test_case_gc_is_disabled_when_days_is_zero(tmp_path) -> None:
    service = make_service(tmp_path, case_gc_days=0)
    await create_case(service, "gc-disabled")
    await service.cancel_case("gc-disabled", CaseCancelRequest(reason="stale"), "bioops-manager")
    await backdate_case(service, "gc-disabled", days=30)

    summary = await service.gc_cases("bioops-manager")

    assert summary["gc_enabled"] is False
    assert summary["deleted_cases"] == 0
    assert (await service._cases.get("gc-disabled")).status == "cancelled"


@pytest.mark.asyncio
async def test_case_gc_endpoint_is_manager_only(tmp_path) -> None:
    settings = make_settings(tmp_path)
    app = create_app(settings, FakeCygnusXClient())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://bridge.test"
    ) as client:
        denied = await client.post(
            "/v1/maintenance/case-gc",
            headers={"X-Bridge-Identity": "data-steward", "X-Bridge-Token": "steward"},
        )
        assert denied.status_code == 403
        allowed = await client.post(
            "/v1/maintenance/case-gc",
            headers={"X-Bridge-Identity": "bioops-manager", "X-Bridge-Token": "manager"},
        )
        assert allowed.status_code == 200
        assert allowed.json()["gc_enabled"] is True


def test_case_gc_autorun_only_outside_production(tmp_path) -> None:
    development = make_settings(tmp_path)
    assert case_gc_autorun_enabled(development) is True
    assert case_gc_autorun_enabled(development.model_copy(update={"case_gc_days": 0})) is False
    assert (
        case_gc_autorun_enabled(development.model_copy(update={"environment": "production"}))
        is False
    )


@pytest.mark.asyncio
async def test_delete_case_removes_terminal_case_and_audit_events(tmp_path) -> None:
    service = make_service(tmp_path)
    await create_case(service, "delete-terminal")
    await service.cancel_case(
        "delete-terminal", CaseCancelRequest(reason="done"), "bioops-manager"
    )

    result = await service.delete_case("delete-terminal", "bioops-manager")

    assert result["deleted"] is True
    assert result["cancelled_before_delete"] is False
    assert result["deleted_events"] > 0
    with pytest.raises(Exception) as excinfo:
        await service._cases.get("delete-terminal")
    assert getattr(excinfo.value, "status_code", None) == 404
    assert await service._audit.list_events("delete-terminal") == []


@pytest.mark.asyncio
async def test_delete_case_cancels_active_case_and_reclaims_work_items(tmp_path) -> None:
    service = make_service(tmp_path)
    await create_case(service, "delete-active")
    await assign_and_claim(service, "delete-active", "wi-1")

    result = await service.delete_case("delete-active", "bioops-manager", reason="user deleted")

    assert result["deleted"] is True
    assert result["cancelled_before_delete"] is True
    with pytest.raises(Exception) as excinfo:
        await service._cases.get("delete-active")
    assert getattr(excinfo.value, "status_code", None) == 404
    assert await service._audit.list_events("delete-active") == []


@pytest.mark.asyncio
async def test_delete_case_endpoint_is_manager_only(tmp_path) -> None:
    settings = make_settings(tmp_path)
    app = create_app(settings, FakeCygnusXClient())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://bridge.test"
    ) as client:
        created = await client.post(
            "/v1/cases",
            headers={"X-Bridge-Identity": "bioops-manager", "X-Bridge-Token": "manager"},
            json={
                "case_id": "delete-endpoint",
                "project_ref": {"kind": "project", "id": "project-1"},
                "intent": "delete-endpoint-test",
                "requester_ref": "user-1",
            },
        )
        assert created.status_code == 201
        denied = await client.delete(
            "/v1/cases/delete-endpoint",
            headers={"X-Bridge-Identity": "data-steward", "X-Bridge-Token": "steward"},
        )
        assert denied.status_code == 403
        deleted = await client.delete(
            "/v1/cases/delete-endpoint",
            headers={"X-Bridge-Identity": "bioops-manager", "X-Bridge-Token": "manager"},
        )
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
        missing = await client.get(
            "/v1/cases/delete-endpoint",
            headers={"X-Bridge-Identity": "bioops-manager", "X-Bridge-Token": "manager"},
        )
        assert missing.status_code == 404
