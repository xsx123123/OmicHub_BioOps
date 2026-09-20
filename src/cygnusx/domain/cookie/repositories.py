"""饼干域仓储接口"""

from __future__ import annotations

from datetime import date
from typing import Protocol
from uuid import UUID

from cygnusx.domain.cookie.entities import (
    ConsumptionLog,
    CookieAccount,
    CookiePricing,
    CookieTransaction,
    LedgerEntry,
)


class ICookieAccountRepository(Protocol):
    """账户仓储接口"""

    async def get_by_user(self, user_id: UUID) -> CookieAccount | None: ...

    async def get_by_id(self, account_id: int) -> CookieAccount | None: ...

    async def save(self, account: CookieAccount) -> CookieAccount: ...

    async def list_all(
        self, status: str | None = None, offset: int = 0, limit: int = 50
    ) -> list[CookieAccount]: ...


class ICookieTransactionRepository(Protocol):
    """交易流水仓储接口"""

    async def add(self, txn: CookieTransaction) -> CookieTransaction: ...

    async def list_by_user(
        self,
        user_id: UUID,
        txn_type: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[CookieTransaction]: ...

    async def list_by_source(self, source_type: str, source_id: str) -> list[CookieTransaction]: ...

    async def count_by_user(self, user_id: UUID) -> int: ...


class ICookiePricingRepository(Protocol):
    """定价策略仓储接口"""

    async def get_by_id(self, pricing_id: int) -> CookiePricing | None: ...

    async def list_all(self, active_only: bool = True) -> list[CookiePricing]: ...

    async def find_match(
        self,
        flow_category: str = "",
        resource_type: str = "",
        pricing_type: str = "",
    ) -> CookiePricing | None:
        """按 flow_category + resource_type + priority 匹配最优定价"""

    async def save(self, pricing: CookiePricing) -> CookiePricing: ...

    async def delete(self, pricing_id: int) -> bool: ...


class IConsumptionLogRepository(Protocol):
    """消费明细仓储接口"""

    async def add(self, log: ConsumptionLog) -> ConsumptionLog: ...

    async def list_by_task(self, task_id: str) -> list[ConsumptionLog]: ...

    async def list_by_user(
        self, user_id: UUID, offset: int = 0, limit: int = 50
    ) -> list[ConsumptionLog]: ...


class ILedgerRepository(Protocol):
    """日终账本仓储接口"""

    async def add(self, entry: LedgerEntry) -> LedgerEntry: ...

    async def get_by_date_user(self, snapshot_date: date, user_id: UUID) -> LedgerEntry | None: ...

    async def list_by_date(
        self, snapshot_date: date, offset: int = 0, limit: int = 100
    ) -> list[LedgerEntry]: ...
