"""阶段 R 故障恢复与断点续跑：失联回收、级联跳过、手动干预、重启续跑。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from omichub_agentteams_bridge.audit import AuditStore
from omichub_agentteams_bridge.case_store import CaseStore
from omichub_agentteams_bridge.config import BridgeSettings
from omichub_agentteams_bridge.models import (
    ApprovalRequest,
    CaseCreateRequest,
    ContextRef,
    ReadOnlyExecutionRequest,
    WorkItemCreateRequest,
    WorkItemUpdateRequest,
)
from omichub_agentteams_bridge.service import BridgeService


class FakeOmicHubClient:
    async def aclose(self) -> None:
        return None


class CompletingGateway:
    configured = True

    async def consult(self, payload: dict[str, object]) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "status": "completed",
            "conclusion": f"Completed {payload['agent_id']}",
            "recommendations": [],
            "evidence_refs": [],
            "risks": [],
            "agent_id": payload["agent_id"],
            "schema_ver": "1.0",
            "duration_ms": 10,
            "token_usage": 1,
        }


class PlanningGateway(CompletingGateway):
    """Returns a DAG plan declaring retry/timeout fields on the planning consult."""

    async def consult(self, payload: dict[str, object]) -> dict[str, object]:
        result = await super().consult(payload)
        if payload.get("capability") == "planning_advice":
            result["proposed_submission"] = {
                "name": "dag-with-retry",
                "parameters": {
                    "work_items": [
                        {
                            "work_item_id": "exec-01",
                            "target": "agent-code",
                            "objective": "Run the declared step.",
                            "skill_name": "code-run",
                            "retry": {"max_attempts": 2, "backoff_seconds": 45},
                            "timeout_seconds": 900,
                        },
                        {
                            "work_item_id": "exec-02",
                            "target": "agent-viz",
                            "objective": "Render outputs.",
                            "skill_name": "viz-render",
                            "depends_on": ["exec-01"],
                        },
                    ]
                },
            }
        return result


def make_settings(tmp_path) -> BridgeSettings:
    return BridgeSettings(
        omichub_service_token="service-token",
        approval_signing_secret="test-signing-secret",
        identities=(
            "approval-authority:approval,bioops-manager:manager,"
            "agent-code:code,agent-viz:viz"
        ),
        role_agent_map="agent-code:agent-code,agent-viz:agent-viz",
        audit_log_path=str(tmp_path / "audit.jsonl"),
        case_store_path=str(tmp_path / "cases.json"),
        manifest_dir=str(tmp_path / "manifests"),
    )


def make_service(tmp_path, gateway=None) -> BridgeService:
    settings = make_settings(tmp_path)
    return BridgeService(
        settings,
        FakeOmicHubClient(),
        AuditStore(settings.audit_log_path),
        CaseStore(settings.case_store_path),
        gateway if gateway is not None else CompletingGateway(),
    )


async def create_case(service: BridgeService, case_id: str = "recovery-case") -> None:
    await service.create_case(
        CaseCreateRequest(
            case_id=case_id,
            project_ref=ContextRef(kind="project", id="project-1"),
            intent="recovery acceptance",
            requester_ref="user-1",
        ),
        "bioops-manager",
    )


async def assign(
    service: BridgeService,
    work_item_id: str,
    *,
    target: str = "agent-code",
    depends_on: list[str] | None = None,
    max_attempts: int = 3,
    case_id: str = "recovery-case",
) -> None:
    await service.assign_work_item(
        case_id,
        WorkItemCreateRequest(
            work_item_id=work_item_id,
            target=target,
            objective=f"Objective of {work_item_id}",
            skill_name="code-review",
            depends_on=depends_on or [],
            max_attempts=max_attempts,
        ),
        "bioops-manager",
    )


def expire_lease(item):
    return item.model_copy(
        update={"lease_expires_at": datetime.now(UTC) - timedelta(seconds=1)}
    )


@pytest.mark.asyncio
async def test_lease_renewal_failure_is_recorded_for_diagnosis(tmp_path, monkeypatch) -> None:
    service = make_service(tmp_path)
    recorded: list[dict] = []

    async def fail_heartbeat(*_args, **_kwargs):
        raise RuntimeError("case store unavailable")

    async def record(**kwargs):
        recorded.append(kwargs)

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(service._cases, "heartbeat_work_item", fail_heartbeat)
    monkeypatch.setattr(service._audit, "record", record)
    monkeypatch.setattr("omichub_agentteams_bridge.service.asyncio.sleep", no_wait)

    await service._renew_work_item_lease("recovery-case", "code-01", "agent-code", 30)

    assert recorded == [{
        "case_id": "recovery-case",
        "actor": "agent-code",
        "event_type": "worker.lease_renewal_failed",
        "payload": {
            "work_item_id": "code-01",
            "error": "case store unavailable",
            "deadline_seconds": 30,
        },
    }]


@pytest.mark.asyncio
async def test_killed_worker_task_is_reclaimed_by_watchdog_and_completes(tmp_path) -> None:
    service = make_service(tmp_path)
    await create_case(service)
    await assign(service, "code-01")

    claimed = await service.claim_work_item("recovery-case", "code-01", "agent-code")
    assert claimed.attempt == 1
    # 模拟 Worker 被 kill：租约过期、再无心跳，也没有其他 Worker 轮询 inbox。
    await service._cases.update_work_item("recovery-case", "code-01", expire_lease(claimed))

    sweep = await service.sweep_work_items()

    assert sweep == {"requeued": 1, "timed_out": 0, "retry_promoted": 0}
    requeued = await service._cases.get_work_item("recovery-case", "code-01")
    assert requeued.status == "pending"
    assert requeued.lease_owner is None
    # 同角色重派后链路最终完成。
    reclaimed = await service.claim_work_item("recovery-case", "code-01", "agent-code")
    assert reclaimed.attempt == 2
    completed = await service.execute_readonly_work_item(
        "recovery-case",
        "code-01",
        ReadOnlyExecutionRequest(
            agent_id="agent-code", capability="planning_advice", question="Finish it."
        ),
        "agent-code",
    )
    assert completed.status == "completed"

    events = await service.get_case_events("recovery-case", "bioops-manager")
    event_types = [event["event_type"] for event in events.events]
    assert "work_item.lease_expired" in event_types
    lease_event = next(
        event for event in events.events if event["event_type"] == "work_item.lease_expired"
    )
    assert lease_event["payload"]["action"] == "requeued"
    assert "心跳超时" in lease_event["payload"]["summary"]
    assert event_types.index("work_item.lease_expired") < event_types.index("skill.finished")


@pytest.mark.asyncio
async def test_lease_loss_with_exhausted_budget_times_out_and_cascades_skip(tmp_path) -> None:
    service = make_service(tmp_path)
    await create_case(service)
    await assign(service, "stage-a", max_attempts=1)
    await assign(service, "stage-b", depends_on=["stage-a"])
    await assign(service, "stage-c", target="agent-viz", depends_on=["stage-b"])

    claimed = await service.claim_work_item("recovery-case", "stage-a", "agent-code")
    await service._cases.update_work_item("recovery-case", "stage-a", expire_lease(claimed))

    sweep = await service.sweep_work_items()

    assert sweep == {"requeued": 0, "timed_out": 1, "retry_promoted": 0}
    case = await service._cases.get("recovery-case")
    statuses = {item.work_item_id: item.status for item in case.work_items}
    assert statuses == {"stage-a": "timeout", "stage-b": "skipped", "stage-c": "skipped"}
    # 终态工作项不可再被认领（终态保护或依赖未满足，均为 409）。
    for work_item_id, target in (("stage-a", "agent-code"), ("stage-b", "agent-code")):
        with pytest.raises(HTTPException, match="terminal|dependencies are not completed"):
            await service.claim_work_item("recovery-case", work_item_id, target)

    events = await service.get_case_events("recovery-case", "bioops-manager")
    timeout_events = [e for e in events.events if e["event_type"] == "work_item.timeout"]
    skipped_events = [e for e in events.events if e["event_type"] == "work_item.skipped"]
    assert len(timeout_events) == 1
    assert timeout_events[0]["payload"]["attempt"] == 1
    assert {e["payload"]["work_item_id"] for e in skipped_events} == {"stage-b", "stage-c"}
    assert all(e["payload"]["cause_work_item_id"] == "stage-a" for e in skipped_events)
    assert all("跳过" in e["payload"]["summary"] for e in skipped_events)


@pytest.mark.asyncio
async def test_retry_exhaustion_cascades_skip_and_notifies(tmp_path) -> None:
    service = make_service(tmp_path)
    await create_case(service)
    await assign(service, "stage-a", max_attempts=1)
    await assign(service, "stage-b", depends_on=["stage-a"])

    await service.claim_work_item("recovery-case", "stage-a", "agent-code")
    failed = await service.update_work_item(
        "recovery-case",
        "stage-a",
        WorkItemUpdateRequest(status="failed", summary="deterministic input error"),
        "agent-code",
    )
    assert failed.status == "failed"

    case = await service._cases.get("recovery-case")
    statuses = {item.work_item_id: item.status for item in case.work_items}
    assert statuses["stage-a"] == "failed"
    assert statuses["stage-b"] == "skipped"

    events = await service.get_case_events("recovery-case", "bioops-manager")
    exhausted = next(e for e in events.events if e["event_type"] == "work_item.retry_exhausted")
    assert "手动重试" in exhausted["payload"]["summary"]
    skipped = next(e for e in events.events if e["event_type"] == "work_item.skipped")
    assert skipped["payload"]["cause_work_item_id"] == "stage-a"


@pytest.mark.asyncio
async def test_restart_resumes_without_reexecuting_completed_stages(tmp_path) -> None:
    service = make_service(tmp_path)
    await create_case(service)
    await assign(service, "stage-01")
    await assign(service, "stage-02", depends_on=["stage-01"])

    await service.claim_work_item("recovery-case", "stage-01", "agent-code")
    completed = await service.execute_readonly_work_item(
        "recovery-case",
        "stage-01",
        ReadOnlyExecutionRequest(
            agent_id="agent-code", capability="planning_advice", question="Stage one."
        ),
        "agent-code",
    )
    assert completed.status == "completed"
    claimed = await service.claim_work_item("recovery-case", "stage-02", "agent-code")
    # 服务在 stage-02 运行中崩溃。
    await service._cases.update_work_item("recovery-case", "stage-02", expire_lease(claimed))

    # 重启：同一持久化路径上的全新 CaseStore / Service。
    settings = make_settings(tmp_path)
    restarted = BridgeService(
        settings,
        FakeOmicHubClient(),
        AuditStore(settings.audit_log_path),
        CaseStore(settings.case_store_path),
        CompletingGateway(),
    )
    sweep = await restarted.sweep_work_items()

    assert sweep["requeued"] == 1
    case = await restarted._cases.get("recovery-case")
    items = {item.work_item_id: item for item in case.work_items}
    assert items["stage-01"].status == "completed"
    assert items["stage-01"].attempt == 1  # 已成功的 stage 不重复执行
    assert items["stage-02"].status == "pending"
    reclaimed = await restarted.claim_work_item("recovery-case", "stage-02", "agent-code")
    assert reclaimed.attempt == 2
    finished = await restarted.execute_readonly_work_item(
        "recovery-case",
        "stage-02",
        ReadOnlyExecutionRequest(
            agent_id="agent-code", capability="planning_advice", question="Stage two."
        ),
        "agent-code",
    )
    assert finished.status == "completed"


@pytest.mark.asyncio
async def test_manual_retry_resets_budget_after_exhaustion(tmp_path) -> None:
    service = make_service(tmp_path)
    await create_case(service)
    await assign(service, "fragile-01", max_attempts=1)

    await service.claim_work_item("recovery-case", "fragile-01", "agent-code")
    failed = await service.update_work_item(
        "recovery-case",
        "fragile-01",
        WorkItemUpdateRequest(status="failed", summary="boom"),
        "agent-code",
    )
    assert failed.status == "failed"
    with pytest.raises(HTTPException) as exhausted_claim:
        await service.claim_work_item("recovery-case", "fragile-01", "agent-code")
    assert exhausted_claim.value.status_code == 409
    # 非 Manager 不允许手动重置。
    with pytest.raises(HTTPException) as denied:
        await service.update_work_item(
            "recovery-case",
            "fragile-01",
            WorkItemUpdateRequest(status="pending"),
            "agent-code",
        )
    assert denied.value.status_code == 422

    requeued = await service.update_work_item(
        "recovery-case",
        "fragile-01",
        WorkItemUpdateRequest(status="pending"),
        "bioops-manager",
    )
    assert requeued.status == "pending"
    assert requeued.attempt == 0

    reclaimed = await service.claim_work_item("recovery-case", "fragile-01", "agent-code")
    assert reclaimed.attempt == 1
    completed = await service.execute_readonly_work_item(
        "recovery-case",
        "fragile-01",
        ReadOnlyExecutionRequest(
            agent_id="agent-code", capability="planning_advice", question="Retry succeeds."
        ),
        "agent-code",
    )
    assert completed.status == "completed"
    events = await service.get_case_events("recovery-case", "bioops-manager")
    assert any(e["event_type"] == "work_item.manual_retry" for e in events.events)


@pytest.mark.asyncio
async def test_manager_force_cancel_running_item_cascades_skip(tmp_path) -> None:
    service = make_service(tmp_path)
    await create_case(service)
    await assign(service, "run-01")
    await assign(service, "run-02", depends_on=["run-01"])

    claimed = await service.claim_work_item("recovery-case", "run-01", "agent-code")
    assert claimed.lease_owner == "agent-code"

    cancelled = await service.update_work_item(
        "recovery-case",
        "run-01",
        WorkItemUpdateRequest(status="cancelled", summary="用户要求终止该步骤"),
        "bioops-manager",
    )
    assert cancelled.status == "cancelled"
    assert cancelled.lease_owner is None

    case = await service._cases.get("recovery-case")
    statuses = {item.work_item_id: item.status for item in case.work_items}
    assert statuses["run-02"] == "skipped"
    events = await service.get_case_events("recovery-case", "bioops-manager")
    assert any(e["event_type"] == "work_item.cancelled" for e in events.events)
    assert any(e["event_type"] == "work_item.skipped" for e in events.events)


@pytest.mark.asyncio
async def test_dag_retry_and_timeout_fields_flow_into_work_items(tmp_path) -> None:
    service = make_service(tmp_path, PlanningGateway())
    case = await service.create_case(
        CaseCreateRequest(
            case_id="dag-case",
            context_refs=[ContextRef(kind="file", id="input.csv")],
            intent="run a small dag",
            requester_ref="user-1",
            lead_planner="agent-code",
        ),
        "bioops-manager",
    )
    assert case.status == "planning_running"
    await service.claim_work_item("dag-case", "plan-01", "agent-code")
    await service.execute_readonly_work_item(
        "dag-case",
        "plan-01",
        ReadOnlyExecutionRequest(
            agent_id="agent-code", capability="planning_advice", question="Plan it."
        ),
        "agent-code",
    )
    approval = await service.issue_approval(
        ApprovalRequest(case_id="dag-case", action="execute_plan"), "approval-authority"
    )
    approved = await service.execute_general_plan(
        "dag-case", approval.token, "approval-authority"
    )

    items = {item.work_item_id: item for item in approved.work_items}
    assert items["exec-01"].max_attempts == 2
    assert items["exec-01"].retry_backoff_seconds == 45
    assert items["exec-01"].deadline_seconds == 900
    # 未声明的节点使用默认重试策略。
    assert items["exec-02"].max_attempts == 3
    assert items["exec-02"].retry_backoff_seconds is None
    # 声明的 backoff 指数增长：attempt=1 -> 45s。
    assert service._retry_delay_seconds(items["exec-01"].model_copy(update={"attempt": 1})) == 45
    assert service._retry_delay_seconds(items["exec-01"].model_copy(update={"attempt": 2})) == 90
