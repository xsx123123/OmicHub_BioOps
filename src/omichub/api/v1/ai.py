"""AI 对话路由 - WebSocket 全双工流式通信 + 对话 CRUD"""

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from omichub.api.deps import CurrentUserId, DbSession, get_active_user_from_token_payload
from omichub.application.schemas.ai import (
    ConversationDetailDTO,
    ConversationDTO,
    CreateConversationDTO,
)
from omichub.application.schemas.tool_invocation import ToolInvocationContext
from omichub.application.services.ai_service import AIService
from omichub.application.services.analysis_flow_tool_service import AnalysisFlowToolService
from omichub.application.services.tool_confirmation_service import (
    ConfirmationError,
    get_tool_confirmation_service,
)
from omichub.core.security import decode_token
from omichub.infrastructure.database.session import get_session_factory

router = APIRouter()


def get_ai_service(db: DbSession) -> AIService:
    return AIService(db)


AIServiceDep = Annotated[AIService, Depends(get_ai_service)]


@router.get("/status", summary="AI 服务配置状态")
async def ai_status(db: DbSession) -> dict[str, bool]:
    """返回 AI 服务是否已配置（无需登录，便于前端提前提示）

    修复：不再只检查默认 provider 或 .env 环境变量，而是检查数据库中
    是否存在任意一个已启用且配置了 API Key 的 provider，与 /chat/models 保持一致。
    """
    from omichub.infrastructure.database.repositories.ai_provider_repository import (
        SqlAlchemyAIProviderConfigRepository,
    )

    repo = SqlAlchemyAIProviderConfigRepository(db)
    configs = await repo.list_all(active_only=True)
    configured = any(bool(c.api_key) and bool(c.model) for c in configs)
    return {"configured": configured}


@router.get("/conversations", response_model=list[ConversationDTO], summary="对话列表")
async def list_conversations(
    current_user_id: CurrentUserId, service: AIServiceDep
) -> list[ConversationDTO]:
    return await service.list_conversations(UUID(current_user_id))


@router.post(
    "/conversations",
    response_model=ConversationDTO,
    status_code=201,
    summary="创建对话",
)
async def create_conversation(
    current_user_id: CurrentUserId,
    service: AIServiceDep,
    req: CreateConversationDTO,
) -> ConversationDTO:
    return await service.create_conversation(UUID(current_user_id), req)


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailDTO,
    summary="对话详情（含消息）",
)
async def get_conversation(
    current_user_id: CurrentUserId,
    service: AIServiceDep,
    conversation_id: UUID,
) -> ConversationDetailDTO:
    return await service.get_conversation(UUID(current_user_id), conversation_id)


@router.delete("/conversations/{conversation_id}", summary="删除对话")
async def delete_conversation(
    current_user_id: CurrentUserId,
    service: AIServiceDep,
    conversation_id: UUID,
) -> dict[str, bool]:
    ok = await service.delete_conversation(UUID(current_user_id), conversation_id)
    return {"deleted": ok}


@router.websocket("/ws", name="ai_chat_websocket")
async def ai_websocket(websocket: WebSocket) -> None:
    """AI 对话 WebSocket 端点

    连接：wss://host/api/v1/ai/ws?token=<JWT>
    客户端发送 JSON：{"type":"chat","conversation_id":"<uuid>","content":"你好"}
    服务端流式返回事件：token / user_message / assistant_message / tool_call / tool_result / done / error
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
    await websocket.accept()

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "detail": "非 JSON 消息"}))
                continue

            msg_type = data.get("type")
            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue

            if msg_type != "chat":
                await websocket.send_text(
                    json.dumps({"type": "error", "detail": f"未知消息类型: {msg_type}"})
                )
                continue

            conv_id_raw = data.get("conversation_id", "")
            content = data.get("content", "")
            assistant_id = data.get("assistant_id")
            try:
                conversation_id = UUID(str(conv_id_raw))
            except ValueError:
                await websocket.send_text(
                    json.dumps({"type": "error", "detail": "无效的 conversation_id"})
                )
                continue

            # 每次对话使用独立 DB 会话
            factory = get_session_factory()
            async with factory() as session:
                try:
                    service = AIService(session)
                    async for event in service.stream_chat(
                        user_id, conversation_id, content, assistant_id
                    ):
                        await websocket.send_text(json.dumps(event, default=str))
                    await session.commit()
                except Exception as e:  # noqa: BLE001
                    await session.rollback()
                    await websocket.send_text(
                        json.dumps({"type": "error", "detail": f"内部错误：{e}"})
                    )
    except WebSocketDisconnect:
        pass


# ============================================================
# AI 工具确认（分析流程提交二次确认）
# ============================================================


@router.post("/tool-confirmations/{confirmation_id}/approve", summary="确认并提交分析任务")
async def approve_tool_confirmation(
    current_user_id: CurrentUserId,
    db: DbSession,
    confirmation_id: UUID,
) -> dict[str, Any]:
    """用户确认 AI 预检的分析流程，正式提交任务。"""
    context = ToolInvocationContext(
        user_id=str(current_user_id),
        session_id="",
        db=db,
    )
    service = AnalysisFlowToolService(context=context)
    try:
        result = await service.confirm_and_submit(str(confirmation_id))
    except ConfirmationError as e:
        raise HTTPException(status_code=400, detail={"code": e.code, "message": e.message}) from e
    return {"success": True, **result}


@router.post("/tool-confirmations/{confirmation_id}/reject", summary="拒绝分析任务提交")
async def reject_tool_confirmation(
    current_user_id: CurrentUserId,
    db: DbSession,
    confirmation_id: UUID,
    reason: str | None = None,
) -> dict[str, Any]:
    """用户拒绝 AI 预检的分析流程。"""
    context = ToolInvocationContext(
        user_id=str(current_user_id),
        session_id="",
        db=db,
    )
    confirmation_service = get_tool_confirmation_service()
    try:
        record = await confirmation_service.reject(
            context=context,
            confirmation_id=str(confirmation_id),
            reason=reason,
        )
    except ConfirmationError as e:
        raise HTTPException(status_code=400, detail={"code": e.code, "message": e.message}) from e
    return {"success": True, "status": record.status}
