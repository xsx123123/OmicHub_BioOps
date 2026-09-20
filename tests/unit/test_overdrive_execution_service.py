from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import quote

import pytest

from cygnusx.application.services.overdrive_execution_service import (
    DeliveryAssembler,
    ManagerReviewService,
    OverdrivePreflightService,
    approved_queued_instances,
    deterministic_nickname,
    mark_artifacts_process_on_termination,
    persona_snapshot,
    ready_tasks,
    requeue_repair_instances,
)
from cygnusx.application.services.overdrive_run_service import OverdriveRunService
from cygnusx.core.exceptions import ValidationError
from cygnusx.infrastructure.celery_app.tasks.overdrive import _overdrive_workspace_context


def make_run(tasks):
    return SimpleNamespace(
        run_id="overdrive:test",
        session_id="session-1",
        tasks=tasks,
        plan={"version_path": "output/plan.v1.md"},
        artifact_index=[],
    )


def test_ready_tasks_unlock_per_dependency_without_wave_barrier() -> None:
    run = make_run(
        [
            {"task_id": "fast", "status": "succeeded", "depends_on": []},
            {"task_id": "slow", "status": "running", "depends_on": []},
            {"task_id": "downstream", "status": "pending", "depends_on": ["fast"]},
            {"task_id": "blocked", "status": "pending", "depends_on": ["slow"]},
        ]
    )

    assert [task["task_id"] for task in ready_tasks(run)] == ["downstream"]


def test_independent_qc_context_uses_current_overdrive_paths_not_pipeline_task_ids() -> None:
    run = SimpleNamespace(
        run_id="overdrive-e3c666973e9a48b3",
        session_id="77a734c5-7aee-4c03-9864-d4184d590ca0",
        plan={
            "version_path": (
                "output/overdrive/77a734c5-7aee-4c03-9864-d4184d590ca0/"
                "overdrive-e3c666973e9a48b3/plan.v1.md"
            )
        },
        artifact_index=[
            {
                "path": (
                    "output/overdrive/77a734c5-7aee-4c03-9864-d4184d590ca0/"
                    "overdrive-e3c666973e9a48b3/tasks/scrna-plan/result.md"
                )
            }
        ],
    )

    context = _overdrive_workspace_context(
        run,
        {"task_id": "independent-qc", "depends_on": ["scrna-plan"]},
    )

    assert "plan.v1.md" in context
    assert "tasks/scrna-plan/result.md" in context
    assert "task_result_summary" in context
    assert "Pipeline 任务系统" in context


def test_persona_snapshot_never_copies_permissions_or_tools() -> None:
    snapshot = persona_snapshot(
        {
            "persona": {
                "version": "agent-qc@1",
                "archetype": "审计员",
                "traits": ["审慎"],
                "tools": ["dangerous"],
                "permissions": {"admin": True},
            },
            "tool_packs": ["workspace"],
        }
    )

    assert snapshot == {
        "version": "agent-qc@1",
        "archetype": "审计员",
        "traits": ["审慎"],
    }


def test_nickname_is_stable_and_unique_with_used_set() -> None:
    first = deterministic_nickname("run", "agent-qc", "qc", set())
    assert deterministic_nickname("run", "agent-qc", "qc", set()) == first
    second = deterministic_nickname("run", "agent-qc", "qc", {first})
    assert second != first


def test_rule_review_accepts_only_real_paths_and_completed_criteria() -> None:
    task = {"completion_criteria": ["file_exists", "schema_valid"]}
    accepted = ManagerReviewService().review(
        task,
        {
            "status": "succeeded",
            "artifacts": [{"path": "output/result.tsv"}],
            "self_check": {"file_exists": True, "schema_valid": True},
        },
    )
    escalated = ManagerReviewService().review(
        task,
        {
            "status": "succeeded",
            "artifacts": [{"path": ""}],
            "self_check": {"file_exists": True, "schema_valid": True},
        },
    )

    assert accepted["accepted"] is True
    assert accepted["review_mode"] == "rule"
    assert escalated["accepted"] is False
    assert escalated["review_mode"] == "llm_required"

    missing_file = ManagerReviewService().review(
        task,
        {
            "status": "succeeded",
            "artifacts": [{"path": "output/not-really-there.tsv"}],
            "artifact_paths_valid": False,
            "self_check": {"file_exists": True, "schema_valid": True},
        },
    )
    assert missing_file["accepted"] is False
    assert missing_file["review_mode"] == "llm_required"


def test_rule_review_preserves_branch_local_user_and_approval_waits() -> None:
    service = ManagerReviewService()

    ask = service.review({}, {"status": "awaiting_input", "artifacts": []})
    approval = service.review({}, {"status": "approval_pending", "artifacts": []})

    assert ask["decision"] == "ask_user"
    assert approval["decision"] == "await_approval"
    # 等待态不是失败：basis 不得出现失败措辞
    assert "未成功完成" not in ask["basis"]
    assert "未全部命中" not in ask["basis"]
    assert "未成功完成" not in approval["basis"]
    assert "未全部命中" not in approval["basis"]


def test_independent_qc_adverse_or_missing_conclusion_blocks_delivery() -> None:
    task = {
        "task_id": "independent-qc",
        "completion_criteria": ["audit"],
    }
    failed_gate = ManagerReviewService().review(
        task,
        {
            "status": "succeeded",
            "answer": "已检查全部输出。质量结论：返工",
            "artifacts": [{"path": "output/qc.md"}],
            "self_check": {"audit": True},
        },
    )
    missing_gate = ManagerReviewService().review(
        task,
        {
            "status": "succeeded",
            "answer": "已检查全部输出。",
            "artifacts": [{"path": "output/qc.md"}],
            "self_check": {"audit": True},
        },
    )

    assert failed_gate["decision"] == "quality_gate_failed"
    assert failed_gate["review_mode"] == "rule"
    assert failed_gate["accepted"] is False
    assert missing_gate["review_mode"] == "llm_required"


def test_approved_branch_requeues_the_same_assistant_instance() -> None:
    run = make_run([{
        "task_id": "task-a",
        "status": "queued",
        "depends_on": [],
        "pending_approval": {"status": "approved"},
    }])
    run.assistant_instances = [
        {"assistant_instance_id": "asst:1", "task_id": "task-a", "status": "queued"},
        {"assistant_instance_id": "asst:2", "task_id": "task-a", "status": "awaiting_approval"},
    ]

    instances = approved_queued_instances(run)

    assert [item["assistant_instance_id"] for item in instances] == ["asst:1"]


def test_repair_reuses_original_instance_then_fails_when_budget_is_exhausted() -> None:
    run = make_run([{
        "task_id": "task-a",
        "status": "pending",
        "attempt": 1,
        "repair_feedback": "补充证据链",
        "depends_on": [],
    }])
    run.assistant_instances = [
        {"assistant_instance_id": "asst:original", "task_id": "task-a", "status": "pending"},
    ]

    requeued, exhausted = requeue_repair_instances(run, max_repair_rounds=1)

    assert [item["assistant_instance_id"] for item in requeued] == ["asst:original"]
    assert exhausted == []
    run.tasks[0].update({"status": "pending", "attempt": 2, "repair_feedback": "仍缺证据"})
    run.assistant_instances[0]["status"] = "pending"
    requeued, exhausted = requeue_repair_instances(run, max_repair_rounds=1)
    assert requeued == []
    assert exhausted == ["task-a"]
    assert run.tasks[0]["status"] == "failed"


def test_delivery_excludes_process_and_failed_artifacts() -> None:
    run = make_run([{"task_id": "failed", "status": "failed", "error_summary": "boom"}])
    run.artifact_index = [
        {"path": "output/final.tsv", "status": "validated", "kind": "result", "source": "agent"},
        {"path": "output/debug.log", "status": "failed", "kind": "failed", "source": "agent"},
    ]

    content, official = DeliveryAssembler().assemble(run)

    assert [item["path"] for item in official] == ["output/final.tsv"]
    assert "failed: boom" in content


def test_termination_preserves_prior_files_as_process_artifacts() -> None:
    run = make_run([])
    run.artifact_index = [
        {"path": "output/final.tsv", "kind": "result", "status": "validated"},
        {"path": "output/error.log", "kind": "failed", "status": "failed"},
    ]

    mark_artifacts_process_on_termination(run)

    assert run.artifact_index[0] == {
        "path": "output/final.tsv",
        "kind": "process",
        "status": "process",
        "termination_status": "validated",
    }
    assert run.artifact_index[1]["kind"] == "failed"


def test_preflight_verifies_explicit_workspace_inputs_before_recruitment(monkeypatch, tmp_path) -> None:
    from cygnusx.application.services import overdrive_execution_service as module
    from cygnusx.infrastructure.config.storage_config import StorageConfig
    from cygnusx.infrastructure.storage import LocalStorageBackend, reset_storage_backend
    from cygnusx.infrastructure.storage.path_factory import StoragePathFactory

    run_root = tmp_path / "workspace" / "output" / "overdrive" / "session-1" / "run-1"
    (tmp_path / "workspace" / "input").mkdir(parents=True)
    (tmp_path / "workspace" / "input" / "samples.csv").write_text("sample\nS1\n")
    monkeypatch.setattr(module, "overdrive_run_root", lambda *_: run_root)

    factory = StoragePathFactory(StorageConfig(data_root=str(tmp_path), users_subdir="users"))
    monkeypatch.setattr(module, "get_path_factory", lambda: factory)
    monkeypatch.setattr(
        module, "get_storage_backend", lambda: LocalStorageBackend(path_factory=factory)
    )
    reset_storage_backend()

    class Runs:
        async def assert_execution_allowed(self, _run):
            return None

        async def append_event(self, *_args, **_kwargs):
            return None

    run = make_run([
        {
            "task_id": "input-check", "accepts_inputs": ["input/samples.csv"],
            "produces_outputs": ["validated-samples"],
        },
        {
            "task_id": "analysis", "accepts_inputs": ["validated-samples"],
            "produces_outputs": ["analysis-result"],
        },
    ])

    result = asyncio.run(OverdrivePreflightService(Runs()).run(run))

    assert result["status"] == "passed"
    assert any(check.get("path") == "input/samples.csv" and check["status"] == "passed" for check in result["checks"])
    run.tasks[0]["accepts_inputs"] = ["input/missing.csv"]
    with pytest.raises(Exception, match="串行前置检查失败"):
        asyncio.run(OverdrivePreflightService(Runs()).run(run))
    assert run.status == "FAILED"


def test_projected_events_are_session_scoped_and_replay_deduplicable() -> None:
    event = {
        "run_id": "overdrive:test",
        "session_id": "session-1",
        "sequence": 7,
        "event_type": "assistant_result_ready",
        "payload": {
            "assistant_instance_id": "asst:1",
            "task_id": "task-a",
            "result": {"status": "ok", "answer": "已完成"},
        },
    }

    projected = OverdriveRunService.project_event(event)

    assert projected is not None
    assert projected["session_id"] == "session-1"
    assert projected["message_id"] == "overdrive-event-overdrive:test-7"
    assert OverdriveRunService.project_event(event) == projected


def test_worker_speech_shows_real_agent_name_and_keeps_instance_id() -> None:
    event = {
        "run_id": "overdrive:test",
        "session_id": "session-1",
        "sequence": 12,
        "event_type": "assistant_result_ready",
        "payload": {
            "assistant_instance_id": "asst:overdrive:test:wave-1:1",
            "task_id": "task-a",
            "agent_id": "agent-rna-seq",
            "agent_name": "RNA-seq 分析师",
            "display_name": "衡准",
            "result": {"status": "ok", "answer": "差异表达分析已完成。"},
        },
    }

    projected = OverdriveRunService.project_event(event)

    assert projected is not None
    assert projected["sender"] == {
        "agent_id": "agent-rna-seq",
        "name": "RNA-seq 分析师·衡准",
        "role": "worker",
        "instance_id": "asst:overdrive:test:wave-1:1",
    }

    # 旧事件没有身份字段时保持原行为：回退“执行助手”，agent_id 用 instance id。
    legacy = {
        **event,
        "payload": {
            "assistant_instance_id": "asst:1",
            "task_id": "task-a",
            "result": {"status": "ok", "answer": "已完成"},
        },
    }
    legacy_sender = OverdriveRunService.project_event(legacy)["sender"]  # type: ignore[index]
    assert legacy_sender["name"] == "执行助手"
    assert legacy_sender["agent_id"] == "asst:1"
    assert legacy_sender["instance_id"] == "asst:1"


def test_worker_speech_linkifies_run_artifact_paths() -> None:
    # run_id 中的冒号在相对根目录里被净化为 -，与工作区权威路径一致
    root = "output/overdrive/session-1/overdrive-test"
    event = {
        "run_id": "overdrive:test",
        "session_id": "session-1",
        "sequence": 13,
        "event_type": "assistant_result_ready",
        "payload": {
            "assistant_instance_id": "asst:1",
            "task_id": "task-a",
            "agent_id": "agent-rna-seq",
            "agent_name": "RNA-seq 分析师",
            "result": {
                "status": "ok",
                "answer": (
                    f"结果见 {root}/tasks/task-a/result.md，图表见 {root}/tasks/task-a/volcano.png。"
                    f"已链接的 [报告]({root}/tasks/task-a/qc.html) 不重复包裹。"
                ),
            },
        },
    }

    projected = OverdriveRunService.project_event(event)

    assert projected is not None
    content = projected["content"]
    url_prefix = "/api/v1/chat/sessions/session-1/overdrive-runs/overdrive:test/artifacts?path="
    result_url = url_prefix + quote(f"{root}/tasks/task-a/result.md", safe="")
    volcano_url = url_prefix + quote(f"{root}/tasks/task-a/volcano.png", safe="")
    assert f"[result.md]({result_url})" in content
    # 结尾中文句号截断在链接之外
    assert f"[volcano.png]({volcano_url})。" in content
    # 已在 ](...) 中的路径不重复包裹
    assert content.count("qc.html") == 1
    assert "[qc.html](" not in content


def test_assistant_tool_call_projects_worker_progress() -> None:
    event = {
        "run_id": "overdrive:test",
        "session_id": "session-1",
        "sequence": 5,
        "event_type": "assistant_tool_call",
        "payload": {
            "assistant_instance_id": "asst:1",
            "task_id": "task-a",
            "agent_id": "agent-rna-seq",
            "agent_name": "RNA-seq 分析师",
            "display_name": "衡准",
            "tool_name": "sandbox_execute",
        },
    }

    assert OverdriveRunService.project_event(event) == {
        "type": "overdrive_progress",
        "run_id": "overdrive:test",
        "session_id": "session-1",
        "sequence": 5,
        "phase": "worker_running",
        "label": "RNA-seq 分析师·衡准 正在调用 sandbox_execute",
    }


def test_assistant_heartbeat_and_retrying_stay_unprojected() -> None:
    for event_type in ("assistant_heartbeat", "assistant_retrying"):
        assert OverdriveRunService.project_event({
            "run_id": "overdrive:test",
            "session_id": "session-1",
            "sequence": 5,
            "event_type": event_type,
            "payload": {"assistant_instance_id": "asst:1", "task_id": "task-a"},
        }) is None


def test_research_projection_exposes_tool_style_activities() -> None:
    projected = OverdriveRunService.project_event({
        "run_id": "overdrive:test",
        "session_id": "session-1",
        "sequence": 3,
        "event_type": "research_completed",
        "payload": {
            "knowledge_base": {"status": "succeeded", "evidence_ids": ["ev-1"], "duration_ms": 20},
            "web": {
                "status": "succeeded",
                "queries": ["TP53 lung cancer single-cell RNA-seq"],
                "accepted_count": 2,
                "rejected_count": 1,
                "duration_ms": 45,
            },
            "model_knowledge": {"status": "timed_out", "error": "timeout", "duration_ms": 20000},
        },
    })

    assert projected is not None
    assert projected["type"] == "overdrive_progress"
    assert [item["kind"] for item in projected["activities"]] == ["mcp", "search", "model"]
    assert projected["activities"][1]["accepted"] == 2
    assert projected["activities"][2]["error"] == "timeout"


def test_control_rejects_unconfirmed_plan_before_any_execution_transition() -> None:
    db = SimpleNamespace(get=AsyncMock(return_value=None), add=lambda _item: None)
    service = OverdriveRunService(db)  # type: ignore[arg-type]
    service.get_for_user = AsyncMock(return_value=SimpleNamespace(  # type: ignore[method-assign]
        status="AWAITING_PLAN_CONFIRMATION", run_id="overdrive:test", control={}, version=0,
    ))

    with pytest.raises(ValidationError, match="计划尚未进入执行阶段"):
        asyncio.run(service.apply_control(
            run_id="overdrive:test", user_id="user-1", command_id="command-1", action="pause",
        ))


def test_control_persists_action_payload_for_execution_run() -> None:
    command_rows = []
    db = SimpleNamespace(get=AsyncMock(return_value=None), add=command_rows.append)
    service = OverdriveRunService(db)  # type: ignore[arg-type]
    run = SimpleNamespace(
        status="RUNNING", run_id="overdrive:test", control={}, version=0,
    )
    service.get_for_user = AsyncMock(return_value=run)  # type: ignore[method-assign]
    service.append_event = AsyncMock()  # type: ignore[method-assign]
    service._write_snapshot = AsyncMock()  # type: ignore[method-assign]

    result = asyncio.run(service.apply_control(
        run_id="overdrive:test", user_id="user-1", command_id="command-1", action="pause",
    ))

    assert result["status"] == "PAUSED"
    assert len(command_rows) == 1
    assert command_rows[0].command_type == "control_pause"
    assert command_rows[0].payload == {"action": "pause"}


def test_preflight_termination_finishes_synchronously_before_workers_start() -> None:
    command_rows = []
    db = SimpleNamespace(get=AsyncMock(return_value=None), add=command_rows.append)
    service = OverdriveRunService(db)  # type: ignore[arg-type]
    run = SimpleNamespace(
        status="SERIAL_PREFLIGHT",
        run_id="overdrive:stale-plan",
        control={},
        version=0,
        finished_at=None,
        tasks=[{"task_id": "plan", "status": "pending"}],
    )
    service.get_for_user = AsyncMock(return_value=run)  # type: ignore[method-assign]
    service.append_event = AsyncMock()  # type: ignore[method-assign]
    service._write_snapshot = AsyncMock()  # type: ignore[method-assign]

    result = asyncio.run(service.apply_control(
        run_id=run.run_id,
        user_id="user-1",
        command_id="terminate-stale-plan",
        action="terminate",
    ))

    assert result["status"] == "TERMINATED"
    assert run.finished_at is not None
    assert service.append_event.await_args.args[1] == "run_terminated"


def test_approving_plan_only_run_completes_without_worker_preflight(monkeypatch, tmp_path) -> None:
    from cygnusx.application.services import overdrive_run_service as module
    from cygnusx.infrastructure.config.storage_config import StorageConfig
    from cygnusx.infrastructure.storage import LocalStorageBackend, reset_storage_backend
    from cygnusx.infrastructure.storage.path_factory import StoragePathFactory

    command_rows = []
    db = SimpleNamespace(get=AsyncMock(return_value=None), add=command_rows.append)
    service = OverdriveRunService(db)  # type: ignore[arg-type]
    run = SimpleNamespace(
        status="AWAITING_PLAN_CONFIRMATION",
        run_id="overdrive:plan-only",
        session_id="session-1",
        plan={
            "version": 1,
            "hash": "sha256:plan",
            "status": "awaiting_confirmation",
            "path": "output/overdrive/session-1/overdrive:plan-only/plan.md",
            "version_path": "output/overdrive/session-1/overdrive:plan-only/plan.v1.md",
            "summary": {"planning_only": True, "title": "单细胞分析方案"},
        },
        artifact_index=[],
        version=0,
        finished_at=None,
    )
    service.get_for_user = AsyncMock(return_value=run)  # type: ignore[method-assign]
    async def _noop_assert_plan(_run):
        return None

    service._assert_plan_file_matches = _noop_assert_plan  # type: ignore[method-assign]
    service.append_event = AsyncMock()  # type: ignore[method-assign]
    service._write_snapshot = AsyncMock()  # type: ignore[method-assign]

    def fake_root(session_id: str, run_id: str) -> Path:
        return tmp_path / session_id / run_id

    factory = StoragePathFactory(StorageConfig(data_root=str(tmp_path), users_subdir="users"))
    monkeypatch.setattr(module, "get_path_factory", lambda: factory)
    monkeypatch.setattr(
        module, "get_storage_backend", lambda: LocalStorageBackend(path_factory=factory)
    )
    reset_storage_backend()

    with patch.multiple(
        "cygnusx.application.services.overdrive_run_service",
        overdrive_run_root=fake_root,
        relative_overdrive_run_root=lambda session_id, run_id: f"output/overdrive/{session_id}/{run_id}",
    ):
        result = asyncio.run(service.decide_plan(
            run_id=run.run_id,
            user_id="user-1",
            command_id="command-plan-only",
            action="approve",
            plan_version=1,
            plan_digest="sha256:plan",
        ))

    assert result["status"] == "COMPLETED"
    assert run.status == "COMPLETED"
    assert run.finished_at is not None
    event_types = [call.args[1] for call in service.append_event.await_args_list]
    assert event_types == ["run_completed", "manager_delivery_ready"]

    # 方案规划型 run 必须落一份项目 README,并登记为可下载交付物。
    delivery_path = result["delivery"]["path"]
    assert delivery_path.endswith("/delivery/README.md")
    readme = fake_root(run.session_id, run.run_id) / "delivery" / "README.md"
    content = readme.read_text(encoding="utf-8")
    assert "单细胞分析方案" in content
    assert "下载方式" in content
    assert run.artifact_index == [
        {"path": delivery_path, "kind": "delivery", "source": "manager", "status": "succeeded"}
    ]

    completed_payload = service.append_event.await_args_list[0].args[2]
    assert completed_payload["planning_only"] is True
    assert completed_payload["delivery_path"] == delivery_path
    assert completed_payload["artifacts"][0]["path"] == delivery_path

    # 交付事件投影为 Manager 的 room_speech,完成事件带 planning_only 标志。
    delivery_event = {
        "run_id": run.run_id,
        "session_id": run.session_id,
        "sequence": 11,
        "event_type": "manager_delivery_ready",
        "payload": service.append_event.await_args_list[1].args[2],
    }
    projected = OverdriveRunService.project_event(delivery_event)
    assert projected is not None
    assert projected["type"] == "room_speech"
    assert projected["sender"]["role"] == "manager"
    assert projected["delivery_path"] == delivery_path
    assert "README" in projected["content"]
    # Manager 交付发言必须是详细描述:协作安排、交付位置与下一步引导,
    # 而不是只说文件在哪里;发言人统一显示为超频 Manager。
    assert projected["sender"]["name"] == "超频 Manager"
    assert "协作安排" in projected["content"]
    assert "下一步" in projected["content"]
    assert "按方案开始执行" in projected["content"]
    assert "上传" in projected["content"]

    completed_event = {
        "run_id": run.run_id,
        "session_id": run.session_id,
        "sequence": 10,
        "event_type": "run_completed",
        "payload": completed_payload,
    }
    projected_completed = OverdriveRunService.project_event(completed_event)
    assert projected_completed is not None
    assert projected_completed["type"] == "overdrive_progress"
    assert projected_completed["planning_only"] is True


def test_projected_manager_review_suppresses_wait_state_speech() -> None:
    base = {
        "run_id": "overdrive:test",
        "session_id": "session-1",
        "sequence": 9,
        "event_type": "manager_review_ready",
    }
    for decision in ("ask_user", "await_approval"):
        event = {**base, "payload": {"decision": decision, "basis": "ignored"}}
        assert OverdriveRunService.project_event(event) is None

    failure = {
        **base,
        "payload": {"decision": "repair_or_review", "basis": "worker 未成功完成"},
    }
    projected = OverdriveRunService.project_event(failure)
    assert projected is not None
    assert projected["type"] == "room_speech"
    assert projected["content"] == "worker 未成功完成"


def test_projected_plan_cancellation_updates_progress_card() -> None:
    event = {
        "run_id": "overdrive:test",
        "session_id": "session-1",
        "sequence": 10,
        "event_type": "run_cancelled",
        "payload": {},
    }

    projected = OverdriveRunService.project_event(event)

    assert projected is not None
    assert projected["type"] == "overdrive_progress"
    assert projected["phase"] == "terminated"
    assert projected["label"] == "用户已取消本轮超频协作，计划不会执行"


def test_projected_worker_approval_keeps_run_and_exact_call_context() -> None:
    event = {
        "run_id": "overdrive:test",
        "session_id": "session-1",
        "sequence": 8,
        "event_type": "assistant_result_ready",
        "payload": {
            "result": {"status": "approval_pending"},
            "approval": {
                "approval_id": "overdrive-v2-approval:overdrive:test:task-a:1",
                "run_id": "overdrive:test",
                "task_id": "task-a",
                "attempt": 1,
                "tool_name": "workspace_write",
                "arguments": {"path": "output/a.txt", "content": "x"},
                "status": "pending",
            },
        },
    }

    projected = OverdriveRunService.project_event(event)

    assert projected == {
        "type": "overdrive_approval_request",
        "run_id": "overdrive:test",
        "session_id": "session-1",
        "sequence": 8,
        "message_id": "overdrive-approval-overdrive:test-8",
        "approval": event["payload"]["approval"],
    }


def test_artifact_index_keeps_official_process_and_failed_entries_separate() -> None:
    run = make_run([])
    run.artifact_index = [
        {"path": "output/final.md", "kind": "delivery", "status": "validated"},
        {"path": "output/evidence.json", "kind": "process", "status": "passed"},
        {"path": "output/failed.log", "kind": "failed", "status": "failed"},
    ]

    _content, official = DeliveryAssembler().assemble(run)

    assert [item["path"] for item in official] == ["output/final.md"]
    assert {item["path"] for item in run.artifact_index if item["kind"] == "process"} == {
        "output/evidence.json"
    }
    assert {item["path"] for item in run.artifact_index if item["status"] == "failed"} == {
        "output/failed.log"
    }


def test_latest_run_lookup_includes_terminal_runs_for_history_recovery() -> None:
    terminal_run = SimpleNamespace(run_id="overdrive:completed", status="COMPLETED")
    result = SimpleNamespace(scalar_one_or_none=lambda: terminal_run)
    db = SimpleNamespace(execute=AsyncMock(return_value=result))

    restored = asyncio.run(
        OverdriveRunService(db).get_latest_for_session("session-1", "user-1")
    )

    assert restored is terminal_run
    statement = db.execute.await_args.args[0]
    rendered = str(statement)
    assert "overdrive_runs.session_id" in rendered
    assert "overdrive_runs.user_id" in rendered
    assert "overdrive_runs.status NOT IN" not in rendered


def test_write_readme_covers_delivery_downloads_and_manager_summary(monkeypatch, tmp_path) -> None:
    from cygnusx.application.services import overdrive_execution_service as module
    from cygnusx.infrastructure.config.storage_config import StorageConfig
    from cygnusx.infrastructure.storage import LocalStorageBackend, reset_storage_backend
    from cygnusx.infrastructure.storage.path_factory import StoragePathFactory

    run = make_run(
        [
            {"task_id": "task-a", "status": "succeeded"},
            {"task_id": "task-b", "status": "failed", "error_summary": "超时"},
        ]
    )
    run.finished_at = None
    run.plan = {
        "version": 2,
        "hash": "sha256:abcdef123456",
        "summary": {"title": "TP53 单细胞分析"},
    }
    run.artifact_index = [
        {"path": "output/overdrive/session-1/overdrive:test/tasks/task-a/result.md",
         "kind": "result", "status": "validated", "source": "agent-scrna"},
    ]

    def fake_root(session_id: str, run_id: str) -> Path:
        return tmp_path / session_id / run_id

    factory = StoragePathFactory(StorageConfig(data_root=str(tmp_path), users_subdir="users"))
    monkeypatch.setattr(module, "get_path_factory", lambda: factory)
    monkeypatch.setattr(
        module, "get_storage_backend", lambda: LocalStorageBackend(path_factory=factory)
    )
    reset_storage_backend()

    with patch.multiple(
        "cygnusx.application.services.overdrive_execution_service",
        overdrive_run_root=fake_root,
        relative_overdrive_run_root=lambda session_id, run_id: f"output/overdrive/{session_id}/{run_id}",
    ):
        delivery = {
            "path": "output/overdrive/session-1/overdrive:test/delivery/final-report.md",
            "official_artifacts": run.artifact_index,
        }
        readme = asyncio.run(
            DeliveryAssembler().write_readme(run, delivery, manager_summary="Manager 总结:全部完成。")
        )

    assert readme["path"].endswith("/delivery/README.md")
    content = (fake_root(run.session_id, run.run_id) / "delivery" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "TP53 单细胞分析" in content
    assert "v2" in content and "sha256:a"[:8] in content
    assert "final-report.md" in content
    assert "task-a/result.md" in content
    assert "artifacts?path=" in content
    assert "Manager 总结:全部完成。" in content
    assert "task-b: 超时" in content


def test_write_readme_includes_software_and_environment_sections(monkeypatch, tmp_path) -> None:
    from cygnusx.application.services import overdrive_execution_service as module
    from cygnusx.application.services.project_archive_service import collect_environment
    from cygnusx.infrastructure.config.storage_config import StorageConfig
    from cygnusx.infrastructure.storage import LocalStorageBackend, reset_storage_backend
    from cygnusx.infrastructure.storage.path_factory import StoragePathFactory

    run = make_run([{"task_id": "task-a", "status": "succeeded"}])
    run.finished_at = None
    run.plan = {"version": 1, "hash": "sha256:abc", "summary": {"title": "T"}}

    def fake_root(session_id: str, run_id: str) -> Path:
        return tmp_path / session_id / run_id

    factory = StoragePathFactory(StorageConfig(data_root=str(tmp_path), users_subdir="users"))
    monkeypatch.setattr(module, "get_path_factory", lambda: factory)
    monkeypatch.setattr(
        module, "get_storage_backend", lambda: LocalStorageBackend(path_factory=factory)
    )
    reset_storage_backend()

    environment = collect_environment(
        image=None, flow_id="overdrive", flow_name="超频协作", flow_version="v1"
    )
    with patch.multiple(
        "cygnusx.application.services.overdrive_execution_service",
        overdrive_run_root=fake_root,
        relative_overdrive_run_root=lambda session_id, run_id: f"output/overdrive/{session_id}/{run_id}",
    ):
        asyncio.run(
            DeliveryAssembler().write_readme(
                run,
                {"path": "output/overdrive/session-1/overdrive:test/delivery/final-report.md"},
                environment=environment,
            )
        )

    content = (fake_root(run.session_id, run.run_id) / "delivery" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "## 软件与版本" in content
    assert "## 分析环境" in content
    assert "流程版本: v1" in content
    assert "environment.json" in content


def test_delivery_write_creates_downloadable_artifact_bundle(monkeypatch, tmp_path) -> None:
    from cygnusx.application.services import overdrive_execution_service as module
    from cygnusx.infrastructure.config.storage_config import StorageConfig
    from cygnusx.infrastructure.storage.path_factory import StoragePathFactory

    run = make_run([{"task_id": "task-a", "status": "succeeded"}])
    run.artifact_index = [
        {
            "path": "output/overdrive/session-1/overdrive:test/tasks/task-a/result.md",
            "kind": "result",
            "status": "validated",
            "source": "agent-general",
        }
    ]

    def fake_root(session_id: str, run_id: str) -> Path:
        return tmp_path / session_id / run_id

    factory = StoragePathFactory(StorageConfig(data_root=str(tmp_path), users_subdir="users"))

    class FakeBackend:
        def __init__(self) -> None:
            self.files: dict[str, bytes] = {
                run.artifact_index[0]["path"]: "实体清单\n".encode()
            }

        async def ensure_dir(self, _path: str) -> None:
            return None

        async def read(self, path: str) -> bytes:
            return self.files[path]

        async def write(self, path: str, content: bytes) -> None:
            self.files[path] = content

    backend = FakeBackend()
    monkeypatch.setattr(module, "get_path_factory", lambda: factory)
    monkeypatch.setattr(module, "get_storage_backend", lambda: backend)

    with patch.multiple(
        module,
        overdrive_run_root=fake_root,
        relative_overdrive_run_root=lambda session_id, run_id: f"output/overdrive/{session_id}/{run_id}",
    ):
        delivery = asyncio.run(DeliveryAssembler().write(run))

    assert delivery["archive_path"].endswith("/delivery/artifacts.zip")
    archive_key = next(path for path in backend.files if path.endswith("/delivery/artifacts.zip"))
    archive = backend.files[archive_key]
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        assert bundle.read("final-report.md").startswith(b"# ")
        assert bundle.read(
            "output/overdrive/session-1/overdrive:test/tasks/task-a/result.md"
        ) == "实体清单\n".encode()
