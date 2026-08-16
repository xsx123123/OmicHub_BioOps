"""scripts/export_agentteams_evidence.py 序列化逻辑的单元测试。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from scripts.export_agentteams_evidence import export_case_evidence


@pytest.mark.asyncio
async def test_export_case_evidence_writes_all_nine_files(tmp_path: Path) -> None:
    service = AsyncMock()
    service.available = True
    service.admin_get_case.return_value = {
        "case_id": "case-abc",
        "requester_ref": "user-1",
        "status": "delivery_ready",
        "quality_decision": "manual_review",
        "omic_task_ids": ["task-1"],
        "intent": "RNA-seq 交付",
        "manifest_uri": "omic://cases/case-abc/manifest",
    }
    service._public_case = Mock(return_value={
        "case_id": "case-abc",
        "status": "delivery_ready",
        "intent": "RNA-seq 交付",
    })

    async def fake_request(path: str, **kwargs):
        return {
            f"/v1/cases/case-abc/events": {
                "events": [
                    {"event_id": "e1", "event_type": "approval.requested", "payload": {}},
                    {"event_id": "e2", "event_type": "approval.resolved", "payload": {"approved": True}},
                    {"event_id": "e3", "event_type": "skill.finished", "payload": {"skill_name": "project-preflight", "status": "passed"}},
                    {"event_id": "e4", "event_type": "quality.decision", "payload": {"decision": "manual_review"}},
                ]
            },
            f"/v1/cases/case-abc/manifest": {"case_id": "case-abc", "manifest": "ok"},
            f"/v1/tasks/task-1": {"task_id": "task-1", "status": "completed"},
            f"/v1/tasks/task-1/events": {"events": [{"event_id": "te1", "event_type": "omic_task.completed"}]},
            f"/v1/tasks/task-1/artifacts": {"artifacts": [{"name": "report.html"}]},
            "/v1/metrics": {"cases": 5, "events": 42},
        }[path]

    service._request = fake_request

    base = await export_case_evidence("case-abc", tmp_path, service=service)

    expected_files = {
        "case-summary.json",
        "approvals.json",
        "preflight-report.json",
        "task-events.ndjson",
        "artifact-manifest.json",
        "quality-decision.json",
        "evidence-events.ndjson",
        "delivery-manifest.json",
        "observability-summary.json",
    }
    assert {p.name for p in base.iterdir()} == expected_files

    # 验证 approvals.json 只包含 approval.* 事件
    approvals = json.loads((base / "approvals.json").read_text())
    assert approvals["count"] == 2
    assert all(ev["event_type"].startswith("approval.") for ev in approvals["events"])

    # 验证 quality-decision.json 包含事件与 case 字段
    quality = json.loads((base / "quality-decision.json").read_text())
    assert quality["quality_decision"] == "manual_review"
    assert quality["quality_decision_event"]["event_type"] == "quality.decision"

    # 验证 task-events.ndjson 为 NDJSON 且带 task_id
    task_events_lines = (base / "task-events.ndjson").read_text().strip().split("\n")
    assert len(task_events_lines) == 1
    assert json.loads(task_events_lines[0])["task_id"] == "task-1"

    # 验证 delivery-manifest.json 内容
    manifest = json.loads((base / "delivery-manifest.json").read_text())
    assert manifest["manifest"] == "ok"

    # 验证 observability-summary.json 包含 Bridge 指标
    obs = json.loads((base / "observability-summary.json").read_text())
    assert obs["bridge_metrics"]["cases"] == 5
    assert obs["event_counts"]["case_events"] == 4
