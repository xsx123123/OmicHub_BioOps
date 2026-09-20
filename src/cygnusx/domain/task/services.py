"""任务域服务 - 状态机管理"""

import contextlib
from datetime import datetime
from uuid import UUID

from loguru import logger

from cygnusx.core.exceptions import ValidationError
from cygnusx.core.telemetry import get_meter
from cygnusx.domain.task.entities import Task
from cygnusx.domain.task.repositories import ITaskRepository
from cygnusx.domain.task.value_objects import ExecutionMode, LogLevel, TaskStatus

# ===== 工具箱任务遥测指标（全局代理 meter，未初始化时为 noop）=====
_task_meter = get_meter("cygnusx.toolbox")
_task_count = _task_meter.create_counter("toolbox.task.count", description="工具箱任务状态迁移次数")
_task_duration = _task_meter.create_histogram(
    "toolbox.task.duration", unit="ms", description="工具箱任务执行耗时（终态记录）"
)


class TaskDomainService:
    """任务域服务 - 状态转换、调度策略"""

    def __init__(self, repo: ITaskRepository):
        self._repo = repo

    async def submit(
        self,
        flow_id: str,
        user_id: UUID,
        name: str,
        parameters: dict,
        execution_mode: ExecutionMode = ExecutionMode.LOCAL,
        sample_count: int = 0,
        task_id: UUID | None = None,
    ) -> Task:
        """提交新任务：创建聚合根并持久化

        task_id 可选：调用方预生成 id 用于工作目录路径时传入，否则自动生成。
        """
        from uuid import uuid4

        task = Task(
            id=task_id or uuid4(),
            flow_id=flow_id,
            user_id=user_id,
            name=name,
            status=TaskStatus.PENDING,
            execution_mode=execution_mode,
            parameters=parameters,
            sample_count=sample_count,
        )
        return await self._repo.save(task)

    async def transition_status(self, task: Task, new_status: TaskStatus) -> Task:
        """执行状态转换（含合法性校验）"""
        if not task.can_transition_to(new_status):
            raise ValidationError(f"非法状态转换: {task.status} → {new_status}")
        task.status = new_status
        if new_status == TaskStatus.RUNNING and task.started_at is None:
            task.started_at = datetime.now()
        elif new_status in {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED}:
            task.finished_at = datetime.now()
        saved = await self._repo.save(task)

        with contextlib.suppress(Exception):
            status_value = new_status.value if hasattr(new_status, "value") else str(new_status)
            attrs = {"toolbox.flow_id": task.flow_id, "toolbox.status": status_value}
            _task_count.add(1, attrs)
            duration_ms: float | None = None
            if (
                new_status in {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED}
                and task.started_at is not None
                and task.finished_at is not None
            ):
                duration_ms = (task.finished_at - task.started_at).total_seconds() * 1000
                _task_duration.record(duration_ms, {"toolbox.flow_id": task.flow_id})
            logger.bind(
                event="toolbox.task.transition",
                task_id=str(task.id),
                flow_id=task.flow_id,
                status=status_value,
                duration_ms=round(duration_ms, 2) if duration_ms is not None else None,
            ).info("toolbox.task.transition")
        return saved

    async def add_log(self, task_id: UUID, level: LogLevel, message: str, source: str = "") -> None:
        """追加任务日志"""
        from datetime import datetime

        await self._repo.append_log(
            task_id,
            {
                "timestamp": datetime.now().isoformat(),
                "level": level.value,
                "message": message,
                "source": source,
            },
        )
