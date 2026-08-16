from omichub.application.services.case_room_projector import CaseRoomProjector
from omichub.application.services.chat_service import _fanout_ask_request


def test_fanout_awaiting_input_becomes_ask_request() -> None:
    request = _fanout_ask_request(
        {
            "ui_payload": {"progress": [{"index": 2, "status": "awaiting_input"}]},
            "llm_payload": {
                "results": [
                    {
                        "index": 2,
                        "agent_id": "agent-rnaseq",
                        "task_id": "task-2",
                        "status": "awaiting_input",
                        "packet": {
                            "needs_user_input": True,
                            "questions": [{"question": "请补充分组信息", "options": ["A/B"]}],
                        },
                    }
                ]
            },
        }
    )

    assert request == {
        "questions": [{"question": "请补充分组信息", "options": ["A/B"]}],
        "question": "请补充分组信息",
        "options": ["A/B"],
        "agent_id": "agent-rnaseq",
        "task_id": "task-2",
        "status": "awaiting_input",
    }


def test_projects_worker_assignment_to_speech_and_progress() -> None:
    events = _projector().project(
        {
            "event_id": "event-1",
            "case_id": "case-1",
            "actor": "workflow-operator",
            "event_type": "work_item.assigned",
            "payload": {"work_item_id": "run-1", "objective": "运行 RNA-seq 流程"},
        },
        session_id="session-1",
    )

    assert [event["type"] for event in events] == ["room_speech", "overdrive_progress"]
    assert events[0]["sender"]["agent_id"] == "agent-rnaseq"
    assert events[1]["tasks"] == [
        {"taskId": "run-1", "agentId": "agent-rnaseq", "status": "pending"}
    ]


def test_projects_claimed_progress_and_hard_gate_speech() -> None:
    projector = _projector()
    claimed = projector.project(
        {
            "event_id": "event-claimed",
            "case_id": "case-1",
            "actor": "workflow-operator",
            "event_type": "work_item.claimed",
            "payload": {"work_item_id": "run-1"},
        },
        session_id="session-1",
    )
    hard_gate = projector.project(
        {
            "event_id": "event-gate",
            "case_id": "case-1",
            "actor": "quality-auditor",
            "event_type": "quality.hard_gate",
            "payload": {"decision": "BLOCKED", "reason": "mapping_rate 低于阈值"},
        },
        session_id="session-1",
    )

    assert [event["type"] for event in claimed] == ["room_speech", "overdrive_progress"]
    assert claimed[1]["tasks"][0]["status"] == "running"
    assert "BLOCKED" in hard_gate[0]["content"]


def test_projects_specialist_roles_to_real_platform_agents() -> None:
    projector = _projector()
    expected = {
        "data-steward": "agent-data",
        "quality-auditor": "agent-qc",
        "delivery-reporter": "agent-delivery",
    }

    for actor, agent_id in expected.items():
        events = projector.project(
            {
                "event_id": f"event-{actor}",
                "case_id": "case-1",
                "actor": actor,
                "event_type": "work_item.assigned",
                "payload": {"work_item_id": f"{actor}-01"},
            },
            session_id="session-1",
        )
        assert events[0]["sender"]["agent_id"] == agent_id


def test_projects_approval_and_case_close() -> None:
    projector = _projector()
    approval = projector.project(
        {
            "event_id": "event-2",
            "case_id": "case-1",
            "event_type": "approval.requested",
            "payload": {"approval_id": "approval-1", "action": "submit_task"},
        },
        session_id="session-1",
    )
    closed = projector.project(
        {
            "event_id": "event-3",
            "case_id": "case-1",
            "event_type": "case.closed",
            "payload": {"manifest_uri": "output/manifest.json"},
        },
        session_id="session-1",
    )

    assert approval[-1]["type"] == "overdrive_approval_request"
    assert approval[-1]["approval"]["case_id"] == "case-1"
    assert closed[-1]["type"] == "mode_changed"
    assert closed[-1]["idempotency_key"] == "case-1:event-3:mode_changed:1"


def test_projected_events_carry_stable_publish_dedup_keys() -> None:
    events = _projector().project(
        {
            "event_id": "event-4",
            "case_id": "case-1",
            "actor": "workflow-operator",
            "event_type": "work_item.assigned",
            "payload": {"work_item_id": "run-1"},
        },
        session_id="session-1",
    )

    assert [event["idempotency_key"] for event in events] == [
        "case-1:event-4:room_speech:0",
        "case-1:event-4:overdrive_progress:1",
    ]


def test_projects_execution_failure_with_error_excerpt_and_retry_guidance() -> None:
    events = _projector().project(
        {
            "event_id": "event-failed",
            "case_id": "case-1",
            "actor": "workflow-operator",
            "event_type": "case.execution_failed",
            "payload": {
                "error_excerpt": "Snakemake rule align exited with code 1",
                "recommendation": "检查 FASTQ 输入后按冻结计划重试。",
            },
        },
        session_id="session-1",
    )

    assert len(events) == 1
    assert events[0]["type"] == "room_speech"
    assert "Snakemake rule align exited with code 1" in events[0]["content"]
    assert "按冻结计划重试" in events[0]["content"]


def test_projects_approval_timeout_reminder_and_auto_cancel() -> None:
    reminder = _projector().project(
        {
            "event_id": "event-reminder",
            "case_id": "case-1",
            "actor": "bioops-manager",
            "event_type": "approval.reminder",
            "payload": {"auto_cancel_after_days": 7},
        },
        session_id="session-1",
    )
    cancelled = _projector().project(
        {
            "event_id": "event-cancelled",
            "case_id": "case-1",
            "actor": "bioops-manager",
            "event_type": "case.cancelled",
            "payload": {"reason": "approval_timeout_7d", "automatic": True},
        },
        session_id="session-1",
    )

    assert "超过 24 小时" in reminder[0]["content"]
    assert "超过 7 天已自动取消" in cancelled[0]["content"]


def test_projects_case_scoped_artifact_download_and_html_preview_urls() -> None:
    events = _projector().project(
        {
            "event_id": "event-report",
            "case_id": "case-1",
            "actor": "delivery-reporter",
            "event_type": "skill.finished",
            "payload": {
                "work_item_id": "delivery-01",
                "artifacts": [
                    {
                        "path": "workspace/agentteams/case-1/delivery-01/report.html",
                        "kind": "file",
                        "s3_uri": "s3://agentteams-evidence/case-1/delivery-01/report.html",
                    }
                ],
            },
        },
        session_id="session-1",
    )

    artifact = events[-1]["artifacts"][0]
    assert artifact["preview_url"] == (
        "/api/v1/agent-teams/cases/case-1/artifacts/delivery-01/report.html"
    )
    assert artifact["download_url"] == f"{artifact['preview_url']}?download=true"


def test_projects_case_queue_reason_and_dequeue_notice() -> None:
    projector = _projector()
    queued = projector.project(
        {
            "event_id": "event-queued",
            "case_id": "case-1",
            "actor": "bioops-manager",
            "event_type": "case.queued",
            "payload": {"reason": "requester_active_case_quota"},
        },
        session_id="session-1",
    )
    dequeued = projector.project(
        {
            "event_id": "event-dequeued",
            "case_id": "case-1",
            "actor": "bioops-manager",
            "event_type": "case.dequeued",
            "payload": {"status": "received"},
        },
        session_id="session-1",
    )

    assert "当前用户" in queued[0]["content"]
    assert "自动继续" in queued[0]["content"]
    assert "开始规划" in dequeued[0]["content"]


def test_projects_manager_review_and_plan_revision_version_notice() -> None:
    projector = _projector()
    review = projector.project(
        {
            "event_id": "event-review",
            "case_id": "case-1",
            "actor": "bioops-manager",
            "event_type": "manager.review_ready",
            "payload": {
                "work_item_id": "viz-01",
                "decision": "accepted",
                "summary": "图表结构与冻结计划一致。",
            },
        },
        session_id="session-1",
    )
    revision = projector.project(
        {
            "event_id": "event-revision",
            "case_id": "case-1",
            "actor": "bioops-manager",
            "event_type": "planning.revised",
            "payload": {"plan_version": 3, "plan_hash": "abcdef1234567890"},
        },
        session_id="session-1",
    )

    assert "Manager 已验收" in review[0]["content"]
    assert "v3" in revision[0]["content"]
    assert "abcdef12" in revision[0]["content"]


def test_projects_retry_schedule_and_exhausted_choices() -> None:
    projector = _projector()
    scheduled = projector.project(
        {
            "event_id": "event-retry",
            "case_id": "case-1",
            "actor": "agent-rnaseq",
            "event_type": "work_item.retry_scheduled",
            "payload": {"work_item_id": "analysis-01", "delay_seconds": 120},
        },
        session_id="session-1",
    )
    exhausted = projector.project(
        {
            "event_id": "event-exhausted",
            "case_id": "case-1",
            "actor": "bioops-manager",
            "event_type": "work_item.retry_exhausted",
            "payload": {
                "work_item_id": "analysis-01",
                "options": ["retry", "skip", "terminate"],
            },
        },
        session_id="session-1",
    )

    assert "120 秒后自动重试" in scheduled[0]["content"]
    assert "重试、跳过或终止" in exhausted[0]["content"]


class _Registry:
    def role_agent_map(self):
        return {
            "data-steward": "agent-data",
            "quality-auditor": "agent-qc",
            "delivery-reporter": "agent-delivery",
        }

    def role_labels(self):
        return {
            role: {
                "agent_id": agent_id,
                "name": role,
                "avatar": "💬",
                "color": "#123456",
                "role": "worker",
            }
            for role, agent_id in self.role_agent_map().items()
        } | {
            "agent-rnaseq": {
                "agent_id": "agent-rnaseq",
                "name": "RNA-seq",
                "avatar": "🧬",
                "color": "#123456",
                "role": "worker",
            }
        }

    def agent_for_flow(self, flow_id):
        return "agent-rnaseq"


def _projector():
    return CaseRoomProjector(_Registry())
