"""饼干积分 — 管理端路由"""

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from omichub.api.deps import CurrentUserId, DbSession
from omichub.application.schemas.cookie import (
    AdjustBalanceRequest,
    AdminCookieAccountDTO,
    CookieAccountDTO,
    CookieDiscountDTO,
    CookieDiscountRequest,
    CookieStatsDTO,
    CookieTransactionDTO,
    PricingCreateRequest,
)
from omichub.application.services.cookie_monitor_service import CookieMonitorService
from omichub.application.services.cookie_service import CookieService
from omichub.middleware.rbac import AdminRequired  # 统一 RBAC 实现

router = APIRouter()


def get_cookie_service(db: DbSession) -> CookieService:
    return CookieService(db)


CookieServiceDep = Annotated[CookieService, Depends(get_cookie_service)]


@router.get("/accounts", response_model=list[AdminCookieAccountDTO], summary="所有账户")
async def list_accounts(
    _admin: AdminRequired,
    service: CookieServiceDep,
    status: str | None = None,
    search: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> list[AdminCookieAccountDTO]:
    """所有饼干账户 — 关联用户身份/角色/课题组/存储资产，支持按用户名/邮箱/用户ID检索。"""
    return await service.list_all_accounts(status, search, offset, limit)


@router.post("/accounts/{user_id}/adjust", response_model=CookieTransactionDTO, summary="调整余额")
async def adjust_balance(
    user_id: UUID,
    req: AdjustBalanceRequest,
    current_user_id: CurrentUserId,
    _admin: AdminRequired,
    service: CookieServiceDep,
) -> CookieTransactionDTO:
    return await service.adjust_balance(user_id, req.amount, req.reason, UUID(current_user_id))


@router.put("/accounts/{user_id}/freeze", response_model=CookieAccountDTO, summary="冻结账户")
async def freeze_account(
    user_id: UUID,
    current_user_id: CurrentUserId,
    _admin: AdminRequired,
    service: CookieServiceDep,
    reason: str = "",
) -> CookieAccountDTO:
    return await service.freeze_account(user_id, reason, UUID(current_user_id))


@router.put("/accounts/{user_id}/unfreeze", response_model=CookieAccountDTO, summary="解冻账户")
async def unfreeze_account(
    user_id: UUID,
    _admin: AdminRequired,
    service: CookieServiceDep,
) -> CookieAccountDTO:
    return await service.unfreeze_account(user_id)


@router.put("/accounts/{user_id}/suspend", response_model=CookieAccountDTO, summary="停用账户")
async def suspend_account(
    user_id: UUID,
    current_user_id: CurrentUserId,
    _admin: AdminRequired,
    service: CookieServiceDep,
    reason: str = "",
) -> CookieAccountDTO:
    return await service.suspend_account(user_id, reason, UUID(current_user_id))


@router.get("/transactions", response_model=list[CookieTransactionDTO], summary="全局交易流水")
async def list_all_transactions(
    _admin: AdminRequired,
    service: CookieServiceDep,
    offset: int = 0,
    limit: int = 50,
) -> list[CookieTransactionDTO]:
    return await service.list_all_transactions(offset, limit)


@router.get("/stats", response_model=CookieStatsDTO, summary="系统统计")
async def get_stats(
    _admin: AdminRequired,
    service: CookieServiceDep,
) -> CookieStatsDTO:
    return await service.get_stats()


@router.get("/pricing", summary="所有定价策略(含停用)")
async def list_all_pricing(
    _admin: AdminRequired,
    service: CookieServiceDep,
):
    return await service.list_pricing(active_only=False)


@router.post("/pricing", summary="创建定价策略")
async def create_pricing(
    req: PricingCreateRequest,
    current_user_id: CurrentUserId,
    _admin: AdminRequired,
    service: CookieServiceDep,
):
    return await service.create_pricing(req, UUID(current_user_id))


@router.put("/pricing/{pricing_id}", summary="更新定价策略")
async def update_pricing(
    pricing_id: int,
    req: PricingCreateRequest,
    current_user_id: CurrentUserId,
    _admin: AdminRequired,
    service: CookieServiceDep,
):
    return await service.update_pricing(pricing_id, req, UUID(current_user_id))


@router.delete("/pricing/{pricing_id}", summary="删除定价策略")
async def delete_pricing(
    pricing_id: int,
    _admin: AdminRequired,
    service: CookieServiceDep,
):
    ok = await service.delete_pricing(pricing_id)
    return {"deleted": ok}


@router.get("/discounts", response_model=list[CookieDiscountDTO], summary="Token 优惠规则")
async def list_discounts(_admin: AdminRequired, service: CookieServiceDep):
    return await service.list_discounts()


@router.post("/discounts", response_model=CookieDiscountDTO, summary="创建 Token 优惠规则")
async def create_discount(
    req: CookieDiscountRequest,
    current_user_id: CurrentUserId,
    _admin: AdminRequired,
    service: CookieServiceDep,
):
    return await service.create_discount(req, UUID(current_user_id))


@router.put("/discounts/{discount_id}", response_model=CookieDiscountDTO, summary="更新 Token 优惠规则")
async def update_discount(
    discount_id: int,
    req: CookieDiscountRequest,
    current_user_id: CurrentUserId,
    _admin: AdminRequired,
    service: CookieServiceDep,
):
    return await service.update_discount(discount_id, req, UUID(current_user_id))


@router.delete("/discounts/{discount_id}", summary="删除 Token 优惠规则")
async def delete_discount(
    discount_id: int,
    _admin: AdminRequired,
    service: CookieServiceDep,
):
    return {"deleted": await service.delete_discount(discount_id)}


@router.get("/transactions/filtered", summary="全局交易流水审计(多维度过滤)")
async def list_all_transactions_filtered(
    _admin: AdminRequired,
    service: CookieServiceDep,
    user_id: UUID | None = None,
    txn_type: str | None = None,
    source_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: int = 0,
    limit: int = 50,
):
    """全局交易流水审计 — 支持按用户/类型/来源/日期过滤，返回用户名"""
    items = await service.list_all_transactions_filtered(
        user_id=user_id,
        txn_type=txn_type,
        source_type=source_type,
        date_from=date_from,
        date_to=date_to,
        offset=offset,
        limit=limit,
    )
    total = await service.count_all_transactions_filtered(
        user_id=user_id,
        txn_type=txn_type,
        source_type=source_type,
        date_from=date_from,
        date_to=date_to,
    )
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.post("/reconcile", summary="手动触发日终对账")
async def trigger_reconcile(
    _admin: AdminRequired,
    db: DbSession,
    snapshot_date: date | None = None,
):
    """手动触发账本快照 + 异常检测（通常由 Celery Beat 每日自动执行）"""
    monitor = CookieMonitorService(db)
    result = await monitor.reconcile_ledger(snapshot_date)
    return result.model_dump()


@router.get("/anomalies", summary="异常检测报告")
async def get_anomalies(
    _admin: AdminRequired,
    db: DbSession,
    snapshot_date: date | None = None,
):
    """获取余额异常检测报告"""
    monitor = CookieMonitorService(db)
    anomalies = await monitor.detect_anomalies(snapshot_date)
    return {
        "snapshot_date": str(snapshot_date or datetime.now().date()),
        "anomalies": [a.model_dump() for a in anomalies],
    }


@router.get("/ledger", summary="账本快照报告")
async def get_ledger_report(
    _admin: AdminRequired,
    db: DbSession,
    snapshot_date: Annotated[date, Query(description="快照日期 YYYY-MM-DD")],
    offset: int = 0,
    limit: int = 100,
):
    """获取指定日期的账本快照"""
    monitor = CookieMonitorService(db)
    entries = await monitor.get_ledger_report(snapshot_date, offset, limit)
    return {
        "snapshot_date": str(snapshot_date),
        "entries": [
            {
                "user_id": str(e.user_id),
                "account_id": e.account_id,
                "opening_balance": float(e.opening_balance),
                "total_earned": float(e.total_earned),
                "total_spent": float(e.total_spent),
                "total_adjusted": float(e.total_adjusted),
                "closing_balance": float(e.closing_balance),
                "transaction_count": e.transaction_count,
            }
            for e in entries
        ],
    }
