"""Agent (ChatAssistant) 管理 API — 管理员 CRUD"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from cygnusx.api.deps import DbSession
from cygnusx.api.v1.admin.users import AdminRequired
from cygnusx.application.schemas.chat import (
    ChatAssistantDTO,
    CreateAssistantRequest,
    UpdateAssistantRequest,
)
from cygnusx.application.services.chat_service import ChatService

router = APIRouter()


def get_chat_service(db: DbSession) -> ChatService:
    return ChatService(db)


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


@router.get("", response_model=list[ChatAssistantDTO], summary="助手列表（含停用）")
async def list_assistants(
    _admin: AdminRequired,
    service: ChatServiceDep,
) -> list[ChatAssistantDTO]:
    return await service.list_all_assistants()


@router.post("", response_model=ChatAssistantDTO, status_code=201, summary="创建助手")
async def create_assistant(
    _admin: AdminRequired,
    service: ChatServiceDep,
    req: CreateAssistantRequest,
) -> ChatAssistantDTO:
    return await service.create_custom_assistant(
        user_id="admin",
        assistant_id=req.assistant_id,
        name=req.name,
        description=req.description,
        system_prompt=req.system_prompt,
        default_temperature=req.default_temperature,
        default_max_tokens=req.default_max_tokens,
        icon=req.icon,
        color=req.color,
        category=req.category,
    )


@router.get("/{assistant_id}", response_model=ChatAssistantDTO, summary="助手详情")
async def get_assistant(
    _admin: AdminRequired,
    service: ChatServiceDep,
    assistant_id: str,
) -> ChatAssistantDTO:
    return await service.get_assistant_dto(assistant_id)


@router.put("/{assistant_id}", response_model=ChatAssistantDTO, summary="更新助手")
async def update_assistant(
    _admin: AdminRequired,
    service: ChatServiceDep,
    assistant_id: str,
    req: UpdateAssistantRequest,
) -> ChatAssistantDTO:
    return await service.update_assistant(assistant_id, req)


@router.delete("/{assistant_id}", summary="删除助手")
async def delete_assistant(
    _admin: AdminRequired,
    service: ChatServiceDep,
    assistant_id: str,
) -> dict[str, bool]:
    await service.delete_assistant(assistant_id)
    return {"deleted": True}


@router.post("/{assistant_id}/toggle", response_model=ChatAssistantDTO, summary="启用/停用助手")
async def toggle_assistant(
    _admin: AdminRequired,
    service: ChatServiceDep,
    assistant_id: str,
) -> ChatAssistantDTO:
    return await service.toggle_assistant(assistant_id)


@router.post("/{assistant_id}/set-default", summary="设为默认助手")
async def set_default(
    _admin: AdminRequired,
    service: ChatServiceDep,
    assistant_id: str,
) -> dict[str, bool]:
    await service.set_default_assistant(assistant_id)
    return {"success": True}
