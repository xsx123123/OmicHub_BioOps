"""产物血缘（F1）Bridge 侧测试：缺 source_refs 拒绝登记 + room.artifact_rejected 审计事件、
交付 manifest 血缘清单。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from cygnusx_agentteams_bridge.audit import AuditStore
from cygnusx_agentteams_bridge.case_store import CaseStore
from cygnusx_agentteams_bridge.config import BridgeSettings
from cygnusx_agentteams_bridge.models import (
    CaseCloseRequest,
    CaseRecord,
    ContextRef,
    QualityGateRequest,
    WorkItemRecord,
)
from cygnusx_agentteams_bridge.service import BridgeService


class FakeCygnusXClient:
    async def aclose(self) -> None:
        return None


def make_service(tmp_path) -> BridgeService:
    settings = BridgeSettings(
        cygnusx_service_token="service-token",
        approval_signing_secret="test-signing-secret",
        identities=(
            "approval-authority:approval,bioops-manager:manager,data-steward:steward,"
            "workflow-operator:operator,quality-auditor:auditor,delivery-reporter:reporter"
        ),
        role_agent_map="quality-auditor:agent-qc,delivery-reporter:agent-delivery",
        audit_log_path=str(tmp_path / "audit.jsonl"),
        case_store_path=str(tmp_path / "cases.json"),
        manifest_dir=str(tmp_path / "manifests"),
    )
    return BridgeService(
        settings,
        FakeCygnusXClient(),
        AuditStore(settings.audit_log_path),
        CaseStore(settings.case_store_path),
        None,
    )


async def _create_quality_case(service: BridgeService, case_id: str) -> None:
    now = datetime.now(UTC)
    await service._cases.create(
        CaseRecord(
            case_id=case_id,
            project_ref=ContextRef(kind="project", id="project-1"),
            context_refs=[ContextRef(kind="project", id="project-1")],
            intent="artifact lineage",
            requester_ref="user-1",
            team_id="team-1",
            flow_id="rna_seq",
            status="quality_running",
            omic_task_ids=["task-1"],
            work_items=[
                WorkItemRecord(
                    work_item_id="quality-01",
                    target="quality-auditor",
                    objective="Review quality",
                    skill_name="quality-gate",
                    context_refs=[ContextRef(kind="task", id="task-1")],
                    status="running",
                    updated_at=now,
                )
            ],
            created_at=now,
            updated_at=now,
        )
    )


def _gate_request(case_id: str, **overrides) -> QualityGateRequest:
    payload = {
        "case_id": case_id,
        "work_item_id": "quality-01",
        "rule_version": "quality-v1",
        "decision": "passed",
        "summary": "QC passed with verified evidence.",
        "evidence_refs": [ContextRef(kind="task", id="task-1")],
    }
    payload.update(overrides)
    return QualityGateRequest(**payload)


async def test_artifact_hashes_without_source_refs_are_rejected_and_audited(tmp_path) -> None:
    service = make_service(tmp_path)
    await _create_quality_case(service, "lineage-reject-case")

    with pytest.raises(HTTPException) as excinfo:
        await service.quality_gate(
            "task-1",
            _gate_request("lineage-reject-case", artifact_hashes={"results/plot.svg": "abc123"}),
            "quality-auditor",
        )

    assert excinfo.value.status_code == 422
    case = await service._cases.get("lineage-reject-case")
    assert case.status == "quality_running"
    assert case.quality_decision is None
    events = await service._audit.list_events("lineage-reject-case")
    rejected = [event for event in events if event["event_type"] == "room.artifact_rejected"]
    assert len(rejected) == 1
    assert rejected[0]["payload"]["reason"] == "missing_source_refs"
    assert rejected[0]["payload"]["artifact_paths"] == ["results/plot.svg"]
    assert rejected[0]["actor"] == "quality-auditor"


async def test_artifact_lineage_lands_in_delivery_manifest(tmp_path) -> None:
    service = make_service(tmp_path)
    await _create_quality_case(service, "lineage-manifest-case")

    decision = await service.quality_gate(
        "task-1",
        _gate_request(
            "lineage-manifest-case",
            artifact_hashes={"results/plot.svg": "abc123"},
            source_refs=[{"artifact_id": "projects/p1/counts.tsv", "relation": "input_to"}],
            execution_summary="plot rendered from counts",
        ),
        "quality-auditor",
    )
    assert decision.source_refs[0].artifact_id == "projects/p1/counts.tsv"
    case = await service._cases.get("lineage-manifest-case")
    assert case.status == "delivery_ready"

    closed = await service.close_case(
        CaseCloseRequest(case_id="lineage-manifest-case", quality_decision="passed"),
        "delivery-reporter",
    )
    lineage = closed.manifest["artifact_lineage"]
    assert len(lineage) == 1
    assert lineage[0]["artifact_hashes"] == {"results/plot.svg": "abc123"}
    assert lineage[0]["source_refs"] == [
        {"artifact_id": "projects/p1/counts.tsv", "relation": "input_to", "note": ""}
    ]
    assert lineage[0]["execution_summary"] == "plot rendered from counts"
    assert lineage[0]["event_id"]
