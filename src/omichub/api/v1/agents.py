"""Agent 模板公开 API — 前台智能体集市/沙盒读取 Agent 设定"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from omichub.api.deps import CurrentUserId, DbSession
from omichub.application.schemas.agent import (
    AgentTemplateDTO,
    UserAgentCapabilityDTO,
    UserAgentCapabilityRequest,
    UserSelectableMCPDTO,
)
from omichub.application.services.agent_service import AgentService

router = APIRouter()


def get_agent_service(db: DbSession) -> AgentService:
    return AgentService(db)


AgentServiceDep = Annotated[AgentService, Depends(get_agent_service)]


@router.get("", response_model=list[AgentTemplateDTO], summary="启用中的 Agent 列表")
async def list_agents(
    _user: CurrentUserId,
    service: AgentServiceDep,
) -> list[AgentTemplateDTO]:
    return await service.list_agents(active_only=True)


@router.get(
    "/capability-mcps",
    response_model=list[UserSelectableMCPDTO],
    summary="当前用户可为 Agent 选择的 MCP 服务",
)
async def list_user_selectable_mcps(
    _user: CurrentUserId,
    service: AgentServiceDep,
) -> list[UserSelectableMCPDTO]:
    return await service.list_user_selectable_mcps()


@router.get(
    "/{agent_id}/capabilities",
    response_model=UserAgentCapabilityDTO,
    summary="当前用户的 Agent 能力选择",
)
async def get_user_capabilities(
    current_user_id: CurrentUserId,
    service: AgentServiceDep,
    agent_id: str,
) -> UserAgentCapabilityDTO:
    return await service.get_user_capabilities(current_user_id, agent_id)


@router.put(
    "/{agent_id}/capabilities",
    response_model=UserAgentCapabilityDTO,
    summary="保存当前用户的 Agent 能力选择",
)
async def update_user_capabilities(
    current_user_id: CurrentUserId,
    service: AgentServiceDep,
    agent_id: str,
    req: UserAgentCapabilityRequest,
) -> UserAgentCapabilityDTO:
    return await service.update_user_capabilities(current_user_id, agent_id, req)


@router.delete(
    "/{agent_id}/capabilities",
    status_code=204,
    summary="恢复 Agent 的管理员默认能力",
)
async def reset_user_capabilities(
    current_user_id: CurrentUserId,
    service: AgentServiceDep,
    agent_id: str,
) -> Response:
    await service.reset_user_capabilities(current_user_id, agent_id)
    return Response(status_code=204)


@router.get("/{agent_id}", response_model=AgentTemplateDTO, summary="Agent 详情")
async def get_agent(
    _user: CurrentUserId,
    service: AgentServiceDep,
    agent_id: str,
) -> AgentTemplateDTO:
    return await service.get_agent_dto(agent_id)
