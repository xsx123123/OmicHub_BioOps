"""团队域仓储 SQLAlchemy 实现"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.domain.team.value_objects import TeamRole
from omichub.infrastructure.database.models.team import TeamMemberModel, TeamModel


class TeamRepositoryImpl:
    """团队协作空间仓储"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_for_user(self, user_id: UUID) -> list[dict]:
        """返回用户作为 owner 或 member 所属的所有团队，并附带当前用户角色。"""
        stmt = (
            select(TeamModel, TeamMemberModel.role.label("member_role"))
            .outerjoin(
                TeamMemberModel,
                (TeamMemberModel.team_id == TeamModel.id)
                & (TeamMemberModel.user_id == user_id),
            )
            .where(
                or_(
                    TeamModel.owner_id == user_id,
                    TeamMemberModel.user_id == user_id,
                )
            )
            .order_by(TeamModel.created_at.desc())
        )
        result = await self._session.execute(stmt)
        rows = []
        for team, member_role in result.all():
            role = (
                TeamRole.OWNER.value
                if team.owner_id == user_id
                else (member_role or TeamRole.READER.value)
            )
            rows.append(
                {
                    "id": team.id,
                    "name": team.name,
                    "owner_id": team.owner_id,
                    "description": team.description,
                    "role": role,
                    "created_at": team.created_at,
                    "updated_at": team.updated_at,
                }
            )
        return rows

    async def get_member_role(self, team_id: UUID, user_id: UUID) -> TeamRole | None:
        team = await self._session.get(TeamModel, team_id)
        if team is None:
            return None
        if team.owner_id == user_id:
            return TeamRole.OWNER
        stmt = select(TeamMemberModel.role).where(
            TeamMemberModel.team_id == team_id,
            TeamMemberModel.user_id == user_id,
        )
        role = (await self._session.execute(stmt)).scalar_one_or_none()
        return TeamRole(role) if role else None
