"""OmicStudio Celery 任务：长时间沙盒执行与空闲沙盒回收。"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from celery import shared_task
from sqlalchemy import select

from cygnusx.core.config import get_settings
from cygnusx.domain.task.value_objects import LogLevel, TaskStatus
from cygnusx.infrastructure.cache.pubsub import publish_arq_progress, publish_task_log

logger = logging.getLogger(__name__)

_MAX_CAPTURE_CHARS = 20_000
_MAX_PERSISTED_LINES = 200


@shared_task(name="cygnusx.infrastructure.celery_app.tasks.studio.cleanup_expired_workspaces")
def cleanup_expired_workspaces() -> dict[str, Any]:
    """删除超过保留期且无豁免的闲置 Studio 工作区，报告中心产物不受影响。

    删除依据为 retention.active_days（不再使用 session.workspace_retention_days，
    后者保留为后续休眠功能的候选线）。豁免条件（满足任一即跳过）：
    1. 最近 active_days 天内有消息（chat_messages.created_at）或沙盒执行活动；
    2. 用户 pin 的会话（sandbox_meta.pinned = true）；
    3. 绑定到项目的会话（projects 表无状态字段，项目存在即视为进行中）。
    """
    return asyncio.run(_cleanup_expired_workspaces())


async def _cleanup_expired_workspaces() -> dict[str, Any]:
    from sqlalchemy import func

    from cygnusx.application.services.studio_sharing import share_is_active
    from cygnusx.infrastructure.database.models.chat import (
        ChatMessageModel,
        ChatSessionModel,
    )
    from cygnusx.infrastructure.database.session import get_session_factory
    from cygnusx.infrastructure.studio.control_client import StudioControlClient
    from cygnusx.infrastructure.studio.manager import studio_sandbox_manager

    config = studio_sandbox_manager._config()
    active_days = max(1, int(config.retention.active_days))
    cutoff = datetime.now(UTC) - timedelta(days=active_days)
    removed = 0
    skipped_shared = 0
    skipped_busy = 0
    skipped_active = 0
    skipped_pinned = 0
    skipped_project = 0
    missing = 0
    control_client = StudioControlClient()
    workspace_cleaner = (
        control_client
        if get_settings().service_name == "worker" and control_client.enabled
        else studio_sandbox_manager
    )

    async with get_session_factory()() as db:
        result = await db.execute(
            select(ChatSessionModel).where(
                ChatSessionModel.mode == "studio",
                ChatSessionModel.updated_at < cutoff,
            )
        )
        sessions = list(result.scalars().all())
        # 批量取候选会话最近一次消息时间，避免逐会话查询
        session_ids = [session.session_id for session in sessions]
        last_message_by_session: dict[str, datetime] = {}
        if session_ids:
            msg_result = await db.execute(
                select(
                    ChatMessageModel.session_id,
                    func.max(ChatMessageModel.created_at),
                )
                .where(ChatMessageModel.session_id.in_(session_ids))
                .group_by(ChatMessageModel.session_id)
            )
            last_message_by_session = {
                str(row[0]): row[1] for row in msg_result.all() if row[1] is not None
            }
        for session in sessions:
            if share_is_active(session):
                skipped_shared += 1
                continue
            # 豁免 1：近期有消息或沙盒执行活动
            last_message_at = last_message_by_session.get(session.session_id)
            if last_message_at is not None and _as_utc(last_message_at) >= cutoff:
                skipped_active += 1
                continue
            recent_activity = await studio_sandbox_manager.last_activity_at(
                session.session_id
            )
            if recent_activity is not None and recent_activity > cutoff.timestamp():
                skipped_busy += 1
                continue
            # 豁免 2：用户 pin 的会话（sandbox_meta.pinned 标记位）
            sandbox_meta = getattr(session, "sandbox_meta", None) or {}
            if sandbox_meta.get("pinned") is True:
                skipped_pinned += 1
                continue
            # 豁免 3：绑定到项目的会话（项目存在即视为进行中）
            if getattr(session, "project_id", None):
                skipped_project += 1
                continue
            status = await workspace_cleaner.purge_workspace(session.session_id)
            if status == "busy":
                skipped_busy += 1
            elif status == "removed":
                removed += 1
            else:
                missing += 1
        await db.commit()

    return {
        "status": "ok",
        "active_days": active_days,
        "removed_workspaces": removed,
        "skipped_shared": skipped_shared,
        "skipped_busy": skipped_busy,
        "skipped_active": skipped_active,
        "skipped_pinned": skipped_pinned,
        "skipped_project": skipped_project,
        "missing_workspaces": missing,
    }


def _as_utc(value: datetime) -> datetime:
    """naive datetime 按 UTC 解释，aware 原样返回。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


# ------------------------------------------------------------------
# WP1 会话工作区生命周期：休眠打包 / 到期清理
# ------------------------------------------------------------------

# 单次 beat 运行最多打包的会话数（小步批量，异常单个跳过）
_HIBERNATE_BATCH_LIMIT = 50


async def _load_studio_sessions_with_last_message(
    db: Any,
) -> tuple[list[Any], dict[str, datetime]]:
    """全部 studio 会话 + 每会话最近消息时间（批量查询，避免 N+1）。"""
    from sqlalchemy import func

    from cygnusx.infrastructure.database.models.chat import (
        ChatMessageModel,
        ChatSessionModel,
    )

    result = await db.execute(
        select(ChatSessionModel).where(
            ChatSessionModel.mode == "studio",
            ChatSessionModel.status != "deleted",
        )
    )
    sessions = list(result.scalars().all())
    last_message_by_session: dict[str, datetime] = {}
    session_ids = [s.session_id for s in sessions]
    if session_ids:
        msg_result = await db.execute(
            select(
                ChatMessageModel.session_id,
                func.max(ChatMessageModel.created_at),
            )
            .where(ChatMessageModel.session_id.in_(session_ids))
            .group_by(ChatMessageModel.session_id)
        )
        last_message_by_session = {
            str(row[0]): row[1] for row in msg_result.all() if row[1] is not None
        }
    return sessions, last_message_by_session


def _has_archive_marker(session: Any) -> bool:
    return isinstance((session.sandbox_meta or {}).get("workspace_archive"), dict)


async def _is_dormant_exempt(
    session: Any,
    *,
    last_message_at: datetime | None,
    active_cutoff: datetime,
) -> str | None:
    """返回豁免原因；无豁免返回 None。豁免规则与 purge 一致（WP0 口径）。"""
    from cygnusx.application.services.studio_sharing import share_is_active
    from cygnusx.infrastructure.studio.manager import studio_sandbox_manager

    sandbox_meta = getattr(session, "sandbox_meta", None) or {}
    if sandbox_meta.get("pinned") is True:
        return "pinned"
    if getattr(session, "project_id", None):
        return "project_bound"
    if share_is_active(session):
        return "shared"
    if last_message_at is not None and _as_utc(last_message_at) >= active_cutoff:
        return "recent_message"
    recent_activity = await studio_sandbox_manager.last_activity_at(session.session_id)
    if recent_activity is not None and recent_activity > active_cutoff.timestamp():
        return "recent_activity"
    return None


async def _try_pack(
    db: Any, session_id: str, *, quota_cleanup: bool = False
) -> str:
    """单个会话打包；返回 packed / skipped:<reason> / error:<msg>。"""
    from cygnusx.application.services.workspace_archive_service import (
        WorkspaceArchiveBusyError,
        pack_session,
    )

    try:
        await pack_session(db, session_id, "system", is_admin=True)
        return "packed"
    except WorkspaceArchiveBusyError:
        return "skipped:busy"
    except Exception as exc:  # noqa: BLE001 - 单个失败不拖垮整批
        logger.exception(
            "[Studio] 休眠打包失败 session=%s quota_cleanup=%s: %s",
            session_id[:12],
            quota_cleanup,
            exc,
        )
        return f"error:{exc}"


@shared_task(name="cygnusx.infrastructure.celery_app.tasks.studio.hibernate_dormant_workspaces")
def hibernate_dormant_workspaces() -> dict[str, Any]:
    """每天 04:30：先跑工作区配额清理，再跑 dormant 休眠扫描。

    - 配额清理：某用户工作区总量超 quota.workspace_gb 时，按 updated_at 最旧
      且无豁免的会话依次 pack，直到低于配额或无可 pack；
    - dormant 扫描：updated_at 早于 retention.dormant_days 且无豁免、未归档的
      studio 会话 pack（operator=system）。
    单次运行打包上限 _HIBERNATE_BATCH_LIMIT，异常单个跳过记日志。
    """
    return asyncio.run(_hibernate_dormant_workspaces())


async def _hibernate_dormant_workspaces() -> dict[str, Any]:
    from cygnusx.infrastructure.celery_app.tasks.storage import _dir_size
    from cygnusx.infrastructure.database.session import get_session_factory
    from cygnusx.infrastructure.studio.manager import studio_sandbox_manager

    config = studio_sandbox_manager._config()
    active_days = max(1, int(config.retention.active_days))
    dormant_days = max(1, int(config.retention.dormant_days))
    workspace_quota_bytes = int(config.quota.workspace_gb) * 1024**3
    active_cutoff = datetime.now(UTC) - timedelta(days=active_days)
    dormant_cutoff = datetime.now(UTC) - timedelta(days=dormant_days)

    packed = 0
    quota_packed = 0
    skipped: dict[str, int] = {}
    errors = 0
    workspace_size_cache: dict[str, int] = {}

    async with get_session_factory()() as db:
        sessions, last_message_by_session = await _load_studio_sessions_with_last_message(db)

        async def workspace_bytes(session: Any) -> int:
            cached = workspace_size_cache.get(session.session_id)
            if cached is None:
                try:
                    workspace = studio_sandbox_manager.workspace_dir(session.session_id)
                except Exception:  # noqa: BLE001
                    workspace_size_cache[session.session_id] = 0
                    return 0
                workspace_size_cache[session.session_id] = (
                    _dir_size(workspace) if workspace.is_dir() else 0
                )
                cached = workspace_size_cache[session.session_id]
            return cached

        async def exempt_reason(session: Any) -> str | None:
            return await _is_dormant_exempt(
                session,
                last_message_at=last_message_by_session.get(session.session_id),
                active_cutoff=active_cutoff,
            )

        # ---- 第一遍：配额清理（按用户工作区总量倒序处理超限用户）----
        if workspace_quota_bytes > 0 and packed < _HIBERNATE_BATCH_LIMIT:
            by_user: dict[str, list[Any]] = {}
            for session in sessions:
                if _has_archive_marker(session):
                    continue  # 已归档目录已删，不计占用也不需再 pack
                by_user.setdefault(str(session.user_id), []).append(session)
            for user_id, user_sessions in sorted(
                by_user.items(), key=lambda item: str(item[1][0].user_id)
            ):
                if packed >= _HIBERNATE_BATCH_LIMIT:
                    break
                total = sum([await workspace_bytes(s) for s in user_sessions])
                if total <= workspace_quota_bytes:
                    continue
                logger.info(
                    "[Studio] 用户 %s 工作区超配额: %s > %s bytes，按最久未访问休眠",
                    user_id[:8],
                    total,
                    workspace_quota_bytes,
                )
                for session in sorted(user_sessions, key=lambda s: s.updated_at or s.created_at):
                    if packed >= _HIBERNATE_BATCH_LIMIT:
                        break
                    if total <= workspace_quota_bytes:
                        break
                    if _has_archive_marker(session):
                        continue
                    reason = await exempt_reason(session)
                    if reason is not None:
                        skipped[f"quota_exempt_{reason}"] = (
                            skipped.get(f"quota_exempt_{reason}", 0) + 1
                        )
                        continue
                    result = await _try_pack(db, session.session_id, quota_cleanup=True)
                    if result == "packed":
                        packed += 1
                        quota_packed += 1
                        total -= workspace_size_cache.get(session.session_id, 0)
                        workspace_size_cache[session.session_id] = 0
                    elif result.startswith("skipped:"):
                        skipped[f"quota_{result[8:]}"] = skipped.get(f"quota_{result[8:]}", 0) + 1
                    else:
                        errors += 1

        # ---- 第二遍：dormant 休眠扫描 ----
        for session in sorted(sessions, key=lambda s: s.updated_at or s.created_at):
            if packed >= _HIBERNATE_BATCH_LIMIT:
                skipped["batch_limit"] = skipped.get("batch_limit", 0) + 1
                break
            updated_at = session.updated_at or session.created_at
            if updated_at is None or _as_utc(updated_at) >= dormant_cutoff:
                continue
            if _has_archive_marker(session):
                continue
            reason = await exempt_reason(session)
            if reason is not None:
                skipped[f"dormant_exempt_{reason}"] = skipped.get(f"dormant_exempt_{reason}", 0) + 1
                continue
            result = await _try_pack(db, session.session_id)
            if result == "packed":
                packed += 1
            elif result.startswith("skipped:"):
                skipped[f"dormant_{result[8:]}"] = skipped.get(f"dormant_{result[8:]}", 0) + 1
            else:
                errors += 1

    return {
        "status": "ok",
        "active_days": active_days,
        "dormant_days": dormant_days,
        "packed": packed,
        "quota_packed": quota_packed,
        "errors": errors,
        "skipped": skipped,
    }


@shared_task(
    name="cygnusx.infrastructure.celery_app.tasks.studio.cleanup_expired_workspace_archives"
)
def cleanup_expired_workspace_archives() -> dict[str, Any]:
    """每天 05:30：删除 expires_at 已过的归档包（文件 + deleted_at + 审计）。"""
    return asyncio.run(_cleanup_expired_workspace_archives())


async def _cleanup_expired_workspace_archives() -> dict[str, Any]:
    from pathlib import Path

    from cygnusx.application.services.workspace_archive_service import (
        _utcnow,
        _write_audit,
    )
    from cygnusx.infrastructure.database.models.workspace_archive import (
        WorkspaceArchiveModel,
    )
    from cygnusx.infrastructure.database.session import get_session_factory
    from cygnusx.infrastructure.studio.archive_storage import get_archive_storage
    from cygnusx.infrastructure.studio.manager import studio_sandbox_manager

    config = studio_sandbox_manager._config()
    storage = get_archive_storage(config)
    now = _utcnow()
    deleted = 0
    errors = 0

    async with get_session_factory()() as db:
        result = await db.execute(
            select(WorkspaceArchiveModel).where(
                WorkspaceArchiveModel.expires_at < now,
                WorkspaceArchiveModel.deleted_at.is_(None),
            )
        )
        records = list(result.scalars().all())
        for record in records:
            try:
                deleted_file = await asyncio.to_thread(
                    storage.delete_package, Path(record.package_path)
                )
                record.deleted_at = now
                await _write_audit(
                    db,
                    operator="system",
                    method="DELETE",
                    path="/api/v1/admin/workspace-archive/packages/expired",
                    resource_id=str(record.id),
                    status_code=200,
                    detail={
                        "event": "workspace_archive_expired_cleanup",
                        "package_id": str(record.id),
                        "session_id": record.session_id,
                        "package_path": record.package_path,
                        "expires_at": record.expires_at.isoformat() if record.expires_at else None,
                        "deleted_file": deleted_file,
                    },
                )
                deleted += 1
            except Exception as exc:  # noqa: BLE001 - 单个失败不拖垮整批
                errors += 1
                logger.exception(
                    "[Archive] 过期归档包清理失败 package=%s: %s", record.id, exc
                )
        await db.commit()

    return {"status": "ok", "deleted": deleted, "errors": errors, "scanned": len(records)}


@shared_task(name="cygnusx.infrastructure.celery_app.tasks.studio.run_studio_sandbox", bind=True)
def run_studio_sandbox(
    self: Any,
    *,
    task_id: str | None = None,
    user_id: str,
    session_id: str,
    language: str,
    code: str,
    timeout_sec: int,
    image: str | None = None,
) -> dict[str, Any]:
    """在 Celery worker 中执行预计超过 10 分钟的 Studio 代码。

    bind=True：DB job 行 id 经 enqueue_task 的 task_id 选项作为 Celery 消息 id
    下发（dispatcher 的 task_id 参数与任务 kwargs 同名，无法直接透传），此处从
    self.request.id 取回，保证 Celery id == DB task id——worker 幂等认领与
    对账（AsyncResult/队列扫描）都依赖这一等式。
    """
    task_id = task_id or str(self.request.id)
    return asyncio.run(
        _run_studio_sandbox(
            task_id=task_id,
            user_id=user_id,
            session_id=session_id,
            language=language,
            code=code,
            timeout_sec=timeout_sec,
            image=image,
        )
    )


async def _run_studio_sandbox(
    *,
    task_id: str,
    user_id: str,
    session_id: str,
    language: str,
    code: str,
    timeout_sec: int,
    image: str | None,
) -> dict[str, Any]:
    from cygnusx.core.config import get_settings
    from cygnusx.domain.task.services import TaskDomainService
    from cygnusx.infrastructure.database.repositories.task_repository import TaskRepositoryImpl
    from cygnusx.infrastructure.database.session import get_session_factory
    from cygnusx.infrastructure.studio.control_client import StudioControlClient
    from cygnusx.infrastructure.studio.manager import studio_sandbox_manager

    task_uuid = UUID(task_id)
    settings = get_settings()
    control_client = StudioControlClient()
    sandbox_executor = (
        control_client
        if settings.service_name == "worker" and control_client.enabled
        else studio_sandbox_manager
    )
    session_factory = get_session_factory()
    async with session_factory() as db:
        repo = TaskRepositoryImpl(db)
        domain = TaskDomainService(repo)
        task = await repo.get_by_id(task_uuid)
        if task is None:
            return {"status": "failed", "message": f"任务 {task_id} 不存在"}
        if task.status != TaskStatus.QUEUED:
            return {"status": task.status.value, "task_id": task_id}

        async def publish_progress(phase: str, progress: float, message: str) -> None:
            task.progress = max(0.0, min(1.0, progress))
            await repo.save(task)
            await db.commit()
            await publish_arq_progress(task_id, phase, task.progress, message)

        async def publish_log(level: LogLevel, message: str, source: str = "studio") -> None:
            await domain.add_log(task_uuid, level, message, source=source)
            await publish_task_log(task_id, level.value, message, source=source)

        task = await domain.transition_status(task, TaskStatus.RUNNING)
        await db.commit()
        await publish_log(LogLevel.INFO, "Studio 长任务开始执行", source="celery")
        await publish_progress("STARTING", 0.05, "正在启动 Studio 沙盒")

        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        result_event: dict[str, Any] = {}
        started = time.monotonic()
        last_progress_update = started

        try:
            async for event in sandbox_executor.exec(
                session_id,
                language,
                code,
                timeout_sec=timeout_sec,
                image=image,
                user_id=user_id,
            ):
                event_type = str(event.get("type") or "")
                if event_type in {"stdout", "stderr"}:
                    data = str(event.get("data") or "")
                    target = stdout_parts if event_type == "stdout" else stderr_parts
                    _append_bounded(target, data)
                    await publish_task_log(
                        task_id,
                        LogLevel.INFO.value if event_type == "stdout" else LogLevel.WARNING.value,
                        data,
                        source=f"studio_{event_type}",
                    )
                    now = time.monotonic()
                    if now - last_progress_update >= 2:
                        elapsed_ratio = min((now - started) / max(timeout_sec, 1), 1.0)
                        await publish_progress(
                            "RUNNING",
                            min(0.9, 0.1 + elapsed_ratio * 0.8),
                            f"沙盒执行中，已运行 {int(now - started)} 秒",
                        )
                        last_progress_update = now
                elif event_type == "result":
                    result_event = event

            exit_code = int(result_event.get("exit_code", -1))
            timed_out = bool(result_event.get("timed_out"))
            artifacts = result_event.get("artifacts") or []
            stdout = "\n".join(stdout_parts)
            stderr = "\n".join(stderr_parts)
            task.parameters = {
                **task.parameters,
                "studio_result": {
                    "exit_code": exit_code,
                    "duration_ms": int(result_event.get("duration_ms", 0)),
                    "timed_out": timed_out,
                    "stdout": stdout[-10_000:],
                    "stderr": stderr[-10_000:],
                    "artifacts": artifacts,
                    "output_files": result_event.get("truncated_output_files") or [],
                },
            }
            task.result_path = f"/api/v1/studio/sessions/{session_id}/artifacts"

            for line in stdout.splitlines()[-_MAX_PERSISTED_LINES:]:
                if line.strip():
                    await publish_log(LogLevel.INFO, line, source="studio_stdout")
            for line in stderr.splitlines()[-_MAX_PERSISTED_LINES:]:
                if line.strip():
                    await publish_log(LogLevel.WARNING, line, source="studio_stderr")

            if exit_code == 0 and not timed_out:
                task.progress = 1.0
                task = await repo.save(task)
                task = await domain.transition_status(task, TaskStatus.SUCCESS)
                await publish_log(LogLevel.INFO, "Studio 长任务执行完成", source="celery")
                await db.commit()
                await publish_arq_progress(task_id, "COMPLETED", 1.0, "执行完成，产物已刷新")
                return {"status": "success", "task_id": task_id, **task.parameters["studio_result"]}

            task.error_message = str(
                result_event.get("error")
                or (f"沙盒执行退出码 {exit_code}" if not timed_out else "沙盒执行超时")
            )
            task.progress = 1.0
            task = await repo.save(task)
            task = await domain.transition_status(task, TaskStatus.FAILED)
            await publish_log(LogLevel.ERROR, task.error_message, source="celery")
            await db.commit()
            await publish_arq_progress(task_id, "FAILED", 1.0, task.error_message)
            return {"status": "failed", "task_id": task_id, **task.parameters["studio_result"]}
        except Exception as exc:  # noqa: BLE001
            logger.exception("Studio 长任务执行失败: %s", task_id)
            fresh = await repo.get_by_id(task_uuid)
            if fresh is not None and fresh.status == TaskStatus.RUNNING:
                fresh.error_message = str(exc)
                fresh.progress = 1.0
                fresh = await repo.save(fresh)
                await domain.transition_status(fresh, TaskStatus.FAILED)
                await db.commit()
            await publish_task_log(task_id, LogLevel.ERROR.value, str(exc), source="celery")
            await publish_arq_progress(task_id, "FAILED", 1.0, f"执行失败：{exc}")
            return {"status": "failed", "task_id": task_id, "error": str(exc)}


def _append_bounded(parts: list[str], value: str) -> None:
    parts.append(value)
    total = sum(len(item) for item in parts)
    while parts and total > _MAX_CAPTURE_CHARS:
        total -= len(parts.pop(0))


# ------------------------------------------------------------------
# WP2 任务4 契约 c：reconcile-only 对账 —— 只报告/标记状态漂移，绝不自动重提交
# ------------------------------------------------------------------

# 单次对账最多扫描的悬挂/滞留任务数（小步批量，异常单个跳过）
STUDIO_RECONCILE_BATCH_LIMIT = 100
# DB 仍 QUEUED 但早于该阈值：消息大概率已丢失或 worker 未认领
STUDIO_RECONCILE_QUEUED_GRACE_SECONDS = 1800
# DB 仍 RUNNING 且早于该阈值（6h 硬超时 + 10min 余量）：worker 大概率已丢失，仅报告
STUDIO_RECONCILE_RUNNING_GRACE_SECONDS = 6 * 3600 + 600
# 对账对象：Studio 长任务 job 的 flow_id
STUDIO_FLOW_ID_FOR_RECONCILE = "studio_sandbox"


def _celery_backend_state(task_id: str) -> str | None:
    """读取 Celery result backend 中该任务的状态（PENDING/STARTED/SUCCESS/...）。

    返回 None 表示无法确认（无 result backend 或查询失败），调用方按"仅告警"处理。
    """
    try:
        from cygnusx.infrastructure.celery_app.celery import celery_app

        return str(celery_app.AsyncResult(task_id).state)
    except Exception:  # noqa: BLE001 - 对账不能因为查询失败而中断
        logger.warning("[Studio] 对账查询 Celery 状态失败 task=%s", task_id)
        return None


def _celery_backend_result(task_id: str) -> Any:
    """读取 Celery result backend 中该任务的返回值（对账恢复终态时使用）。"""
    try:
        from cygnusx.infrastructure.celery_app.celery import celery_app

        return celery_app.AsyncResult(task_id).result
    except Exception:  # noqa: BLE001 - 结果缺失时按"未可靠回写"降级
        logger.warning("[Studio] 对账查询 Celery 结果失败 task=%s", task_id)
        return None


def _celery_message_in_queue(task_id: str, queue: str = "analysis") -> bool | None:
    """扫描 broker 队列确认该 task_id 的消息是否还在排队（未被 worker 取走）。

    返回 None 表示无法确认（非 Redis broker 或查询失败），调用方按"仅告警"处理。
    """
    try:
        from cygnusx.infrastructure.celery_app.celery import celery_app

        with celery_app.connection() as conn:
            channel = conn.default_channel
            client = getattr(channel, "client", None)  # kombu RedisTransport 暴露的 redis client
            if client is None:
                return None
            for raw in client.lrange(queue, 0, -1):
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", "ignore")
                if task_id in raw:
                    return True
            return False
    except Exception:  # noqa: BLE001 - 对账不能因为查询失败而中断
        logger.warning("[Studio] 对账扫描 broker 队列失败 task=%s", task_id)
        return None


@shared_task(name="cygnusx.infrastructure.celery_app.tasks.studio.reconcile_studio_long_tasks")
def reconcile_studio_long_tasks() -> dict[str, Any]:
    """对账 Studio 长任务：只报告/标记状态漂移，绝不自动重提交（reconcile-only）。

    借鉴 OpenAI4S compute/manager.py reconcile()：worker 丢失时"诚实的动作是把
    漂移摆出来"，自动重猜的代价是重复执行或丢失结果，因此这里任何分支都不会
    调用 enqueue_task。语义按现有状态机取最贴近者：

    - DB QUEUED 超 grace：
      * backend PENDING 且消息不在 broker 队列 → 消息丢失/worker 未认领，
        标记 FAILED（QUEUED→RUNNING→FAILED 合法两跳）并记任务日志；
      * backend SUCCESS/FAILURE → worker 已结束但 DB 未回写，按队列结果恢复
        终态（SUCCESS 走 QUEUED→RUNNING→SUCCESS），结果取自 backend meta；
      * 其余（仍在队列 / STARTED 执行中 / 无法确认）→ 仅记录日志，不动状态。
    - DB RUNNING 超 grace：worker 可能已丢失，但沙盒容器或许仍在运行，
      按 OpenAI4S "unknown 刻意为 live" 的语义仅报告，不改状态。
    """
    return asyncio.run(_reconcile_studio_long_tasks())


async def _load_stale_queued_models(db: Any, cutoff: datetime) -> list[Any]:
    from cygnusx.infrastructure.database.models.task import TaskModel

    result = await db.execute(
        select(TaskModel)
        .where(
            TaskModel.flow_id == STUDIO_FLOW_ID_FOR_RECONCILE,
            TaskModel.status == TaskStatus.QUEUED.value,
            TaskModel.created_at < cutoff,
        )
        .order_by(TaskModel.created_at)
        .limit(STUDIO_RECONCILE_BATCH_LIMIT)
    )
    return list(result.scalars().all())


async def _load_stale_running_models(db: Any, cutoff: datetime) -> list[Any]:
    from cygnusx.infrastructure.database.models.task import TaskModel

    result = await db.execute(
        select(TaskModel)
        .where(
            TaskModel.flow_id == STUDIO_FLOW_ID_FOR_RECONCILE,
            TaskModel.status == TaskStatus.RUNNING.value,
            TaskModel.started_at.isnot(None),
            TaskModel.started_at < cutoff,
        )
        .order_by(TaskModel.started_at)
        .limit(STUDIO_RECONCILE_BATCH_LIMIT)
    )
    return list(result.scalars().all())


async def _reconcile_studio_long_tasks() -> dict[str, Any]:
    from cygnusx.domain.task.services import TaskDomainService
    from cygnusx.infrastructure.database.repositories.task_repository import (
        TaskRepositoryImpl,
    )
    from cygnusx.infrastructure.database.session import get_session_factory

    now = datetime.now(UTC)
    queued_cutoff = now - timedelta(seconds=STUDIO_RECONCILE_QUEUED_GRACE_SECONDS)
    running_cutoff = now - timedelta(seconds=STUDIO_RECONCILE_RUNNING_GRACE_SECONDS)

    result: dict[str, Any] = {
        "status": "ok",
        "queued_scanned": 0,
        "queued_marked_failed": [],
        "queued_recovered": [],
        "queued_still_pending": [],
        "running_reported": [],
        "errors": 0,
    }

    async with get_session_factory()() as db:
        repo = TaskRepositoryImpl(db)
        domain = TaskDomainService(repo)

        stale_queued = await _load_stale_queued_models(db, queued_cutoff)
        result["queued_scanned"] = len(stale_queued)

        for model in stale_queued:
            task_id = str(model.id)
            try:
                backend_state = _celery_backend_state(task_id)
                if backend_state in {"SUCCESS", "FAILURE"}:
                    # worker 已把结果写入 backend，但 DB 仍停在 QUEUED（回写丢失）。
                    # 恢复终态而非重跑——执行确实发生过，重跑只会产生重复副作用。
                    task = await repo.get_by_id(model.id)
                    if task is None or task.status != TaskStatus.QUEUED:
                        continue
                    meta: Any = None
                    if backend_state == "SUCCESS":
                        meta = _celery_backend_result(task_id)
                    task = await domain.transition_status(task, TaskStatus.RUNNING)
                    if backend_state == "SUCCESS" and isinstance(meta, dict):
                        task.parameters = {
                            **task.parameters,
                            "studio_result": {
                                k: v
                                for k, v in meta.items()
                                if k not in {"status", "task_id", "error"}
                            },
                            "reconcile_note": "对账恢复：worker 已完成但 DB 未回写，按队列结果恢复终态（未重新执行）",
                        }
                        task.progress = 1.0
                        await repo.save(task)
                        task = await domain.transition_status(task, TaskStatus.SUCCESS)
                    else:
                        task.error_message = (
                            "对账：worker 已结束（结果未可靠回写），按 reconcile-only 策略标记失败，"
                            "不会自动重提交"
                        )
                        task.progress = 1.0
                        await repo.save(task)
                        task = await domain.transition_status(task, TaskStatus.FAILED)
                    await domain.add_log(
                        model.id,
                        LogLevel.WARNING,
                        task.error_message or "对账恢复终态（未重新执行）",
                        source="reconcile",
                    )
                    await db.commit()
                    bucket = (
                        result["queued_recovered"] if backend_state == "SUCCESS" else result["queued_marked_failed"]
                    )
                    bucket.append(task_id)
                    continue

                in_queue = _celery_message_in_queue(task_id) if backend_state == "PENDING" else None
                if backend_state == "PENDING" and in_queue is False:
                    # 队列里已无此消息且 worker 从未开始：悬挂 pending，标记失败。
                    task = await repo.get_by_id(model.id)
                    if task is None or task.status != TaskStatus.QUEUED:
                        continue
                    task = await domain.transition_status(task, TaskStatus.RUNNING)
                    task.error_message = (
                        "对账：队列中已无此任务且 worker 未执行（消息丢失或 worker 异常），"
                        "按 reconcile-only 策略标记失败，不会自动重提交"
                    )
                    task.progress = 1.0
                    await repo.save(task)
                    await domain.transition_status(task, TaskStatus.FAILED)
                    await domain.add_log(
                        model.id, LogLevel.ERROR, task.error_message, source="reconcile"
                    )
                    await db.commit()
                    result["queued_marked_failed"].append(task_id)
                    logger.warning(
                        "[Studio] 对账标记悬挂长任务失败 task=%s（队列消息已丢失，未重提交）",
                        task_id,
                    )
                else:
                    # 仍在队列等待 / worker 执行中（STARTED）/ 无法确认：
                    # 按 reconcile-only 语义仅报告，保持 QUEUED 不动。
                    result["queued_still_pending"].append(task_id)
                    logger.info(
                        "[Studio] 对账：长任务仍 QUEUED task=%s backend=%s in_queue=%s，仅报告",
                        task_id,
                        backend_state,
                        in_queue,
                    )
            except Exception as exc:  # noqa: BLE001 - 单个失败不拖垮整批
                result["errors"] += 1
                await db.rollback()
                logger.exception("[Studio] 对账处理 QUEUED 任务失败 task=%s: %s", task_id, exc)

        stale_running = await _load_stale_running_models(db, running_cutoff)

        for model in stale_running:
            task_id = str(model.id)
            try:
                # RUNNING 滞留：沙盒容器可能仍在运行（对应 OpenAI4S unknown 刻意为 live），
                # 绝不改状态、绝不重提交，只报告漂移供人工排查。
                message = (
                    "对账：任务 RUNNING 超过对账阈值，worker 可能已丢失；"
                    "按 reconcile-only 策略仅报告，不改动状态、不自动重提交"
                )
                await domain.add_log(model.id, LogLevel.WARNING, message, source="reconcile")
                await db.commit()
                result["running_reported"].append(task_id)
                logger.warning("[Studio] 对账报告滞留 RUNNING 长任务 task=%s", task_id)
            except Exception as exc:  # noqa: BLE001 - 单个失败不拖垮整批
                result["errors"] += 1
                await db.rollback()
                logger.exception("[Studio] 对账处理 RUNNING 任务失败 task=%s: %s", task_id, exc)

    return result


@shared_task(name="cygnusx.infrastructure.celery_app.tasks.studio.recycle_idle_sandboxes")
def recycle_idle_sandboxes() -> dict[str, Any]:
    """每 5 分钟回收空闲超 TTL 的 Studio 沙盒容器（默认 30min）。"""
    return asyncio.run(_run_recycle())


async def _run_recycle() -> dict[str, Any]:
    from cygnusx.core.config import get_settings
    from cygnusx.infrastructure.studio.control_client import StudioControlClient
    from cygnusx.infrastructure.studio.manager import studio_sandbox_manager

    try:
        control_client = StudioControlClient()
        if get_settings().service_name == "worker" and control_client.enabled:
            count = await control_client.recycle_idle()
        else:
            count = await studio_sandbox_manager.recycle_idle()
        if count:
            logger.info("[Studio] 回收空闲沙盒 %s 个", count)
        return {"recycled": count}
    except Exception as exc:  # noqa: BLE001
        logger.error("[Studio] 空闲沙盒回收失败: %s", exc)
        return {"recycled": 0, "error": str(exc)}
