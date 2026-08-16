"""节日彩蛋域仓库接口"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from omichub.domain.festival.entities import FestivalClaim, FestivalConfig


class FestivalConfigRepository(ABC):
    """节日配置仓库接口"""

    @abstractmethod
    async def load_all(self) -> list[FestivalConfig]:
        """加载全部节日配置"""
        raise NotImplementedError

    @abstractmethod
    async def save_all(self, festivals: list[FestivalConfig]) -> None:
        """保存全部节日配置"""
        raise NotImplementedError

    @abstractmethod
    async def reload(self) -> list[FestivalConfig]:
        """强制重载配置"""
        raise NotImplementedError


class FestivalClaimRepository(ABC):
    """节日领取记录仓库接口"""

    @abstractmethod
    async def get_claim(
        self, user_id: UUID, festival_id: str, year: int
    ) -> FestivalClaim | None:
        """查询用户某年是否领取过指定节日"""
        raise NotImplementedError

    @abstractmethod
    async def save_claim(self, claim: FestivalClaim) -> FestivalClaim:
        """保存领取记录"""
        raise NotImplementedError


__all__ = ["FestivalConfigRepository", "FestivalClaimRepository"]
