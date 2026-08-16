"""Agent 模板管理 API — 管理员 CRUD"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from omichub.api.deps import DbSession
from omichub.api.v1.admin.users import AdminRequired
from omichub.application.schemas.agent import (
    AgentTemplateDTO,
    CreateAgentRequest,
    UpdateAgentRequest,
)
from omichub.application.services.agent_service import AgentService

router = APIRouter()


def get_agent_service(db: DbSession) -> AgentService:
    return AgentService(db)


AgentServiceDep = Annotated[AgentService, Depends(get_agent_service)]


@router.get("", response_model=list[AgentTemplateDTO], summary="Agent 列表（含停用）")
async def list_agents(
    _admin: AdminRequired,
    service: AgentServiceDep,
) -> list[AgentTemplateDTO]:
    return await service.list_agents(active_only=False)


@router.post("", response_model=AgentTemplateDTO, status_code=201, summary="创建 Agent")
async def create_agent(
    _admin: AdminRequired,
    service: AgentServiceDep,
    req: CreateAgentRequest,
) -> AgentTemplateDTO:
    return await service.create_agent(req)


@router.get("/{agent_id}", response_model=AgentTemplateDTO, summary="Agent 详情")
async def get_agent(
    _admin: AdminRequired,
    service: AgentServiceDep,
    agent_id: str,
) -> AgentTemplateDTO:
    return await service.get_agent_dto(agent_id)


@router.put("/{agent_id}", response_model=AgentTemplateDTO, summary="更新 Agent")
async def update_agent(
    _admin: AdminRequired,
    service: AgentServiceDep,
    agent_id: str,
    req: UpdateAgentRequest,
) -> AgentTemplateDTO:
    return await service.update_agent(agent_id, req)


@router.delete("/{agent_id}", summary="删除 Agent")
async def delete_agent(
    _admin: AdminRequired,
    service: AgentServiceDep,
    agent_id: str,
) -> dict[str, bool]:
    await service.delete_agent(agent_id)
    return {"deleted": True}


@router.post("/{agent_id}/toggle", response_model=AgentTemplateDTO, summary="启用/停用 Agent")
async def toggle_agent(
    _admin: AdminRequired,
    service: AgentServiceDep,
    agent_id: str,
) -> AgentTemplateDTO:
    return await service.toggle_agent(agent_id)


@router.post("/{agent_id}/set-default", summary="设为默认 Agent")
async def set_default(
    _admin: AdminRequired,
    service: AgentServiceDep,
    agent_id: str,
) -> dict[str, bool]:
    await service.set_default_agent(agent_id)
    return {"success": True}
