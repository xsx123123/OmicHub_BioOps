"""Skill 仓储实现 — SQLAlchemy"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.domain.skill.entities import Skill
from omichub.domain.skill.repositories import ISkillRepository
from omichub.infrastructure.database.models.skill import SkillModel


class SqlAlchemySkillRepository(ISkillRepository):
    """技能仓储实现"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self, active_only: bool = False) -> list[Skill]:
        query = select(SkillModel).order_by(SkillModel.created_at)
        if active_only:
            query = query.where(SkillModel.is_active == True)  # noqa: E712
        result = await self._session.execute(query)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def get_by_skill_id(self, skill_id: str) -> Skill | None:
        result = await self._session.execute(
            select(SkillModel).where(SkillModel.skill_id == skill_id)
        )
        m = result.scalar_one_or_none()
        return self._to_entity(m) if m else None

    async def save(self, skill: Skill) -> Skill:
        model = SkillModel(
            id=skill.id,
            skill_id=skill.skill_id,
            name=skill.name,
            description=skill.description,
            prompt=skill.prompt,
            tool_definition=skill.tool_definition,
            icon=skill.icon,
            category=skill.category,
            is_active=skill.is_active,
            is_builtin=skill.is_builtin,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_entity(model)

    async def delete(self, skill_id: str) -> bool:
        result = await self._session.execute(
            select(SkillModel).where(SkillModel.skill_id == skill_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return False
        await self._session.delete(model)
        await self._session.flush()
        return True

    @staticmethod
    def _to_entity(m: SkillModel) -> Skill:
        return Skill(
            id=m.id,
            skill_id=m.skill_id,
            name=m.name,
            description=m.description,
            prompt=m.prompt,
            tool_definition=m.tool_definition,
            icon=m.icon,
            category=m.category,
            is_active=m.is_active,
            is_builtin=m.is_builtin,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )
