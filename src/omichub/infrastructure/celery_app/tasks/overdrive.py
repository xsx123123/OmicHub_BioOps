"""Durable, one-task-per-job execution for overdrive v2."""

from __future__ import annotations

import asyncio
import json
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from celery import shared_task
from omichub.infrastructure.storage import get_path_factory, get_storage_backend
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


@shared_task(name="omichub.infrastructure.celery_app.tasks.overdrive.advance_run")
def advance_run(run_id: str) -> dict[str, object]:
    """Advance preflight/DAG scheduling without holding a chat SSE request open."""
    return asyncio.run(_advance_run(run_id))


def _overdrive_workspace_context(run: Any, task: dict[str, Any]) -> str:
    """Provide workers with the authoritative paths for this durable Overdrive run."""
    from omichub.application.services.overdrive_run_service import relative_overdrive_run_root

    root = relative_overdrive_run_root(str(run.session_id), str(run.run_id))
    plan = dict(run.plan or {})
    dependencies = [str(item) for item in task.get("depends_on") or [] if str(item).strip()]
    registered_paths = [
        str(item.get("path") or "").strip()
        for item in run.artifact_index or []
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    ]
    workspace_resources = [
        item for item in plan.get("workspace_resources") or [] if isinstance(item, dict)
    ]
    upstream_results = [f"{root}/tasks/{task_id}/result.md" for task_id in dependencies]
    lines = [
        "## 当前 Overdrive Run 的权威工作区上下文",
        f"- Run ID：`{run.run_id}`",
        f"- 共享根目录：`{root}/`",
        f"- 冻结计划：`{plan.get('version_path') or plan.get('path') or f'{root}/plan.md'}`",
    ]
    if upstream_results:
        lines.extend(["- 直接上游任务结果：", *[f"  - `{path}`" for path in upstream_results]])
    if registered_paths:
        lines.extend([
            "- 已登记产物：",
            *[f"  - `{path}`" for path in registered_paths[:40]],
        ])
    if workspace_resources:
        lines.append("- 父 Session 只读输入引用：")
        for resource in workspace_resources:
            ref = str(resource.get("resource_ref") or "")
            sandbox_path = str(resource.get("sandbox_path") or "")
            if not ref or not sandbox_path:
                continue
            manifest = resource.get("manifest_summary") or {}
            suffix = ""
            if resource.get("resource_type") == "directory":
                suffix = (
                    f"（目录，约 {manifest.get('file_count', 0)} 个文件，"
                    f"{manifest.get('total_size_bytes', 0)} bytes；先分页列举）"
                )
            lines.append(f"  - `{ref}` → `{sandbox_path}` {suffix}")
    if str(task.get("task_id") or "") == "independent-qc":
        lines.extend(
            [
                "- 本任务是独立 QC：使用 `workspace_read` / `workspace_list` 在上述共享工作区核验计划和产物。",
                "- 不要调用 `task_result_summary` 或 `task_file_preview`：它们查询的是独立 Pipeline 任务系统，"
                "不能代表当前 Overdrive Run，也不能据其“任务不存在”判定本任务失败。",
            ]
        )
    return "\n".join(lines)


@shared_task(name="omichub.infrastructure.celery_app.tasks.overdrive.replan_run")
def replan_run(run_id: str) -> dict[str, object]:
    """Regenerate a revised immutable plan away from the request/SSE lifetime."""
    return asyncio.run(_replan_run(run_id))


async def _replan_run(run_id: str) -> dict[str, object]:
    """Use the same ChatService planning path, protected by a durable lease.

    A plan revision is deliberately not dependent on a second user chat message.
    The lease keeps a simultaneous normal chat turn from racing the planner and all
    resulting plan-confirmation events remain replayable from the run ledger.
    """
    from omichub.application.services.agent_service import AgentService
    from omichub.application.services.chat_service import ChatService
    from omichub.application.services.overdrive_run_service import OverdriveRunService
    from omichub.infrastructure.database.models.overdrive import OverdriveRunModel
    from omichub.infrastructure.database.session import get_session_factory

    lock_id = str(uuid.uuid4())
    user_id = ""
    session_id = ""
    feedback = ""
    async with get_session_factory()() as db:
        run = (
            await db.execute(
                select(OverdriveRunModel)
                .where(OverdriveRunModel.run_id == run_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if run is None:
            return {"status": "missing", "run_id": run_id}
        if run.status != "REPLANNING":
            return {"status": "duplicate", "run_id": run_id}
        control = deepcopy(run.control or {})
        if control.get("replan_lock"):
            return {"status": "in_progress", "run_id": run_id}
        control["replan_lock"] = lock_id
        run.control = control
        user_id = str(run.user_id)
        session_id = str(run.session_id)
        feedback = str((run.plan or {}).get("revision_feedback") or "")
        runs = OverdriveRunService(db)
        await runs.append_event(
            run_id,
            "replanning_started",
            {"plan_version": (run.plan or {}).get("version")},
            dedupe_key=f"replanning_started:{lock_id}",
        )
        await runs.persist_snapshot(run)
        await db.commit()

    try:
        async with get_session_factory()() as db:
            run = await OverdriveRunService(db).get_for_user(run_id, user_id)
            if run is None:
                return {"status": "missing", "run_id": run_id}
            manager_ctx = await AgentService(db).assemble_context(
                str(run.lead_planner_agent_id or "agent-general"), user_id=user_id
            )
            if manager_ctx is None:
                raise RuntimeError("找不到规划 Agent 上下文")
            chat = ChatService(db)
            async for _chunk in chat._run_overdrive_turn(
                user_id=user_id,
                session_id=session_id,
                user_content=feedback or "请根据已提交修改意见重新生成计划。",
                manager_ctx=manager_ctx,
                replan_lock_id=lock_id,
            ):
                # The durable run event ledger, rather than this detached task's SSE,
                # is the user-visible transport for progress and the new plan card.
                pass
            current = await OverdriveRunService(db).get_for_user(run_id, user_id, lock=True)
            if current is not None:
                control = deepcopy(current.control or {})
                if control.get("replan_lock") == lock_id:
                    control.pop("replan_lock", None)
                    current.control = control
                    if current.status == "REPLANNING":
                        current.status = "FAILED"
                        current.finished_at = datetime.now(UTC)
                        await OverdriveRunService(db).append_event(
                            run_id,
                            "replanning_failed",
                            {"error": "规划任务结束但没有生成可确认的新计划"},
                            dedupe_key=f"replanning_failed:no_plan:{lock_id}",
                        )
                    await OverdriveRunService(db).persist_snapshot(current)
            await db.commit()
        return {"status": "replanned", "run_id": run_id}
    except Exception as exc:  # noqa: BLE001
        async with get_session_factory()() as db:
            run = (
                await db.execute(
                    select(OverdriveRunModel)
                    .where(OverdriveRunModel.run_id == run_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if run is not None:
                control = deepcopy(run.control or {})
                if control.get("replan_lock") == lock_id:
                    control.pop("replan_lock", None)
                    run.control = control
                    run.status = "FAILED"
                    run.finished_at = datetime.now(UTC)
                    runs = OverdriveRunService(db)
                    await runs.append_event(
                        run_id,
                        "replanning_failed",
                        {"error": str(exc)[:500]},
                        dedupe_key=f"replanning_failed:{lock_id}",
                    )
                    await runs.persist_snapshot(run)
                    await db.commit()
        return {"status": "FAILED", "run_id": run_id, "error": str(exc)[:500]}


async def _advance_run(run_id: str) -> dict[str, object]:
    from omichub.application.services.agent_service import AgentService
    from omichub.application.services.overdrive_execution_service import (
        DeliveryAssembler,
        OverdrivePreflightService,
        OverdriveScheduler,
        approved_queued_instances,
        branch_waits,
        mark_artifacts_process_on_termination,
        ready_tasks,
        requeue_repair_instances,
        resume_paused_instances,
    )
    from omichub.application.services.overdrive_run_service import OverdriveRunService
    from omichub.application.services.overdrive_runtime import load_overdrive_limits
    from omichub.infrastructure.database.models.overdrive import OverdriveRunModel
    from omichub.infrastructure.database.session import get_session_factory

    delivery_summary_pending = False
    async with get_session_factory()() as db:
        run = (
            await db.execute(
                select(OverdriveRunModel)
                .where(OverdriveRunModel.run_id == run_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if run is None:
            return {"status": "missing", "run_id": run_id}
        runs = OverdriveRunService(db)
        action = str((run.control or {}).get("action") or "run")
        if action == "terminate" or run.status == "TERMINATING":
            active = [
                task
                for task in run.tasks
                if str(task.get("status") or "") in {"queued", "running", "reviewing"}
            ]
            if active:
                await runs.append_event(
                    run_id,
                    "run_termination_waiting",
                    {"active_task_ids": [str(task.get("task_id")) for task in active]},
                    dedupe_key=f"termination_waiting:{run.version}",
                )
                await db.commit()
                return {"status": "termination_requested", "run_id": run_id}
            tasks = deepcopy(run.tasks)
            for task in tasks:
                if task.get("status") not in {"succeeded", "failed", "skipped", "cancelled"}:
                    task["status"] = "cancelled"
            run.tasks = tasks
            mark_artifacts_process_on_termination(run)
            run.status = "TERMINATED"
            run.finished_at = datetime.now(UTC)
            await runs.append_event(run_id, "run_terminated", {"status": "TERMINATED"})
            await runs.persist_snapshot(run)
            await db.commit()
            return {"status": "TERMINATED", "run_id": run_id}
        if action == "pause" or run.status == "PAUSED":
            await db.commit()
            return {"status": "PAUSED", "run_id": run_id}

        if run.status == "SERIAL_PREFLIGHT":
            preflight = await OverdrivePreflightService(runs).run(run)
            if preflight["status"] != "passed":
                await db.commit()
                return {"status": "FAILED", "run_id": run_id}
            run.status = "RECRUITING"
            await runs.append_event(run_id, "recruiting_started", {})

        if run.status not in {"RECRUITING", "RUNNING", "WAITING_FOR_RESULTS"}:
            await runs.persist_snapshot(run)
            await db.commit()
            return {"status": run.status, "run_id": run_id}

        manager_jobs: list[dict[str, object]] = []
        if not run.manager_tasks:
            run.manager_tasks = [
                {
                    "task_id": "manager:evidence-ledger",
                    "task": "维护研究证据、任务状态和最终交付整合框架",
                    "status": "pending",
                    "owner": "agent-orchestrator",
                }
            ]
        manager_tasks = deepcopy(run.manager_tasks)
        for manager_task in manager_tasks:
            if str(manager_task.get("status") or "pending") != "pending":
                continue
            manager_task.update(
                {
                    "status": "queued",
                    "queued_at": datetime.now(UTC).isoformat(),
                    "dispatched_at": datetime.now(UTC).isoformat(),
                }
            )
            manager_jobs.append(deepcopy(manager_task))
            await runs.append_event(
                run_id,
                "manager_task_queued",
                deepcopy(manager_task),
                dedupe_key=f"manager_task_queued:{manager_task['task_id']}",
            )
        run.manager_tasks = manager_tasks

        reapproved = approved_queued_instances(run)
        resumed = resume_paused_instances(run) if action == "run" else []
        repair_limits = load_overdrive_limits(str(run.lead_planner_agent_id or ""))
        repaired, exhausted_repairs = requeue_repair_instances(
            run,
            max_repair_rounds=int(repair_limits.get("max_repair_rounds") or 1),
        )
        if exhausted_repairs:
            await runs.append_event(
                run_id,
                "repair_budget_exhausted",
                {"task_ids": exhausted_repairs},
                dedupe_key=f"repair_budget_exhausted:{run.version}",
            )

        agent_service = AgentService(db)
        catalog: dict[str, dict[str, object]] = {}
        for task in ready_tasks(run):
            agent_id = str(task.get("agent_id") or "")
            agent = await agent_service.get_agent(agent_id)
            if agent is not None:
                catalog[agent_id] = {
                    "agent_id": agent.agent_id,
                    "name": agent.name,
                    "features": deepcopy(agent.features or {}),
                }
        scheduler = OverdriveScheduler(runs)
        recruited = await scheduler.recruit_ready(run, catalog)
        # A failed prerequisite must deterministically skip its descendants, otherwise
        # a pending DAG node would leave the run in WAITING_FOR_RESULTS forever.
        await scheduler.mark_blocked(run)
        manager_active = any(
            str(task.get("status") or "") in {"queued", "running"}
            for task in run.manager_tasks
        )
        if recruited or resumed or reapproved or repaired or manager_jobs:
            run.status = "RUNNING"
        elif any(
            task.get("status") in {"queued", "running", "reviewing"} for task in run.tasks
        ) or manager_active:
            run.status = "WAITING_FOR_RESULTS"
        elif any(branch_waits(run.tasks).values()):
            # A waiting branch must not block unrelated ready branches or be presented as a
            # global pause.  Keep the run in its normal scheduler state and expose task ids.
            await runs.append_event(
                run_id,
                "branch_waiting",
                {"waits": branch_waits(run.tasks)},
                dedupe_key=f"branch_waiting:{run.version}",
            )
            run.status = "WAITING_FOR_RESULTS"
        elif (
            all(task.get("status") in {"succeeded", "skipped"} for task in run.tasks)
            and all(
                task.get("status") in {"succeeded", "skipped"}
                for task in run.manager_tasks
            )
        ):
            run.status = "QUALITY_REVIEW"
            run.finished_at = datetime.now(UTC)
            delivery = await DeliveryAssembler().write(run)
            readme = await DeliveryAssembler().write_readme(run, delivery)
            run.artifact_index = [
                *run.artifact_index,
                {
                    "artifact_id": "final_report",
                    "path": delivery["path"],
                    "kind": "delivery",
                    "status": "validated",
                    "source": "manager",
                },
                {
                    "artifact_id": "project_readme",
                    "path": readme["path"],
                    "kind": "delivery",
                    "status": "validated",
                    "source": "manager",
                },
            ]
            run.status = "COMPLETED"
            delivery_summary_pending = True
            await runs.append_event(
                run_id,
                "run_completed",
                {
                    "delivery_path": delivery["path"],
                    "readme_path": readme["path"],
                    "artifact_count": len(delivery["official_artifacts"]),
                    "artifacts": deepcopy(run.artifact_index),
                },
            )
        elif (
            all(task.get("status") in {"succeeded", "failed", "skipped", "cancelled"} for task in run.tasks)
            and all(
                task.get("status") in {"succeeded", "failed", "skipped", "cancelled"}
                for task in run.manager_tasks
            )
        ):
            run.status = "FAILED"
            run.finished_at = datetime.now(UTC)
            await runs.append_event(run_id, "run_failed", {"reason": "required task failed"})
        await runs.persist_snapshot(run)
        await db.commit()

    scheduled_instances = [*resumed, *reapproved, *repaired, *recruited]
    for instance in scheduled_instances:
        run_assistant_job.delay(run_id, str(instance["assistant_instance_id"]))
    for manager_task in manager_jobs:
        run_manager_job.delay(run_id, str(manager_task["task_id"]))
    if delivery_summary_pending:
        run_delivery_summary_job.delay(run_id)
    return {
        "status": "scheduled",
        "run_id": run_id,
        "jobs": len(scheduled_instances) + len(manager_jobs),
    }


@shared_task(name="omichub.infrastructure.celery_app.tasks.overdrive.run_manager_job")
def run_manager_job(run_id: str, manager_task_id: str) -> dict[str, object]:
    """Maintain the evidence ledger independently while assistant jobs run."""
    return asyncio.run(_run_manager_job(run_id, manager_task_id))


async def _run_manager_job(run_id: str, manager_task_id: str) -> dict[str, object]:
    from omichub.application.services.overdrive_run_service import (
        OverdriveRunService,
        overdrive_run_root,
        relative_overdrive_run_root,
    )
    from omichub.infrastructure.database.models.overdrive import OverdriveRunModel
    from omichub.infrastructure.database.session import get_session_factory

    async with get_session_factory()() as db:
        run = (
            await db.execute(
                select(OverdriveRunModel)
                .where(OverdriveRunModel.run_id == run_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if run is None:
            return {"status": "missing", "run_id": run_id}
        manager_task = next(
            (item for item in run.manager_tasks if item.get("task_id") == manager_task_id),
            None,
        )
        if manager_task is None or manager_task.get("status") in {"succeeded", "failed", "cancelled"}:
            return {"status": "duplicate", "run_id": run_id, "task_id": manager_task_id}
        manager_tasks = deepcopy(run.manager_tasks)
        for item in manager_tasks:
            if item.get("task_id") == manager_task_id:
                item.update({"status": "running", "started_at": datetime.now(UTC).isoformat()})
        run.manager_tasks = manager_tasks
        runs = OverdriveRunService(db)
        await runs.append_event(
            run_id,
            "manager_task_started",
            {"task_id": manager_task_id},
            dedupe_key=f"manager_task_started:{manager_task_id}",
        )
        await db.commit()
        session_id = run.session_id
        research = deepcopy(run.research)
        tasks = deepcopy(run.tasks)

    factory = get_path_factory()
    backend = get_storage_backend()
    root = overdrive_run_root(session_id, run_id) / "manager"
    root_rel = factory.relative_to_root(root)
    await backend.ensure_dir(root_rel)
    ledger_rel = f"{root_rel}/evidence-ledger.md"
    lines = ["# Manager 证据账本", "", "## 研究来源", ""]
    for source, details in research.items():
        lines.append(f"- {source}: {details.get('status', 'unknown')} ({len(details.get('evidence_ids') or [])} 条证据)")
    lines.extend(["", "## 任务整合状态", ""])
    lines.extend(f"- {task.get('task_id')}: {task.get('status')}" for task in tasks)
    await backend.write(ledger_rel, ("\n".join(lines).rstrip() + "\n").encode("utf-8"))
    relative_path = f"{relative_overdrive_run_root(session_id, run_id)}/manager/evidence-ledger.md"

    async with get_session_factory()() as db:
        run = (
            await db.execute(
                select(OverdriveRunModel)
                .where(OverdriveRunModel.run_id == run_id)
                .with_for_update()
            )
        ).scalar_one()
        runs = OverdriveRunService(db)
        if str((run.control or {}).get("action") or "run") == "terminate":
            status = "cancelled"
        else:
            status = "succeeded"
        manager_tasks = deepcopy(run.manager_tasks)
        for item in manager_tasks:
            if item.get("task_id") == manager_task_id:
                item.update({"status": status, "finished_at": datetime.now(UTC).isoformat()})
        run.manager_tasks = manager_tasks
        if status == "succeeded":
            run.artifact_index = [
                *run.artifact_index,
                {
                    "artifact_id": f"manager:{manager_task_id}",
                    "path": relative_path,
                    "kind": "result",
                    "status": "validated",
                    "source": "agent-orchestrator",
                },
            ]
        await runs.append_event(
            run_id,
            "manager_task_completed",
            {"task_id": manager_task_id, "status": status, "path": relative_path},
            dedupe_key=f"manager_task_completed:{manager_task_id}",
        )
        await runs.persist_snapshot(run)
        await db.commit()
    advance_run.delay(run_id)
    return {"status": status, "run_id": run_id, "task_id": manager_task_id}


@shared_task(name="omichub.infrastructure.celery_app.tasks.overdrive.run_manager_review_job")
def run_manager_review_job(run_id: str, task_id: str, attempt: int) -> dict[str, object]:
    """Escalated Manager review; runs independently from the assistant worker."""
    return asyncio.run(_run_manager_review_job(run_id, task_id, attempt))


async def _run_manager_review_job(run_id: str, task_id: str, attempt: int) -> dict[str, object]:
    from omichub.application.services.agent_service import AgentService
    from omichub.application.services.overdrive_run_service import (
        OverdriveRunService,
        overdrive_run_root,
    )
    from omichub.application.services.overdrive_runtime import load_overdrive_limits
    from omichub.infrastructure.ai_provider.openai_compatible import provider_manager
    from omichub.infrastructure.database.models.overdrive import (
        OverdriveRunModel,
        OverdriveTaskResultModel,
    )
    from omichub.infrastructure.database.session import get_session_factory

    async with get_session_factory()() as db:
        run = (
            await db.execute(
                select(OverdriveRunModel)
                .where(OverdriveRunModel.run_id == run_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if run is None:
            return {"status": "missing", "run_id": run_id}
        task = next((item for item in run.tasks if str(item.get("task_id")) == task_id), None)
        result_row = (
            await db.execute(
                select(OverdriveTaskResultModel).where(
                    OverdriveTaskResultModel.run_id == run_id,
                    OverdriveTaskResultModel.task_id == task_id,
                    OverdriveTaskResultModel.attempt == attempt,
                )
            )
        ).scalar_one_or_none()
        if task is None or result_row is None or task.get("status") != "reviewing":
            return {"status": "duplicate", "run_id": run_id, "task_id": task_id}
        result = deepcopy(result_row.result or {})
        manager_agent_id = str(run.lead_planner_agent_id or "agent-general")
        manager_ctx = await AgentService(db).assemble_context(manager_agent_id, user_id=run.user_id)
        task_snapshot = deepcopy(task)
        result_snapshot = deepcopy(result)

    decision = "repair"
    basis = "Manager 模型不可用，未能完成升级复核"
    review_limits = load_overdrive_limits(manager_agent_id).get("manager_review") or {}
    review_timeout = float(review_limits.get("timeout_seconds") or 30)
    review_tokens = int(review_limits.get("max_tokens") or 1_200)
    if manager_ctx is not None and manager_ctx.model_config is not None:
        prompt = (
            "你是 Manager 质量复核器。只根据任务契约和结果证据做决定，返回严格 JSON："
            '{"decision":"accept|repair|ask_user|await_approval","basis":"具体依据"}。\n\n'
            f"任务契约：{json.dumps(task_snapshot, ensure_ascii=False, default=str)[:12000]}\n"
            f"结果：{json.dumps(result_snapshot, ensure_ascii=False, default=str)[:12000]}\n"
            "accept 只能用于证据足够；repair 表示让原助手按 basis 返工；"
            "ask_user/await_approval 只能在确有补充或审批需求时使用。"
        )
        answer = ""
        try:
            async with asyncio.timeout(review_timeout):
                async for chunk in provider_manager.chat_stream(
                    config=manager_ctx.model_config,
                    messages=[{"role": "user", "content": prompt}],
                    system_prompt=manager_ctx.system_prompt,
                    temperature=0.0,
                    max_tokens=review_tokens,
                    tools=None,
                    deep_thinking=False,
                ):
                    if chunk.type == "text" and not chunk.metadata.get("is_reasoning"):
                        answer += chunk.content
            raw = answer.strip().strip("`")
            if raw.startswith("json"):
                raw = raw[4:].strip()
            payload = json.loads(raw)
            if isinstance(payload, dict) and payload.get("decision") in {
                "accept",
                "repair",
                "ask_user",
                "await_approval",
            }:
                decision = str(payload["decision"])
                basis = str(payload.get("basis") or basis)[:2_000]
        except Exception as exc:  # noqa: BLE001
            basis = f"Manager 复核失败：{str(exc)[:500]}"

    result_status = str(result_snapshot.get("status") or "")
    artifacts = result_snapshot.get("artifacts") if isinstance(result_snapshot.get("artifacts"), list) else []
    factory = get_path_factory()
    backend = get_storage_backend()
    root = overdrive_run_root(run.session_id, run.run_id)
    workspace = root.parents[3]
    workspace_rel = factory.relative_to_root(workspace)
    artifact_prefix = f"output/overdrive/{run.session_id}/{run.run_id.replace(':', '-')}/"
    paths_valid = True
    for item in artifacts:
        if not isinstance(item, dict) or not str(item.get("path") or "").strip():
            paths_valid = False
            break
        rel = str(item.get("path")).removeprefix(artifact_prefix)
        candidate_rel = f"{workspace_rel}/{rel}".strip("/")
        if not await backend.exists(candidate_rel):
            paths_valid = False
            break
    if decision == "accept" and (result_status not in {"ok", "succeeded"} or not paths_valid):
        decision = "repair"
        basis = "复核结果要求接受，但结果状态或产物路径未通过服务端核验"
    accepted = decision == "accept"
    task_status = (
        "succeeded" if accepted else "awaiting_input" if decision == "ask_user"
        else "awaiting_approval" if decision == "await_approval" else "pending"
    )
    review = {
        "review_mode": "llm",
        "decision": decision,
        "accepted": accepted,
        "basis": basis,
        "task_id": task_id,
        "attempt": attempt,
        "reviewed_at": datetime.now(UTC).isoformat(),
    }
    async with get_session_factory()() as db:
        run = (
            await db.execute(
                select(OverdriveRunModel)
                .where(OverdriveRunModel.run_id == run_id)
                .with_for_update()
            )
        ).scalar_one()
        tasks = deepcopy(run.tasks)
        for item in tasks:
            if str(item.get("task_id")) == task_id:
                item.update({
                    "status": task_status,
                    "finished_at": datetime.now(UTC).isoformat() if task_status == "succeeded" else None,
                    "error_summary": "" if accepted else basis,
                    "repair_feedback": basis if task_status == "pending" else None,
                })
        run.tasks = tasks
        instances = deepcopy(run.assistant_instances)
        for item in instances:
            if str(item.get("task_id")) == task_id and item.get("status") == "reviewing":
                item.update({
                    "status": task_status,
                    "finished_at": datetime.now(UTC).isoformat() if task_status == "succeeded" else None,
                })
        run.assistant_instances = instances
        run.manager_reviews = [*run.manager_reviews, review]
        if accepted:
            run.artifact_index = [
                *run.artifact_index,
                *[
                    {
                        **item,
                        "artifact_id": f"{item.get('artifact_id') or task_id}:validated:{attempt}",
                        "status": "validated",
                        "kind": "result",
                        "quality_status": "accept",
                    }
                    for item in artifacts if isinstance(item, dict) and item.get("path")
                ],
            ]
        await OverdriveRunService(db).append_event(run_id, "manager_review_ready", review)
        await OverdriveRunService(db).persist_snapshot(run)
        await db.commit()
    advance_run.delay(run_id)
    return {"status": task_status, "run_id": run_id, "task_id": task_id}


@shared_task(name="omichub.infrastructure.celery_app.tasks.overdrive.run_delivery_summary_job")
def run_delivery_summary_job(run_id: str) -> dict[str, object]:
    """Generate the Manager delivery summary for a completed run."""
    return asyncio.run(_run_delivery_summary_job(run_id))


async def _run_delivery_summary_job(run_id: str) -> dict[str, object]:
    from omichub.application.services.agent_service import AgentService
    from omichub.application.services.overdrive_execution_service import DeliveryAssembler
    from omichub.application.services.overdrive_run_service import (
        OverdriveRunService,
        relative_overdrive_run_root,
    )
    from omichub.application.services.overdrive_runtime import load_overdrive_limits
    from omichub.infrastructure.ai_provider.openai_compatible import provider_manager
    from omichub.infrastructure.database.models.overdrive import (
        OverdriveRunModel,
        OverdriveTaskResultModel,
    )
    from omichub.infrastructure.database.session import get_session_factory

    async with get_session_factory()() as db:
        run = (
            await db.execute(
                select(OverdriveRunModel)
                .where(OverdriveRunModel.run_id == run_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if run is None or run.status != "COMPLETED":
            return {"status": "skipped", "run_id": run_id}
        if (run.control or {}).get("delivery_summary_ready"):
            return {"status": "duplicate", "run_id": run_id}
        result_rows = (
            (
                await db.execute(
                    select(OverdriveTaskResultModel).where(
                        OverdriveTaskResultModel.run_id == run_id
                    )
                )
            )
            .scalars()
            .all()
        )
        manager_agent_id = str(run.lead_planner_agent_id or "agent-general")
        manager_ctx = await AgentService(db).assemble_context(manager_agent_id, user_id=run.user_id)
        plan_snapshot = deepcopy(run.plan or {})
        tasks_snapshot = deepcopy(run.tasks)
        artifact_snapshot = deepcopy(run.artifact_index)

    digest_items = []
    for row in result_rows:
        result = row.result if isinstance(row.result, dict) else {}
        answer = str(result.get("answer") or result.get("error") or "").strip()[:800]
        if answer:
            digest_items.append(f"- {row.task_id}: {answer}")
    results_digest = "\n".join(digest_items)[:12000] or "(无任务结果文本)"
    plan_summary = plan_snapshot.get("summary") if isinstance(plan_snapshot.get("summary"), dict) else {}
    title = str(plan_summary.get("title") or "超频协作")
    official_count = len(
        [
            item
            for item in artifact_snapshot
            if item.get("status") in {"passed", "validated", "succeeded"}
            and item.get("kind") not in {"process", "failed"}
        ]
    )
    fallback_summary = (
        f"本轮《{title}》协作已完成,共产出 {official_count} 项正式交付物,"
        "明细与下载方式见项目 README。"
    )
    manager_summary = fallback_summary
    summary_limits = load_overdrive_limits(manager_agent_id).get("delivery_summary") or {}
    summary_timeout = float(summary_limits.get("timeout_seconds") or 60)
    summary_tokens = int(summary_limits.get("max_tokens") or 1_500)
    if manager_ctx is not None and manager_ctx.model_config is not None:
        prompt = (
            "你是本轮多专家协作的 Manager。协作已全部完成,请用简体中文写一段面向用户的交付总结"
            "(150-300字):概括完成了什么、关键结论或产物是什么、有哪些限制。"
            "不要输出 JSON、不要输出思考过程、不要复述任务清单原文。\n\n"
            f"项目:{title}\n"
            "任务状态:"
            + json.dumps(
                [
                    {"task_id": task.get("task_id"), "status": task.get("status")}
                    for task in tasks_snapshot
                ],
                ensure_ascii=False,
            )
            + f"\n任务结果摘要:\n{results_digest}"
        )
        answer = ""
        try:
            async with asyncio.timeout(summary_timeout):
                async for chunk in provider_manager.chat_stream(
                    config=manager_ctx.model_config,
                    messages=[{"role": "user", "content": prompt}],
                    system_prompt=manager_ctx.system_prompt,
                    temperature=0.2,
                    max_tokens=summary_tokens,
                    tools=None,
                    deep_thinking=False,
                ):
                    if chunk.type == "text" and not chunk.metadata.get("is_reasoning"):
                        answer += chunk.content
            candidate = answer.strip()
            if candidate:
                manager_summary = candidate[:2_000]
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Overdrive delivery summary fell back to rule-based text: run={} error={}",
                run_id,
                exc,
            )

    async with get_session_factory()() as db:
        run = (
            await db.execute(
                select(OverdriveRunModel)
                .where(OverdriveRunModel.run_id == run_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if run is None or run.status != "COMPLETED":
            return {"status": "skipped", "run_id": run_id}
        _, official = DeliveryAssembler().assemble(run)
        relative_root = relative_overdrive_run_root(run.session_id, run.run_id)
        readme = await DeliveryAssembler().write_readme(
            run,
            {
                "path": f"{relative_root}/delivery/final-report.md",
                "official_artifacts": official,
            },
            manager_summary=manager_summary,
        )
        control = deepcopy(run.control or {})
        control["delivery_summary_ready"] = True
        run.control = control
        runs = OverdriveRunService(db)
        await runs.append_event(
            run_id,
            "manager_delivery_ready",
            {"content": manager_summary, "delivery_path": readme["path"]},
            dedupe_key=f"delivery_summary:{run_id}",
        )
        await runs.persist_snapshot(run)
        await db.commit()
    return {"status": "summarized", "run_id": run_id, "delivery_path": readme["path"]}


@shared_task(name="omichub.infrastructure.celery_app.tasks.overdrive.run_assistant_job")
def run_assistant_job(run_id: str, assistant_instance_id: str) -> dict[str, object]:
    """Execute exactly one assistant instance; completion immediately re-enters the scheduler."""
    return asyncio.run(_run_assistant_job(run_id, assistant_instance_id))


async def _run_assistant_job(run_id: str, assistant_instance_id: str) -> dict[str, object]:
    from omichub.application.services.overdrive_execution_service import (
        ManagerReviewService,
        apply_controlled_worker_stop,
        branch_waits,
    )
    from omichub.application.services.overdrive_run_service import (
        OverdriveRunService,
        overdrive_run_root,
        relative_overdrive_run_root,
    )
    from omichub.application.services.parallel_subagent_service import ParallelSubAgentService
    from omichub.infrastructure.database.models.overdrive import (
        OverdriveRunModel,
        OverdriveTaskResultModel,
    )
    from omichub.infrastructure.database.session import get_session_factory

    async with get_session_factory()() as db:
        run = (
            await db.execute(
                select(OverdriveRunModel)
                .where(OverdriveRunModel.run_id == run_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if run is None:
            return {"status": "missing", "run_id": run_id}
        runs = OverdriveRunService(db)
        instance = next(
            (
                item
                for item in run.assistant_instances
                if item.get("assistant_instance_id") == assistant_instance_id
            ),
            None,
        )
        if instance is None:
            return {"status": "missing_instance", "run_id": run_id}
        task_id = str(instance["task_id"])
        control_action = str((run.control or {}).get("action") or "run")
        if control_action in {"pause", "terminate"} or run.status in {
            "PAUSED",
            "TERMINATING",
            "TERMINATED",
        }:
            stop_action = "terminated" if control_action == "terminate" or run.status in {
                "TERMINATING",
                "TERMINATED",
            } else "paused"
            task_status = apply_controlled_worker_stop(
                run,
                task_id=task_id,
                assistant_instance_id=assistant_instance_id,
                action=stop_action,
            )
            await runs.append_event(
                run_id,
                "assistant_controlled_stop",
                {
                    "assistant_instance_id": assistant_instance_id,
                    "task_id": task_id,
                    "status": task_status,
                    "safe_point": "before_start",
                },
                dedupe_key=f"assistant_controlled_stop:{task_id}:before_start:{run.version}",
            )
            await runs.persist_snapshot(run)
            await db.commit()
            advance_run.delay(run_id)
            return {"status": task_status, "run_id": run_id, "task_id": task_id}
        await runs.assert_execution_allowed(run)
        task = next(item for item in run.tasks if str(item.get("task_id")) == task_id)
        attempt = int(task.get("attempt") or 0) + 1
        existing = (
            await db.execute(
                select(OverdriveTaskResultModel).where(
                    OverdriveTaskResultModel.run_id == run_id,
                    OverdriveTaskResultModel.task_id == task_id,
                    OverdriveTaskResultModel.attempt == attempt,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return {"status": "duplicate", "run_id": run_id, "task_id": task_id}
        tasks = deepcopy(run.tasks)
        for item in tasks:
            if str(item.get("task_id")) == task_id:
                item.update({"status": "running", "attempt": attempt, "started_at": datetime.now(UTC).isoformat()})
        instances = deepcopy(run.assistant_instances)
        for item in instances:
            if item.get("assistant_instance_id") == assistant_instance_id:
                item["status"] = "running"
        run.tasks = tasks
        run.assistant_instances = instances
        await runs.append_event(
            run_id,
            "assistant_started",
            {"assistant_instance_id": assistant_instance_id, "task_id": task_id, "attempt": attempt},
            dedupe_key=f"assistant_started:{task_id}:{attempt}",
        )
        await runs.persist_snapshot(run)
        await db.commit()

    async def on_event(event: dict[str, object]) -> None:
        if event.get("type") in {"worker_heartbeat", "worker_retrying", "worker_tool_call"}:
            async with get_session_factory()() as event_db:
                service = OverdriveRunService(event_db)
                await service.append_event(
                    run_id,
                    f"assistant_{str(event.get('type')).removeprefix('worker_')}",
                    {
                        **event,
                        "assistant_instance_id": assistant_instance_id,
                        "task_id": task_id,
                        # 透传真实执行者身份，供房间发言/进度投影显示
                        "agent_id": str(task.get("agent_id") or event.get("agent_id") or ""),
                        "display_name": str(instance.get("display_name") or ""),
                        "agent_name": instance.get("agent_name"),
                    },
                )
                await event_db.commit()

    async def control_check() -> str | None:
        async with get_session_factory()() as control_db:
            current = (
                await control_db.execute(
                    select(OverdriveRunModel).where(OverdriveRunModel.run_id == run_id)
                )
            ).scalar_one_or_none()
            if current is None:
                return "terminated"
            action = str((current.control or {}).get("action") or "run")
            if action == "terminate" or current.status in {"TERMINATING", "TERMINATED"}:
                return "terminated"
            if action == "pause" or current.status == "PAUSED":
                return "paused"
            return None

    # 沙盒可用性预检：预启动本会话沙盒；失败时明确降级 —— 回落写工具授权，
    # 并要求专家把产物直接写在回复正文（平台会代写落盘 result.md），
    # 避免专家反复调用必失败的写工具或幻觉“沙盒写入不可用”。
    from omichub.core.config import get_settings
    from omichub.infrastructure.studio import studio_sandbox_manager

    sandbox_unavailable_reason = ""
    try:
        await studio_sandbox_manager.ensure_running(
            str(run.session_id), user_id=str(run.user_id)
        )
    except Exception as exc:  # noqa: BLE001 - 预检失败绝不阻断任务，仅降级工具授权
        sandbox_unavailable_reason = str(exc)
        logger.warning(
            f"[Overdrive] 会话 {str(run.session_id)[:8]} 沙盒预检失败，本轮降级为纯文本产出: {exc}"
        )
    sandbox_degrade_note = ""
    if sandbox_unavailable_reason:
        sandbox_degrade_note = (
            f"\n沙盒暂不可用：{sandbox_unavailable_reason}。"
            "本轮不要调用 sandbox_execute/workspace_write 等写工具；"
            "将完整产物直接输出在回复正文中，平台会代写落盘 result.md。"
        )

    async with get_session_factory()() as worker_db:
        result_envelope = await ParallelSubAgentService().run(
            user_id=run.user_id,
            parent_agent_id="agent-orchestrator",
            parent_session_id=run.session_id,
            context_summary=(
                f"已确认计划：{(run.plan or {}).get('version_path')}\n"
                f"{_overdrive_workspace_context(run, task)}\n"
                f"本轮 Persona 补充：{str(instance.get('persona_context') or '').strip()}\n"
                f"用户对本分支的补充：{json_safe(task.get('user_responses'))}\n"
                f"Manager 返工意见：{str(task.get('repair_feedback') or '').strip()}\n"
                f"只完成当前任务契约；所有产物必须写入独占目录 "
                f"{relative_overdrive_run_root(run.session_id, run.run_id)}/tasks/{task_id}/，"
                "并在结论中列出真实路径。"
                f"{sandbox_degrade_note}"
            ),
            tasks=[
                {
                    "task_id": task_id,
                    "agent_id": task["agent_id"],
                    "task": task["task"],
                    # 超频专家一律授予工作台工具（对齐 AI 工作台）；
                    # 仅沙盒预检失败时回落，避免反复调用必失败的写工具。
                    "workspace_access": not sandbox_unavailable_reason,
                    "timeout_seconds": task.get("timeout_seconds"),
                    "retry": task.get("retry"),
                }
            ],
            max_rounds=get_settings().overdrive_subagent_max_rounds,
            db=worker_db,
            on_event=on_event,
            runtime_authorized=True,
            control_check=control_check,
            approved_tool_calls=list(task.get("approved_tool_calls") or []),
        )
        await worker_db.commit()
    results = (result_envelope.get("llm_payload") or {}).get("results") or []
    result = results[0] if results else {
        "status": "failed",
        "error": (result_envelope.get("ui_payload") or {}).get("error") or "worker 未返回结果",
    }
    controlled_result = str(result.get("status") or "") in {"paused", "terminated"}
    result_text = str(result.get("answer") or "").strip()
    factory = get_path_factory()
    backend = get_storage_backend()
    task_root = overdrive_run_root(run.session_id, run.run_id) / "tasks" / task_id
    task_root_rel = factory.relative_to_root(task_root)
    await backend.ensure_dir(task_root_rel)
    result_rel = f"{task_root_rel}/result.md"
    if not controlled_result:
        await backend.write(result_rel, (result_text.rstrip() + "\n").encode("utf-8"))
    relative_result_path = (
        f"{relative_overdrive_run_root(run.session_id, run.run_id)}/tasks/{task_id}/result.md"
    )

    async with get_session_factory()() as db:
        run = (
            await db.execute(
                select(OverdriveRunModel)
                .where(OverdriveRunModel.run_id == run_id)
                .with_for_update()
            )
        ).scalar_one()
        runs = OverdriveRunService(db)
        task = next(item for item in run.tasks if str(item.get("task_id")) == task_id)
        live_action = str((run.control or {}).get("action") or "run")
        if live_action == "terminate" or run.status == "TERMINATING":
            result["status"] = "terminated"
            controlled_result = True
        elif live_action == "pause" or run.status == "PAUSED":
            result["status"] = "paused"
        result_artifacts = list(result.get("artifacts") or [])
        result_info = await backend.stat(result_rel)
        if result_info is not None:
            result_artifacts.insert(
                0,
                {
                    "path": relative_result_path,
                    "kind": "task_result",
                    "size_bytes": result_info["size"],
                },
            )
        artifact_paths_valid = True
        for item in result_artifacts:
            if not isinstance(item, dict):
                continue
            if not await _is_registered_artifact_file(run.session_id, run.run_id, item):
                artifact_paths_valid = False
                break
        normalized_result = {
            "status": result.get("status"),
            "answer": result.get("answer"),
            "error": result.get("error"),
            "packet": result.get("packet") if isinstance(result.get("packet"), dict) else {},
            "artifacts": result_artifacts,
            "artifact_paths_valid": artifact_paths_valid,
            "self_check": {
                criterion: bool(result_text) and str(result.get("status") or "") == "ok"
                for criterion in task.get("completion_criteria") or []
            },
            "elapsed_s": result.get("elapsed_s"),
        }
        db.add(
            OverdriveTaskResultModel(
                run_id=run_id,
                task_id=task_id,
                attempt=attempt,
                status=str(result.get("status") or "failed"),
                result=normalized_result,
            )
        )
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            return {"status": "duplicate", "run_id": run_id, "task_id": task_id}
        if result.get("status") in {"paused", "terminated"}:
            review = {
                "review_mode": "rule",
                "decision": str(result.get("status")),
                "accepted": False,
                "basis": "用户控制命令已在安全点生效",
                "reviewed_at": datetime.now(UTC).isoformat(),
            }
        else:
            review = ManagerReviewService().review(task, normalized_result)
        review.update(
            {
                "task_id": task_id,
                "assistant_instance_id": assistant_instance_id,
                "attempt": attempt,
            }
        )
        if review["review_mode"] == "llm_required":
            tasks = deepcopy(run.tasks)
            for item in tasks:
                if str(item.get("task_id")) == task_id:
                    item.update(
                        {
                            "status": "reviewing",
                            "finished_at": None,
                            "error_summary": "Manager 正在复核证据与完成判据",
                        }
                    )
            instances = deepcopy(run.assistant_instances)
            for item in instances:
                if item.get("assistant_instance_id") == assistant_instance_id:
                    item.update({"status": "reviewing", "finished_at": None})
            run.tasks = tasks
            run.assistant_instances = instances
            if await backend.exists(result_rel):
                run.artifact_index = [
                    *run.artifact_index,
                    {
                        "artifact_id": f"task_result:{task_id}:{attempt}",
                        "path": relative_result_path,
                        "kind": "process",
                        "status": "process",
                        "source": assistant_instance_id,
                    },
                ]
            await runs.append_event(
                run_id,
                "assistant_result_ready",
                {
                    "assistant_instance_id": assistant_instance_id,
                    "task_id": task_id,
                    "result": normalized_result,
                    "agent_id": str(task.get("agent_id") or ""),
                    "display_name": str(instance.get("display_name") or ""),
                    "agent_name": instance.get("agent_name"),
                },
                dedupe_key=f"assistant_result:{task_id}:{attempt}",
            )
            await runs.append_event(
                run_id,
                "manager_review_requested",
                {"task_id": task_id, "attempt": attempt, "review": review},
                dedupe_key=f"manager_review_requested:{task_id}:{attempt}",
            )
            await runs.persist_snapshot(run)
            await db.commit()
            run_manager_review_job.delay(run_id, task_id, attempt)
            return {"status": "reviewing", "run_id": run_id, "task_id": task_id}
        tasks = deepcopy(run.tasks)
        task_status = (
            "cancelled"
            if result.get("status") == "terminated"
            else "paused"
            if result.get("status") == "paused"
            else "succeeded"
            if review["accepted"]
            else "awaiting_input"
            if review["decision"] == "ask_user"
            else "awaiting_approval"
            if review["decision"] == "await_approval"
            else "failed"
        )
        pending_approval: dict[str, object] | None = None
        if task_status == "awaiting_approval":
            requests = (
                normalized_result.get("packet", {}).get("approval_requests", [])
                if isinstance(normalized_result.get("packet"), dict)
                else []
            )
            request = requests[0] if isinstance(requests, list) and requests else {}
            if isinstance(request, dict):
                pending_approval = {
                    "approval_id": f"overdrive-v2-approval:{run_id}:{task_id}:{attempt}",
                    "run_id": run_id,
                    "task_id": task_id,
                    "assistant_instance_id": assistant_instance_id,
                    "attempt": attempt,
                    "tool_name": str(request.get("tool_name") or ""),
                    "arguments": deepcopy(request.get("arguments") or {}),
                    "status": "pending",
                    "created_at": datetime.now(UTC).isoformat(),
                }
        for item in tasks:
            if str(item.get("task_id")) == task_id:
                item.update(
                    {
                        "status": task_status,
                        "finished_at": datetime.now(UTC).isoformat(),
                        "error_summary": "" if review["accepted"] else review["basis"],
                        "pending_approval": pending_approval,
                        "repair_feedback": None,
                    }
                )
        instances = deepcopy(run.assistant_instances)
        for item in instances:
            if item.get("assistant_instance_id") == assistant_instance_id:
                item.update(
                    {
                        "status": task_status,
                        "finished_at": datetime.now(UTC).isoformat()
                        if task_status in {"succeeded", "failed", "cancelled"}
                        else None,
                    }
                )
        run.tasks = tasks
        run.assistant_instances = instances
        run.manager_reviews = [*run.manager_reviews, review]
        # Waiting is branch-local. Sibling DAG nodes must remain schedulable; the
        # task status and its durable review event carry the user/approval wait.
        if await backend.exists(result_rel):
            run.artifact_index = [
                *run.artifact_index,
                {
                    "artifact_id": f"task_result:{task_id}:{attempt}",
                    "path": relative_result_path,
                    "kind": (
                        "result"
                        if review["accepted"]
                        else "process"
                        if task_status in {"awaiting_input", "awaiting_approval", "paused"}
                        else "failed"
                    ),
                    "status": (
                        "validated"
                        if review["accepted"]
                        else task_status
                        if task_status in {"awaiting_input", "awaiting_approval", "paused"}
                        else "failed"
                    ),
                    "source": assistant_instance_id,
                    "quality_status": review["decision"],
                },
            ]
        await runs.append_event(
            run_id,
            "assistant_result_ready",
            {
                "assistant_instance_id": assistant_instance_id,
                "task_id": task_id,
                "result": normalized_result,
                "agent_id": str(task.get("agent_id") or ""),
                "display_name": str(instance.get("display_name") or ""),
                "agent_name": instance.get("agent_name"),
                "waits": branch_waits(run.tasks),
                "approval": pending_approval,
            },
            dedupe_key=f"assistant_result:{task_id}:{attempt}",
        )
        await runs.append_event(
            run_id,
            "manager_review_ready",
            review,
            dedupe_key=f"manager_review:{task_id}:{attempt}",
        )
        await runs.persist_snapshot(run)
        await db.commit()
    advance_run.delay(run_id)
    return {"status": task_status, "run_id": run_id, "task_id": task_id}


def json_safe(value: object) -> str:
    import json

    return json.dumps(value or {}, ensure_ascii=False, default=str)


async def _is_registered_artifact_file(session_id: str, run_id: str, artifact: dict[str, object]) -> bool:
    """Accept only existing files below this run's immutable artifact directory."""
    from omichub.application.services.overdrive_run_service import overdrive_run_root

    factory = get_path_factory()
    backend = get_storage_backend()
    relative_path = str(artifact.get("path") or "").strip()
    if not relative_path or Path(relative_path).is_absolute():
        return False
    root = overdrive_run_root(session_id, run_id).resolve()
    workspace = root.parents[3]
    candidate = (workspace / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    candidate_rel = factory.relative_to_root(candidate)
    return await backend.exists(candidate_rel)
