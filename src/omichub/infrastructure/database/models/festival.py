"""节日彩蛋 ORM 模型"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from omichub.infrastructure.database.base import Base


class FestivalClaimModel(Base):
    """节日额度领取记录表

    用于防止同一用户在同一年重复领取同一节日额度。
    """

    __tablename__ = "festival_claims"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "festival_id", "year",
            name="uq_festival_claim_user_festival_year",
        ),
        Index("idx_festival_claim_user", "user_id", "claimed_at"),
        Index("idx_festival_claim_festival", "festival_id", "year"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, comment="领取用户 ID"
    )
    festival_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="节日标识")
    year: Mapped[int] = mapped_column(Integer, nullable=False, comment="领取年份")
    amount: Mapped[float] = mapped_column(default=0.0, comment="领取金额")
    transaction_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="关联饼干交易流水 ID"
    )
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now, comment="领取时间"
    )
