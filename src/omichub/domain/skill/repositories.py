"""Skill 域仓储接口"""

from abc import ABC, abstractmethod

from omichub.domain.skill.entities import Skill


class ISkillRepository(ABC):
    """技能仓储接口"""

    @abstractmethod
    async def list_all(self, active_only: bool = False) -> list[Skill]: ...

    @abstractmethod
    async def get_by_skill_id(self, skill_id: str) -> Skill | None: ...

    @abstractmethod
    async def save(self, skill: Skill) -> Skill: ...

    @abstractmethod
    async def delete(self, skill_id: str) -> bool: ...
