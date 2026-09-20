"""OmicStudio 长任务提交服务。

WP2 任务4 三契约（借鉴 OpenAI4S compute/manager.py 的 job 契约）：

a) job 行先落盘：转 Celery 前先把 job 记录（tasks 行，含幂等键）独立会话
   提交 commit，再投递队列；投递失败立刻把 job 标记 failed，不留
   "队列里没有、DB 里 pending" 的悬挂行。
b) 终态不可重开：success/failed/cancelled 一经写入不可再迁移（见
   domain/task/value_objects.py VALID_TRANSITIONS）；retry_studio_sandbox_task
   对终态 job 拒绝（409 ConflictError + 明确文案），需要再次执行只能提交新任务。
c) reconcile-only：worker 恢复/定时对账（tasks/studio.py
   reconcile_studio_long_tasks）只报告或标记状态漂移，绝不自动重提交。

幂等键复用现有 command_id 语义（与 chat/overdrive 的 command_id 同款：
调用方显式传入、≤128 字符、冲突即返回已有 job）；未显式传入时由服务端
按 user/session/代码内容确定性派生，终态后再次提交同内容会自动抬升
attempt 后缀（:a2、:a3…）生成新 job——同一幂等键永远映射同一 job 行。
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy.exc import IntegrityError

from cygnusx.core.exceptions import ConflictError, NotFoundError, ValidationError
from cygnusx.domain.task.services import TaskDomainService
from cygnusx.domain.task.value_objects import ExecutionMode, TaskStatus
from cygnusx.infrastructure.celery_app.celery import celery_app as _celery_app  # noqa: F401
from cygnusx.infrastructure.celery_app.tasks.studio import run_studio_sandbox
from cygnusx.infrastructure.database.repositories.task_repository import TaskRepositoryImpl
from cygnusx.infrastructure.database.session import get_session_factory
from cygnusx.infrastructure.studio.manager import studio_sandbox_manager
from cygnusx.infrastructure.task_queue.dispatcher import enqueue_task

STUDIO_SANDBOX_FLOW_ID = "studio_sandbox"
STUDIO_LONG_TASK_THRESHOLD_SECONDS = 600

# 终态：与 OpenAI4S compute/states.py TERMINAL_STATES 同语义，终态证据只写一次
STUDIO_JOB_TERMINAL_STATUSES = (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED)
STUDIO_JOB_LIVE_STATUSES = (TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING)

# 与 chat schemas command_id（min_length=1, max_length=128）同一上限
COMMAND_ID_MAX_LENGTH = 128


def _derive_idempotency_key(
    *,
    user_id: str,
    session_id: str,
    language: str,
    code: str,
    timeout_sec: int,
    image: str | None,
) -> str:
    """服务端派生幂等键：同一用户在同一会话提交同内容的长任务映射同一 job。

    显式 command_id 优先（见 submit_studio_sandbox_task）；派生键在命中终态
    job 后由 _resolve_available_key 抬升 attempt 后缀，保证"重跑"得到新 job。
    """
    digest = hashlib.sha256(
        f"{language}\x00{code}\x00{timeout_sec}\x00{image or ''}".encode("utf-8")
    ).hexdigest()[:16]
    return f"studio:{user_id}:{session_id}:{digest}"


def _submission_payload(task: Any, *, deduplicated: bool = False) -> dict[str, Any]:
    session_id = (task.parameters or {}).get("studio_session_id", "")
    payload: dict[str, Any] = {
        "task_id": str(task.id),
        "task_type": STUDIO_SANDBOX_FLOW_ID,
        "status": task.status.value,
        "idempotency_key": task.idempotency_key,
        "deduplicated": deduplicated,
        "task_url": f"/api/v1/tasks/{task.id}",
        "progress_url": f"/api/v1/tasks/{task.id}/progress",
        "result_url": f"/studio/{session_id}",
    }
    return payload


async def submit_studio_sandbox_task(
    *,
    user_id: str,
    session_id: str,
    language: str,
    code: str,
    timeout_sec: int,
    image: str | None,
    command_id: str | None = None,
) -> dict[str, Any]:
    """创建 job（tasks 行，先落盘）并投递 Studio 沙盒 Celery 任务。

    幂等：同一幂等键（显式 command_id 或派生键）的重复提交返回已有 job，
    不新建行、不重复投递；并发同键提交由 DB UNIQUE 索引兜底（第二个提交
    捕获 IntegrityError 后回滚并返回已有行）。

    使用独立数据库会话提交并 commit，避免 Celery worker 早于聊天请求事务
    提交而查不到任务。
    """
    workspace = studio_sandbox_manager.workspace_dir(session_id)
    if command_id is not None:
        command_id = command_id.strip()
        if not command_id or len(command_id) > COMMAND_ID_MAX_LENGTH:
            raise ValidationError(
                f"command_id 长度须为 1~{COMMAND_ID_MAX_LENGTH} 字符（复用任务提交幂等键语义）"
            )
        base_key: str | None = command_id
    else:
        base_key = _derive_idempotency_key(
            user_id=user_id,
            session_id=session_id,
            language=language,
            code=code,
            timeout_sec=timeout_sec,
            image=image,
        )

    session_factory = get_session_factory()

    # ---- 契约 a：job 行先落盘（含幂等键），随后才提交队列 ----
    try:
        async with session_factory() as db:
            repo = TaskRepositoryImpl(db)
            domain = TaskDomainService(repo)
            key = base_key
            existing = await repo.get_by_idempotency_key(key) if key else None
            if existing is not None and command_id is None:
                # 派生键命中终态 job：视为"同内容再跑一次"，抬升 attempt 生成新 job；
                # 显式 command_id 则保持纯幂等语义（同键永远返回同一 job）。
                if existing.status in STUDIO_JOB_TERMINAL_STATUSES:
                    key = f"{base_key}:a{await repo.count_attempts_by_key_prefix(base_key) + 2}"
                    existing = await repo.get_by_idempotency_key(key)
            if existing is not None:
                logger.bind(
                    event="studio.job.deduplicated",
                    task_id=str(existing.id),
                    idempotency_key=key,
                    status=existing.status.value,
                ).info("[Studio] 幂等键命中已有长任务，返回已有 job")
                return _submission_payload(existing, deduplicated=True)

            task_id = uuid.uuid4()
            parameters = {
                "task_type": STUDIO_SANDBOX_FLOW_ID,
                "studio_session_id": session_id,
                "language": language,
                "timeout": timeout_sec,
                "image": image,
                "code_size": len(code),
                "code_preview": code[:500],
            }
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
            task.idempotency_key = key
            task = await repo.save(task)
            task = await domain.transition_status(task, TaskStatus.QUEUED)
            await db.commit()
    except IntegrityError:
        # 并发同键提交：UNIQUE 索引拒绝第二个 inserter，回滚并返回已有行（不新建、不重投）
        logger.bind(event="studio.job.idempotency_race", idempotency_key=base_key).warning(
            "[Studio] 幂等键并发冲突，返回已有 job"
        )
        async with session_factory() as db:
            repo = TaskRepositoryImpl(db)
            existing = await repo.get_by_idempotency_key(base_key)
            if existing is None:
                raise  # 非幂等键冲突，属于真实约束 bug，上抛
            return _submission_payload(existing, deduplicated=True)

    # ---- 契约 a 续：投递失败必须回滚为 failed，不留悬挂 pending ----
    try:
        # task_id 走 enqueue_task 的 Celery 消息 id 选项（与任务 kwargs 同名被签名遮蔽），
        # worker 侧 bind=True 从 self.request.id 取回：Celery id == DB task id，可对账。
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

    return _submission_payload(task, deduplicated=False)


async def retry_studio_sandbox_task(*, task_id: str, user_id: str) -> dict[str, Any]:
    """重试入口（终态不可重开，契约 b）。

    现状：仓库中没有任务重试/重提 API（tasks 路由仅有 cancel/delete），
    本函数即 Studio 长任务的重试入口服务实现，API 层可原样映射：
      - 终态（success/failed/cancelled）→ 409 ConflictError，明确文案，
        需要再次执行必须提交新任务（新幂等键）；
      - 存活态 → 409 ConflictError，任务仍在流程中无需重试；
      - 不存在/非本人/非 Studio 长任务 → 404。
    """
    session_factory = get_session_factory()
    async with session_factory() as db:
        repo = TaskRepositoryImpl(db)
        task = await repo.get_by_id(UUID(task_id))
        if task is None or str(task.user_id) != user_id or task.flow_id != STUDIO_SANDBOX_FLOW_ID:
            raise NotFoundError(f"Studio 长任务 {task_id} 不存在")
        if task.status in STUDIO_JOB_TERMINAL_STATUSES:
            raise ConflictError(
                f"任务已处于终态（{task.status.value}），不可重开；"
                "如需再次执行请提交新任务（终态结果只写一次，防止迟到的探测复活旧任务）"
            )
        raise ConflictError(
            f"任务当前状态为 {task.status.value}，仍在执行流程中，无需重试；"
            "若任务长时间无进展，对账会将悬挂任务标记失败，届时请提交新任务"
        )
