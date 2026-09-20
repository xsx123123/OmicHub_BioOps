"""AI 可观测性指标 — 管理端趋势 / 模型分布 / 告警（Metrics 仪表盘数据源）。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from cygnusx.api.deps import DbSession
from cygnusx.application.services.ai_metrics_service import AiMetricsService
from cygnusx.middleware.rbac import AdminRequired

router = APIRouter()


def get_service(db: DbSession) -> AiMetricsService:
    return AiMetricsService(db)


ServiceDep = Annotated[AiMetricsService, Depends(get_service)]


@router.get("/trend", summary="AI 调用按日趋势")
async def trend(
    _admin: AdminRequired,
    service: ServiceDep,
    days: Annotated[int, Query(ge=1, le=90, description="回溯天数")] = 14,
    model: Annotated[str | None, Query(description="按模型过滤")] = None,
    provider: Annotated[str | None, Query(description="按 provider 过滤")] = None,
) -> dict:
    """调用量/错误率/token/成本/延迟（avg+p95）的按日序列 + 汇总。"""
    return await service.daily_trend(days=days, model=model, provider=provider)


@router.get("/models", summary="按模型聚合")
async def models(
    _admin: AdminRequired,
    service: ServiceDep,
    days: Annotated[int, Query(ge=1, le=90)] = 14,
) -> list[dict]:
    """各模型调用量/token/成本/错误率（按 token 降序）。"""
    return await service.model_breakdown(days=days)


@router.get("/alerts/status", summary="告警规则当前状态")
async def alert_status(_admin: AdminRequired, service: ServiceDep) -> dict:
    """C4 三条规则的当前值/阈值/是否超阈值。"""
    return await service.alert_status()


@router.get("/alerts/history", summary="告警历史")
async def alert_history(
    _admin: AdminRequired,
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict]:
    """近期触发的告警（倒序）。"""
    return await service.alert_history(limit=limit)
