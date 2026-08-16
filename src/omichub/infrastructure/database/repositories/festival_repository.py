"""节日彩蛋领取记录仓储"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.domain.festival.entities import FestivalClaim
from omichub.domain.festival.repositories import FestivalClaimRepository
from omichub.infrastructure.database.models.festival import FestivalClaimModel


class SqlAlchemyFestivalClaimRepository(FestivalClaimRepository):
    """节日领取记录的 SQLAlchemy 实现"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_claim(
        self, user_id: UUID, festival_id: str, year: int
    ) -> FestivalClaim | None:
        stmt = select(FestivalClaimModel).where(
            FestivalClaimModel.user_id == user_id,
            FestivalClaimModel.festival_id == festival_id,
            FestivalClaimModel.year == year,
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_entity(model)

    async def save_claim(self, claim: FestivalClaim) -> FestivalClaim:
        model = FestivalClaimModel(
            user_id=claim.user_id,
            festival_id=claim.festival_id,
            year=claim.year,
            amount=claim.amount,
            transaction_id=claim.transaction_id,
            claimed_at=claim.claimed_at,
        )
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return self._to_entity(model)

    @staticmethod
    def _to_entity(model: FestivalClaimModel) -> FestivalClaim:
        return FestivalClaim(
            id=model.id,
            user_id=model.user_id,
            festival_id=model.festival_id,
            year=model.year,
            amount=model.amount,
            transaction_id=model.transaction_id,
            claimed_at=model.claimed_at,
        )


__all__ = ["SqlAlchemyFestivalClaimRepository"]
