"""仪表板统计 — 管理员全平台视角（全局态势）。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from cygnusx.api.deps import DbSession
from cygnusx.application.services.stats_service import StatsService
from cygnusx.middleware.rbac import AdminRequired  # 统一 RBAC 实现

router = APIRouter()


def get_stats_service(db: DbSession) -> StatsService:
    """获取统计服务实例"""
    return StatsService(db)


StatsServiceDep = Annotated[StatsService, Depends(get_stats_service)]


@router.get("/status", summary="全平台任务状态分布")
async def admin_status(_admin: AdminRequired, service: StatsServiceDep) -> dict:
    """各状态任务数（pending/queued/running/success/failed/cancelled）。"""
    return await service.admin_status()


@router.get("/flows", summary="流程使用占比")
async def admin_flows(_admin: AdminRequired, service: StatsServiceDep) -> list[dict]:
    """各生信流程累计调用频次（降序）。"""
    return await service.admin_flow_usage()


@router.get("/users", summary="全平台用户与活跃度")
async def admin_users(_admin: AdminRequired, service: StatsServiceDep) -> dict:
    """注册用户总数 + 近 7 天活跃用户数。"""
    return await service.admin_user_stats()


@router.get("/recent-failed", summary="近期失败任务监控")
async def admin_recent_failed(
    _admin: AdminRequired,
    service: StatsServiceDep,
    limit: Annotated[int, Query(ge=1, le=50, description="返回条数")] = 10,
) -> list[dict]:
    """跨用户拉取近期失败任务（实时，不缓存）。"""
    return await service.admin_recent_failed(limit)
