"""工作区归档服务（WP1 会话工作区生命周期）。

职责：
- pack_session：会话工作区整目录 tar.gz 打包 → 平台侧归档存储 → 删本地工作区
  → sandbox_meta 打 workspace_archive 标记（jsonb_set 原子合并）→ 项目 AGENTS.md
  幂等追加 → audit_logs；配额超限显式拒绝（error 日志 + 审计，绝不静默）。
- unpack_session：归档包解回工作区目录（防 tar 路径逃逸、manifest 校验）→ 清
  sandbox_meta 标记 → restored_at 落库；不做任何容器操作（懒启动由现有链路触发）。

sandbox_meta 写入一律走 jsonb_set 原子合并（api/v1/studio.py 同款写法），
禁止读-改-写整列回写（曾发生并发覆盖事故）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.core.exceptions import BusinessError, ConflictError, CygnusXError, NotFoundError
from cygnusx.infrastructure.celery_app.tasks.storage import _dir_size
from cygnusx.infrastructure.config.studio_loader import get_studio_config
from cygnusx.infrastructure.database.models.audit_log import AuditLogModel
from cygnusx.infrastructure.database.models.chat import ChatSessionModel
from cygnusx.infrastructure.database.models.project import ProjectModel
from cygnusx.infrastructure.database.models.workspace_archive import WorkspaceArchiveModel
from cygnusx.infrastructure.studio.archive_storage import (
    ArchiveStorageError,
    LocalArchiveStorage,
    get_archive_storage,
)
from cygnusx.infrastructure.studio.manager import studio_sandbox_manager

ANALYSIS_LOG_HEADING = "## 分析记录"
_ARCHIVE_LOG_TABLE_HEADER = (
    "| 时间 | 运行目录 | 分析类型 | 状态 | 摘要 |\n| --- | --- | --- | --- | --- |"
)
_ARCHIVE_ANALYSIS_TYPE = "工作区归档"


class WorkspaceArchiveQuotaError(CygnusXError):
    """归档/工作区配额超限。"""

    status_code = 409


class WorkspaceArchiveBusyError(CygnusXError):
    """会话沙盒忙碌，禁止打包。"""

    status_code = 409


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _archive_marker(session: ChatSessionModel) -> dict[str, Any] | None:
    marker = (session.sandbox_meta or {}).get("workspace_archive")
    return dict(marker) if isinstance(marker, dict) else None


async def _active_package(db: AsyncSession, session_id: str) -> WorkspaceArchiveModel | None:
    """该会话当前 active 的归档包（未删除且未恢复），幂等判重依据。"""
    result = await db.execute(
        select(WorkspaceArchiveModel)
        .where(
            WorkspaceArchiveModel.session_id == session_id,
            WorkspaceArchiveModel.deleted_at.is_(None),
            WorkspaceArchiveModel.restored_at.is_(None),
        )
        .order_by(WorkspaceArchiveModel.created_at.desc())
    )
    return result.scalars().first()


async def _user_archive_bytes(db: AsyncSession, user_id: str) -> int:
    """用户未删除归档包总字节数。"""
    result = await db.execute(
        select(func.coalesce(func.sum(WorkspaceArchiveModel.size_bytes), 0)).where(
            WorkspaceArchiveModel.user_id == user_id,
            WorkspaceArchiveModel.deleted_at.is_(None),
        )
    )
    return int(result.scalar_one() or 0)


def _user_workspace_bytes(user_id: str, sessions: list[ChatSessionModel]) -> int:
    """该用户所有 studio 会话工作区目录总字节数（已归档的目录已删除，天然不计）。"""
    total = 0
    for session in sessions:
        try:
            workspace = studio_sandbox_manager.workspace_dir(session.session_id)
        except Exception:  # noqa: BLE001 - 非法 session_id 跳过
            continue
        if workspace.is_dir():
            total += _dir_size(workspace)
    return total


async def _write_audit(
    db: AsyncSession,
    *,
    operator: str,
    method: str,
    path: str,
    resource_id: str,
    status_code: int,
    detail: dict[str, Any],
) -> None:
    """audit_logs 直写（无 service 封装，同 middleware 口径）。"""
    user_uuid: uuid.UUID | None = None
    with contextlib.suppress(ValueError):
        user_uuid = uuid.UUID(operator)
    db.add(
        AuditLogModel(
            id=uuid.uuid4(),
            user_id=user_uuid,
            username=None if user_uuid else operator,
            method=method,
            path=path,
            resource_type="workspace_archive",
            resource_id=resource_id,
            status_code=status_code,
            detail=detail,
        )
    )


async def _set_archive_marker(
    db: AsyncSession, session_id: str, marker: dict[str, Any] | None
) -> None:
    """sandbox_meta.workspace_archive 原子写入；marker=None 时删除该键。"""
    if marker is None:
        await db.execute(
            sql_text(
                "UPDATE chat_sessions SET sandbox_meta = "
                "COALESCE(sandbox_meta, '{}'::jsonb) - 'workspace_archive', "
                "updated_at = now() WHERE session_id = :sid"
            ),
            {"sid": session_id},
        )
    else:
        await db.execute(
            sql_text(
                "UPDATE chat_sessions SET sandbox_meta = jsonb_set("
                "COALESCE(sandbox_meta, '{}'::jsonb), '{workspace_archive}', "
                "CAST(:marker AS jsonb), true), updated_at = now() WHERE session_id = :sid"
            ),
            {"marker": json.dumps(marker, ensure_ascii=False), "sid": session_id},
        )
    await db.flush()


# ------------------------------------------------------------------
# 项目级 AGENTS.md 幂等追加（参照 project_archive_service 的 marker 去重模式）
# ------------------------------------------------------------------


def _one_line(text: str, *, limit: int = 500) -> str:
    collapsed = " ".join(str(text or "").split())
    collapsed = collapsed.replace("|", "\\|")
    if len(collapsed) > limit:
        collapsed = collapsed[: limit - 1] + "…"
    return collapsed or "（无）"


def append_workspace_archive_entry(
    content: str,
    *,
    marker: str,
    timestamp: str,
    line: str,
) -> tuple[str, bool]:
    """向项目 AGENTS.md「分析记录」追加归档行；marker 已存在时幂等跳过。"""
    if marker in content:
        return content, False
    row = f"| {timestamp} | `{marker}` | {_one_line(_ARCHIVE_ANALYSIS_TYPE, limit=40)} | 完成 | {_one_line(line)} |"
    if ANALYSIS_LOG_HEADING not in content:
        content = content.rstrip() + f"\n\n{ANALYSIS_LOG_HEADING}\n\n{_ARCHIVE_LOG_TABLE_HEADER}\n"
        return content + row + "\n", True
    return content.rstrip() + "\n" + row + "\n", True


async def _append_project_agents_md(
    db: AsyncSession,
    *,
    session: ChatSessionModel,
    package_id: str,
    package_path: str,
    manifest_sha256: str,
) -> None:
    """项目级 AGENTS.md 幂等追加归档条目；无项目 / 项目记录缺失时静默跳过。"""
    project_id = str(session.project_id or "")
    if not project_id:
        return
    project = await db.get(ProjectModel, uuid.UUID(project_id))
    if project is None or str(project.user_id) != str(session.user_id):
        return
    from cygnusx.infrastructure.storage import get_path_factory

    factory = get_path_factory()
    agents_path = factory.project_dir(str(session.user_id), project.slug) / "AGENTS.md"
    marker = f"workspace-archive/{package_id}"
    try:
        content = agents_path.read_text(encoding="utf-8") if agents_path.is_file() else ""
        if not content:
            # 没有既有 AGENTS.md 时生成最小骨架（与 project_archive_service 同构）
            lines = [
                f"# {project.name}",
                "",
                "> 本文件由 CygnusX 平台自动生成与维护：每次分析归档时追加运行记录，请勿手工删除条目。",
                "",
                f"- 项目: {project.name}",
                f"- 客户: {project.customer or '未填写'}",
                f"- 描述: {project.description or '（无）'}",
                f"- 项目目录: `projects/{project.slug}/`",
                "",
            ]
            content = "\n".join(lines)
        line = (
            f"会话 {session.session_id} 于 {_utcnow().isoformat()} 归档，"
            f"包路径 {package_path}，manifest sha256 {manifest_sha256}"
        )
        content, appended = append_workspace_archive_entry(
            content, marker=marker, timestamp=_utcnow().isoformat(), line=line
        )
        if appended:
            agents_path.parent.mkdir(parents=True, exist_ok=True)
            agents_path.write_text(content, encoding="utf-8")
    except OSError as exc:
        # AGENTS.md 是增强动作，失败不阻断归档主流程
        logger.warning("[Archive] 项目 AGENTS.md 追加失败（跳过）: {}", exc)


# ------------------------------------------------------------------
# 打包 / 解包
# ------------------------------------------------------------------


async def pack_session(
    db: AsyncSession,
    session_id: str,
    operator: str,
    *,
    is_admin: bool = False,
) -> dict[str, Any]:
    """打包会话工作区：tar.gz 归档 + 删本地目录 + 打标记。

    幂等：已有 active 包（未删除且未恢复）直接返回；sandbox 忙碌拒绝。
    """
    started = _utcnow()
    config = get_studio_config()
    session = await db.scalar(
        select(ChatSessionModel).where(ChatSessionModel.session_id == session_id)
    )
    if session is None:
        raise NotFoundError(f"会话不存在：{session_id}")
    if session.mode != "studio":
        raise BusinessError("仅 studio 模式会话支持工作区归档")
    if not is_admin and str(session.user_id) != str(operator):
        raise NotFoundError("会话不存在或无权访问")

    existing = await _active_package(db, session_id)
    if existing is not None:
        logger.info("[Archive] 会话 {} 已有 active 归档包 {}，幂等返回", session_id[:12], existing.id)
        return {
            "packed": True,
            "idempotent": True,
            "package_id": str(existing.id),
            "package_path": existing.package_path,
            "size_bytes": existing.size_bytes,
            "manifest_sha256": existing.manifest_sha256,
            "created_at": existing.created_at.isoformat() if existing.created_at else None,
            "expires_at": existing.expires_at.isoformat() if existing.expires_at else None,
        }

    # 复核非 busy：先走 hibernate（空闲即回收容器、保留工作区），忙碌则拒绝
    hibernate_result = await studio_sandbox_manager.hibernate(session_id)
    if hibernate_result == "busy":
        await _write_audit(
            db,
            operator=operator,
            method="POST",
            path=f"/api/v1/admin/workspace-archive/sessions/{session_id}/dormant",
            resource_id=session_id,
            status_code=409,
            detail={"event": "workspace_archive_pack_rejected", "session_id": session_id, "reason": "busy"},
        )
        await db.commit()
        raise WorkspaceArchiveBusyError("会话正在执行任务，无法休眠打包")

    workspace = studio_sandbox_manager.workspace_dir(session_id)
    if not workspace.is_dir():
        raise BusinessError(f"工作区目录不存在，无可归档内容: {workspace}")

    # 配额：该用户归档总用量 + 本包预估 > quota.archive_gb → 显式拒绝
    estimate = _dir_size(workspace)
    used = await _user_archive_bytes(db, str(session.user_id))
    quota_bytes = int(config.quota.archive_gb) * 1024**3
    if quota_bytes > 0 and used + estimate > quota_bytes:
        reason = (
            f"归档配额不足：已用 {used} bytes + 本包预估 {estimate} bytes "
            f"> 配额 {quota_bytes} bytes (archive_gb={config.quota.archive_gb})"
        )
        logger.error("[Archive] 会话 {} 打包被拒: {}", session_id[:12], reason)
        await _write_audit(
            db,
            operator=operator,
            method="POST",
            path=f"/api/v1/admin/workspace-archive/sessions/{session_id}/dormant",
            resource_id=session_id,
            status_code=409,
            detail={
                "event": "workspace_archive_pack_rejected",
                "session_id": session_id,
                "reason": "archive_quota_exceeded",
                "detail": reason,
                "used_bytes": used,
                "estimate_bytes": estimate,
                "quota_bytes": quota_bytes,
            },
        )
        await db.commit()
        raise WorkspaceArchiveQuotaError(reason)

    storage = get_archive_storage(config)
    created_at = _utcnow()
    try:
        package = await asyncio.to_thread(
            storage.save_package, str(session.user_id), session_id, workspace, created_at=created_at
        )
    except ArchiveStorageError as exc:
        logger.error("[Archive] 会话 {} 打包失败（工作区保留）: {}", session_id[:12], exc)
        raise BusinessError(f"打包失败：{exc}") from exc

    retention_days = max(1, int(config.archive.retention_days))
    record = WorkspaceArchiveModel(
        id=uuid.uuid4(),
        session_id=session_id,
        user_id=str(session.user_id),
        package_path=str(package.path),
        size_bytes=package.size_bytes,
        manifest_sha256=package.manifest_sha256,
        created_at=created_at,
        expires_at=created_at + timedelta(days=retention_days),
    )
    db.add(record)
    await db.flush()

    # 打包成功才删本地工作区（manager 级别路径防护）
    removed = await asyncio.to_thread(
        studio_sandbox_manager.remove_workspace, session_id
    )
    if not removed:
        logger.warning("[Archive] 会话 {} 工作区删除未生效（可能已不存在）", session_id[:12])

    await _set_archive_marker(
        db,
        session_id,
        {
            "package_id": str(record.id),
            "created_at": created_at.isoformat(),
            "expires_at": record.expires_at.isoformat(),
        },
    )
    await _append_project_agents_md(
        db,
        session=session,
        package_id=str(record.id),
        package_path=str(package.path),
        manifest_sha256=package.manifest_sha256,
    )
    duration_ms = int((_utcnow() - started).total_seconds() * 1000)
    await _write_audit(
        db,
        operator=operator,
        method="POST",
        path=f"/api/v1/admin/workspace-archive/sessions/{session_id}/dormant",
        resource_id=session_id,
        status_code=200,
        detail={
            "event": "workspace_archive_packed",
            "session_id": session_id,
            "package_id": str(record.id),
            "size_bytes": package.size_bytes,
            "duration_ms": duration_ms,
            "manifest_sha256": package.manifest_sha256,
            "manifest_file_count": package.manifest.get("file_count"),
            "missing_env_snapshot": (package.manifest.get("env_snapshot") or {}).get(
                "missing_env_snapshot"
            ),
        },
    )
    await db.commit()
    logger.info(
        "[Archive] 会话 {} 归档完成 package={} size={} duration_ms={}",
        session_id[:12],
        record.id,
        package.size_bytes,
        duration_ms,
    )
    return {
        "packed": True,
        "package_id": str(record.id),
        "package_path": str(package.path),
        "size_bytes": package.size_bytes,
        "manifest_sha256": package.manifest_sha256,
        "created_at": created_at.isoformat(),
        "expires_at": record.expires_at.isoformat(),
        "duration_ms": duration_ms,
    }


async def unpack_session(
    db: AsyncSession,
    session_id: str,
    operator: str,
) -> dict[str, Any]:
    """解包归档恢复工作区目录；幂等；不做任何容器操作。"""
    started = _utcnow()
    config = get_studio_config()
    session = await db.scalar(
        select(ChatSessionModel).where(ChatSessionModel.session_id == session_id)
    )
    if session is None:
        raise NotFoundError(f"会话不存在：{session_id}")
    if session.mode != "studio":
        raise BusinessError("仅 studio 模式会话支持工作区恢复")
    if str(session.user_id) != str(operator):
        raise NotFoundError("会话不存在或无权访问")

    marker = _archive_marker(session)
    record = await _active_package(db, session_id)
    if record is None:
        # 无 active 包：曾恢复过 → 幂等成功；从未归档 → not_archived；
        # 标记在但包被删 → 明确冲突
        restored = await db.scalar(
            select(WorkspaceArchiveModel).where(
                WorkspaceArchiveModel.session_id == session_id,
                WorkspaceArchiveModel.restored_at.is_not(None),
            )
        )
        if restored is not None:
            return {"restored": True, "idempotent": True}
        if not marker:
            return {"restored": False, "reason": "not_archived"}
        raise ConflictError("归档包已被删除，无法恢复")

    storage = get_archive_storage(config)
    if not storage.exists(Path(record.package_path)):
        raise ConflictError(f"归档包文件缺失: {record.package_path}")

    # 配额：该用户工作区总占用 + 本包大小 > quota.workspace_gb → 409
    user_sessions = list(
        (
            await db.execute(
                select(ChatSessionModel).where(
                    ChatSessionModel.user_id == str(session.user_id),
                    ChatSessionModel.mode == "studio",
                )
            )
        )
        .scalars()
        .all()
    )
    workspace_used = _user_workspace_bytes(str(session.user_id), user_sessions)
    quota_bytes = int(config.quota.workspace_gb) * 1024**3
    if quota_bytes > 0 and workspace_used + record.size_bytes > quota_bytes:
        reason = (
            f"工作区配额不足：已用 {workspace_used} bytes + 恢复包 {record.size_bytes} bytes "
            f"> 配额 {quota_bytes} bytes (workspace_gb={config.quota.workspace_gb})"
        )
        logger.error("[Archive] 会话 {} 恢复被拒: {}", session_id[:12], reason)
        await _write_audit(
            db,
            operator=operator,
            method="POST",
            path=f"/api/v1/studio/sessions/{session_id}/restore",
            resource_id=session_id,
            status_code=409,
            detail={
                "event": "workspace_archive_restore_rejected",
                "session_id": session_id,
                "reason": "workspace_quota_exceeded",
                "detail": reason,
                "used_bytes": workspace_used,
                "package_bytes": record.size_bytes,
                "quota_bytes": quota_bytes,
            },
        )
        await db.commit()
        raise WorkspaceArchiveQuotaError(reason)

    workspace = studio_sandbox_manager.workspace_dir(session_id)
    studio_sandbox_manager.ensure_workspace_dirs(workspace)
    extract = await asyncio.to_thread(
        LocalArchiveStorage.extract_workspace, Path(record.package_path), workspace
    )
    if extract["skipped_members"]:
        logger.warning(
            "[Archive] 会话 {} 解包跳过 {} 个非法成员: {}",
            session_id[:12],
            len(extract["skipped_members"]),
            extract["skipped_members"][:5],
        )
    if extract["sha256_mismatch"]:
        logger.warning(
            "[Archive] 会话 {} 解包 {} 个文件 manifest 校验不一致（位腐需人工核查）: {}",
            session_id[:12],
            len(extract["sha256_mismatch"]),
        )

    restored_at = _utcnow()
    record.restored_at = restored_at
    await _set_archive_marker(db, session_id, None)
    duration_ms = int((_utcnow() - started).total_seconds() * 1000)
    await _write_audit(
        db,
        operator=operator,
        method="POST",
        path=f"/api/v1/studio/sessions/{session_id}/restore",
        resource_id=session_id,
        status_code=200,
        detail={
            "event": "workspace_archive_restored",
            "session_id": session_id,
            "package_id": str(record.id),
            "extracted_files": extract["extracted_files"],
            "skipped_members": extract["skipped_members"],
            "sha256_mismatch": extract["sha256_mismatch"],
            "duration_ms": duration_ms,
        },
    )
    await db.commit()
    logger.info(
        "[Archive] 会话 {} 恢复完成 package={} files={} duration_ms={}",
        session_id[:12],
        record.id,
        extract["extracted_files"],
        duration_ms,
    )
    return {"restored": True, "package_id": str(record.id), "extracted_files": extract["extracted_files"]}


async def delete_package(
    db: AsyncSession,
    package_id: str,
    operator: str,
) -> dict[str, Any]:
    """删除归档包（admin）：删文件 + deleted_at 落库 + 清 sandbox_meta 标记。"""
    record = await db.get(WorkspaceArchiveModel, uuid.UUID(package_id))
    if record is None:
        raise NotFoundError(f"归档包不存在：{package_id}")
    config = get_studio_config()
    storage = get_archive_storage(config)
    deleted_file = await asyncio.to_thread(
        storage.delete_package, Path(record.package_path)
    )
    record.deleted_at = _utcnow()
    # 清标记：仅当 sandbox_meta 指向当前包时才清（原子删除键）
    await db.execute(
        sql_text(
            "UPDATE chat_sessions SET sandbox_meta = "
            "COALESCE(sandbox_meta, '{}'::jsonb) - 'workspace_archive', "
            "updated_at = now() WHERE session_id = :sid AND "
            "sandbox_meta->'workspace_archive'->>'package_id' = :pid"
        ),
        {"sid": record.session_id, "pid": package_id},
    )
    await _write_audit(
        db,
        operator=operator,
        method="DELETE",
        path=f"/api/v1/admin/workspace-archive/packages/{package_id}",
        resource_id=package_id,
        status_code=200,
        detail={
            "event": "workspace_archive_deleted",
            "package_id": package_id,
            "session_id": record.session_id,
            "package_path": record.package_path,
            "deleted_file": deleted_file,
        },
    )
    await db.commit()
    return {"deleted": True, "package_id": package_id, "deleted_file": deleted_file}
