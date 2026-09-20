"""报告仓储实现 — SQLAlchemy"""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cygnusx.infrastructure.database.models.report import ReportFileModel, ReportModel


class ReportRepositoryImpl:
    """报告仓储 SQLAlchemy 实现"""

    def __init__(self, session: AsyncSession):
        self._session = session

    @staticmethod
    def _report_query():
        """构建包含报告文件的查询，避免异步会话中触发延迟加载。"""
        return select(ReportModel).options(selectinload(ReportModel.files))

    async def get_by_id(self, report_id: UUID) -> ReportModel | None:
        """根据 ID 获取报告"""
        result = await self._session.execute(
            self._report_query().where(ReportModel.id == report_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: UUID,
        *,
        keyword: str | None = None,
        flow_id: str | None = None,
        status: str | None = None,
        date_range: str | None = None,
        is_starred: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ReportModel], int]:
        """列出用户报告，返回 (items, total)"""
        query = self._report_query().where(
            ReportModel.user_id == user_id,
            ReportModel.flow_id != "studio",
        )
        count_query = select(func.count(ReportModel.id)).where(
            ReportModel.user_id == user_id,
            ReportModel.flow_id != "studio",
        )

        if keyword:
            like = f"%{keyword}%"
            filter_ = or_(
                ReportModel.title.ilike(like),
                ReportModel.flow_name.ilike(like),
                ReportModel.description.ilike(like),
            )
            query = query.where(filter_)
            count_query = count_query.where(filter_)

        if flow_id:
            query = query.where(ReportModel.flow_id == flow_id)
            count_query = count_query.where(ReportModel.flow_id == flow_id)

        if status:
            query = query.where(ReportModel.status == status)
            count_query = count_query.where(ReportModel.status == status)

        if date_range:
            days = {"7d": 7, "30d": 30, "90d": 90}.get(date_range, 0)
            if days:
                cutoff = datetime.now() - timedelta(days=days)
                query = query.where(ReportModel.created_at >= cutoff)
                count_query = count_query.where(ReportModel.created_at >= cutoff)

        if is_starred is not None:
            query = query.where(ReportModel.is_starred == is_starred)
            count_query = count_query.where(ReportModel.is_starred == is_starred)

        total_result = await self._session.execute(count_query)
        total = total_result.scalar_one()

        query = query.order_by(ReportModel.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await self._session.execute(query)
        return list(result.scalars().all()), total

    async def list_version_candidates(self, user_id: UUID) -> list[ReportModel]:
        """列出用户可参与版本树构建的报告。"""
        result = await self._session.execute(
            self._report_query()
            .where(ReportModel.user_id == user_id, ReportModel.flow_id != "studio")
            .order_by(ReportModel.version, ReportModel.created_at)
        )
        return list(result.scalars().all())

    async def get_by_task_id(self, task_id: UUID) -> ReportModel | None:
        """根据任务 ID 获取报告"""
        result = await self._session.execute(
            self._report_query().where(ReportModel.task_id == task_id)
        )
        return result.scalar_one_or_none()

    async def create(self, model: ReportModel) -> ReportModel:
        """创建报告"""
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return model

    async def save(self, model: ReportModel) -> ReportModel:
        """保存报告"""
        await self._session.flush()
        await self._session.refresh(model)
        return model

    async def delete(self, report_id: UUID) -> bool:
        """删除报告"""
        model = await self._session.get(ReportModel, report_id)
        if model:
            await self._session.delete(model)
            await self._session.flush()
            return True
        return False

    async def get_file_by_id(self, file_id: UUID) -> ReportFileModel | None:
        """根据文件 ID 获取报告文件"""
        result = await self._session.execute(
            select(ReportFileModel).where(ReportFileModel.id == file_id)
        )
        return result.scalar_one_or_none()

    async def count_by_user(self, user_id: UUID) -> dict[str, int]:
        """用户报告统计"""
        total_stmt = select(func.count(ReportModel.id)).where(
            ReportModel.user_id == user_id,
            ReportModel.flow_id != "studio",
        )
        total_result = await self._session.execute(total_stmt)
        total = total_result.scalar_one()

        starred_stmt = select(func.count(ReportModel.id)).where(
            ReportModel.user_id == user_id,
            ReportModel.flow_id != "studio",
            ReportModel.is_starred == True,  # noqa: E712
        )
        starred_result = await self._session.execute(starred_stmt)
        starred = starred_result.scalar_one()

        generating_stmt = select(func.count(ReportModel.id)).where(
            ReportModel.user_id == user_id,
            ReportModel.flow_id != "studio",
            ReportModel.status == "generating",
        )
        generating_result = await self._session.execute(generating_stmt)
        generating = generating_result.scalar_one()

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_stmt = select(func.count(ReportModel.id)).where(
            ReportModel.user_id == user_id,
            ReportModel.flow_id != "studio",
            ReportModel.created_at >= today,
        )
        today_result = await self._session.execute(today_stmt)
        today_count = today_result.scalar_one()

        return {
            "total": total,
            "starred": starred,
            "generating": generating,
            "today": today_count,
        }
