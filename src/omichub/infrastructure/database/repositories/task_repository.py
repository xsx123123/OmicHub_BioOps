"""任务仓储实现 — SQLAlchemy"""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.core.config import get_settings
from omichub.domain.task.entities import Task, TaskLog
from omichub.domain.task.repositories import ITaskRepository
from omichub.domain.task.value_objects import ExecutionMode, LogLevel, TaskStatus
from omichub.infrastructure.database.models.task import TaskModel


class TaskRepositoryImpl(ITaskRepository):
    """任务仓储 SQLAlchemy 实现"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, task_id: UUID) -> Task | None:
        """根据 ID 获取任务"""
        result = await self._session.execute(select(TaskModel).where(TaskModel.id == task_id))
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_by_user(self, user_id: UUID, status: str | None = None) -> list[Task]:
        """列出用户的任务"""
        query = select(TaskModel).where(TaskModel.user_id == user_id)
        if status:
            query = query.where(TaskModel.status == status)
        query = query.order_by(TaskModel.created_at.desc())
        result = await self._session.execute(query)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def save(self, task: Task) -> Task:
        """保存任务（插入或更新）"""
        existing = await self._session.get(TaskModel, task.id)
        if existing:
            model = self._update_model(existing, task)
        else:
            model = self._to_model(task)
            self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def delete(self, task_id: UUID) -> bool:
        """删除任务"""
        model = await self._session.get(TaskModel, task_id)
        if model:
            await self._session.delete(model)
            await self._session.flush()
            return True
        return False

    async def append_log(self, task_id: UUID, log_entry: dict) -> None:
        """追加单条日志，并限制 DB 中的日志体积。"""
        model = await self._session.get(TaskModel, task_id)
        if model is None:
            return

        settings = get_settings()
        bounded_entry = self._bound_log_entry(
            log_entry,
            max_chars=settings.task_log_message_max_chars,
        )
        logs = list(model.logs or [])
        logs.append(bounded_entry)
        if settings.task_log_max_entries > 0:
            logs = logs[-settings.task_log_max_entries :]
        model.logs = logs
        await self._session.flush()

    @staticmethod
    def _bound_log_entry(log_entry: dict, max_chars: int) -> dict:
        """截断超长 message，避免 tasks.logs JSON 字段无限膨胀。"""
        entry = dict(log_entry)
        message = entry.get("message")
        if isinstance(message, str) and max_chars > 0 and len(message) > max_chars:
            omitted = len(message) - max_chars
            entry["message"] = f"{message[:max_chars]}... [truncated {omitted} chars]"
            entry["truncated"] = True
            entry["original_length"] = len(message)
        return entry

    # ------------------------------------------------------------------
    # 仪表板统计聚合（返回原始行/标量，不走 _to_entity）
    # ------------------------------------------------------------------

    async def count_trend_by_day(self, days: int, user_id: UUID | None = None) -> list[Row]:
        """按天聚合过去 N 天的任务数与样本数。

        user_id 为 None 时统计全平台（管理员视角）。
        缺日（无任务）由服务层补 0。
        """
        cutoff = datetime.now() - timedelta(days=days)
        date_col = func.date(TaskModel.created_at).label("date")
        stmt = (
            select(
                date_col,
                func.count(TaskModel.id).label("task_count"),
                func.coalesce(func.sum(TaskModel.sample_count), 0).label("sample_count"),
            )
            .where(TaskModel.created_at >= cutoff)
            .group_by(date_col)
            .order_by(date_col)
        )
        if user_id is not None:
            stmt = stmt.where(TaskModel.user_id == user_id)
        result = await self._session.execute(stmt)
        return list(result.all())

    async def count_by_status(self, user_id: UUID | None = None) -> list[Row]:
        """按状态聚合任务数。user_id 为 None 时为全平台。"""
        stmt = select(TaskModel.status, func.count(TaskModel.id))
        if user_id is not None:
            stmt = stmt.where(TaskModel.user_id == user_id)
        stmt = stmt.group_by(TaskModel.status)
        result = await self._session.execute(stmt)
        return list(result.all())

    async def count_by_flow(self, user_id: UUID | None = None) -> list[Row]:
        """按流程聚合任务数。user_id 为 None 时为全平台。"""
        stmt = select(TaskModel.flow_id, func.count(TaskModel.id))
        if user_id is not None:
            stmt = stmt.where(TaskModel.user_id == user_id)
        stmt = stmt.group_by(TaskModel.flow_id)
        result = await self._session.execute(stmt)
        return list(result.all())

    async def count_active_users_since(self, days: int) -> int:
        """近 N 天内有提交任务行为的去重用户数。"""
        cutoff = datetime.now() - timedelta(days=days)
        stmt = select(func.count(func.distinct(TaskModel.user_id))).where(
            TaskModel.created_at >= cutoff
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def list_recent_failed(self, limit: int = 10, user_id: UUID | None = None) -> list[Task]:
        """近期失败任务。user_id 为 None 时为全平台（管理员）。"""
        stmt = select(TaskModel).where(TaskModel.status == TaskStatus.FAILED.value)
        if user_id is not None:
            stmt = stmt.where(TaskModel.user_id == user_id)
        stmt = stmt.order_by(TaskModel.created_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars().all()]

    # ------------------------------------------------------------------
    # 模型 ↔ 实体转换
    # ------------------------------------------------------------------

    @staticmethod
    def _to_entity(model: TaskModel) -> Task:
        from datetime import datetime

        logs = [
            TaskLog(
                timestamp=log.get("timestamp") or datetime.now(),
                level=LogLevel(log.get("level", "info")),
                message=log.get("message", ""),
                source=log.get("source", ""),
            )
            for log in (model.logs or [])
        ]
        return Task(
            id=model.id,
            flow_id=model.flow_id,
            user_id=model.user_id,
            name=model.name,
            status=TaskStatus(model.status),
            execution_mode=ExecutionMode(model.execution_mode),
            parameters=model.parameters or {},
            work_dir=model.work_dir,
            result_path=model.result_path,
            error_message=model.error_message,
            progress=model.progress,
            sample_count=model.sample_count,
            logs=logs,
            created_at=model.created_at,
            started_at=model.started_at,
            finished_at=model.finished_at,
        )

    @staticmethod
    def _to_model(task: Task) -> TaskModel:
        return TaskModel(
            id=task.id,
            flow_id=task.flow_id,
            user_id=task.user_id,
            name=task.name,
            status=task.status.value,
            execution_mode=task.execution_mode.value,
            parameters=task.parameters,
            work_dir=task.work_dir,
            result_path=task.result_path,
            error_message=task.error_message,
            progress=task.progress,
            sample_count=task.sample_count,
            logs=[log.model_dump(mode="json") for log in task.logs],
            started_at=task.started_at,
            finished_at=task.finished_at,
        )

    @staticmethod
    def _update_model(model: TaskModel, task: Task) -> TaskModel:
        model.flow_id = task.flow_id
        model.user_id = task.user_id
        model.name = task.name
        model.status = task.status.value
        model.execution_mode = task.execution_mode.value
        model.parameters = task.parameters
        model.work_dir = task.work_dir
        model.result_path = task.result_path
        model.error_message = task.error_message
        model.progress = task.progress
        model.sample_count = task.sample_count
        # 注意: logs 不在此处覆盖，由 append_log 单独管理，避免丢失直接追加的日志
        model.started_at = task.started_at
        model.finished_at = task.finished_at
        return model
