"""存储生命周期任务 — 空间对账 / 过期清理 / 冷数据归档

每日凌晨由 Celery Beat 触发，修复异常中断导致的 used_storage 偏差，
并按保留策略清理临时文件与归档冷数据。
"""

from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from celery import shared_task

from omichub.core.config import get_settings


@shared_task(name="omichub.infrastructure.celery_app.tasks.storage.reconcile_used_storage")
def reconcile_used_storage() -> dict:
    """空间使用量自动校准对账：盘点各用户物理目录真实大小，校正 used_storage。

    修复：上传中断未合并、删除文件未扣减、手工放入文件等导致的统计偏差。
    """
    return asyncio.run(_reconcile_used_storage())


async def _reconcile_used_storage() -> dict:
    from sqlalchemy import select, update

    from omichub.infrastructure.database.models.user import UserModel
    from omichub.infrastructure.database.session import get_session_factory

    settings = get_settings()
    users_root = Path(settings.storage_path) / "users"
    session_factory = get_session_factory()

    reconciled = 0
    async with session_factory() as session:
        result = await session.execute(select(UserModel.id))
        user_ids = [row[0] for row in result.all()]

        for user_id in user_ids:
            user_dir = users_root / str(user_id)
            actual = _dir_size(user_dir) if user_dir.exists() else 0
            await session.execute(
                update(UserModel).where(UserModel.id == user_id).values(used_storage=actual)
            )
            reconciled += 1

        await session.commit()

    return {"status": "ok", "reconciled_users": reconciled}


@shared_task(name="omichub.infrastructure.celery_app.tasks.storage.cleanup_expired")
def cleanup_expired() -> dict:
    """过期结果归档与清理：僵尸会话 + 临时文件 + 冷数据归档。

    策略（受 core/config 控制）：
    - 超 24h 的 pending/uploading 上传会话：删会话 + 清临时分片；
    - 超 file_temp_retention_days 的临时/中间文件：删除；
    - 超 file_archive_retention_days 的 active 结果文件：按 file_archive_mode 归档或删除。
    """
    return asyncio.run(_cleanup_expired())


async def _cleanup_expired() -> dict:
    from sqlalchemy import select

    from omichub.core.config import get_settings
    from omichub.infrastructure.database.models.file import (
        FileRecordModel,
        UploadSessionModel,
    )
    from omichub.infrastructure.database.session import get_session_factory

    settings = get_settings()
    storage_root = Path(settings.storage_path)
    now = datetime.utcnow()
    session_timeout = now - timedelta(hours=settings.file_upload_session_timeout_hours)
    temp_cutoff = now - timedelta(days=settings.file_temp_retention_days)
    archive_cutoff = now - timedelta(days=settings.file_archive_retention_days)

    session_factory = get_session_factory()
    expired_sessions = 0
    expired_files = 0
    archived_files = 0

    async with session_factory() as session:
        # 1) 僵尸上传会话：删会话记录 + 清临时分片目录
        result = await session.execute(
            select(UploadSessionModel).where(
                UploadSessionModel.status.in_(["pending", "uploading"]),
                UploadSessionModel.updated_at < session_timeout,
            )
        )
        for sm in result.scalars().all():
            shutil.rmtree(storage_root / ".tmp" / str(sm.id), ignore_errors=True)
            await session.delete(sm)
            expired_sessions += 1

        # 2) 临时/中间文件（status 标记为 temp 或 uploading 的 FileRecord）超期清理
        result = await session.execute(
            select(FileRecordModel).where(
                FileRecordModel.status.in_(["uploading", "temp"]),
                FileRecordModel.created_at < temp_cutoff,
            )
        )
        for fm in result.scalars().all():
            _safe_unlink(storage_root / fm.storage_path)
            await session.delete(fm)
            expired_files += 1

        # 3) 冷数据：超期未活跃的 active 结果文件归档或删除
        result = await session.execute(
            select(FileRecordModel).where(
                FileRecordModel.status == "active",
                FileRecordModel.created_at < archive_cutoff,
            )
        )
        for fm in result.scalars().all():
            if settings.file_archive_mode == "delete":
                _safe_unlink(storage_root / fm.storage_path)
                await session.delete(fm)
                expired_files += 1
            else:  # archive
                archive_dir = storage_root / "archive" / str(fm.user_id)
                archive_dir.mkdir(parents=True, exist_ok=True)
                src = storage_root / fm.storage_path
                if src.exists():
                    shutil.move(str(src), str(archive_dir / src.name))
                fm.status = "archived"
                archived_files += 1

        await session.commit()

    return {
        "status": "ok",
        "expired_sessions": expired_sessions,
        "expired_files": expired_files,
        "archived_files": archived_files,
    }


def _dir_size(path: Path) -> int:
    """递归统计目录真实占用字节数"""
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                continue
    return total


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass
