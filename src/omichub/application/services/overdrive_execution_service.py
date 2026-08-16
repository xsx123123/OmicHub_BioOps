"""Preflight, event-driven scheduling, review, and delivery for overdrive v2."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from omichub.application.services.overdrive_run_service import (
    OverdriveRunService,
    overdrive_run_root,
    relative_overdrive_run_root,
)
from omichub.core.exceptions import ValidationError
from omichub.infrastructure.database.models.overdrive import OverdriveRunModel
from omichub.infrastructure.storage import get_path_factory, get_storage_backend

TERMINAL_TASK_STATUSES = frozenset({"succeeded", "failed", "cancelled", "skipped"})
ACCEPTED_TASK_STATUSES = frozenset({"succeeded", "skipped"})
ACTIVE_TASK_STATUSES = frozenset(
    {"queued", "running", "reviewing", "paused", "awaiting_input", "awaiting_approval"}
)

_NICKNAMES = (
    "衡准",
    "探微",
    "明析",
    "溯源",
    "砺行",
    "知序",
    "澄观",
    "归一",
    "映真",
    "守正",
    "见远",
    "成章",
)


def deterministic_nickname(run_id: str, agent_id: str, task_id: str, used: set[str]) -> str:
    """Choose a stable unique nickname without refresh-time randomness."""
    digest = hashlib.sha256(f"{run_id}:{agent_id}:{task_id}".encode()).digest()
    offset = int.from_bytes(digest[:2], "big") % len(_NICKNAMES)
    for index in range(len(_NICKNAMES)):
        candidate = _NICKNAMES[(offset + index) % len(_NICKNAMES)]
        if candidate not in used:
            return candidate
    return f"助手-{len(used) + 1}"


def task_states(run: OverdriveRunModel) -> dict[str, str]:
    return {str(task.get("task_id")): str(task.get("status") or "pending") for task in run.tasks}


def ready_tasks(run: OverdriveRunModel) -> list[dict[str, Any]]:
    """Unlock nodes as soon as their own dependencies pass, not at wave barriers."""
    states = task_states(run)
    ready: list[dict[str, Any]] = []
    for task in run.tasks:
        if str(task.get("status") or "pending") != "pending":
            continue
        dependencies = [str(item) for item in task.get("depends_on") or []]
        if all(states.get(dependency) in ACCEPTED_TASK_STATUSES for dependency in dependencies):
            ready.append(task)
    return ready


def blocked_tasks(run: OverdriveRunModel) -> list[dict[str, Any]]:
    states = task_states(run)
    return [
        task
        for task in run.tasks
        if str(task.get("status") or "pending") == "pending"
        and any(states.get(str(dep)) == "failed" for dep in task.get("depends_on") or [])
    ]


def branch_waits(tasks: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Expose branch-local waits without turning them into a run-global stop state."""
    return {
        status: sorted(
            str(task.get("task_id"))
            for task in tasks
            if str(task.get("status") or "pending") == status
        )
        for status in ("awaiting_input", "awaiting_approval")
    }


def resume_paused_instances(run: OverdriveRunModel) -> list[dict[str, Any]]:
    """Requeue existing instances after a cooperative pause; never recruit duplicates."""
    paused_task_ids = {
        str(task.get("task_id"))
        for task in run.tasks
        if str(task.get("status") or "") == "paused"
    }
    if not paused_task_ids:
        return []
    tasks = deepcopy(run.tasks)
    for task in tasks:
        if str(task.get("task_id")) in paused_task_ids:
            task["status"] = "queued"
    instances = deepcopy(run.assistant_instances)
    resumed: list[dict[str, Any]] = []
    for instance in instances:
        if (
            str(instance.get("task_id")) in paused_task_ids
            and str(instance.get("status") or "") == "paused"
        ):
            instance["status"] = "queued"
            instance["finished_at"] = None
            resumed.append(instance)
    run.tasks = tasks
    run.assistant_instances = instances
    return resumed


def approved_queued_instances(run: OverdriveRunModel) -> list[dict[str, Any]]:
    """Return existing instances requeued after one exact tool approval.

    New recruitment uses ``status=recruited``.  ``queued`` therefore means this
    particular instance has already stopped for approval and may be dispatched
    again without creating a second assistant identity.
    """
    queued_approval_tasks = {
        str(task.get("task_id") or "")
        for task in run.tasks
        if str(task.get("status") or "") == "queued"
        and isinstance(task.get("pending_approval"), dict)
        and task["pending_approval"].get("status") == "approved"
    }
    return [
        deepcopy(instance)
        for instance in run.assistant_instances
        if str(instance.get("status") or "") == "queued"
        and str(instance.get("task_id") or "") in queued_approval_tasks
    ]


def requeue_repair_instances(
    run: OverdriveRunModel, *, max_repair_rounds: int
) -> tuple[list[dict[str, Any]], list[str]]:
    """Reuse the original assistant for Manager-requested repair, within its budget."""
    tasks = deepcopy(run.tasks)
    instances = deepcopy(run.assistant_instances)
    by_task = {str(task.get("task_id") or ""): task for task in tasks}
    requeued: list[dict[str, Any]] = []
    exhausted: list[str] = []
    for instance in instances:
        task_id = str(instance.get("task_id") or "")
        task = by_task.get(task_id)
        if (
            task is None
            or str(task.get("status") or "") != "pending"
            or not str(task.get("repair_feedback") or "").strip()
            or str(instance.get("status") or "") != "pending"
        ):
            continue
        if int(task.get("attempt") or 0) > max(0, max_repair_rounds):
            task.update(
                {
                    "status": "failed",
                    "error_summary": "已达到 Manager 返工轮次上限："
                    + str(task.get("repair_feedback") or ""),
                }
            )
            instance.update({"status": "failed", "finished_at": datetime.now(UTC).isoformat()})
            exhausted.append(task_id)
            continue
        task.update({"status": "queued", "error_summary": ""})
        instance.update({"status": "queued", "finished_at": None})
        requeued.append(deepcopy(instance))
    run.tasks = tasks
    run.assistant_instances = instances
    return requeued, exhausted


def apply_controlled_worker_stop(
    run: OverdriveRunModel,
    *,
    task_id: str,
    assistant_instance_id: str,
    action: str,
) -> str:
    """Patch only one worker branch while preserving concurrent sibling results."""
    status = "cancelled" if action == "terminated" else "paused"
    tasks = deepcopy(run.tasks)
    for task in tasks:
        if str(task.get("task_id")) == task_id and task.get("status") not in TERMINAL_TASK_STATUSES:
            task["status"] = status
            task["stopped_at"] = datetime.now(UTC).isoformat()
            task["error_summary"] = "用户终止运行" if status == "cancelled" else "运行已暂停"
    instances = deepcopy(run.assistant_instances)
    for instance in instances:
        if str(instance.get("assistant_instance_id")) == assistant_instance_id:
            instance["status"] = status
            instance["finished_at"] = (
                datetime.now(UTC).isoformat() if status == "cancelled" else None
            )
    run.tasks = tasks
    run.assistant_instances = instances
    return status


def mark_artifacts_process_on_termination(run: OverdriveRunModel) -> None:
    """Keep prior files for audit, but never present a terminated run as delivery."""
    artifacts = deepcopy(run.artifact_index)
    for artifact in artifacts:
        if not isinstance(artifact, dict) or artifact.get("kind") == "failed":
            continue
        prior_status = str(artifact.get("status") or "")
        artifact.update(
            {
                "kind": "process",
                "status": "process",
                "termination_status": prior_status,
            }
        )
    run.artifact_index = artifacts


def persona_snapshot(agent_features: dict[str, Any] | None) -> dict[str, Any]:
    """Return presentation fields only; never copy tools or permission settings."""
    raw = (agent_features or {}).get("persona")
    if not isinstance(raw, dict):
        return {}
    allowed = {
        "archetype",
        "traits",
        "working_style",
        "communication_style",
        "challenge_style",
        "status_lines",
        "version",
    }
    return {key: deepcopy(value) for key, value in raw.items() if key in allowed}


class OverdrivePreflightService:
    """Perform serial, non-worker checks after the immutable plan is approved."""

    def __init__(self, run_service: OverdriveRunService) -> None:
        self._runs = run_service

    async def run(self, run: OverdriveRunModel) -> dict[str, Any]:
        await self._runs.assert_execution_allowed(run)
        factory = get_path_factory()
        backend = get_storage_backend()
        root = overdrive_run_root(run.session_id, run.run_id)
        root_rel = factory.relative_to_root(root)
        checks: list[dict[str, Any]] = []
        await backend.ensure_dir(root_rel)
        checks.append({"name": "run_directory", "status": "passed", "path": str(root)})
        task_ids = {str(task.get("task_id") or "") for task in run.tasks}
        checks.append(
            {
                "name": "task_contracts",
                "status": "passed" if "" not in task_ids and len(task_ids) == len(run.tasks) else "failed",
                "count": len(task_ids),
            }
        )
        # A contract name such as ``normalized-counts`` is produced by another
        # DAG node and must not be mistaken for a filesystem path.  Explicit
        # workspace-relative paths, however, are hard preconditions and are
        # checked before any worker can be recruited.
        produced_contracts = {
            str(output)
            for task in run.tasks
            for output in task.get("produces_outputs") or []
            if str(output).strip()
        }
        workspace = root.parents[3]
        workspace_rel = factory.relative_to_root(workspace)
        required_paths = sorted(
            {
                str(item).strip()
                for task in run.tasks
                for item in task.get("accepts_inputs") or []
                if str(item).strip() not in produced_contracts
                and _is_workspace_relative_path(str(item).strip())
            }
        )
        for relative_path in required_paths:
            candidate = (workspace / relative_path).resolve()
            try:
                candidate.relative_to(workspace.resolve())
                candidate_rel = factory.relative_to_root(candidate)
                exists = await backend.exists(candidate_rel)
            except ValueError:
                exists = False
            checks.append(
                {
                    "name": "required_workspace_input",
                    "path": relative_path,
                    "status": "passed" if exists else "failed",
                    "reason": "已核验真实工作区路径" if exists else "工作区输入不存在或越出边界",
                }
            )
        shared = root / "preflight" / "preflight_result.json"
        shared_rel = factory.relative_to_root(shared)
        result = {
            "status": "passed" if all(item["status"] == "passed" for item in checks) else "failed",
            "checked_at": datetime.now(UTC).isoformat(),
            "checks": checks,
            "output_root": relative_overdrive_run_root(run.session_id, run.run_id),
        }
        await backend.ensure_dir(factory.relative_to_root(shared.parent))
        await backend.write(
            shared_rel,
            (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        run.artifact_index = [
            *run.artifact_index,
            {
                "artifact_id": "preflight_result",
                "path": f"{relative_overdrive_run_root(run.session_id, run.run_id)}/preflight/preflight_result.json",
                "kind": "process",
                "status": result["status"],
                "source": "manager",
            },
        ]
        await self._runs.append_event(run.run_id, "preflight_completed", result)
        if result["status"] != "passed":
            run.status = "FAILED"
            run.finished_at = datetime.now(UTC)
            raise ValidationError("串行前置检查失败，禁止招募执行助手")
        return result


def _is_workspace_relative_path(value: str) -> bool:
    """Recognize only explicit workspace paths, never opaque task contracts."""
    normalized = value.replace("\\", "/")
    return normalized.startswith(("input/", "uploads/", "output/"))


class OverdriveScheduler:
    def __init__(self, run_service: OverdriveRunService) -> None:
        self._runs = run_service

    async def recruit_ready(
        self,
        run: OverdriveRunModel,
        agent_catalog: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        await self._runs.assert_execution_allowed(run)
        recruited: list[dict[str, Any]] = []
        used_names = {str(item.get("display_name")) for item in run.assistant_instances}
        instances = deepcopy(run.assistant_instances)
        tasks = deepcopy(run.tasks)
        task_map = {str(task["task_id"]): task for task in tasks}
        for task in ready_tasks(run):
            task_id = str(task["task_id"])
            agent_id = str(task["agent_id"])
            agent = agent_catalog.get(agent_id)
            if agent is None:
                raise ValidationError(f"无法招募未知 Agent: {agent_id}")
            wave = 1 + max(
                (
                    int(task_map.get(str(dep), {}).get("wave") or 0)
                    for dep in task.get("depends_on") or []
                ),
                default=0,
            )
            display_name = deterministic_nickname(run.run_id, agent_id, task_id, used_names)
            used_names.add(display_name)
            persona = persona_snapshot(agent.get("features"))
            status_lines = persona.get("status_lines") if isinstance(persona, dict) else {}
            queued_lines = status_lines.get("queued") if isinstance(status_lines, dict) else []
            instance = {
                "assistant_instance_id": f"asst:{run.run_id}:wave-{wave}:{len(instances) + 1}",
                "agent_id": agent_id,
                "agent_name": str(agent.get("name") or "") or None,
                "display_name": display_name,
                "persona_version": str(
                    (agent.get("features") or {}).get("persona", {}).get("version")
                    or f"{agent_id}@1"
                ),
                "persona": persona,
                "persona_context": str(task.get("persona_context") or ""),
                "task_id": task_id,
                "wave_id": f"wave-{wave}",
                "status": "recruited",
                "status_line": str(queued_lines[0]) if queued_lines else "已加入执行队列",
                "task_summary": str(task.get("task") or "")[:240],
                "created_at": datetime.now(UTC).isoformat(),
                "finished_at": None,
            }
            instances.append(instance)
            task_map[task_id]["status"] = "queued"
            task_map[task_id]["wave"] = wave
            recruited.append(instance)
            await self._runs.append_event(
                run.run_id,
                "assistant_recruited",
                deepcopy(instance),
                dedupe_key=f"assistant_recruited:{task_id}:{int(task_map[task_id].get('attempt') or 0)}",
            )
        run.tasks = tasks
        run.assistant_instances = instances
        return recruited

    async def mark_blocked(self, run: OverdriveRunModel) -> None:
        blocked = {str(task["task_id"]) for task in blocked_tasks(run)}
        if not blocked:
            return
        tasks = deepcopy(run.tasks)
        for task in tasks:
            if str(task.get("task_id")) in blocked:
                task["status"] = "skipped"
                task["error_summary"] = "上游必需任务失败"
        run.tasks = tasks
        await self._runs.append_event(run.run_id, "tasks_blocked", {"task_ids": sorted(blocked)})


class ManagerReviewService:
    """Rule fast path with explicit escalation when evidence is incomplete or conflicting."""

    def review(self, task: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), list) else []
        criteria = [str(item) for item in task.get("completion_criteria") or []]
        checks = result.get("self_check") if isinstance(result.get("self_check"), dict) else {}
        result_status = str(result.get("status") or "")
        if result_status == "paused":
            return {
                "review_mode": "rule",
                "decision": "pause",
                "accepted": False,
                "basis": "助手在用户暂停命令的安全点停止",
                "reviewed_at": datetime.now(UTC).isoformat(),
            }
        if result_status == "terminated":
            return {
                "review_mode": "rule",
                "decision": "terminate",
                "accepted": False,
                "basis": "助手在用户终止命令的安全点停止",
                "reviewed_at": datetime.now(UTC).isoformat(),
            }
        success = result_status in {"ok", "succeeded"}
        awaiting_input = result_status == "awaiting_input"
        awaiting_approval = result_status == "approval_pending"
        criteria_met = all(bool(checks.get(item)) for item in criteria) if criteria else success
        paths_valid = all(
            isinstance(item, dict) and bool(str(item.get("path") or "").strip())
            for item in artifacts
        )
        # The job boundary independently checks filesystem existence and containment.
        # Keep this explicit flag so a rule-fast-path review can never accept a
        # worker-supplied, merely non-empty path.
        paths_valid = paths_valid and bool(result.get("artifact_paths_valid", True))
        conflict = bool(result.get("conflicts"))
        accepted = success and criteria_met and paths_valid and not conflict
        is_independent_qc = str(task.get("task_id") or "") == "independent-qc"
        qc_match = re.search(
            r"(?:质量结论|QC结论)\s*[:：]\s*(通过|返工|人工复核)",
            str(result.get("answer") or ""),
            flags=re.IGNORECASE,
        )
        qc_decision = qc_match.group(1) if qc_match else None
        # The independent auditor is a release gate, not an ordinary worker: a
        # successful tool invocation cannot silently turn an adverse or absent
        # audit conclusion into a successful run.
        if is_independent_qc:
            accepted = accepted and qc_decision == "通过"
        # Awaiting user input / approval is a healthy wait state, not a worker
        # failure: keep the failure wording out of the user-visible basis.
        waiting = awaiting_input or awaiting_approval
        reasons: list[str] = []
        if not success and not waiting:
            reasons.append("worker 未成功完成")
        if not criteria_met and not waiting:
            reasons.append("完成判据未全部命中")
        if not paths_valid:
            reasons.append("产物路径无效")
        if conflict:
            reasons.append("与已回流结果存在冲突")
        if is_independent_qc and qc_decision is None:
            reasons.append("独立 QC 未按约定输出质量结论")
        if is_independent_qc and qc_decision in {"返工", "人工复核"}:
            reasons.append(f"独立 QC 质量门结论为{qc_decision}")
        quality_gate_failed = is_independent_qc and qc_decision in {"返工", "人工复核"}
        return {
            "review_mode": (
                "rule"
                if accepted or awaiting_input or awaiting_approval or quality_gate_failed
                else "llm_required"
            ),
            "decision": (
                "accept"
                if accepted
                else "ask_user"
                if awaiting_input
                else "await_approval"
                if awaiting_approval
                else "quality_gate_failed"
                if quality_gate_failed
                else "repair_or_review"
            ),
            "accepted": accepted,
            "basis": (
                "完成判据与产物路径均已验证"
                if accepted
                else "助手正在等待你补充输入，回答后将继续执行"
                if awaiting_input
                else "助手正在等待审批，通过后将继续执行"
                if awaiting_approval
                else "；".join(reasons)
            ),
            "reviewed_at": datetime.now(UTC).isoformat(),
        }


class DeliveryAssembler:
    def assemble(self, run: OverdriveRunModel) -> tuple[str, list[dict[str, Any]]]:
        official = [
            item
            for item in run.artifact_index
            if item.get("status") in {"passed", "validated", "succeeded"}
            and item.get("kind") not in {"process", "failed"}
        ]
        process = [item for item in run.artifact_index if item not in official]
        failures = [task for task in run.tasks if task.get("status") in {"failed", "skipped"}]
        lines = [
            "# 超频协作最终交付",
            "",
            f"- Run: `{run.run_id}`",
            f"- 计划: `{(run.plan or {}).get('version_path', '')}`",
            f"- 正式产物: {len(official)}",
            f"- 过程/失败产物: {len(process)}",
            f"- 失败或跳过任务: {len(failures)}",
            "",
            "## 正式交付",
            "",
        ]
        lines.extend(
            f"- `{item.get('path')}`（来源：{item.get('source') or 'unknown'}）" for item in official
        )
        lines.extend(["", "## 限制与未完成项", ""])
        lines.extend(
            f"- {task.get('task_id')}: {task.get('error_summary') or task.get('status')}"
            for task in failures
        )
        return "\n".join(lines).rstrip() + "\n", official

    async def write(self, run: OverdriveRunModel) -> dict[str, Any]:
        content, official = self.assemble(run)
        factory = get_path_factory()
        backend = get_storage_backend()
        root = overdrive_run_root(run.session_id, run.run_id) / "delivery"
        root_rel = factory.relative_to_root(root)
        await backend.ensure_dir(root_rel)
        path_rel = f"{root_rel}/final-report.md"
        await backend.write(path_rel, content.encode("utf-8"))
        relative = f"{relative_overdrive_run_root(run.session_id, run.run_id)}/delivery/final-report.md"
        return {"path": relative, "official_artifacts": official, "content": content}

    async def write_readme(
        self,
        run: OverdriveRunModel,
        delivery: dict[str, Any],
        *,
        manager_summary: str = "",
    ) -> dict[str, Any]:
        """生成项目 README:交付清单、下载方式与 Manager 总结。

        沿用工作台 output/README 索引的约定,让每轮超频协作都有
        “最终结果在哪、从哪里下载”的权威说明。Manager 总结后补时
        可用同一方法重写(幂等覆盖)。
        """
        plan = run.plan or {}
        summary = plan.get("summary") if isinstance(plan.get("summary"), dict) else {}
        title = str(summary.get("title") or "超频协作")
        official = [
            item
            for item in delivery.get("official_artifacts") or []
            if isinstance(item, dict) and item.get("path")
        ]
        failures = [task for task in run.tasks if task.get("status") in {"failed", "skipped"}]
        finished = run.finished_at.isoformat() if run.finished_at else datetime.now(UTC).isoformat()
        lines = [
            "# 项目交付 README",
            "",
            f"- 项目: {title}",
            f"- Run: `{run.run_id}`",
            f"- 计划版本: v{int(plan.get('version') or 0)}(hash `{str(plan.get('hash') or '')[:8]}`)",
            f"- 完成时间: {finished}",
            "",
            "## 最终结果与下载",
            "",
            "以下正式产物均可在聊天窗口的超频卡片产物入口下载,或调用产物接口 "
            f"`GET /sessions/{run.session_id}/overdrive-runs/{run.run_id}/artifacts?path=<路径>`:",
            "",
            f"- 最终报告: `{delivery.get('path')}`",
        ]
        lines.extend(f"- `{item.get('path')}`(来源:{item.get('source') or 'unknown'})" for item in official)
        if manager_summary.strip():
            lines.extend(["", "## Manager 总结", "", manager_summary.strip()])
        if failures:
            lines.extend(["", "## 限制与未完成项", ""])
            lines.extend(
                f"- {task.get('task_id')}: {task.get('error_summary') or task.get('status')}"
                for task in failures
            )
        content = "\n".join(lines).rstrip() + "\n"
        factory = get_path_factory()
        backend = get_storage_backend()
        root = overdrive_run_root(run.session_id, run.run_id) / "delivery"
        root_rel = factory.relative_to_root(root)
        await backend.ensure_dir(root_rel)
        await backend.write(f"{root_rel}/README.md", content.encode("utf-8"))
        relative = f"{relative_overdrive_run_root(run.session_id, run.run_id)}/delivery/README.md"
        return {"path": relative, "content": content}


def safe_task_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]", "-", value).strip("-") or "task"
