"""Workflow monitor API."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Query, Request, WebSocket, WebSocketDisconnect

from omichub.api.deps import CurrentUserId, DbSession, get_active_user_from_token_payload
from omichub.application.schemas.workflow_monitor import (
    MonitorTemplateListResponse,
    MonitorTemplateResponse,
    WorkflowEventListResponse,
    WorkflowOverviewResponse,
    WorkflowTaskSnapshot,
)
from omichub.application.services.workflow_monitor_service import WorkflowMonitorService
from omichub.application.services.workflow_monitor_template_service import (
    WorkflowMonitorTemplateService,
)
from omichub.core.config import get_settings
from omichub.core.exceptions import AuthenticationError, AuthorizationError
from omichub.core.security import decode_token
from omichub.infrastructure.cache.workflow_monitor_pubsub import (
    subscribe_global,
    subscribe_task,
    subscribe_user,
)
from omichub.infrastructure.database.models.task import TaskModel
from omichub.infrastructure.database.models.user import UserModel
from omichub.infrastructure.database.session import get_session_factory

router = APIRouter()


def get_monitor_service(db: DbSession) -> WorkflowMonitorService:
    return WorkflowMonitorService(db)


MonitorServiceDep = Annotated[WorkflowMonitorService, Depends(get_monitor_service)]


async def _get_user_role(db: DbSession, user_id: str) -> str:
    user = await db.get(UserModel, UUID(user_id))
    return user.role if user else "user"


def _validate_ingest_token(authorization: str | None, x_monitor_token: str | None) -> str | None:
    expected = get_settings().workflow_monitor_ingest_token
    if not expected:
        return None
    token = x_monitor_token or ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    if token != expected:
        raise AuthenticationError("流程监控摄取令牌无效")
    return expected


def _validate_monitor_signature(
    body: bytes,
    signing_key: str | None,
    timestamp: str | None,
    nonce: str | None,
    signature: str | None,
) -> None:
    if not signature:
        return
    if not signing_key:
        raise AuthenticationError("流程监控签名已提供，但服务端未配置签名密钥")
    if not timestamp or not nonce:
        raise AuthenticationError("流程监控签名缺少 timestamp 或 nonce")

    try:
        request_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuthenticationError("流程监控签名 timestamp 格式无效") from exc
    skew = abs((datetime.now(UTC) - request_time).total_seconds())
    if skew > get_settings().workflow_monitor_signature_max_skew_seconds:
        raise AuthenticationError("流程监控签名 timestamp 超出允许时间窗口")

    body_hash = hashlib.sha256(body).hexdigest()
    content = f"{timestamp}\n{nonce}\n{body_hash}"
    expected = "v1=" + hmac.new(
        signing_key.encode("utf-8"), content.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise AuthenticationError("流程监控签名无效")


@router.get("/templates", response_model=MonitorTemplateListResponse, summary="流程监控模板列表")
async def list_templates(current_user_id: CurrentUserId, db: DbSession) -> MonitorTemplateListResponse:
    role = await _get_user_role(db, current_user_id)
    return WorkflowMonitorTemplateService().list_templates(role)


@router.get(
    "/templates/{template_id}",
    response_model=MonitorTemplateResponse,
    summary="流程监控模板详情",
)
async def get_template(
    template_id: str,
    current_user_id: CurrentUserId,
    db: DbSession,
) -> MonitorTemplateResponse:
    role = await _get_user_role(db, current_user_id)
    return WorkflowMonitorTemplateService().get_template(template_id, role)


@router.post("/templates/reload", summary="重新加载流程监控模板")
async def reload_templates(current_user_id: CurrentUserId, db: DbSession) -> dict:
    role = await _get_user_role(db, current_user_id)
    if role != "admin":
        raise AuthorizationError("仅管理员可重新加载流程监控模板")
    return WorkflowMonitorTemplateService().reload()


@router.get("/overview", response_model=WorkflowOverviewResponse, summary="流程监控总览")
async def overview(
    current_user_id: CurrentUserId,
    db: DbSession,
    service: MonitorServiceDep,
    status: Annotated[str, Query(description="任务状态过滤")] = "running",
    flow_id: Annotated[str, Query(description="流程 ID")] = "all",
    keyword: Annotated[str, Query(description="关键词")] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> WorkflowOverviewResponse:
    role = await _get_user_role(db, current_user_id)
    return await service.overview(
        current_user_id=current_user_id,
        role=role,
        status=status,
        flow_id=flow_id,
        keyword=keyword,
        limit=limit,
    )


@router.get(
    "/tasks/{task_id}/summary",
    response_model=WorkflowTaskSnapshot,
    summary="单任务流程监控摘要",
)
async def task_summary(
    task_id: str,
    current_user_id: CurrentUserId,
    db: DbSession,
    service: MonitorServiceDep,
) -> WorkflowTaskSnapshot:
    role = await _get_user_role(db, current_user_id)
    return await service.task_summary(task_id, current_user_id, role)


@router.get(
    "/tasks/{task_id}/events",
    response_model=WorkflowEventListResponse,
    summary="单任务流程监控事件",
)
async def task_events(
    task_id: str,
    current_user_id: CurrentUserId,
    db: DbSession,
    service: MonitorServiceDep,
    level: Annotated[str | None, Query(description="逗号分隔日志级别")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> WorkflowEventListResponse:
    role = await _get_user_role(db, current_user_id)
    levels = {item.strip().lower() for item in level.split(",")} if level else None
    return await service.task_events(task_id, current_user_id, role, levels=levels, limit=limit)


@router.post("/events", summary="OmicHub 原生流程监控事件摄取")
async def ingest_event(
    request: Request,
    db: DbSession,
    service: MonitorServiceDep,
    payload: Annotated[dict, Body()],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_monitor_token: Annotated[str | None, Header(alias="X-Workflow-Monitor-Token")] = None,
    x_omichub_timestamp: Annotated[str | None, Header(alias="X-OmicHub-Timestamp")] = None,
    x_omichub_nonce: Annotated[str | None, Header(alias="X-OmicHub-Nonce")] = None,
    x_omichub_signature: Annotated[str | None, Header(alias="X-OmicHub-Signature")] = None,
) -> dict:
    signing_key = _validate_ingest_token(authorization, x_monitor_token)
    _validate_monitor_signature(
        await request.body(),
        signing_key,
        x_omichub_timestamp,
        x_omichub_nonce,
        x_omichub_signature,
    )
    return await service.ingest_native_event(payload)


@router.post("/loki/api/v1/push", summary="Loki-compatible 流程监控事件摄取")
async def ingest_loki(
    db: DbSession,
    service: MonitorServiceDep,
    payload: Annotated[dict, Body()],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_monitor_token: Annotated[str | None, Header(alias="X-Workflow-Monitor-Token")] = None,
) -> dict:
    _validate_ingest_token(authorization, x_monitor_token)
    return await service.ingest_loki_payload(payload)


@router.websocket("/ws", name="workflow_monitor_websocket")
async def workflow_monitor_websocket(websocket: WebSocket):
    token = websocket.query_params.get("token")
    payload = decode_token(token) if token else None
    if payload is None or payload.get("type") != "access":
        await websocket.close(code=1008, reason="Invalid token")
        return
    user = await get_active_user_from_token_payload(payload)
    if user is None:
        await websocket.close(code=1008, reason="User inactive or not found")
        return

    await websocket.accept()
    pubsub = await (subscribe_global() if user.role == "admin" else subscribe_user(str(user.id)))
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe()
        await pubsub.close()


@router.websocket("/tasks/{task_id}/ws", name="workflow_monitor_task_websocket")
async def workflow_monitor_task_websocket(websocket: WebSocket, task_id: str):
    token = websocket.query_params.get("token")
    payload = decode_token(token) if token else None
    if payload is None or payload.get("type") != "access":
        await websocket.close(code=1008, reason="Invalid token")
        return
    user = await get_active_user_from_token_payload(payload)
    if user is None:
        await websocket.close(code=1008, reason="User inactive or not found")
        return

    async with get_session_factory()() as session:
        task = await session.get(TaskModel, UUID(task_id))
        if task is None or (user.role != "admin" and str(task.user_id) != str(user.id)):
            await websocket.close(code=1008, reason="Task not found")
            return

    await websocket.accept()
    pubsub = await subscribe_task(task_id)
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe()
        await pubsub.close()
