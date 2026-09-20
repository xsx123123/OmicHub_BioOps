"""团队空间应用服务"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.infrastructure.database.repositories.team_repository import TeamRepositoryImpl


class TeamService:
    """团队协作空间服务"""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._teams = TeamRepositoryImpl(session)

    async def list_my_teams(self, user_id: UUID) -> list[dict]:
        """返回当前用户所属团队列表（owner / writer / reader）。"""
        return await self._teams.list_for_user(user_id)
