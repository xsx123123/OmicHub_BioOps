"""OmicStudio 长任务提交服务。"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from loguru import logger

from omichub.domain.task.services import TaskDomainService
from omichub.domain.task.value_objects import ExecutionMode, TaskStatus
from omichub.infrastructure.celery_app.tasks.studio import run_studio_sandbox
from omichub.infrastructure.database.repositories.task_repository import TaskRepositoryImpl
from omichub.infrastructure.database.session import get_session_factory
from omichub.infrastructure.studio.manager import studio_sandbox_manager
from omichub.infrastructure.task_queue.dispatcher import enqueue_task

STUDIO_SANDBOX_FLOW_ID = "studio_sandbox"
STUDIO_LONG_TASK_THRESHOLD_SECONDS = 600


async def submit_studio_sandbox_task(
    *,
    user_id: str,
    session_id: str,
    language: str,
    code: str,
    timeout_sec: int,
    image: str | None,
) -> dict[str, Any]:
    """创建任务中心记录并投递 Studio 沙盒 Celery 任务。

    使用独立数据库会话提交并 commit，避免 Celery worker 早于聊天请求事务提交而查不到任务。
    """
    task_id = uuid.uuid4()
    workspace = studio_sandbox_manager.workspace_dir(session_id)
    parameters = {
        "task_type": STUDIO_SANDBOX_FLOW_ID,
        "studio_session_id": session_id,
        "language": language,
        "timeout": timeout_sec,
        "image": image,
        "code_size": len(code),
        "code_preview": code[:500],
    }

    session_factory = get_session_factory()
    async with session_factory() as db:
        repo = TaskRepositoryImpl(db)
        domain = TaskDomainService(repo)
        task = await domain.submit(
            flow_id=STUDIO_SANDBOX_FLOW_ID,
            user_id=UUID(user_id),
            name=f"Studio 长任务 · {language} · {session_id[:8]}",
            parameters=parameters,
            execution_mode=ExecutionMode.LOCAL,
            task_id=task_id,
        )
        task.work_dir = str(workspace)
        task.result_path = f"/api/v1/studio/sessions/{session_id}/artifacts"
        task = await repo.save(task)
        task = await domain.transition_status(task, TaskStatus.QUEUED)
        await db.commit()

    try:
        enqueue_task(
            run_studio_sandbox,
            task_id=str(task_id),
            user_id=user_id,
            session_id=session_id,
            language=language,
            code=code,
            timeout_sec=timeout_sec,
            image=image,
        )
    except Exception:
        logger.exception(f"[Studio] 长任务投递失败: {task_id}")
        async with session_factory() as db:
            repo = TaskRepositoryImpl(db)
            domain = TaskDomainService(repo)
            task = await repo.get_by_id(task_id)
            if task is not None and task.status == TaskStatus.QUEUED:
                task = await domain.transition_status(task, TaskStatus.RUNNING)
                task.error_message = "Celery 任务投递失败"
                await repo.save(task)
                await domain.transition_status(task, TaskStatus.FAILED)
                await db.commit()
        raise

    return {
        "task_id": str(task_id),
        "task_type": STUDIO_SANDBOX_FLOW_ID,
        "status": TaskStatus.QUEUED.value,
        "task_url": f"/api/v1/tasks/{task_id}",
        "progress_url": f"/api/v1/tasks/{task_id}/progress",
        "result_url": f"/studio/{session_id}",
    }
