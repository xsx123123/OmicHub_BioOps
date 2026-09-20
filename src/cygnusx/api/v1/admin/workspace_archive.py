"""工作区归档管理后台（WP1）—— 管理员视角的归档总览 / 强制休眠 / 删包 / 配置热更。

所有路由 require_admin；配置写回走「临时文件 + os.replace」原子写，
依赖 studio.yaml 的 mtime 热重载即时生效。
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, select

from cygnusx.api.deps import CurrentUserId, DbSession
from cygnusx.application.services.workspace_archive_service import (
    delete_package,
    pack_session,
)
from cygnusx.infrastructure.celery_app.tasks.storage import _dir_size
from cygnusx.infrastructure.config.studio_loader import get_studio_config
from cygnusx.infrastructure.database.models.chat import ChatSessionModel
from cygnusx.infrastructure.database.models.user import UserModel
from cygnusx.infrastructure.database.models.workspace_archive import WorkspaceArchiveModel
from cygnusx.infrastructure.studio.manager import studio_sandbox_manager
from cygnusx.middleware.rbac import AdminRequired

router = APIRouter()


class WorkspaceArchiveConfigUpdate(BaseModel):
    workspace_gb: int | None = Field(default=None, ge=0)
    archive_gb: int | None = Field(default=None, ge=0)
    active_days: int | None = Field(default=None, ge=1)
    dormant_days: int | None = Field(default=None, ge=1)
    archive_retention_days: int | None = Field(default=None, ge=1)


# studio.yaml 顶层键路径（全部位于 studio: 段下，二级缩进）
_CONFIG_KEY_PATHS = {
    "workspace_gb": ("quota", "workspace_gb"),
    "archive_gb": ("quota", "archive_gb"),
    "active_days": ("retention", "active_days"),
    "dormant_days": ("retention", "dormant_days"),
    "archive_retention_days": ("archive", "retention_days"),
}


def _rewrite_studio_yaml(updates: dict[str, int]) -> None:
    """按行定向改写 studio.yaml 指定键（保留其他键与注释），原子写生效。

    策略：在二级 section（quota/retention/archive）内找三级键行替换值；
    键不存在时在 section 末尾插入。找不到 section / 结构非法时抛 HTTP 400。
    """
    # 从管理器单例取真实路径（避免与 get_settings().studio_config_yaml 漂移）
    from cygnusx.infrastructure.config.studio_loader import studio_config_manager

    config_path = Path(studio_config_manager.config_path)
    if not config_path.is_file():
        raise HTTPException(status_code=500, detail=f"配置文件不存在: {config_path}")

    lines = config_path.read_text(encoding="utf-8").splitlines()
    remaining = dict(updates)

    def _section_indent(name: str) -> int | None:
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped == f"{name}:" and line.startswith("  ") and not line.startswith("    "):
                return idx
        return None

    for key, (section, field_name) in _CONFIG_KEY_PATHS.items():
        if key not in remaining:
            continue
        section_idx = _section_indent(section)
        if section_idx is None:
            raise HTTPException(status_code=400, detail=f"studio.yaml 缺少段: {section}")
        # section 范围：到下一个同级二级段或文件尾
        end = len(lines)
        for idx in range(section_idx + 1, len(lines)):
            line = lines[idx]
            if line.strip() and not line.startswith("    ") and line.startswith("  "):
                end = idx
                break
        replaced = False
        for idx in range(section_idx + 1, end):
            stripped = lines[idx].strip()
            if stripped.startswith(f"{field_name}:"):
                prefix = lines[idx][: len(lines[idx]) - len(lines[idx].lstrip())]
                lines[idx] = f"{prefix}{field_name}: {remaining.pop(key)}"
                replaced = True
                break
        if not replaced:
            insert_at = end
            lines.insert(insert_at, f"    {field_name}: {remaining.pop(key)}")

    if remaining:
        raise HTTPException(status_code=400, detail=f"未知配置键: {sorted(remaining)}")

    # 原子写：同窗目录临时文件 + os.replace
    fd, tmp_name = tempfile.mkstemp(
        dir=str(config_path.parent), prefix=config_path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        os.replace(tmp_name, config_path)
    except OSError:
        os.unlink(tmp_name)
        raise
    logger.info("[Archive] studio.yaml 配置已更新: {}", updates)
    # 强制刷新缓存（mtime 热重载本就会生效，这里双保险）
    studio_config_manager.reload()


@router.get("/overview", summary="工作区归档总览")
async def workspace_archive_overview(
    _admin: AdminRequired,
    db: DbSession,
) -> dict[str, Any]:
    """归档总量 / 工作区总量 / 配额与保留参数 / 临近到期包 / 按用户细分。"""
    config = get_studio_config()
    now = datetime.now(UTC)

    archive_total_bytes, archive_total_packages = (
        await db.execute(
            select(
                func.coalesce(func.sum(WorkspaceArchiveModel.size_bytes), 0),
                func.count(),
            ).where(WorkspaceArchiveModel.deleted_at.is_(None))
        )
    ).one()

    workspace_root = config.workspace_root
    workspace_total_bytes = await asyncio.to_thread(
        _dir_size, workspace_root
    ) if workspace_root.is_dir() else 0

    soon_rows = (
        (
            await db.execute(
                select(WorkspaceArchiveModel).where(
                    WorkspaceArchiveModel.deleted_at.is_(None),
                    WorkspaceArchiveModel.expires_at < now + timedelta(days=7),
                )
            )
        )
        .scalars()
        .all()
    )
    user_ids = sorted({row.user_id for row in soon_rows})
    usernames = await _username_map(db, user_ids)
    expiring_soon = [
        {
            "package_id": str(row.id),
            "session_id": row.session_id,
            "username": usernames.get(row.user_id, row.user_id),
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        }
        for row in soon_rows
    ]

    # 按用户细分：归档字节/包数 + 工作区字节/会话数
    archive_rows = (
        (
            await db.execute(
                select(
                    WorkspaceArchiveModel.user_id,
                    func.coalesce(func.sum(WorkspaceArchiveModel.size_bytes), 0),
                    func.count(),
                )
                .where(WorkspaceArchiveModel.deleted_at.is_(None))
                .group_by(WorkspaceArchiveModel.user_id)
            )
        )
        .all()
    )
    session_rows = (
        (
            await db.execute(
                select(ChatSessionModel.user_id, ChatSessionModel.session_id).where(
                    ChatSessionModel.mode == "studio",
                    ChatSessionModel.status != "deleted",
                )
            )
        )
        .all()
    )
    sessions_by_user: dict[str, list[str]] = {}
    for user_id, session_id in session_rows:
        sessions_by_user.setdefault(str(user_id), []).append(session_id)

    per_user_map: dict[str, dict[str, Any]] = {}
    for user_id, archive_bytes, package_count in archive_rows:
        per_user_map.setdefault(user_id, {})
        per_user_map[user_id].update(
            {"archive_bytes": int(archive_bytes), "package_count": int(package_count)}
        )
    for user_id, session_ids in sessions_by_user.items():
        entry = per_user_map.setdefault(user_id, {})
        workspace_bytes = 0
        for session_id in session_ids:
            try:
                workspace = studio_sandbox_manager.workspace_dir(session_id)
            except Exception:  # noqa: BLE001
                continue
            if workspace.is_dir():
                workspace_bytes += await asyncio.to_thread(_dir_size, workspace)
        entry.update(
            {
                "workspace_bytes": workspace_bytes,
                "session_count": len(session_ids),
            }
        )
    all_user_ids = sorted(per_user_map)
    usernames_all = await _username_map(db, all_user_ids)
    per_user = [
        {
            "user_id": user_id,
            "username": usernames_all.get(user_id, user_id),
            "workspace_bytes": int(per_user_map[user_id].get("workspace_bytes", 0)),
            "archive_bytes": int(per_user_map[user_id].get("archive_bytes", 0)),
            "package_count": int(per_user_map[user_id].get("package_count", 0)),
            "session_count": int(per_user_map[user_id].get("session_count", 0)),
        }
        for user_id in all_user_ids
    ]

    return {
        "archive_total_bytes": int(archive_total_bytes or 0),
        "archive_total_packages": int(archive_total_packages or 0),
        "workspace_total_bytes": int(workspace_total_bytes),
        "active_days": int(config.retention.active_days),
        "dormant_days": int(config.retention.dormant_days),
        "archive_retention_days": int(config.archive.retention_days),
        "quota": {
            "workspace_gb": int(config.quota.workspace_gb),
            "archive_gb": int(config.quota.archive_gb),
        },
        "expiring_soon": expiring_soon,
        "per_user": per_user,
    }


async def _username_map(db: Any, user_ids: list[str]) -> dict[str, str]:
    """user_id(str uuid) → username；查不到的回退原值。"""
    if not user_ids:
        return {}
    result = await db.execute(
        select(cast(UserModel.id, String), UserModel.username).where(
            cast(UserModel.id, String).in_(user_ids)
        )
    )
    return {row[0]: row[1] for row in result.all()}


@router.post("/sessions/{session_id}/dormant", summary="强制休眠指定会话（打包归档）")
async def force_dormant_session(
    current_user_id: CurrentUserId,
    _admin: AdminRequired,
    db: DbSession,
    session_id: str,
) -> dict[str, Any]:
    """管理员强制打包会话工作区（不受属主限制；busy 返回 409）。"""
    return await pack_session(db, session_id, current_user_id, is_admin=True)


@router.delete("/packages/{package_id}", summary="删除归档包")
async def remove_archive_package(
    current_user_id: CurrentUserId,
    _admin: AdminRequired,
    db: DbSession,
    package_id: str,
) -> dict[str, Any]:
    """删除归档包文件 + deleted_at 落库 + 清 sandbox_meta 标记。"""
    return await delete_package(db, package_id, current_user_id)


@router.put("/config", summary="更新工作区归档配置（热生效）")
async def update_workspace_archive_config(
    current_user_id: CurrentUserId,
    _admin: AdminRequired,
    db: DbSession,
    req: WorkspaceArchiveConfigUpdate,
) -> dict[str, Any]:
    """更新 studio.yaml 的 quota/retention/archive 段；原子写 + mtime 热重载。"""
    updates = {
        key: value
        for key, value in req.model_dump(exclude_none=True).items()
        if value is not None
    }
    if not updates:
        raise HTTPException(status_code=400, detail="无可更新字段")
    _rewrite_studio_yaml(updates)

    import uuid as uuid_module

    from cygnusx.infrastructure.database.models.audit_log import AuditLogModel

    db.add(
        AuditLogModel(
            id=uuid_module.uuid4(),
            user_id=uuid_module.UUID(current_user_id),
            username=None,
            method="PUT",
            path="/api/v1/admin/workspace-archive/config",
            resource_type="workspace_archive",
            resource_id="config",
            status_code=200,
            detail={"event": "workspace_archive_config_updated", "updates": updates},
        )
    )
    await db.commit()
    config = get_studio_config()
    return {
        "updated": updates,
        "quota": {
            "workspace_gb": int(config.quota.workspace_gb),
            "archive_gb": int(config.quota.archive_gb),
        },
        "active_days": int(config.retention.active_days),
        "dormant_days": int(config.retention.dormant_days),
        "archive_retention_days": int(config.archive.retention_days),
    }
