from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from omichub_agentteams_bridge.audit import AuditStore
from omichub_agentteams_bridge.case_store import CaseStore
from omichub_agentteams_bridge.config import BridgeSettings
from omichub_agentteams_bridge.models import (
    ApprovalRequest,
    ApprovedSubmission,
    CaseCancelRequest,
    CaseCreateRequest,
    CaseRecord,
    ContextRef,
    PlanRevisionRequest,
    PreflightInputSnapshot,
    QualityGateRequest,
    ReadOnlyExecutionRequest,
    RetryCaseSubmissionRequest,
    TaskSpec,
    WorkItemCreateRequest,
    WorkItemRecord,
    WorkItemUpdateRequest,
)
from omichub_agentteams_bridge.service import BridgeService


class FakeOmicHubClient:
    async def aclose(self) -> None:
        return None


class ConcurrentGateway:
    configured = True

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.payloads: list[dict[str, object]] = []

    async def consult(self, payload: dict[str, object]) -> dict[str, object]:
        self.payloads.append(payload)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.03)
            return {
                "schema_version": "1.0",
                "status": "completed",
                "conclusion": f"Completed {payload['agent_id']}",
                "recommendations": ["Keep the result reproducible."],
                "evidence_refs": ["omic://project/project-1"],
                "risks": [],
                "agent_id": payload["agent_id"],
                "schema_ver": "1.0",
                "duration_ms": 30,
                "token_usage": 42,
            }
        finally:
            self.active -= 1


class FailingGateway:
    configured = True

    async def consult(self, _payload: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("temporary gateway failure")


class PlanningGateway:
    configured = True

    async def consult(self, payload: dict[str, object]) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "status": "completed",
            "conclusion": "冻结 RNA-seq 执行计划。",
            "recommendations": ["Proceed with project preflight."],
            "evidence_refs": ["omic://project/project-1"],
            "risks": [],
            "agent_id": payload["agent_id"],
            "schema_ver": "1.0",
            "duration_ms": 1,
            "token_usage": 10,
            "proposed_submission": {
                "flow_id": "rna_seq",
                "name": "rna-seq-analysis",
                "sample_sheet": [{"sample": "sample-a", "group": "control"}],
                "comparisons": [{"control": "control", "treatment": "treated"}],
            },
        }


class HardGateGateway:
    configured = True

    async def consult(self, payload: dict[str, object]) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "status": "completed",
            "conclusion": "BLOCKED\nmapping_rate=0.30 < threshold=0.70",
            "recommendations": ["检查比对参数并重跑。"],
            "evidence_refs": ["task:task-1", "rule:rna_seq:mapping_rate"],
            "risks": [],
            "agent_id": payload["agent_id"],
            "schema_ver": "1.0",
            "duration_ms": 1,
            "token_usage": 1,
            "hard_gate": {
                "decision": "BLOCKED",
                "audit_event": {
                    "event_type": "quality.hard_gate",
                    "decision": "BLOCKED",
                    "reason": "mapping_rate 30.0% 低于阈值 70.0%",
                    "metric": "mapping_rate",
                    "value": 0.3,
                    "threshold": 0.7,
                    "flow_id": "rna_seq",
                    "rule_version": "1.0.0",
                },
            },
        }


class TreeplotPlanningGateway:
    configured = True

    async def consult(self, payload: dict[str, object]) -> dict[str, object]:
        if payload["agent_id"] == "agent-code" and payload.get("capability") == "planning_advice":
            proposed_submission = {
                "name": "treeplot-analysis",
                "parameters": {
                    "work_items": [
                        {
                            "work_item_id": "exec-01",
                            "target": "agent-code",
                            "objective": "Align two FASTA inputs and build a tree.",
                            "skill_name": "phylo-build",
                        },
                        {
                            "work_item_id": "exec-02",
                            "target": "agent-viz",
                            "objective": "Render the validated treeplot.",
                            "skill_name": "treeplot-render",
                            "depends_on": ["exec-01"],
                        },
                    ]
                },
            }
        else:
            proposed_submission = None
        return {
            "schema_version": "1.0",
            "status": "completed",
            "conclusion": "Treeplot step completed.",
            "recommendations": [],
            "evidence_refs": [],
            "risks": [],
            "agent_id": payload["agent_id"],
            "schema_ver": "1.0",
            "duration_ms": 1,
            "token_usage": 1,
            "proposed_submission": proposed_submission,
            "artifacts": [
                {
                    "path": "users/test/workspace/agentteams/treeplot-case/exec-01/tree.nwk",
                    "kind": "file",
                    "bytes": 8,
                }
            ],
        }


def make_service(tmp_path, gateway: ConcurrentGateway) -> BridgeService:
    settings = BridgeSettings(
        omichub_service_token="service-token",
        approval_signing_secret="test-signing-secret",
        identities=(
            "approval-authority:approval,bioops-manager:manager,data-steward:steward,"
            "workflow-operator:operator,quality-auditor:auditor,delivery-reporter:reporter,"
            "agent-code:code,agent-viz:viz,agent-scrna:scrna,agent-rnaseq:rnaseq"
        ),
        role_agent_map=(
            "data-steward:agent-data,quality-auditor:agent-qc,"
            "delivery-reporter:agent-delivery,agent-code:agent-code,"
            "agent-viz:agent-viz,agent-scrna:agent-scrna,agent-rnaseq:agent-rnaseq"
        ),
        audit_log_path=str(tmp_path / "audit.jsonl"),
        case_store_path=str(tmp_path / "cases.json"),
        manifest_dir=str(tmp_path / "manifests"),
    )
    return BridgeService(
        settings,
        FakeOmicHubClient(),
        AuditStore(settings.audit_log_path),
        CaseStore(settings.case_store_path),
        gateway,
    )


async def create_case(service: BridgeService, case_id: str = "cluster-case") -> None:
    await service.create_case(
        CaseCreateRequest(
            case_id=case_id,
            project_ref=ContextRef(kind="project", id="project-1"),
            intent="read_only_cluster_consultation",
            requester_ref="user-1",
        ),
        "bioops-manager",
    )


@pytest.mark.asyncio
async def test_planning_consultation_freezes_plan_before_preflight(tmp_path) -> None:
    service = make_service(tmp_path, PlanningGateway())
    case = await service.create_case(
        CaseCreateRequest(
            case_id="planned-case",
            project_ref=ContextRef(kind="project", id="project-1"),
            intent="bulk_rnaseq_delivery",
            requester_ref="user-1",
            flow_id="rna_seq",
        ),
        "bioops-manager",
    )

    assert case.status == "planning_running"
    assert case.work_items[0].work_item_id == "plan-01"
    assert case.work_items[0].target == "agent-rnaseq"
    await service.claim_work_item("planned-case", "plan-01", "agent-rnaseq")
    result = await service.execute_readonly_work_item(
        "planned-case",
        "plan-01",
        ReadOnlyExecutionRequest(
            agent_id="agent-rnaseq",
            capability="planning_advice",
            question="Draft a frozen RNA-seq plan.",
            trace_id="trace-plan-01",
        ),
        "agent-rnaseq",
    )
    frozen_case = await service._cases.get("planned-case")

    assert result.status == "completed"
    assert frozen_case.status == "preflight_running"
    assert frozen_case.plan_hash
    assert (
        frozen_case.proposed_submission and frozen_case.proposed_submission["flow_id"] == "rna_seq"
    )
    preflight = next(item for item in frozen_case.work_items if item.work_item_id == "preflight-01")
    assert preflight.depends_on == ["plan-01"]


@pytest.mark.asyncio
async def test_workspace_execution_is_rejected_without_frozen_approved_plan(tmp_path) -> None:
    service = make_service(tmp_path, ConcurrentGateway())
    await create_case(service, "workspace-case")

    with pytest.raises(Exception, match="approval_required or a frozen plan"):
        await service.assign_work_item(
            "workspace-case",
            WorkItemCreateRequest(
                work_item_id="code-write-01",
                target="agent-code",
                objective="Generate a scoped report artifact.",
                skill_name="code-review",
                execution_mode="workspace_execution",
            ),
            "bioops-manager",
        )


@pytest.mark.asyncio
async def test_treeplot_general_case_freezes_plan_and_dispatches_workspace_dag(tmp_path) -> None:
    service = make_service(tmp_path, TreeplotPlanningGateway())
    case = await service.create_case(
        CaseCreateRequest(
            case_id="treeplot-case",
            context_refs=[
                ContextRef(kind="file", id="tree-a.fa"),
                ContextRef(kind="file", id="tree-b.fa"),
            ],
            intent="build a treeplot from two fasta files",
            requester_ref="user-1",
            lead_planner="agent-code",
        ),
        "bioops-manager",
    )
    assert case.status == "planning_running"
    await service.claim_work_item("treeplot-case", "plan-01", "agent-code")
    await service.execute_readonly_work_item(
        "treeplot-case",
        "plan-01",
        ReadOnlyExecutionRequest(
            agent_id="agent-code",
            capability="planning_advice",
            question="Plan treeplot.",
            trace_id="plan",
        ),
        "agent-code",
    )
    frozen = await service._cases.get("treeplot-case")
    assert frozen.status == "approval_pending"
    assert frozen.plan_hash
    approval = await service.issue_approval(
        ApprovalRequest(case_id="treeplot-case", action="execute_plan"), "approval-authority"
    )
    approved = await service.execute_general_plan(
        "treeplot-case", approval.token, "approval-authority"
    )
    assert approved.status == "approved"
    assert {item.work_item_id for item in approved.work_items} >= {"exec-01", "exec-02"}
    executable = next(item for item in approved.work_items if item.work_item_id == "exec-01")
    assert executable.plan_hash == approved.plan_hash
    await service.claim_work_item("treeplot-case", "exec-01", "agent-code")
    completed = await service.execute_readonly_work_item(
        "treeplot-case",
        "exec-01",
        ReadOnlyExecutionRequest(
            agent_id="agent-code",
            capability="workspace_execution",
            question="Build tree.",
            trace_id="exec",
            execution_mode="workspace_execution",
        ),
        "agent-code",
    )
    assert completed.status == "completed"
    assert completed.output_refs == [
        ContextRef(
            kind="file",
            id="users/test/workspace/agentteams/treeplot-case/exec-01/tree.nwk",
            location="users/test/workspace/agentteams/treeplot-case/exec-01/tree.nwk",
            meta={
                "local_path": "users/test/workspace/agentteams/treeplot-case/exec-01/tree.nwk",
                "size_bytes": 8,
                "sha256": None,
            },
        )
    ]


def test_general_plan_expands_fan_out_and_freezes_execution_mode(tmp_path) -> None:
    service = make_service(tmp_path, TreeplotPlanningGateway())
    payload = service._validate_general_plan(
        {
            "name": "clean-and-merge",
            "parameters": {
                "work_items": [
                    {
                        "work_item_id": "clean",
                        "target": "agent-code",
                        "objective": "清洗 CSV",
                        "skill_name": "csv-clean",
                        "fan_out": {"count": 4, "merge_strategy": "collect"},
                    }
                ]
            },
        }
    )
    work_items = payload["parameters"]["work_items"]

    assert [item["work_item_id"] for item in work_items] == [
        "clean-shard-01",
        "clean-shard-02",
        "clean-shard-03",
        "clean-shard-04",
        "clean-merge",
    ]
    assert work_items[-1]["depends_on"] == [item["work_item_id"] for item in work_items[:-1]]
    assert all(item["execution_mode"] == "workspace_execution" for item in work_items)


@pytest.mark.asyncio
async def test_workspace_claim_rejects_stale_plan_hash(tmp_path) -> None:
    service = make_service(tmp_path, TreeplotPlanningGateway())
    await service.create_case(
        CaseCreateRequest(
            case_id="stale-plan-case",
            context_refs=[ContextRef(kind="file", id="tree.fa")],
            intent="build a treeplot",
            requester_ref="user-1",
            lead_planner="agent-code",
        ),
        "bioops-manager",
    )
    await service.claim_work_item("stale-plan-case", "plan-01", "agent-code")
    await service.execute_readonly_work_item(
        "stale-plan-case",
        "plan-01",
        ReadOnlyExecutionRequest(
            agent_id="agent-code",
            capability="planning_advice",
            question="Plan treeplot.",
        ),
        "agent-code",
    )
    approval = await service.issue_approval(
        ApprovalRequest(case_id="stale-plan-case", action="execute_plan"),
        "approval-authority",
    )
    approved = await service.execute_general_plan(
        "stale-plan-case", approval.token, "approval-authority"
    )
    executable = next(item for item in approved.work_items if item.work_item_id == "exec-01")
    await service._cases.update_work_item(
        "stale-plan-case",
        "exec-01",
        executable.model_copy(update={"plan_hash": "0" * 64}),
    )

    with pytest.raises(Exception, match="not bound to the frozen plan"):
        await service.claim_work_item("stale-plan-case", "exec-01", "agent-code")


def test_workspace_artifact_refs_reject_paths_outside_work_item_directory() -> None:
    refs = BridgeService._workspace_artifact_refs(
        "treeplot-case",
        "exec-01",
        [
            {
                "path": "users/test/workspace/agentteams/treeplot-case/exec-01/tree.png",
                "kind": "file",
            },
            {
                "path": "users/test/workspace/agentteams/other-case/exec-01/leak.png",
                "kind": "file",
            },
            {"path": "../treeplot-case/exec-01/leak.png", "kind": "file"},
            {"path": "/tmp/treeplot-case/exec-01/leak.png", "kind": "file"},
        ],
    )

    assert [ref.id for ref in refs] == [
        "users/test/workspace/agentteams/treeplot-case/exec-01/tree.png"
    ]


def test_general_case_requires_a_file_or_workspace_context() -> None:
    with pytest.raises(ValueError, match="context_ref"):
        CaseCreateRequest(
            case_id="missing-context",
            intent="build a treeplot",
            requester_ref="user-1",
            lead_planner="agent-code",
        )


@pytest.mark.asyncio
async def test_all_readonly_worker_roles_execute_in_parallel(tmp_path) -> None:
    gateway = ConcurrentGateway()
    service = make_service(tmp_path, gateway)
    await create_case(service)
    assignments = [
        ("agent-code", "code-01", "code-review", "agent-code", "planning_advice"),
        ("agent-viz", "viz-01", "visualization-review", "agent-viz", "result_interpretation"),
        ("agent-scrna", "scrna-01", "scrna-interpretation", "agent-scrna", "interpretation"),
        (
            "data-steward",
            "data-01",
            "project-preflight",
            "agent-data",
            "project-preflight",
        ),
        ("quality-auditor", "quality-01", "quality-gate", "agent-qc", "quality-gate"),
        (
            "delivery-reporter",
            "delivery-01",
            "delivery-report",
            "agent-delivery",
            "delivery-pack",
        ),
    ]
    for identity, work_item_id, skill_name, *_ in assignments:
        await service.assign_work_item(
            "cluster-case",
            WorkItemCreateRequest(
                work_item_id=work_item_id,
                target=identity,
                objective=f"Review {identity} output.",
                skill_name=skill_name,
                context_refs=[ContextRef(kind="project", id="project-1")],
            ),
            "bioops-manager",
        )
        await service.claim_work_item("cluster-case", work_item_id, identity)

    results = await asyncio.gather(
        *(
            service.execute_readonly_work_item(
                "cluster-case",
                work_item_id,
                ReadOnlyExecutionRequest(
                    agent_id=agent_id,
                    capability=capability,
                    question=f"Review {identity} output.",
                    trace_id=f"trace-{work_item_id}",
                ),
                identity,
            )
            for identity, work_item_id, _, agent_id, capability in assignments
        )
    )

    assert gateway.max_active == len(assignments)
    assert {payload["requester_ref"] for payload in gateway.payloads} == {"user-1"}
    assert [result.status for result in results] == ["completed"] * len(assignments)
    events = await service.get_case_events("cluster-case", "bioops-manager")
    assert {event["event_type"] for event in events.events} >= {
        "work_item.claimed",
        "work_item.running",
        "worker.heartbeat",
        "skill.finished",
        "manager.review_ready",
    }


@pytest.mark.asyncio
async def test_expired_lease_is_requeued_and_can_be_claimed_again(tmp_path) -> None:
    service = make_service(tmp_path, ConcurrentGateway())
    await create_case(service)
    await service.assign_work_item(
        "cluster-case",
        WorkItemCreateRequest(
            work_item_id="code-01",
            target="agent-code",
            objective="Review code.",
            skill_name="code-review",
            deadline_seconds=30,
        ),
        "bioops-manager",
    )
    claimed = await service.claim_work_item("cluster-case", "code-01", "agent-code")
    expired = claimed.model_copy(
        update={"lease_expires_at": datetime.now(UTC) - timedelta(seconds=1)}
    )
    await service._cases.update_work_item("cluster-case", "code-01", expired)

    inbox = await service.list_worker_inbox("agent-code")

    assert inbox.items[0].work_item.status == "pending"
    reclaimed = await service.claim_work_item("cluster-case", "code-01", "agent-code")
    assert reclaimed.status == "claimed"
    assert reclaimed.attempt == 2


@pytest.mark.asyncio
async def test_failed_work_item_uses_persisted_backoff_then_exposes_choices(tmp_path) -> None:
    service = make_service(tmp_path, FailingGateway())
    await create_case(service)
    await service.assign_work_item(
        "cluster-case",
        WorkItemCreateRequest(
            work_item_id="retry-01",
            target="agent-code",
            objective="Retry bounded consultation.",
            skill_name="code-review",
            max_attempts=4,
        ),
        "bioops-manager",
    )

    observed_delays: list[int] = []
    for attempt in range(1, 5):
        claimed = await service.claim_work_item("cluster-case", "retry-01", "agent-code")
        assert claimed.attempt == attempt
        failed = await service.execute_readonly_work_item(
            "cluster-case",
            "retry-01",
            ReadOnlyExecutionRequest(
                agent_id="agent-code",
                capability="planning_advice",
                question="Try the bounded operation.",
            ),
            "agent-code",
        )
        assert failed.status == "failed"
        if attempt < 4:
            assert failed.retry_not_before is not None
            with pytest.raises(HTTPException, match="retry is not ready"):
                await service.claim_work_item("cluster-case", "retry-01", "agent-code")
            await service._cases.update_work_item(
                "cluster-case",
                "retry-01",
                failed.model_copy(
                    update={"retry_not_before": datetime.now(UTC) - timedelta(seconds=1)}
                ),
            )
            inbox = await service.list_worker_inbox("agent-code")
            assert inbox.items[0].work_item.status == "pending"
        else:
            assert failed.retry_not_before is None

    events = await service.get_case_events("cluster-case", "bioops-manager")
    observed_delays = [
        event["payload"]["delay_seconds"]
        for event in events.events
        if event["event_type"] == "work_item.retry_scheduled"
    ]
    exhausted = next(
        event for event in events.events if event["event_type"] == "work_item.retry_exhausted"
    )
    assert observed_delays == [30, 120, 480]
    assert exhausted["payload"]["options"] == ["retry", "skip", "terminate"]


@pytest.mark.asyncio
async def test_cancel_case_reclaims_running_work_and_retains_artifacts(tmp_path) -> None:
    service = make_service(tmp_path, ConcurrentGateway())
    await create_case(service)
    await service.assign_work_item(
        "cluster-case",
        WorkItemCreateRequest(
            work_item_id="running-01",
            target="agent-code",
            objective="Produce an intermediate artifact.",
            skill_name="code-review",
        ),
        "bioops-manager",
    )
    claimed = await service.claim_work_item("cluster-case", "running-01", "agent-code")
    running = await service._cases.transition_work_item(
        "cluster-case", "running-01", "agent-code", "running"
    )
    artifact = ContextRef(kind="file", id="workspace/intermediate.tsv")
    await service._cases.update_work_item(
        "cluster-case",
        "running-01",
        running.model_copy(update={"output_refs": [artifact]}),
    )

    cancelled = await service.cancel_case(
        "cluster-case", CaseCancelRequest(reason="User stopped the analysis"), "bioops-manager"
    )
    events = await service.get_case_events("cluster-case", "bioops-manager")
    item = next(item for item in cancelled.work_items if item.work_item_id == "running-01")

    assert claimed.lease_owner == "agent-code"
    assert cancelled.status == "cancelled"
    assert item.status == "cancelled"
    assert item.lease_owner is None
    assert item.lease_expires_at is None
    assert item.cancelled_at is not None
    assert item.output_refs == [artifact]
    assert events.events[-1]["payload"]["reclaimed_work_items"] == ["running-01"]
    assert events.events[-1]["payload"]["artifacts_retained"] is True


@pytest.mark.asyncio
async def test_bridge_records_omichub_hard_gate_audit_event(tmp_path) -> None:
    service = make_service(tmp_path, HardGateGateway())
    await create_case(service)
    await service.assign_work_item(
        "cluster-case",
        WorkItemCreateRequest(
            work_item_id="quality-01",
            target="quality-auditor",
            objective="Review deterministic QC evidence.",
            skill_name="quality-gate",
            context_refs=[ContextRef(kind="task", id="task-1")],
        ),
        "bioops-manager",
    )
    await service.claim_work_item("cluster-case", "quality-01", "quality-auditor")

    await service.execute_readonly_work_item(
        "cluster-case",
        "quality-01",
        ReadOnlyExecutionRequest(
            agent_id="agent-qc",
            capability="quality-gate",
            question="Review QC.",
        ),
        "quality-auditor",
    )
    events = await service.get_case_events("cluster-case", "bioops-manager")
    hard_gate = next(event for event in events.events if event["event_type"] == "quality.hard_gate")

    assert hard_gate["payload"]["decision"] == "BLOCKED"
    assert hard_gate["payload"]["metric"] == "mapping_rate"
    assert hard_gate["payload"]["value"] == 0.3


@pytest.mark.asyncio
async def test_concurrent_claims_allow_exactly_one_winner(tmp_path) -> None:
    service = make_service(tmp_path, ConcurrentGateway())
    await create_case(service)
    await service.assign_work_item(
        "cluster-case",
        WorkItemCreateRequest(
            work_item_id="claim-race-01",
            target="agent-code",
            objective="Claim exactly once.",
            skill_name="code-review",
        ),
        "bioops-manager",
    )

    results = await asyncio.gather(
        service.claim_work_item("cluster-case", "claim-race-01", "agent-code"),
        service.claim_work_item("cluster-case", "claim-race-01", "agent-code"),
        return_exceptions=True,
    )

    winners = [result for result in results if not isinstance(result, Exception)]
    failures = [result for result in results if isinstance(result, Exception)]
    assert len(winners) == 1
    assert winners[0].status == "claimed"
    assert len(failures) == 1
    assert "already claimed" in str(failures[0]).lower()


class TaskStateClient:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = responses

    async def get_task(self, _task_id: str) -> dict[str, object]:
        return self.responses.pop(0)

    async def get_agentteams_capabilities(self) -> dict[str, object]:
        return {
            "allowed_flow_ids": [],
            "flow_agent_map": {},
            "flow_quality_gate_map": {},
            "role_agent_map": {},
            "worker_profiles": {},
        }


async def _make_executing_case_service(
    tmp_path, responses, *, quality_gate_required: bool | None = None
) -> BridgeService:
    settings = BridgeSettings(
        omichub_service_token="service-token",
        approval_signing_secret="test-signing-secret",
        omic_task_stall_timeout_seconds=30,
        audit_log_path=str(tmp_path / "audit.jsonl"),
        case_store_path=str(tmp_path / "cases.json"),
        manifest_dir=str(tmp_path / "manifests"),
    )
    cases = CaseStore(settings.case_store_path)
    audit = AuditStore(settings.audit_log_path)
    service = BridgeService(settings, TaskStateClient(responses), audit, cases)
    now = datetime.now(UTC)
    await cases.create(
        CaseRecord(
            case_id="watchdog-case",
            intent="watch queued task",
            requester_ref="user-1",
            team_id="bioops-delivery",
            status="executing",
            omic_task_ids=["task-1"],
            proposed_submission=(
                {"quality_gate_required": quality_gate_required}
                if quality_gate_required is not None
                else None
            ),
            created_at=now,
            updated_at=now,
        )
    )
    return service


@pytest.mark.asyncio
async def test_reconcile_success_skips_unplanned_quality_gate(tmp_path) -> None:
    service = await _make_executing_case_service(
        tmp_path,
        [{"id": "task-1", "status": "success"}],
        quality_gate_required=False,
    )

    case = await service.reconcile_case("watchdog-case", "bioops-manager")
    events = await service.get_case_events("watchdog-case", "bioops-manager")

    assert case.status == "delivery_ready"
    assert "delivery-01" in {item.work_item_id for item in case.work_items}
    assert "quality-01" not in {item.work_item_id for item in case.work_items}
    assert any(event["event_type"] == "quality.skipped" for event in events.events)


@pytest.mark.asyncio
async def test_reconcile_success_runs_frozen_quality_gate(tmp_path) -> None:
    service = await _make_executing_case_service(
        tmp_path,
        [{"id": "task-1", "status": "success"}],
        quality_gate_required=True,
    )

    case = await service.reconcile_case("watchdog-case", "bioops-manager")
    events = await service.get_case_events("watchdog-case", "bioops-manager")

    assert case.status == "quality_running"
    assert "quality-01" in {item.work_item_id for item in case.work_items}
    assert "delivery-01" not in {item.work_item_id for item in case.work_items}
    assert all(event["event_type"] != "quality.skipped" for event in events.events)


@pytest.mark.asyncio
async def test_reconcile_marks_stalled_queued_task_execution_failed(tmp_path) -> None:
    old = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    service = await _make_executing_case_service(
        tmp_path,
        [
            {"id": "task-1", "status": "queued", "created_at": old},
            {"id": "task-1", "status": "queued", "created_at": old},
        ],
    )

    case = await service.reconcile_case("watchdog-case", "bioops-manager")
    events = await service.get_case_events("watchdog-case", "bioops-manager")

    assert case.status == "execution_failed"
    assert events.events[-1]["event_type"] == "omic_task.stalled"


@pytest.mark.asyncio
async def test_reconcile_does_not_stall_recently_requeued_task(tmp_path) -> None:
    old = (datetime.now(UTC) - timedelta(minutes=20)).isoformat()
    recent = datetime.now(UTC).isoformat()
    service = await _make_executing_case_service(
        tmp_path,
        [{"id": "task-1", "status": "queued", "created_at": old, "updated_at": recent}],
    )

    case = await service.reconcile_case("watchdog-case", "bioops-manager")
    events = await service.get_case_events("watchdog-case", "bioops-manager")

    assert case.status == "executing"
    assert all(event["event_type"] != "omic_task.stalled" for event in events.events)


@pytest.mark.asyncio
async def test_reconcile_failed_task_records_error_excerpt(tmp_path) -> None:
    error_message = "prefix-" + "x" * 700
    service = await _make_executing_case_service(
        tmp_path,
        [{"id": "task-1", "status": "failed", "error_message": error_message}],
    )

    case = await service.reconcile_case("watchdog-case", "bioops-manager")
    events = await service.get_case_events("watchdog-case", "bioops-manager")
    task_failed = next(event for event in events.events if event["event_type"] == "omic_task.failed")
    case_failed = events.events[-1]

    assert case.status == "execution_failed"
    assert task_failed["payload"]["error_excerpt"] == error_message[-500:]
    assert case_failed["event_type"] == "case.execution_failed"
    assert case_failed["payload"]["retry_allowed"] is True


@pytest.mark.asyncio
async def test_retry_failed_case_queues_new_submission_version(tmp_path) -> None:
    service = make_service(tmp_path, ConcurrentGateway())
    task = TaskSpec(
        flow_id="rna_seq",
        name="rna-seq-analysis",
        sample_sheet=[{"sample": "sample-a", "group": "control"}],
        comparisons=[{"control": "control", "treatment": "treated"}],
        execution_mode="cluster",
    )
    snapshot = PreflightInputSnapshot(
        flow_id=task.flow_id,
        sample_sheet=task.sample_sheet,
        comparisons=task.comparisons,
        context_refs=[ContextRef(kind="project", id="project-1")],
    )
    now = datetime.now(UTC)
    await service._cases.create(
        CaseRecord(
            case_id="retry-case",
            project_ref=ContextRef(kind="project", id="project-1"),
            intent="retry failed RNA-seq",
            requester_ref="user-1",
            team_id="bioops-delivery",
            flow_id="rna_seq",
            status="execution_failed",
            proposed_submission=task.model_dump(mode="json"),
            plan_hash="a" * 64,
            task_specs=[task.model_dump(mode="json")],
            preflight_input=snapshot,
            work_items=[
                WorkItemRecord(
                    work_item_id="submit-01",
                    target="analysis-worker",
                    objective="Submit analysis",
                    skill_name="workflow-submit",
                    context_refs=[ContextRef(kind="project", id="project-1")],
                    read_only=False,
                    approval_required=True,
                    status="completed",
                    approved_submission=ApprovedSubmission(
                        approval_id="approval-v1",
                        expires_at=now + timedelta(hours=1),
                        idempotency_key="retry-case-submit-v1",
                        task=task,
                        input_snapshot_hash=service._snapshot_hash(snapshot),
                        prepared_at=now,
                        consumed_at=now,
                    ),
                    updated_at=now,
                )
            ],
            omic_task_ids=["task-v1"],
            created_at=now,
            updated_at=now,
        )
    )
    approval = await service.issue_approval(
        ApprovalRequest(case_id="retry-case", action="submit_task", flow_id="rna_seq"),
        "approval-authority",
    )

    queued = await service.retry_case_submission(
        "retry-case",
        RetryCaseSubmissionRequest(approval_token=approval.token),
        "bioops-manager",
    )
    case = await service._cases.get("retry-case")
    retry_item = next(item for item in case.work_items if item.work_item_id == "submit-02")

    assert queued.status == "queued"
    assert case.status == "remediation_pending"
    assert retry_item.depends_on == ["submit-01"]
    assert retry_item.approved_submission is not None
    assert retry_item.approved_submission.idempotency_key == "retry-case-submit-v2"

    async def submit_task(payload):
        assert payload == task.model_dump()
        return {"id": "task-v2", "status": "queued"}

    service._client.submit_task = submit_task
    await service.claim_work_item("retry-case", "submit-02", "analysis-worker")
    receipt = await service.submit_approved_work_item(
        "retry-case", "submit-02", "analysis-worker"
    )
    executing = await service._cases.get("retry-case")

    assert receipt.omic_task_id == "task-v2"
    assert executing.status == "executing"
    assert executing.omic_task_ids == ["task-v1", "task-v2"]

@pytest.mark.asyncio
async def test_approval_timeout_reconcile_reminds_once_after_24_hours(tmp_path) -> None:
    service = make_service(tmp_path, ConcurrentGateway())
    now = datetime.now(UTC)
    await service._cases.create(
        CaseRecord(
            case_id="approval-reminder-case",
            project_ref=ContextRef(kind="project", id="project-1"),
            intent="await approval",
            requester_ref="user-1",
            team_id="team-reminder",
            status="approval_pending",
            created_at=now - timedelta(days=2),
            updated_at=now - timedelta(hours=25),
        )
    )

    first = await service.reconcile_approval_timeouts("bioops-manager", now=now)
    second = await service.reconcile_approval_timeouts("bioops-manager", now=now)
    events = await service.get_case_events("approval-reminder-case", "bioops-manager")

    assert first == {"scanned": 1, "reminded": 1, "cancelled": 0}
    assert second == {"scanned": 1, "reminded": 0, "cancelled": 0}
    assert [event["event_type"] for event in events.events] == ["approval.reminder"]


@pytest.mark.asyncio
async def test_approval_timeout_reconcile_auto_cancels_after_seven_days(tmp_path) -> None:
    service = make_service(tmp_path, ConcurrentGateway())
    now = datetime.now(UTC)
    await service._cases.create(
        CaseRecord(
            case_id="approval-expired-case",
            project_ref=ContextRef(kind="project", id="project-1"),
            intent="expired approval",
            requester_ref="user-1",
            team_id="team-expired",
            status="approval_pending",
            created_at=now - timedelta(days=9),
            updated_at=now - timedelta(days=8),
        )
    )

    result = await service.reconcile_approval_timeouts("bioops-manager", now=now)
    case = await service.get_case("approval-expired-case", "bioops-manager")
    events = await service.get_case_events("approval-expired-case", "bioops-manager")

    assert result == {"scanned": 1, "reminded": 0, "cancelled": 1}
    assert case.status == "cancelled"
    assert events.events[-1]["event_type"] == "case.cancelled"
    assert events.events[-1]["payload"]["reason"] == "approval_timeout_7d"
    assert events.events[-1]["payload"]["automatic"] is True


@pytest.mark.asyncio
async def test_reconcile_advances_received_case_and_assigns_planner_once(tmp_path) -> None:
    service = make_service(tmp_path, ConcurrentGateway())
    await service._cases.create(
        CaseRecord(
            case_id="received-residue-case",
            project_ref=ContextRef(kind="project", id="project-1"),
            intent="bulk_rnaseq_delivery",
            requester_ref="user-1",
            team_id="bioops-delivery",
            flow_id="rna_seq",
            status="received",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )

    first = await service.reconcile_case("received-residue-case", "bioops-manager")
    second = await service.reconcile_case("received-residue-case", "bioops-manager")
    events = await service.get_case_events("received-residue-case", "bioops-manager")

    assert first.status == "planning_running"
    assert second.status == "planning_running"
    planning_items = [
        item for item in second.work_items if item.work_item_id == "plan-01"
    ]
    assert len(planning_items) == 1
    assert planning_items[0].target == "agent-rnaseq"
    assert sum(event["event_type"] == "case.reconciled" for event in events.events) == 1


@pytest.mark.asyncio
async def test_plan_revision_replays_changed_general_item_and_dependents(tmp_path) -> None:
    service = make_service(tmp_path, ConcurrentGateway())
    now = datetime.now(UTC)
    original = {
        "name": "general-analysis",
        "parameters": {
            "work_items": [
                {
                    "work_item_id": "clean-01",
                    "target": "agent-code",
                    "objective": "Clean the table",
                    "skill_name": "data-clean",
                    "depends_on": [],
                },
                {
                    "work_item_id": "plot-01",
                    "target": "agent-viz",
                    "objective": "Plot the cleaned table",
                    "skill_name": "plot",
                    "depends_on": ["clean-01"],
                },
            ]
        },
    }
    original_hash = service._plan_hash(original)
    await service._cases.create(
        CaseRecord(
            case_id="general-revision-case",
            context_refs=[ContextRef(kind="workspace", id="workspace-1")],
            intent="revise general plan",
            requester_ref="user-1",
            team_id="team-revision",
            status="execution_failed",
            proposed_submission=original,
            plan_hash=original_hash,
            preflight_input=PreflightInputSnapshot(
                flow_id="general",
                sample_sheet=[],
                context_refs=[ContextRef(kind="workspace", id="workspace-1")],
            ),
            work_items=[
                WorkItemRecord(
                    work_item_id="clean-01",
                    target="agent-code",
                    objective="Clean the table",
                    skill_name="data-clean",
                    read_only=False,
                    execution_mode="workspace_execution",
                    plan_hash=original_hash,
                    status="completed",
                    updated_at=now,
                ),
                WorkItemRecord(
                    work_item_id="plot-01",
                    target="agent-viz",
                    objective="Plot the cleaned table",
                    skill_name="plot",
                    read_only=False,
                    execution_mode="workspace_execution",
                    plan_hash=original_hash,
                    depends_on=["clean-01"],
                    status="completed",
                    updated_at=now,
                ),
            ],
            created_at=now,
            updated_at=now,
        )
    )
    revised_parameters = {
        "work_items": [
            {**original["parameters"]["work_items"][0], "objective": "Clean and normalize the table"},
            original["parameters"]["work_items"][1],
        ]
    }

    response = await service.revise_plan(
        "general-revision-case",
        PlanRevisionRequest(
            expected_plan_hash=original_hash,
            parameters=revised_parameters,
            reason="Normalize values before plotting",
        ),
        "bioops-manager",
    )
    case = await service.get_case("general-revision-case", "bioops-manager")

    assert response.status == "approval_pending"
    assert response.replay_work_item_ids == ["clean-01", "plot-01"]
    assert response.plan_hash != original_hash
    assert [item.status for item in case.work_items] == ["pending", "pending"]
    assert case.work_items[0].objective == "Clean and normalize the table"
    assert all(item.plan_hash == response.plan_hash for item in case.work_items)
    events = await service.get_case_events("general-revision-case", "bioops-manager")
    revision_event = next(
        event for event in events.events if event["event_type"] == "planning.revised"
    )
    assert revision_event["payload"]["plan_version"] == response.plan_version


@pytest.mark.asyncio
async def test_plan_revision_limit_requires_explicit_user_override(tmp_path) -> None:
    service = make_service(tmp_path, ConcurrentGateway())
    now = datetime.now(UTC)
    original = {
        "name": "general-analysis",
        "parameters": {
            "work_items": [
                {
                    "work_item_id": "review-01",
                    "target": "agent-code",
                    "objective": "Review the input table",
                    "skill_name": "code-review",
                    "depends_on": [],
                }
            ]
        },
    }
    original_hash = service._plan_hash(original)
    await service._cases.create(
        CaseRecord(
            case_id="revision-limit-case",
            context_refs=[ContextRef(kind="workspace", id="workspace-1")],
            intent="exercise revision escalation",
            requester_ref="user-1",
            team_id="team-revision",
            status="approval_pending",
            proposed_submission=original,
            plan_hash=original_hash,
            plan_version=6,
            plan_revision_count=5,
            preflight_input=PreflightInputSnapshot(
                flow_id="general",
                sample_sheet=[],
                context_refs=[ContextRef(kind="workspace", id="workspace-1")],
            ),
            created_at=now,
            updated_at=now,
        )
    )
    revised_parameters = {
        "work_items": [
            {
                **original["parameters"]["work_items"][0],
                "objective": "Review and summarize the input table",
            }
        ]
    }

    with pytest.raises(HTTPException) as blocked:
        await service.revise_plan(
            "revision-limit-case",
            PlanRevisionRequest(
                expected_plan_hash=original_hash,
                parameters=revised_parameters,
                reason="Need a concise summary",
            ),
            "bioops-manager",
        )

    detail = blocked.value.detail
    assert blocked.value.status_code == 409
    assert detail["code"] == "PLAN_REVISION_LIMIT_REACHED"
    assert detail["options"] == [
        "continue_revision",
        "replace_lead_planner",
        "cancel_case",
    ]

    continued = await service.revise_plan(
        "revision-limit-case",
        PlanRevisionRequest(
            expected_plan_hash=original_hash,
            parameters=revised_parameters,
            reason="User explicitly chose to continue",
            override_revision_limit=True,
        ),
        "bioops-manager",
    )

    assert continued.plan_version == 7
    assert continued.revision_count == 6

@pytest.mark.asyncio
async def test_blocked_quality_gate_assigns_remediation_and_returns_to_approval(tmp_path) -> None:
    service = make_service(tmp_path, ConcurrentGateway())
    now = datetime.now(UTC)
    await service._cases.create(
        CaseRecord(
            case_id="quality-remediation-case",
            project_ref=ContextRef(kind="project", id="project-1"),
            context_refs=[ContextRef(kind="project", id="project-1")],
            intent="quality remediation",
            requester_ref="user-1",
            team_id="team-quality",
            flow_id="rna_seq",
            status="quality_running",
            omic_task_ids=["task-quality"],
            work_items=[
                WorkItemRecord(
                    work_item_id="quality-01",
                    target="quality-auditor",
                    objective="Review quality",
                    skill_name="quality-gate",
                    context_refs=[ContextRef(kind="task", id="task-quality")],
                    status="running",
                    updated_at=now,
                )
            ],
            created_at=now,
            updated_at=now,
        )
    )

    await service.quality_gate(
        "task-quality",
        QualityGateRequest(
            case_id="quality-remediation-case",
            work_item_id="quality-01",
            rule_version="quality-v2",
            decision="blocked",
            summary="Sample metadata groups do not match the submitted design.",
            evidence_refs=[ContextRef(kind="task", id="task-quality")],
            remediation_request={
                "target": "data-steward",
                "objective": "Correct sample metadata groups and attach verification evidence.",
                "recommended_changes": ["Align group labels with the frozen design."],
            },
        ),
        "quality-auditor",
    )
    case = await service.get_case("quality-remediation-case", "bioops-manager")
    remediation = next(item for item in case.work_items if item.skill_name == "remediation-fix")

    assert case.status == "remediation_pending"
    assert remediation.target == "data-steward"
    await service.claim_work_item(case.case_id, remediation.work_item_id, "data-steward")
    await service.update_work_item(
        case.case_id,
        remediation.work_item_id,
        WorkItemUpdateRequest(
            status="completed",
            summary="Sample metadata groups corrected and verified.",
        ),
        "data-steward",
    )
    ready = await service.get_case(case.case_id, "bioops-manager")
    events = await service.get_case_events(case.case_id, "bioops-manager")

    assert ready.status == "approval_pending"
    assert any(event["event_type"] == "remediation.requested" for event in events.events)
    assert any(event["event_type"] == "remediation.completed" for event in events.events)


def _workspace_snapshot(*, viz_declares: bool = True) -> dict[str, object]:
    def modes(declares: bool) -> list[str]:
        base = ["readonly_consultation"]
        return base + ["workspace_execution"] if declares else base

    return {
        "role_agent_map": {
            "agent-code": "agent-code",
            "agent-viz": "agent-viz",
            "agent-rnaseq": "agent-rnaseq",
            "data-steward": "agent-data",
        },
        "agent_capabilities": {
            "agent-code": {"agent_id": "agent-code", "execution_modes": modes(True)},
            "agent-viz": {"agent_id": "agent-viz", "execution_modes": modes(viz_declares)},
            "agent-rnaseq": {"agent_id": "agent-rnaseq", "execution_modes": modes(True)},
            "agent-data": {"agent_id": "agent-data", "execution_modes": modes(True)},
        },
    }


def test_capability_snapshot_derives_workspace_execution_targets(tmp_path) -> None:
    service = make_service(tmp_path, TreeplotPlanningGateway())

    service._settings.apply_capability_snapshot(_workspace_snapshot())
    targets = service._workspace_execution_targets()

    assert {"agent-code", "agent-viz", "agent-rnaseq"} <= targets
    # alias identities inherit the canonical agent's declaration
    assert "data-steward" in targets


def test_general_plan_accepts_snapshot_declared_workspace_target(tmp_path) -> None:
    service = make_service(tmp_path, TreeplotPlanningGateway())
    service._settings.apply_capability_snapshot(_workspace_snapshot())

    payload = service._validate_general_plan(
        {
            "name": "rnaseq-qc",
            "parameters": {
                "work_items": [
                    {
                        "work_item_id": "exec-01",
                        "target": "agent-rnaseq",
                        "objective": "Run the RNA-seq QC notebook.",
                        "skill_name": "rnaseq-qc",
                    }
                ]
            },
        }
    )

    assert payload["parameters"]["work_items"][0]["target"] == "agent-rnaseq"


def test_general_plan_rejects_undeclared_workspace_target(tmp_path) -> None:
    service = make_service(tmp_path, TreeplotPlanningGateway())
    service._settings.apply_capability_snapshot(_workspace_snapshot())

    with pytest.raises(ValueError, match="target is not allowed"):
        service._validate_general_plan(
            {
                "name": "qc-exec",
                "parameters": {
                    "work_items": [
                        {
                            "work_item_id": "exec-01",
                            "target": "agent-qc",
                            "objective": "Execute inside the workspace.",
                            "skill_name": "qc-exec",
                        }
                    ]
                },
            }
        )


@pytest.mark.asyncio
async def test_execute_general_plan_downgrades_undeclared_target_and_records_event(
    tmp_path,
) -> None:
    service = make_service(tmp_path, TreeplotPlanningGateway())
    await service.create_case(
        CaseCreateRequest(
            case_id="downgrade-case",
            context_refs=[ContextRef(kind="file", id="tree.fa")],
            intent="build a treeplot",
            requester_ref="user-1",
            lead_planner="agent-code",
        ),
        "bioops-manager",
    )
    await service.claim_work_item("downgrade-case", "plan-01", "agent-code")
    await service.execute_readonly_work_item(
        "downgrade-case",
        "plan-01",
        ReadOnlyExecutionRequest(
            agent_id="agent-code",
            capability="planning_advice",
            question="Plan treeplot.",
        ),
        "agent-code",
    )
    approval = await service.issue_approval(
        ApprovalRequest(case_id="downgrade-case", action="execute_plan"),
        "approval-authority",
    )
    # registry declaration changed after the plan was frozen: agent-viz no longer declares it
    service._settings.apply_capability_snapshot(_workspace_snapshot(viz_declares=False))

    approved = await service.execute_general_plan(
        "downgrade-case", approval.token, "approval-authority"
    )

    exec_01 = next(item for item in approved.work_items if item.work_item_id == "exec-01")
    exec_02 = next(item for item in approved.work_items if item.work_item_id == "exec-02")
    assert exec_01.execution_mode == "workspace_execution"
    assert exec_02.execution_mode == "readonly_consultation"
    assert exec_02.read_only is True
    events = await service._audit.list_events("downgrade-case")
    downgrades = [
        event
        for event in events
        if event["event_type"] == "planning.validation_failed"
        and event["payload"].get("work_item_id") == "exec-02"
    ]
    assert len(downgrades) == 1


@pytest.mark.asyncio
async def test_assign_workspace_execution_follows_snapshot_declaration(tmp_path) -> None:
    service = make_service(tmp_path, TreeplotPlanningGateway())
    await create_case(service, "assign-workspace-case")

    with pytest.raises(HTTPException) as denied:
        await service.assign_work_item(
            "assign-workspace-case",
            WorkItemCreateRequest(
                work_item_id="exec-01",
                target="agent-rnaseq",
                objective="Run the RNA-seq QC notebook.",
                skill_name="rnaseq-qc",
                execution_mode="workspace_execution",
                approval_required=True,
            ),
            "bioops-manager",
        )
    assert denied.value.status_code == 422

    service._settings.apply_capability_snapshot(_workspace_snapshot())
    work_item = await service.assign_work_item(
        "assign-workspace-case",
        WorkItemCreateRequest(
            work_item_id="exec-01",
            target="agent-rnaseq",
            objective="Run the RNA-seq QC notebook.",
            skill_name="rnaseq-qc",
            execution_mode="workspace_execution",
            approval_required=True,
        ),
        "bioops-manager",
    )

    assert work_item.execution_mode == "workspace_execution"


class SlowGateway:
    """Gateway whose consultation outlives the default work item lease."""

    configured = True

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def consult(self, payload: dict[str, object]) -> dict[str, object]:
        self.started.set()
        if self.delay:
            await asyncio.sleep(self.delay)
        else:
            await self.release.wait()
        return {
            "schema_version": "1.0",
            "status": "completed",
            "conclusion": f"Completed {payload['agent_id']}",
            "recommendations": [],
            "evidence_refs": [],
            "risks": [],
            "agent_id": payload["agent_id"],
            "schema_ver": "1.0",
            "duration_ms": 1,
            "token_usage": 1,
        }


@pytest.mark.asyncio
async def test_long_consultation_renews_lease_and_completes(tmp_path) -> None:
    service = make_service(tmp_path, SlowGateway(delay=3.6))
    await create_case(service)
    await service.assign_work_item(
        "cluster-case",
        WorkItemCreateRequest(
            work_item_id="code-01",
            target="agent-code",
            objective="Review code.",
            skill_name="code-review",
            deadline_seconds=3,
        ),
        "bioops-manager",
    )
    await service.claim_work_item("cluster-case", "code-01", "agent-code")

    result = await service.execute_readonly_work_item(
        "cluster-case",
        "code-01",
        ReadOnlyExecutionRequest(
            agent_id="agent-code",
            capability="planning_advice",
            question="Review code.",
        ),
        "agent-code",
    )

    assert result.status == "completed"
    events = await service._audit.list_events("cluster-case")
    event_types = [event["event_type"] for event in events]
    assert "skill.finished" in event_types
    assert "work_item.lease_expired" not in event_types
    assert event_types.count("work_item.claimed") == 1


@pytest.mark.asyncio
async def test_lease_expired_requeue_writes_audit_event(tmp_path) -> None:
    service = make_service(tmp_path, ConcurrentGateway())
    await create_case(service)
    await service.assign_work_item(
        "cluster-case",
        WorkItemCreateRequest(
            work_item_id="code-01",
            target="agent-code",
            objective="Review code.",
            skill_name="code-review",
            deadline_seconds=30,
        ),
        "bioops-manager",
    )
    claimed = await service.claim_work_item("cluster-case", "code-01", "agent-code")
    expired = claimed.model_copy(
        update={"lease_expires_at": datetime.now(UTC) - timedelta(seconds=1)}
    )
    await service._cases.update_work_item("cluster-case", "code-01", expired)

    inbox = await service.list_worker_inbox("agent-code")

    assert inbox.items[0].work_item.status == "pending"
    events = await service._audit.list_events("cluster-case")
    lease_expired = [event for event in events if event["event_type"] == "work_item.lease_expired"]
    assert len(lease_expired) == 1
    payload = lease_expired[0]["payload"]
    assert payload["work_item_id"] == "code-01"
    assert payload["previous_status"] == "claimed"
    assert payload["lease_owner"] == "agent-code"
    assert payload["attempt"] == 1
    assert payload["action"] == "requeued"
    assert payload["lease_expires_at"] is not None

    reclaimed = await service.claim_work_item("cluster-case", "code-01", "agent-code")
    assert reclaimed.attempt == 2
    event_types = [
        event["event_type"] for event in await service._audit.list_events("cluster-case")
    ]
    # the duplicate claim on the timeline is now explained by the requeue event
    assert event_types.index("work_item.lease_expired") < len(event_types) - 1
    assert event_types.count("work_item.claimed") == 2


@pytest.mark.asyncio
async def test_reclaimed_work_item_is_not_overwritten_by_stale_consultation(tmp_path) -> None:
    gateway = SlowGateway()
    service = make_service(tmp_path, gateway)
    await create_case(service)
    await service.assign_work_item(
        "cluster-case",
        WorkItemCreateRequest(
            work_item_id="code-01",
            target="agent-code",
            objective="Review code.",
            skill_name="code-review",
            deadline_seconds=30,
        ),
        "bioops-manager",
    )
    await service.claim_work_item("cluster-case", "code-01", "agent-code")
    execution = asyncio.create_task(
        service.execute_readonly_work_item(
            "cluster-case",
            "code-01",
            ReadOnlyExecutionRequest(
                agent_id="agent-code",
                capability="planning_advice",
                question="Review code.",
            ),
            "agent-code",
        )
    )
    await gateway.started.wait()

    # the lease expires mid-consultation; the next poll requeues the item
    running = await service._cases.get_work_item("cluster-case", "code-01")
    await service._cases.update_work_item(
        "cluster-case",
        "code-01",
        running.model_copy(update={"lease_expires_at": datetime.now(UTC) - timedelta(seconds=1)}),
    )
    inbox = await service.list_worker_inbox("agent-code")
    assert inbox.items[0].work_item.status == "pending"
    # a newer attempt reclaims it before the stale consultation finishes
    reclaimed = await service.claim_work_item("cluster-case", "code-01", "agent-code")
    assert reclaimed.attempt == 2

    gateway.release.set()
    result = await execution

    # no 409 escapes; the newer attempt's state is untouched
    assert result.attempt == 2
    assert result.status == "claimed"
    events = await service._audit.list_events("cluster-case")
    failures = [
        event
        for event in events
        if event["event_type"] == "skill.failed"
        and event["payload"].get("reason") == "lease_conflict"
    ]
    assert len(failures) == 1
    assert failures[0]["payload"]["work_item_id"] == "code-01"
    assert not any(event["event_type"] == "skill.finished" for event in events)
