"""饼干积分 — 用户端路由"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from cygnusx.api.deps import CurrentUserId, DbSession, get_active_user_from_token_payload
from cygnusx.application.schemas.cookie import (
    CookieAccountDTO,
    AiTokenRateDTO,
    CookieTransactionDTO,
    CostEstimateDTO,
)
from cygnusx.application.services.cookie_service import CookieService
from cygnusx.core.security import decode_token
from cygnusx.infrastructure.cache.cookie_pubsub import subscribe_cookie_balance

router = APIRouter()


def get_cookie_service(db: DbSession) -> CookieService:
    return CookieService(db)


CookieServiceDep = Annotated[CookieService, Depends(get_cookie_service)]


@router.get("/account", response_model=CookieAccountDTO, summary="获取我的饼干账户")
async def get_account(
    current_user_id: CurrentUserId, service: CookieServiceDep
) -> CookieAccountDTO:
    return await service.get_account(UUID(current_user_id))


@router.get("/transactions", response_model=list[CookieTransactionDTO], summary="交易流水")
async def list_transactions(
    current_user_id: CurrentUserId,
    service: CookieServiceDep,
    txn_type: Annotated[str | None, Query()] = None,
    offset: int = 0,
    limit: int = 50,
) -> list[CookieTransactionDTO]:
    return await service.list_transactions(UUID(current_user_id), txn_type, offset, limit)


@router.get("/pricing", summary="查看定价策略")
async def list_pricing(service: CookieServiceDep):
    return await service.list_pricing(active_only=True)


@router.get("/ai-token-rate", response_model=AiTokenRateDTO, summary="查看当前 AI Token 换算")
async def get_ai_token_rate(service: CookieServiceDep) -> AiTokenRateDTO:
    return await service.get_ai_token_rate()


@router.get("/estimate", response_model=CostEstimateDTO, summary="预估任务费用")
async def estimate_cost(
    current_user_id: CurrentUserId,
    service: CookieServiceDep,
    flow_id: str = Query(..., description="流程ID"),
    sample_count: int = Query(0, ge=0, description="样本数量"),
    comparison_count: int = Query(0, ge=0, description="差异比较组数量"),
) -> CostEstimateDTO:
    return await service.estimate_cost(
        UUID(current_user_id), flow_id, sample_count, comparison_count
    )


@router.get("/balance-check", summary="检查余额是否足够")
async def balance_check(
    current_user_id: CurrentUserId,
    service: CookieServiceDep,
    amount: float = Query(..., description="需要的饼干数"),
):
    balance = await service.check_balance(UUID(current_user_id))
    return {"balance": float(balance), "sufficient": balance >= amount}


@router.websocket("/ws", name="cookie_balance_websocket")
async def cookie_balance_websocket(websocket: WebSocket):
    """饼干余额 WebSocket 实时推送。

    连接示例：wss://host/api/v1/cookies/ws?token=<JWT>
    交易完成后推送：{balance, frozen_balance, available_balance, txn_type, amount, description}
    """
    token = websocket.query_params.get("token")
    payload = decode_token(token) if token else None
    if payload is None or payload.get("type") != "access":
        await websocket.close(code=1008, reason="Invalid token")
        return

    user = await get_active_user_from_token_payload(payload)
    if user is None:
        await websocket.close(code=1008, reason="User inactive or not found")
        return

    user_id = str(user.id)

    await websocket.accept()
    pubsub = await subscribe_cookie_balance(user_id)
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe()
        await pubsub.close()
