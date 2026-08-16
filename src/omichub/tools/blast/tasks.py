"""BLAST 工具 Celery 任务。

任务命名：
- omichub.tools.blast.tasks.run_blast_search
- omichub.tools.blast.tasks.build_blast_database

路由队列：
- blast_search
- blast_db_build
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select

from omichub.core.config import get_settings
from omichub.infrastructure.database.models.blast import BlastDatabaseModel, BlastTaskModel
from omichub.infrastructure.database.session import get_session_factory
from omichub.tools.blast.cache import build_result_cache_key, set_cached_result
from omichub.tools.blast.core import build_blast_database, run_blast_search
from omichub.tools.blast.events import publish_blast_event, publish_blast_event_sync

logger = logging.getLogger(__name__)


def _get_db_session() -> Any:
    """获取异步数据库会话工厂。"""
    return get_session_factory()


@shared_task(  # type: ignore[untyped-decorator]
    bind=True,
    name="omichub.tools.blast.tasks.run_blast_search",
    time_limit=3600,
    soft_time_limit=3000,
    max_retries=1,
    default_retry_delay=30,
    queue="blast_search",
    ignore_result=True,
)
def run_blast_search_task(self: Any, task_id: str) -> dict[str, Any]:
    """执行 BLAST 查询任务。"""

    async def _run() -> dict[str, Any]:
        factory = _get_db_session()
        async with factory() as db:
            task = await _get_task(db, task_id)
            if not task:
                await publish_blast_event(task_id, "failed", 0, "任务不存在")
                return {"status": "FAILED", "error": f"任务不存在: {task_id}"}
            if task.status == "cancelled":
                await publish_blast_event(task_id, "cancelled", task.progress, "任务已取消")
                return {"status": "CANCELLED", "task_id": task_id}

            db_model = await db.get(BlastDatabaseModel, task.db_id)
            if not db_model or db_model.build_status != "ready":
                task.status = "failed"
                task.error_message = "目标数据库不可用"
                task.completed_at = datetime.utcnow()
                await db.commit()
                await publish_blast_event(
                    task_id, "failed", 0, "目标数据库不可用", error_message=task.error_message
                )
                return {"status": "FAILED", "error": "目标数据库不可用"}

            task.status = "running"
            task.started_at = datetime.utcnow()
            task.progress = 10
            task.error_message = None
            await db.commit()
            await publish_blast_event(task_id, "running", 10, "BLAST 任务开始执行")

            query_file_path = Path(task.query_file_path or "")
            if query_file_path.name == "query.fasta" and query_file_path.parent.name == "input":
                result_dir = query_file_path.parent.parent / "output"
            else:
                settings = get_settings()
                result_dir = (
                    Path(settings.storage_path)
                    / settings.blast_results_dir
                    / str(task.user_id)
                    / task_id
                )

            def progress_callback(phase: str, progress: int, message: str) -> None:
                publish_blast_event_sync(task_id, phase, int(progress), message)

            try:
                result = run_blast_search(
                    task_id=task_id,
                    user_id=str(task.user_id),
                    program=task.program,
                    query_sequence=task.query_sequence,
                    query_title=task.query_title or "query",
                    db_path=db_model.file_path,
                    evalue=task.evalue,
                    max_target_seqs=task.max_target_seqs,
                    word_size=task.word_size,
                    gapopen=task.gapopen,
                    gapextend=task.gapextend,
                    work_dir=result_dir,
                    progress_callback=progress_callback,
                )

                await db.refresh(task)
                if task.status == "cancelled":
                    await publish_blast_event(task_id, "cancelled", task.progress, "任务已取消")
                    return {"status": "CANCELLED", "task_id": task_id}

                task.status = "completed"
                task.completed_at = datetime.utcnow()
                task.progress = 100
                task.result_path = result.get("xml_path")
                xml_path = Path(task.result_path) if task.result_path else None
                task.result_size_kb = (
                    int(xml_path.stat().st_size / 1024) if xml_path and xml_path.exists() else None
                )
                task.hit_count = result.get("hit_count")
                task.top_hit_identity = result.get("top_hit_identity")
                task.top_hit_evalue = result.get("top_hit_evalue")
                await db.commit()

                cache_key = build_result_cache_key(
                    db_id=str(db_model.id),
                    db_version=_database_cache_version(db_model),
                    program=task.program,
                    query_sequence=task.query_sequence,
                    evalue=task.evalue,
                    max_target_seqs=task.max_target_seqs,
                    word_size=task.word_size,
                    gapopen=task.gapopen,
                    gapextend=task.gapextend,
                )
                await set_cached_result(
                    cache_key,
                    {
                        "result_path": task.result_path,
                        "result_size_kb": task.result_size_kb,
                        "hit_count": task.hit_count,
                        "top_hit_identity": task.top_hit_identity,
                        "top_hit_evalue": task.top_hit_evalue,
                    },
                )
                await publish_blast_event(task_id, "completed", 100, "BLAST 比对完成")
                return result

            except SoftTimeLimitExceeded:
                task.status = "failed"
                task.error_message = "任务执行超时"
                task.completed_at = datetime.utcnow()
                await db.commit()
                await publish_blast_event(
                    task_id,
                    "failed",
                    task.progress,
                    "任务执行超时",
                    error_message=task.error_message,
                )
                raise
            except Exception as exc:
                logger.exception("BLAST 任务执行失败")
                task.error_message = str(exc)
                if self.request.retries < self.max_retries:
                    task.status = "queued"
                    task.progress = 0
                    await db.commit()
                    await publish_blast_event(
                        task_id,
                        "queued",
                        0,
                        "执行失败，等待自动重试",
                        error_message=task.error_message,
                    )
                    raise self.retry(exc=exc) from exc

                task.status = "failed"
                task.completed_at = datetime.utcnow()
                await db.commit()
                await publish_blast_event(
                    task_id,
                    "failed",
                    task.progress,
                    "BLAST 任务执行失败",
                    error_message=task.error_message,
                )
                raise

    return asyncio.run(_run())


@shared_task(  # type: ignore[untyped-decorator]
    bind=True,
    name="omichub.tools.blast.tasks.build_blast_database",
    time_limit=3600 * 2,
    soft_time_limit=3600,
    max_retries=1,
    default_retry_delay=30,
    queue="blast_db_build",
    ignore_result=True,
)
def build_blast_database_task(self: Any, db_id: str) -> dict[str, Any]:
    """执行 makeblastdb 构建数据库索引。"""

    async def _run() -> dict[str, Any]:
        factory = _get_db_session()
        async with factory() as db:
            db_model = await db.get(BlastDatabaseModel, __import__("uuid").UUID(db_id))
            if not db_model:
                return {"status": "FAILED", "error": f"数据库不存在: {db_id}"}

            db_model.build_status = "building"
            await db.commit()

            db_dir = Path(db_model.file_path).parent
            source_fasta = db_dir / f"{db_model.db_key}.fasta"
            settings = get_settings()
            timeout = settings.blast_build_timeout

            try:
                result = build_blast_database(
                    db_dir=db_dir,
                    db_key=db_model.db_key,
                    db_type=db_model.db_type,
                    source_fasta=source_fasta,
                    timeout=timeout,
                )

                sibling_result = await db.execute(
                    select(BlastDatabaseModel).where(
                        BlastDatabaseModel.version_group == db_model.version_group,
                        BlastDatabaseModel.id != db_model.id,
                    )
                )
                for sibling in sibling_result.scalars().all():
                    sibling.is_active = False

                db_model.build_status = "ready"
                db_model.is_active = True
                db_model.sequence_count = result.get("sequence_count", 0)
                db_model.file_size_mb = result.get("file_size_mb", 0.0)
                db_model.build_log = result.get("build_log")
                await db.commit()

                # 构建完成/失败后同步 YAML
                try:
                    from omichub.tools.blast.yaml_sync import blast_db_yaml_manager

                    all_models = (await db.execute(select(BlastDatabaseModel))).scalars().all()
                    blast_db_yaml_manager.sync_from_models(list(all_models))
                except Exception:
                    logger.exception("构建任务完成后同步 blast_db.yaml 失败")

                return result

            except Exception as exc:
                logger.exception("构建 BLAST 数据库失败")
                db_model.build_status = "failed"
                db_model.build_log = str(exc)
                await db.commit()

                # 构建失败后同步 YAML
                try:
                    from omichub.tools.blast.yaml_sync import blast_db_yaml_manager

                    all_models = (await db.execute(select(BlastDatabaseModel))).scalars().all()
                    blast_db_yaml_manager.sync_from_models(list(all_models))
                except Exception:
                    logger.exception("构建任务失败后同步 blast_db.yaml 失败")

                raise self.retry(exc=exc) from exc

    return asyncio.run(_run())


def _database_cache_version(model: BlastDatabaseModel) -> str:
    updated_at = model.updated_at.isoformat() if model.updated_at else ""
    return f"{model.source_version or ''}:{updated_at}"


async def _get_task(db: Any, task_id: str) -> Any:
    result = await db.execute(select(BlastTaskModel).where(BlastTaskModel.task_id == task_id))
    return result.scalar_one_or_none()
