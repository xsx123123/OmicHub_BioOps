"""代码执行沙盒路由 - 会话管理 + WebSocket 代码执行"""

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from loguru import logger

from cygnusx.api.deps import CurrentUserId, DbSession, get_active_user_from_token_payload
from cygnusx.application.schemas.sandbox import (
    CreateSandboxDTO,
    SandboxSessionDTO,
)
from cygnusx.application.services.sandbox_service import SandboxService
from cygnusx.core.security import decode_token
from cygnusx.infrastructure.database.session import get_session_factory

router = APIRouter()


def get_sandbox_service(db: DbSession) -> SandboxService:
    return SandboxService(db)


SandboxServiceDep = Annotated[SandboxService, Depends(get_sandbox_service)]


@router.get("/sessions", response_model=list[SandboxSessionDTO], summary="沙盒会话列表")
async def list_sessions(
    current_user_id: CurrentUserId, service: SandboxServiceDep
) -> list[SandboxSessionDTO]:
    return await service.list_sessions(UUID(current_user_id))


@router.post(
    "/sessions",
    response_model=SandboxSessionDTO,
    status_code=201,
    summary="创建沙盒会话",
)
async def create_session(
    current_user_id: CurrentUserId,
    service: SandboxServiceDep,
    req: CreateSandboxDTO,
) -> SandboxSessionDTO:
    return await service.create_session(UUID(current_user_id), req.language)


@router.get("/sessions/{session_id}", response_model=SandboxSessionDTO, summary="会话详情")
async def get_session(
    current_user_id: CurrentUserId,
    service: SandboxServiceDep,
    session_id: UUID,
) -> SandboxSessionDTO:
    return await service.get_session(UUID(current_user_id), session_id)


@router.delete("/sessions/{session_id}", summary="销毁会话")
async def delete_session(
    current_user_id: CurrentUserId,
    service: SandboxServiceDep,
    session_id: UUID,
) -> dict[str, bool]:
    ok = await service.delete_session(UUID(current_user_id), session_id)
    return {"deleted": ok}


@router.post("/sessions/{session_id}/execute", summary="同步执行代码（收集式）")
async def execute_code_sync(
    current_user_id: CurrentUserId,
    service: SandboxServiceDep,
    session_id: UUID,
    req: dict,
) -> dict:
    """收集式代码执行：聚合所有流式事件后一次性返回。供 MCP Server / API 调用。"""
    code = req.get("code", "")
    timeout = int(req.get("timeout", 0) or 0)

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    images: list[str] = []
    echarts: list[dict] = []
    error: str | None = None

    async for event in service.execute_code(UUID(current_user_id), session_id, code, timeout):
        etype = event.get("type")
        if etype == "stdout":
            stdout_parts.append(event.get("data", ""))
        elif etype == "stderr":
            stderr_parts.append(event.get("data", ""))
        elif etype == "image":
            images.append(event.get("data", ""))
        elif etype == "echarts":
            echarts.append(event.get("data", {}))
        elif etype == "error":
            error = event.get("detail", "执行错误")

    return {
        "stdout": "".join(stdout_parts),
        "stderr": "".join(stderr_parts),
        "images": images,
        "echarts": echarts,
        "error": error,
    }


@router.websocket("/sessions/{session_id}/ws", name="sandbox_execute_websocket")
async def sandbox_websocket(websocket: WebSocket, session_id: str) -> None:
    """沙盒代码执行 WebSocket

    连接：wss://host/api/v1/sandbox/sessions/<id>/ws?token=<JWT>
    客户端发送：{"type":"execute","code":"print(1)","timeout":0}
    服务端流式返回：stdout / stderr / echarts / image / done / error
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

    user_id = user.id
    try:
        conversation_session_id = UUID(session_id)
    except ValueError:
        await websocket.close(code=1008, reason="Invalid session id")
        return

    await websocket.accept()
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "detail": "非 JSON 消息"}))
                continue

            if data.get("type") != "execute":
                await websocket.send_text(
                    json.dumps({"type": "error", "detail": "仅支持 execute 消息"})
                )
                continue

            code = data.get("code", "")
            timeout = int(data.get("timeout", 0) or 0)
            factory = get_session_factory()
            async with factory() as db:
                try:
                    service = SandboxService(db)
                    async for event in service.execute_code(
                        user_id, conversation_session_id, code, timeout
                    ):
                        await websocket.send_text(json.dumps(event, default=str))
                    await db.commit()
                except Exception as e:  # noqa: BLE001
                    await db.rollback()
                    logger.exception(f"沙盒执行异常 (session={conversation_session_id}): {e}")
                    await websocket.send_text(
                        json.dumps({"type": "error", "detail": "沙盒执行内部错误，请联系管理员"})
                    )
    except WebSocketDisconnect:
        pass
