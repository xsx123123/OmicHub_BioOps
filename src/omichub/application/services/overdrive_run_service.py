"""Authoritative state machine and event store for overdrive v2 runs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.core.exceptions import ValidationError
from omichub.infrastructure.database.models.chat import ChatSessionModel
from omichub.infrastructure.storage import get_path_factory, get_storage_backend
from omichub.infrastructure.database.models.overdrive import (
    OverdriveCommandModel,
    OverdriveEventModel,
    OverdriveRunModel,
)

RunStatus = Literal[
    "RECEIVED",
    "RESEARCHING",
    "PLAN_DRAFTED",
    "PLAN_REVIEWING",
    "AWAITING_PLAN_CONFIRMATION",
    "SERIAL_PREFLIGHT",
    "RECRUITING",
    "RUNNING",
    "WAITING_FOR_RESULTS",
    "AWAITING_USER_INPUT",
    "AWAITING_APPROVAL",
    "PAUSED",
    "REPLANNING",
    "QUALITY_REVIEW",
    "DELIVERING",
    "COMPLETED",
    "CANCELLED",
    "TERMINATING",
    "TERMINATED",
    "FAILED",
]

PLAN_SECTIONS = (
    "用户目标与最终交付物",
    "已确认输入",
    "假设、限制与待确认事项",
    "研究与证据摘要",
    "主 Agent 串行前置工作",
    "Agent 选择与理由",
    "执行 DAG 与波次",
    "每个任务的输入、输出、工具、超时与重试",
    "风险、审批点与停止条件",
    "质量门与验收标准",
    "交付目录",
    "计划版本与变更记录",
)

EXECUTION_STATUSES = frozenset(
    {
        "SERIAL_PREFLIGHT",
        "RECRUITING",
        "RUNNING",
        "WAITING_FOR_RESULTS",
        "AWAITING_USER_INPUT",
        "AWAITING_APPROVAL",
        "PAUSED",
        "QUALITY_REVIEW",
        "DELIVERING",
        "COMPLETED",
    }
)


def canonical_plan_bytes(content: str) -> bytes:
    """Normalize line endings and trailing whitespace before hashing a frozen plan."""
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n")).rstrip() + "\n"
    return normalized.encode("utf-8")


def plan_hash(content: str) -> str:
    return "sha256:" + hashlib.sha256(canonical_plan_bytes(content)).hexdigest()


def validate_plan(
    content: str,
    tasks: list[dict[str, Any]],
    known_agent_ids: set[str],
    *,
    allow_empty_tasks: bool = False,
) -> None:
    missing = [section for section in PLAN_SECTIONS if not re.search(
        rf"^##\s+\d+\.\s+{re.escape(section)}\s*$", content, re.MULTILINE
    )]
    if missing:
        raise ValidationError(f"plan.md 缺少章节: {', '.join(missing)}")
    if not tasks and not allow_empty_tasks:
        raise ValidationError("plan.md 至少需要一个执行任务")
    if not tasks:
        return
    task_ids = {str(task.get("task_id") or "") for task in tasks}
    if "" in task_ids or len(task_ids) != len(tasks):
        raise ValidationError("执行任务 task_id 不能为空且必须唯一")
    unresolved: dict[str, set[str]] = {}
    for task in tasks:
        task_id = str(task["task_id"])
        agent_id = str(task.get("agent_id") or "")
        if agent_id not in known_agent_ids:
            raise ValidationError(f"计划引用未知 Agent: {agent_id or '<empty>'}")
        depends_on = task.get("depends_on")
        if not isinstance(depends_on, list):
            raise ValidationError(f"任务 {task_id} 的 depends_on 必须是数组")
        dependencies = {str(item) for item in depends_on}
        if task_id in dependencies:
            raise ValidationError(f"任务 {task_id} 不能依赖自身")
        unknown = dependencies - task_ids
        if unknown:
            raise ValidationError(f"任务 {task_id} 引用未知依赖: {sorted(unknown)}")
        required = {
            "accepts_inputs": task.get("accepts_inputs"),
            "produces_outputs": task.get("produces_outputs"),
            "completion_criteria": task.get("completion_criteria"),
            "tools": task.get("tools"),
            "timeout_seconds": task.get("timeout_seconds"),
            "retry": task.get("retry"),
            "requires_approval": task.get("requires_approval"),
        }
        # Empty tool/input lists and False approval are valid explicit contracts.
        absent = [key for key, value in required.items() if value is None or value == ""]
        if absent:
            raise ValidationError(f"任务 {task_id} 缺少契约字段: {', '.join(absent)}")
        if not isinstance(task.get("accepts_inputs"), list):
            raise ValidationError(f"任务 {task_id} 的 accepts_inputs 必须是数组")
        if not isinstance(task.get("produces_outputs"), list) or not task["produces_outputs"]:
            raise ValidationError(f"任务 {task_id} 至少需要一个 produces_outputs")
        completion_criteria = task.get("completion_criteria")
        if not isinstance(completion_criteria, (str, list)) or not completion_criteria:
            raise ValidationError(f"任务 {task_id} 至少需要一个 completion_criteria")
        if not isinstance(task.get("tools"), list):
            raise ValidationError(f"任务 {task_id} 的 tools 必须是数组")
        if not isinstance(task.get("requires_approval"), bool):
            raise ValidationError(f"任务 {task_id} 的 requires_approval 必须是布尔值")
        try:
            if int(task["timeout_seconds"]) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            raise ValidationError(f"任务 {task_id} 的 timeout_seconds 必须是正整数") from None
        retry = task.get("retry")
        if not isinstance(retry, dict) or not retry:
            raise ValidationError(f"任务 {task_id} 的 retry 必须是非空对象")
        unresolved[task_id] = dependencies
    while unresolved:
        ready = {task_id for task_id, dependencies in unresolved.items() if not dependencies}
        if not ready:
            raise ValidationError("执行 DAG 存在循环依赖")
        unresolved = {
            task_id: dependencies - ready
            for task_id, dependencies in unresolved.items()
            if task_id not in ready
        }


def overdrive_run_root(session_id: str, run_id: str) -> Path:
    from omichub.application.services.overdrive_runtime import overdrive_root

    safe_run_id = re.sub(r"[^a-zA-Z0-9._-]", "-", run_id)
    return overdrive_root(session_id) / safe_run_id


def relative_overdrive_run_root(session_id: str, run_id: str) -> str:
    safe_run_id = re.sub(r"[^a-zA-Z0-9._-]", "-", run_id)
    return f"output/overdrive/{session_id}/{safe_run_id}"


def _worker_display_name(payload: dict[str, Any]) -> str:
    """专家显示名：真实 agent 名优先，拼接昵称区分同 agent 多实例；缺失回退“执行助手”。"""
    agent_name = str(payload.get("agent_name") or "").strip()
    display_name = str(payload.get("display_name") or "").strip()
    if agent_name and display_name and display_name != agent_name:
        return f"{agent_name}·{display_name}"
    return agent_name or display_name or "执行助手"


def _linkify_run_artifact_paths(content: str, session_id: str, run_id: str) -> str:
    """把发言正文中引用的本 run 相对产物路径重写为可点击的下载链接。

    下载 API 已改为 run 根目录禁锢 + 归属校验，不要求 artifact_index 登记；
    已在 ``](...)`` 里的路径不重复包裹，结尾标点（含句号）截断。
    """
    root = relative_overdrive_run_root(session_id, run_id)
    if not session_id or not run_id or not content or f"{root}/" not in content:
        return content
    pattern = re.compile(rf"(?<!\]\(){re.escape(root)}/[\w./\-一-鿿]+")

    def _replace(match: re.Match[str]) -> str:
        path = match.group(0).rstrip("./")
        filename = path.rsplit("/", 1)[-1] or path
        url = (
            f"/api/v1/chat/sessions/{session_id}/overdrive-runs/{run_id}"
            f"/artifacts?path={quote(path, safe='')}"
        )
        return f"[{filename}]({url})"

    return pattern.sub(_replace, content)


class OverdriveRunService:
    """Single authoritative wrapper used by chat- and LangGraph-backed workers."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create_run(
        self,
        *,
        session_id: str,
        user_id: str,
        root_request: str,
        lead_planner_agent_id: str,
        run_id: str | None = None,
    ) -> OverdriveRunModel:
        session = await self._db.scalar(
            select(ChatSessionModel).where(
                ChatSessionModel.session_id == session_id,
                ChatSessionModel.user_id == user_id,
            )
        )
        workspace_resources = list((session.sandbox_meta or {}).get("workspace_resources") or []) if session else []
        run = OverdriveRunModel(
            run_id=run_id or f"overdrive:{uuid.uuid4().hex[:16]}",
            session_id=session_id,
            user_id=user_id,
            status="RECEIVED",
            root_request=root_request,
            lead_planner_agent_id=lead_planner_agent_id,
            research={
                source: {"status": "pending", "evidence_ids": []}
                for source in ("knowledge_base", "web", "model_knowledge")
            },
            plan={
                "version": 0,
                "status": "not_started",
                # Freeze the parent Session authorization summary at Run creation.
                # No host paths are stored here: workers receive controlled sandbox paths
                # and manifest summaries only.
                "workspace_resources": workspace_resources,
            },
            control={"action": "run"},
            event_cursor=0,
            version=0,
        )
        self._db.add(run)
        await self._db.flush()
        await self.append_event(
            run.run_id,
            "run_received",
            {"lead_planner_agent_id": lead_planner_agent_id},
            dedupe_key="run_received",
        )
        await self._write_snapshot(run)
        return run

    async def get_for_user(self, run_id: str, user_id: str, *, lock: bool = False) -> OverdriveRunModel | None:
        statement = select(OverdriveRunModel).where(
            OverdriveRunModel.run_id == run_id,
            OverdriveRunModel.user_id == user_id,
        )
        if lock:
            statement = statement.with_for_update()
        return (await self._db.execute(statement)).scalar_one_or_none()

    async def get_active_for_session(self, session_id: str, user_id: str) -> OverdriveRunModel | None:
        terminal = {"COMPLETED", "CANCELLED", "TERMINATED", "FAILED"}
        result = await self._db.execute(
            select(OverdriveRunModel)
            .where(
                OverdriveRunModel.session_id == session_id,
                OverdriveRunModel.user_id == user_id,
                OverdriveRunModel.status.not_in(terminal),
            )
            .order_by(OverdriveRunModel.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_for_session(self, session_id: str, user_id: str) -> OverdriveRunModel | None:
        """Return the latest run even when terminal, for cold history-card recovery."""
        result = await self._db.execute(
            select(OverdriveRunModel)
            .where(
                OverdriveRunModel.session_id == session_id,
                OverdriveRunModel.user_id == user_id,
            )
            .order_by(OverdriveRunModel.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def accept_branch_user_input(
        self,
        *,
        run_id: str,
        user_id: str,
        response: str,
    ) -> dict[str, Any] | None:
        """Resume the sole waiting-input branch without pausing sibling branches.

        A normal chat message is only routed automatically when exactly one branch is
        waiting. Ambiguous multi-branch waits stay untouched so the UI can ask the user
        to select the intended task explicitly.
        """
        if not response.strip():
            return None
        run = await self.get_for_user(run_id, user_id, lock=True)
        if run is None:
            raise ValidationError("超频 run 不存在或无权访问")
        waiting = [
            task for task in run.tasks if str(task.get("status") or "") == "awaiting_input"
        ]
        if len(waiting) != 1:
            return None
        task_id = str(waiting[0].get("task_id") or "")
        tasks = deepcopy(run.tasks)
        for task in tasks:
            if str(task.get("task_id") or "") != task_id:
                continue
            prior = [str(item) for item in task.get("user_responses") or [] if str(item).strip()]
            task.update(
                {
                    "status": "pending",
                    "user_responses": [*prior, response.strip()],
                    "error_summary": "",
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
        run.tasks = tasks
        # The run remains schedulable; only the affected task was waiting.
        run.status = "RUNNING"
        run.control = {
            **deepcopy(run.control or {}),
            "action": "run",
            "updated_at": datetime.now(UTC).isoformat(),
        }
        run.version += 1
        result = {"run_id": run_id, "task_id": task_id, "status": "pending"}
        await self.append_event(
            run_id,
            "branch_user_input_received",
            {**result, "response": response.strip()},
            dedupe_key=f"branch_input:{task_id}:{int(waiting[0].get('attempt') or 0)}",
        )
        await self.persist_snapshot(run)
        return result

    async def decide_branch_approval(
        self,
        *,
        run_id: str,
        user_id: str,
        command_id: str,
        approval_id: str,
        action: Literal["approve", "reject"],
        reason: str = "",
    ) -> dict[str, Any]:
        """Resolve exactly one worker tool approval without widening its tool authority."""
        existing = await self._db.get(OverdriveCommandModel, command_id)
        if existing is not None:
            if existing.run_id != run_id:
                raise ValidationError("command_id 已用于其他 run")
            return deepcopy(existing.result)
        run = await self.get_for_user(run_id, user_id, lock=True)
        if run is None:
            raise ValidationError("超频 run 不存在或无权访问")
        matched: dict[str, Any] | None = None
        for task in run.tasks:
            approval = task.get("pending_approval")
            if isinstance(approval, dict) and approval.get("approval_id") == approval_id:
                matched = approval
                break
        if matched is None or matched.get("status") != "pending":
            raise ValidationError("待审批工具调用不存在或已经处理")
        task_id = str(matched.get("task_id") or "")
        instance_id = str(matched.get("assistant_instance_id") or "")
        tasks = deepcopy(run.tasks)
        instances = deepcopy(run.assistant_instances)
        if action == "approve":
            matched.update(
                {
                    "status": "approved",
                    "approved_by": user_id,
                    "approved_at": datetime.now(UTC).isoformat(),
                }
            )
            for task in tasks:
                if str(task.get("task_id")) == task_id:
                    task.update(
                        {
                            "status": "queued",
                            "approved_tool_calls": [
                                *list(task.get("approved_tool_calls") or []),
                                {
                                    "approval_id": approval_id,
                                    "tool_name": matched.get("tool_name"),
                                    "arguments": deepcopy(matched.get("arguments") or {}),
                                },
                            ],
                            "pending_approval": matched,
                            "error_summary": "",
                        }
                    )
            for instance in instances:
                if instance.get("assistant_instance_id") == instance_id:
                    instance.update({"status": "queued", "finished_at": None})
            status = "queued"
            event_type = "branch_approval_approved"
        else:
            matched.update(
                {
                    "status": "rejected",
                    "rejected_by": user_id,
                    "rejected_at": datetime.now(UTC).isoformat(),
                    "reason": reason.strip(),
                }
            )
            for task in tasks:
                if str(task.get("task_id")) == task_id:
                    task.update(
                        {
                            "status": "failed",
                            "pending_approval": matched,
                            "error_summary": reason.strip() or "用户拒绝高风险工具调用",
                        }
                    )
            for instance in instances:
                if instance.get("assistant_instance_id") == instance_id:
                    instance.update({"status": "failed", "finished_at": datetime.now(UTC).isoformat()})
            status = "failed"
            event_type = "branch_approval_rejected"
        run.tasks = tasks
        run.assistant_instances = instances
        run.version += 1
        result = {
            "run_id": run_id,
            "approval_id": approval_id,
            "task_id": task_id,
            "assistant_instance_id": instance_id,
            "status": status,
            "action": action,
        }
        self._db.add(
            OverdriveCommandModel(
                command_id=command_id,
                run_id=run_id,
                command_type=f"branch_approval_{action}",
                payload={"approval_id": approval_id, "reason": reason},
                result=result,
            )
        )
        await self.append_event(
            run_id,
            event_type,
            {**result, "approval": deepcopy(matched)},
            dedupe_key=f"command:{command_id}",
        )
        await self.persist_snapshot(run)
        return result

    async def transition(self, run: OverdriveRunModel, status: RunStatus) -> None:
        run.status = status
        run.version += 1
        await self.append_event(
            run.run_id,
            "run_status_changed",
            {"status": status, "version": run.version},
            dedupe_key=f"status:{run.version}:{status}",
        )
        await self._write_snapshot(run)

    async def recover_missing_input(
        self,
        *,
        run_id: str,
        user_id: str,
        missing_inputs: list[str],
        reason: str,
    ) -> dict[str, Any]:
        """Stop an invalid execution and wait for a verifiable input contract."""
        run = await self.get_for_user(run_id, user_id, lock=True)
        if run is None:
            raise ValidationError("超频 run 不存在或无权访问")
        if run.status in {"COMPLETED", "CANCELLED", "TERMINATED", "FAILED"}:
            return {"status": "terminal", "run_id": run_id, "run_status": run.status}

        now = datetime.now(UTC).isoformat()
        tasks = deepcopy(run.tasks or [])
        for task in tasks:
            if str(task.get("status") or "") not in {"cancelled", "terminated"}:
                task["status"] = "awaiting_input"
                task["updated_at"] = now
        run.tasks = tasks
        plan = deepcopy(run.plan or {})
        plan.update(
            {
                "status": "needs_input",
                "approved_by": None,
                "approved_at": None,
                "input_contract": {
                    "status": "missing",
                    "missing_inputs": list(dict.fromkeys(missing_inputs)),
                },
            }
        )
        run.plan = plan
        run.control = {
            **deepcopy(run.control or {}),
            "action": "awaiting_input",
            "reason": reason,
            "missing_inputs": list(dict.fromkeys(missing_inputs)),
        }
        await self.transition(run, "AWAITING_USER_INPUT")
        await self.append_event(
            run_id,
            "input_contract_missing",
            {
                "reason": reason,
                "missing_inputs": list(dict.fromkeys(missing_inputs)),
                "message": "请上传或引用本轮任务所需的真实输入后再继续。",
            },
            dedupe_key="input_contract_missing:recovery",
        )
        await self.persist_snapshot(run)
        return {
            "status": "awaiting_input",
            "run_id": run_id,
            "run_status": run.status,
            "missing_inputs": list(dict.fromkeys(missing_inputs)),
        }

    async def save_research(
        self,
        run: OverdriveRunModel,
        evidence: list[dict[str, Any]],
        statuses: dict[str, str],
        *,
        source_details: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        factory = get_path_factory()
        backend = get_storage_backend()
        root = overdrive_run_root(run.session_id, run.run_id)
        await _async_atomic_write_json(
            backend,
            factory,
            f"{factory.relative_to_root(root)}/evidence.json",
            {"sources": deepcopy(source_details or {}), "evidence": evidence},
        )
        grouped: dict[str, list[str]] = {key: [] for key in run.research}
        for item in evidence:
            grouped.setdefault(str(item.get("source_type") or ""), []).append(
                str(item.get("evidence_id") or "")
            )
        run.research = {}
        for source in ("knowledge_base", "web", "model_knowledge"):
            details = deepcopy((source_details or {}).get(source) or {})
            details.pop("items", None)
            details.update(
                status=statuses.get(source, "failed"),
                evidence_ids=grouped.get(source, []),
            )
            run.research[source] = details
        await self.append_event(run.run_id, "research_completed", deepcopy(run.research))
        await self._write_snapshot(run)

    async def write_plan_draft(self, run: OverdriveRunModel, content: str) -> dict[str, Any]:
        """Publish reviewable plan.md before emitting plan_ready or asking for confirmation."""
        version = int((run.plan or {}).get("version") or 0) + 1
        relative_root = relative_overdrive_run_root(run.session_id, run.run_id)
        path = overdrive_run_root(run.session_id, run.run_id) / "plan.md"
        _atomic_write(path, canonical_plan_bytes(content).decode("utf-8"))
        current = deepcopy(run.plan or {})
        current.update(
            {
                "path": f"{relative_root}/plan.md",
                "draft_version": version,
                "status": "reviewing",
            }
        )
        run.plan = current
        await self._write_snapshot(run)
        return {"path": current["path"], "version": version}

    async def freeze_plan(
        self,
        run: OverdriveRunModel,
        *,
        content: str,
        tasks: list[dict[str, Any]],
        known_agent_ids: set[str],
        summary: dict[str, Any],
        allow_empty_tasks: bool = False,
    ) -> dict[str, Any]:
        validate_plan(content, tasks, known_agent_ids, allow_empty_tasks=allow_empty_tasks)
        version = int((run.plan or {}).get("version") or 0) + 1
        revision_count = int((run.plan or {}).get("revision_count") or 0)
        digest = plan_hash(content)
        root = overdrive_run_root(run.session_id, run.run_id)
        current_path = root / "plan.md"
        version_path = root / f"plan.v{version}.md"
        normalized = canonical_plan_bytes(content).decode("utf-8")
        _atomic_write(current_path, normalized)
        _atomic_write(version_path, normalized)
        relative_root = relative_overdrive_run_root(run.session_id, run.run_id)
        run.tasks = deepcopy(tasks)
        run.plan = {
            "path": f"{relative_root}/plan.md",
            "version_path": f"{relative_root}/plan.v{version}.md",
            "version": version,
            "revision_count": revision_count,
            "hash": digest,
            "status": "awaiting_confirmation",
            "approved_by": None,
            "approved_at": None,
            "summary": deepcopy(summary),
        }
        run.status = "AWAITING_PLAN_CONFIRMATION"
        run.version += 1
        await self.append_event(
            run.run_id,
            "plan_confirmation_requested",
            {**deepcopy(run.plan), "actions": ["approve", "revise", "cancel"]},
            dedupe_key=f"plan_confirmation:{version}:{digest}",
        )
        await self._write_snapshot(run)
        return deepcopy(run.plan)

    async def decide_plan(
        self,
        *,
        run_id: str,
        user_id: str,
        command_id: str,
        action: Literal["approve", "revise", "cancel"],
        plan_version: int,
        plan_digest: str,
        feedback: str = "",
        max_revisions: int = 3,
    ) -> dict[str, Any]:
        existing = await self._db.get(OverdriveCommandModel, command_id)
        if existing is not None:
            if existing.run_id != run_id:
                raise ValidationError("command_id 已用于其他 run")
            return deepcopy(existing.result)
        run = await self.get_for_user(run_id, user_id, lock=True)
        if run is None:
            raise ValidationError("超频 run 不存在或无权访问")
        current_plan = deepcopy(run.plan or {})
        if run.status != "AWAITING_PLAN_CONFIRMATION":
            raise ValidationError(f"当前状态 {run.status} 不接受计划确认")
        if int(current_plan.get("version") or 0) != plan_version:
            raise ValidationError("计划版本已变化，请刷新后重新确认")
        if str(current_plan.get("hash") or "") != plan_digest:
            raise ValidationError("计划 hash 不匹配，请勿确认已变化的快照")
        await self._assert_plan_file_matches(run)
        result: dict[str, Any]
        delivery: dict[str, Any] | None = None
        if action == "approve":
            current_plan.update(
                {
                    "status": "approved",
                    "approved_by": user_id,
                    "approved_at": datetime.now(UTC).isoformat(),
                }
            )
            run.plan = current_plan
            planning_only = bool((current_plan.get("summary") or {}).get("planning_only"))
            run.status = "COMPLETED" if planning_only else "SERIAL_PREFLIGHT"
            if planning_only:
                run.finished_at = datetime.now(UTC)
                delivery = await self._write_planning_only_delivery(run, current_plan)
                run.artifact_index = [
                    *(run.artifact_index or []),
                    {
                        "path": delivery["path"],
                        "kind": "delivery",
                        "source": "manager",
                        "status": "succeeded",
                    },
                ]
            result = {"status": run.status, "plan": deepcopy(current_plan)}
            if delivery is not None:
                result["delivery"] = {"path": delivery["path"]}
            event_type = "run_completed" if planning_only else "plan_approved"
        elif action == "revise":
            revision_count = int(current_plan.get("revision_count") or 0)
            if revision_count >= max_revisions:
                raise ValidationError("计划修改已达到上限，只能确认当前版本或取消")
            if not feedback.strip():
                raise ValidationError("提出修改时必须填写修改意见")
            current_plan.update(
                {
                    "status": "revision_requested",
                    "revision_feedback": feedback,
                    "revision_count": revision_count + 1,
                }
            )
            run.plan = current_plan
            run.status = "REPLANNING"
            result = {"status": run.status, "plan": deepcopy(current_plan)}
            event_type = "plan_revision_requested"
        else:
            current_plan["status"] = "cancelled"
            run.plan = current_plan
            run.status = "CANCELLED"
            run.finished_at = datetime.now(UTC)
            result = {"status": run.status, "plan": deepcopy(current_plan)}
            event_type = "run_cancelled"
        run.version += 1
        self._db.add(
            OverdriveCommandModel(
                command_id=command_id,
                run_id=run_id,
                command_type=f"plan_{action}",
                payload={
                    "plan_version": plan_version,
                    "plan_hash": plan_digest,
                    "feedback": feedback,
                },
                result=result,
            )
        )
        event_payload: dict[str, Any] = {
            "plan_version": plan_version,
            "plan_hash": plan_digest,
            "feedback": feedback,
        }
        if delivery is not None:
            event_payload["planning_only"] = True
            event_payload["delivery_path"] = delivery["path"]
            event_payload["artifacts"] = [
                {
                    "path": delivery["path"],
                    "kind": "delivery",
                    "status": "succeeded",
                    "source": "manager",
                }
            ]
        await self.append_event(
            run_id,
            event_type,
            event_payload,
            dedupe_key=f"command:{command_id}",
        )
        if delivery is not None:
            await self.append_event(
                run_id,
                "manager_delivery_ready",
                {
                    "content": self._planning_only_delivery_speech(run, current_plan, delivery),
                    "delivery_path": delivery["path"],
                },
                dedupe_key=f"command:{command_id}:delivery",
            )
        await self._write_snapshot(run)
        return result

    async def assert_execution_allowed(self, run: OverdriveRunModel) -> None:
        if run.status not in EXECUTION_STATUSES:
            raise ValidationError("计划尚未确认，禁止提交执行助手")
        plan = run.plan or {}
        if plan.get("status") != "approved" or not plan.get("approved_by"):
            raise ValidationError("缺少真实用户的计划确认记录，禁止执行")
        await self._assert_plan_file_matches(run)

    async def apply_control(
        self,
        *,
        run_id: str,
        user_id: str,
        command_id: str,
        action: Literal["pause", "resume", "terminate"],
    ) -> dict[str, Any]:
        """Persist a run command so web and worker processes observe the same state."""
        existing = await self._db.get(OverdriveCommandModel, command_id)
        if existing is not None:
            if existing.run_id != run_id:
                raise ValidationError("command_id 已用于其他 run")
            return deepcopy(existing.result)
        run = await self.get_for_user(run_id, user_id, lock=True)
        if run is None:
            raise ValidationError("超频 run 不存在或无权访问")
        terminal = {"COMPLETED", "CANCELLED", "TERMINATED", "FAILED"}
        if run.status in terminal:
            raise ValidationError(f"终态 run {run.status} 不接受控制命令")
        if run.status not in EXECUTION_STATUSES:
            raise ValidationError("计划尚未进入执行阶段，不能暂停、恢复或终止；请在计划卡中确认或取消")
        if action == "pause":
            run.status = "PAUSED"
            control_action = "pause"
        elif action == "resume":
            if run.status != "PAUSED":
                raise ValidationError("只有已暂停的 run 可以恢复")
            run.status = "RUNNING"
            control_action = "run"
        else:
            has_started_tasks = any(
                str(task.get("status") or "pending") not in {"pending", "queued"}
                for task in run.tasks or []
            )
            if run.status == "SERIAL_PREFLIGHT" and not has_started_tasks:
                run.status = "TERMINATED"
                run.finished_at = datetime.now(UTC)
                control_action = "terminated"
            else:
                run.status = "TERMINATING"
                control_action = "terminate"
        run.control = {
            "action": control_action,
            "command_id": command_id,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        run.version += 1
        result = {"run_id": run_id, "status": run.status, "control": deepcopy(run.control)}
        self._db.add(
            OverdriveCommandModel(
                command_id=command_id,
                run_id=run_id,
                command_type=f"control_{action}",
                payload={"action": action},
                result=result,
            )
        )
        event_type = (
            "run_terminated"
            if action == "terminate" and run.status == "TERMINATED"
            else f"run_{action}_requested"
        )
        await self.append_event(
            run_id,
            event_type,
            result,
            dedupe_key=f"command:{command_id}",
        )
        await self._write_snapshot(run)
        return result

    async def persist_snapshot(self, run: OverdriveRunModel) -> None:
        """Flush an authoritative mutation and refresh its readable file projection."""
        await self._write_snapshot(run)

    async def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        dedupe_key: str | None = None,
    ) -> OverdriveEventModel:
        if dedupe_key:
            duplicate = (
                await self._db.execute(
                    select(OverdriveEventModel).where(
                        OverdriveEventModel.run_id == run_id,
                        OverdriveEventModel.dedupe_key == dedupe_key,
                    )
                )
            ).scalar_one_or_none()
            if duplicate is not None:
                return duplicate
        run = (
            await self._db.execute(
                select(OverdriveRunModel)
                .where(OverdriveRunModel.run_id == run_id)
                .with_for_update()
            )
        ).scalar_one()
        run.event_cursor += 1
        event = OverdriveEventModel(
            run_id=run_id,
            sequence=run.event_cursor,
            event_type=event_type,
            payload=deepcopy(payload),
            dedupe_key=dedupe_key,
        )
        self._db.add(event)
        await self._db.flush()
        await self._append_event_projection(run, event)
        return event

    async def events_after(
        self, run_id: str, user_id: str, after_sequence: int = 0, limit: int = 500
    ) -> list[dict[str, Any]]:
        authorized_run = await self.get_for_user(run_id, user_id)
        if authorized_run is None:
            raise ValidationError("超频 run 不存在或无权访问")
        result = await self._db.execute(
            select(OverdriveEventModel)
            .where(
                OverdriveEventModel.run_id == run_id,
                OverdriveEventModel.sequence > max(0, after_sequence),
            )
            .order_by(OverdriveEventModel.sequence)
            .limit(max(1, min(limit, 1000)))
        )
        return [
            {
                "event_id": str(event.event_id),
                "run_id": event.run_id,
                "session_id": authorized_run.session_id,
                "sequence": event.sequence,
                "event_type": event.event_type,
                "payload": event.payload,
                "occurred_at": event.occurred_at.isoformat(),
            }
            for event in result.scalars()
        ]

    @staticmethod
    def project_event(event: dict[str, Any]) -> dict[str, Any] | None:
        """Project durable domain events into the existing chat SSE vocabulary."""
        event_type = str(event.get("event_type") or "")
        payload = deepcopy(event.get("payload") or {})
        common = {
            "run_id": event.get("run_id"),
            "session_id": event.get("session_id"),
            "sequence": event.get("sequence"),
        }
        if event_type == "research_started":
            source_labels = {
                "knowledge_base": "平台知识库",
                "web": "网络检索",
                "model_knowledge": "模型知识归纳",
            }
            queries = [str(item) for item in payload.get("queries") or []]
            return {
                "type": "overdrive_progress",
                **common,
                "phase": "researching",
                "label": "规划 Agent 正在检索证据",
                "completed": 0,
                "total": len(payload.get("sources") or []),
                "activities": [
                    {
                        "id": source,
                        "label": source_labels.get(source, source),
                        "kind": "mcp" if source == "knowledge_base" else ("model" if source == "model_knowledge" else "search"),
                        "status": "running",
                        "queries": queries if source == "web" else [],
                    }
                    for source in payload.get("sources") or []
                ],
            }
        if event_type == "research_completed":
            source_labels = {
                "knowledge_base": "平台知识库",
                "web": "网络检索",
                "model_knowledge": "模型知识归纳",
            }
            activities = []
            for source, label in source_labels.items():
                detail = payload.get(source) if isinstance(payload.get(source), dict) else {}
                activities.append(
                    {
                        "id": source,
                        "label": label,
                        "kind": "mcp" if source == "knowledge_base" else ("model" if source == "model_knowledge" else "search"),
                        "status": detail.get("status") or "failed",
                        "queries": detail.get("queries") or ([detail.get("query")] if detail.get("query") else []),
                        "accepted": detail.get("accepted_count", len(detail.get("evidence_ids") or [])),
                        "rejected": detail.get("rejected_count", 0),
                        "duration_ms": detail.get("duration_ms", 0),
                        "error": detail.get("error") or "; ".join(detail.get("errors") or []),
                    }
                )
            return {
                "type": "overdrive_progress",
                **common,
                "phase": "researching",
                "label": "证据检索完成，正在生成研究计划",
                "completed": sum(item["status"] in {"succeeded", "completed"} for item in activities),
                "total": len(activities),
                "activities": activities,
            }
        if event_type == "plan_confirmation_requested":
            return {
                "type": "ask_request",
                "kind": "plan_confirmation",
                **common,
                "message_id": f"plan-confirmation-{event.get('run_id')}",
                "run_id": event.get("run_id"),
                "plan_path": payload.get("path"),
                "plan_version": payload.get("version"),
                "plan_hash": payload.get("hash"),
                "summary": payload.get("summary") or {},
                "actions": payload.get("actions") or ["approve", "revise", "cancel"],
            }
        if event_type in {"branch_approval_approved", "branch_approval_rejected"}:
            approval = payload.get("approval") if isinstance(payload.get("approval"), dict) else {}
            return {
                "type": "overdrive_approval_request",
                **common,
                "message_id": f"overdrive-approval-{event.get('run_id')}-{event.get('sequence')}",
                "approval": approval,
            }
        if event_type in {"assistant_result_ready", "manager_review_ready"}:
            is_review = event_type == "manager_review_ready"
            if is_review and str(payload.get("decision") or "") in {"ask_user", "await_approval"}:
                # The wait was already surfaced as an interactive ask/approval card
                # by the preceding assistant_result_ready projection; a manager
                # speech bubble here would only duplicate (and historically
                # mislabel) that state.
                return None
            result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            packet = result.get("packet") if isinstance(result.get("packet"), dict) else {}
            if not is_review and str(result.get("status") or "") == "awaiting_input":
                questions = packet.get("questions") if isinstance(packet.get("questions"), list) else []
                return {
                    "type": "ask_request",
                    "kind": "questions",
                    **common,
                    "message_id": f"overdrive-ask-{event.get('run_id')}-{event.get('sequence')}",
                    "questions": questions or [{"question": "请补充该分支所需信息。", "options": []}],
                }
            if not is_review and str(result.get("status") or "") == "approval_pending":
                approval = payload.get("approval") if isinstance(payload.get("approval"), dict) else {}
                return {
                    "type": "overdrive_approval_request",
                    **common,
                    "message_id": f"overdrive-approval-{event.get('run_id')}-{event.get('sequence')}",
                    "approval": approval,
                }
            content = (
                str(payload.get("basis") or "Manager 已完成本条结果验收。")
                if is_review
                else str(result.get("answer") or result.get("error") or "助手任务已回流。")
            )
            # 专家引用的产物相对路径重写为可点击下载链接（下载 API 负责根目录禁锢与归属校验）
            content = _linkify_run_artifact_paths(
                content,
                str(event.get("session_id") or ""),
                str(event.get("run_id") or ""),
            )
            sender = (
                {"agent_id": "agent-orchestrator", "name": "超频 Manager", "role": "manager"}
                if is_review
                else {
                    "agent_id": payload.get("agent_id") or payload.get("assistant_instance_id"),
                    "name": _worker_display_name(payload),
                    "role": "worker",
                    # instance id 放入额外字段，避免真实 agent_id 顶替后丢失
                    "instance_id": payload.get("assistant_instance_id"),
                }
            )
            return {
                "type": "room_speech",
                "content": content,
                **common,
                "message_id": (
                    f"overdrive-event-{event.get('run_id')}-{event.get('sequence')}"
                ),
                "sender": sender,
                "task_id": payload.get("task_id"),
                "review": payload if is_review else None,
                "result": result if not is_review else None,
            }
        if event_type == "manager_delivery_ready":
            return {
                "type": "room_speech",
                "content": str(payload.get("content") or "本轮协作交付已就绪。"),
                **common,
                "message_id": (
                    f"overdrive-event-{event.get('run_id')}-{event.get('sequence')}"
                ),
                "sender": {
                    "agent_id": "agent-orchestrator",
                    "name": "超频 Manager",
                    "role": "manager",
                },
                "delivery_path": payload.get("delivery_path"),
            }
        if event_type == "assistant_tool_call":
            # 专家工具调用投影为进度标签，让执行过程对用户可见；
            # assistant_heartbeat / assistant_retrying 噪音高，保持不投影。
            tool_name = str(payload.get("tool_name") or "工具")
            return {
                "type": "overdrive_progress",
                **common,
                "phase": "worker_running",
                "label": f"{_worker_display_name(payload)} 正在调用 {tool_name}",
            }
        progress_events = {
            "research_completed": ("researching", "三路研究已完成"),
            "plan_ready": ("plan_ready", "研究计划已生成，等待确认"),
            "plan_approved": ("serial_preflight", "计划已确认，等待分析 Worker 接管"),
            "replanning_started": ("replanning", "规划 Agent 正在生成修改后的计划"),
            "replanning_failed": ("failed", "修改后的计划未能生成"),
            "preflight_completed": ("serial_preflight", "Manager 串行前置已完成"),
            "manager_task_started": ("manager_ready", "Manager 正在维护证据账本"),
            "manager_task_completed": ("manager_ready", "Manager 已完成整合框架"),
            "manager_review_requested": ("peer_reviewing", "Manager 正在复核助手结果"),
            "assistant_recruited": ("recruiting", "已招募执行助手"),
            "assistant_started": ("worker_running", "执行助手正在工作"),
            "run_completed": ("completed", "超频协作已完成"),
            "run_failed": ("failed", "超频协作未通过质量门"),
            "run_cancelled": ("terminated", "用户已取消本轮超频协作，计划不会执行"),
            "run_terminated": ("terminated", "超频协作已终止"),
        }
        if event_type in progress_events:
            phase, label = progress_events[event_type]
            if event_type == "run_completed" and payload.get("planning_only"):
                label = "方案已生成并完成交付"
            return {
                "type": "overdrive_progress",
                **common,
                "phase": phase,
                "label": label,
                **payload,
            }
        return None

    def snapshot(self, run: OverdriveRunModel) -> dict[str, Any]:
        return {
            "version": 2,
            "run_id": run.run_id,
            "session_id": run.session_id,
            "status": run.status,
            "root_request": run.root_request,
            "lead_planner_agent_id": run.lead_planner_agent_id,
            "research": deepcopy(run.research),
            "plan": deepcopy(run.plan),
            "manager_tasks": deepcopy(run.manager_tasks),
            "tasks": deepcopy(run.tasks),
            "assistant_instances": deepcopy(run.assistant_instances),
            "manager_reviews": deepcopy(run.manager_reviews),
            "artifact_index": deepcopy(run.artifact_index),
            "control": deepcopy(run.control),
            "event_cursor": run.event_cursor,
            "state_version": run.version,
        }

    async def _assert_plan_file_matches(self, run: OverdriveRunModel) -> None:
        plan = run.plan or {}
        version = int(plan.get("version") or 0)
        version_path = overdrive_run_root(run.session_id, run.run_id) / f"plan.v{version}.md"
        factory = get_path_factory()
        backend = get_storage_backend()
        rel_path = factory.relative_to_root(version_path)
        if not await backend.exists(rel_path):
            raise ValidationError("已冻结的计划快照不存在")
        content = (await backend.read(rel_path)).decode("utf-8")
        actual = plan_hash(content)
        if actual != plan.get("hash"):
            raise ValidationError("已冻结计划内容与确认 hash 不一致")

    async def _write_planning_only_delivery(
        self, run: OverdriveRunModel, plan: dict[str, Any]
    ) -> dict[str, Any]:
        """为 planning_only run 生成项目 README,作为可下载交付物。

        planning_only run 不经过执行期和 DeliveryAssembler,确认计划即完成;
        这里补齐“最终交付在哪、从哪里下载”的说明,沿用工作台 output/README
        索引的约定。
        """
        summary = plan.get("summary") if isinstance(plan.get("summary"), dict) else {}
        title = str(summary.get("title") or "超频协作执行方案")
        version = int(plan.get("version") or 0)
        digest = str(plan.get("hash") or "")
        plan_path = str(plan.get("path") or "")
        version_path = str(plan.get("version_path") or "")
        finished_at = datetime.now(UTC).isoformat()
        relative_root = relative_overdrive_run_root(run.session_id, run.run_id)
        readme_relative = f"{relative_root}/delivery/README.md"
        lines = [
            "# 项目交付 README",
            "",
            f"- 项目: {title}",
            f"- Run: `{run.run_id}`",
            f"- 计划版本: v{version}(hash `{digest[:8]}`)",
            f"- 完成时间: {finished_at}",
            "",
            "## 本次交付",
            "",
            "本轮为方案规划型协作(不执行分析任务),最终交付为执行方案文档:",
            "",
            f"- 方案全文: `{plan_path}`",
            f"- 版本快照: `{version_path}`",
            f"- 本 README: `{readme_relative}`",
            "",
            "## 下载方式",
            "",
            "- 聊天窗口内超频卡片的产物入口直接下载;",
            f"- 或调用产物接口 `GET /sessions/{run.session_id}/overdrive-runs/{run.run_id}/artifacts?path=<上列路径>`。",
            "",
            "## 后续步骤",
            "",
            "- 如需按本方案正式执行分析,回复“按方案开始执行”,将为你创建执行任务。",
        ]
        content = "\n".join(lines) + "\n"
        factory = get_path_factory()
        backend = get_storage_backend()
        readme_path = overdrive_run_root(run.session_id, run.run_id) / "delivery" / "README.md"
        await _async_atomic_write_text(
            backend, factory, factory.relative_to_root(readme_path), content
        )
        return {"path": readme_relative, "content": content}

    @staticmethod
    def _planning_only_delivery_speech(
        run: OverdriveRunModel, plan: dict[str, Any], delivery: dict[str, Any]
    ) -> str:
        """Manager 对规划型结果的完整交付说明:方案要点 + 交付位置 + 下一步引导。

        不只是告知文件路径,要让用户不看 plan.md 也知道方案安排了什么、
        结果在哪里下载,以及接下来是否上传数据进入正式分析。
        """
        summary = plan.get("summary") if isinstance(plan.get("summary"), dict) else {}
        title = str(summary.get("title") or "超频协作执行方案")
        version = int(plan.get("version") or 0)
        agents = [item for item in summary.get("agents") or [] if isinstance(item, dict)]
        agent_names = "、".join(
            str(item.get("name") or item.get("agent_id") or "") for item in agents if item
        )
        wave_count = int(summary.get("wave_count") or 0)
        overview = str(summary.get("summary") or "").strip()
        lines = [
            f"本轮为方案规划型协作,我已完成《{title}》(计划 v{version}),未启动分析执行任务。",
            "",
        ]
        if overview:
            lines += ["**方案概览**", "", overview, ""]
        lines += ["**协作安排**", ""]
        if agent_names:
            lines.append(f"- 参与专家:{agent_names}")
        if wave_count:
            lines.append(
                f"- 执行波次:{wave_count} 波(无依赖的任务同波并行,有上下游关系的按依赖串行)"
            )
        lines += [
            "",
            "**交付物与下载**",
            "",
            "- 完整方案: plan.md(超频协作卡片的产物入口可直接下载)",
            f"- 项目 README: `{delivery['path']}`,包含交付清单与下载方式",
            "",
            "**下一步**",
            "",
            "- 数据已准备好:把 FASTQ / BAM / VCF 等输入文件上传到本会话工作区,"
            "告诉我“按方案开始执行”,我会按方案启动正式分析;",
            "- 暂时没有数据:可以先让我基于示例或公开数据集把流程走通,或继续调整方案细节。",
        ]
        return "\n".join(lines)

    async def _write_snapshot(self, run: OverdriveRunModel) -> None:
        await self._db.flush()
        factory = get_path_factory()
        backend = get_storage_backend()
        root = overdrive_run_root(run.session_id, run.run_id)
        root_rel = factory.relative_to_root(root)
        await _async_atomic_write_json(
            backend, factory, f"{root_rel}/manifest.json", self.snapshot(run)
        )
        await _async_atomic_write_json(
            backend, factory, f"{root_rel}/control.json", deepcopy(run.control)
        )

    async def _append_event_projection(
        self, run: OverdriveRunModel, event: OverdriveEventModel
    ) -> None:
        factory = get_path_factory()
        backend = get_storage_backend()
        path = overdrive_run_root(run.session_id, run.run_id) / "events.jsonl"
        rel_path = factory.relative_to_root(path)
        record = {
            "event_id": str(event.event_id),
            "run_id": event.run_id,
            "sequence": event.sequence,
            "event_type": event.event_type,
            "payload": event.payload,
            "occurred_at": datetime.now(UTC).isoformat(),
        }
        line = (json.dumps(record, ensure_ascii=False, default=str) + "\n").encode("utf-8")
        existing = b""
        if await backend.exists(rel_path):
            existing = await backend.read(rel_path)
        await backend.write(rel_path, existing + line)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")


async def _async_atomic_write_text(
    backend, factory, rel_path: str, content: str
) -> None:
    """异步原子写入文本（先写临时对象再重命名/覆盖）。"""
    await backend.ensure_dir(rel_path.rsplit("/", 1)[0] if "/" in rel_path else "")
    temp_rel = f"{rel_path}.tmp.{os.getpid()}"
    await backend.write(temp_rel, content.encode("utf-8"))
    await backend.move(temp_rel, rel_path)


async def _async_atomic_write_json(
    backend, factory, rel_path: str, payload: dict[str, Any]
) -> None:
    await _async_atomic_write_text(
        backend, factory, rel_path,
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
    )
