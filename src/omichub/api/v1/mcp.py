"""MCP 服务路由 - 管理端 CRUD 与用户级流水线工具调用。"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from omichub.api.deps import CurrentUserId, DbSession
from omichub.api.v1.admin.users import AdminRequired
from omichub.application.schemas.mcp import (
    CreateMCPServerDTO,
    InvokeToolDTO,
    MCPLogEntryDTO,
    MCPServerDTO,
    MCPServerVersionDTO,
    MCPToolDTO,
    RollbackMCPServerDTO,
    UpdateMCPServerDTO,
)
from omichub.application.services.mcp_service import MCPService

router = APIRouter()


def get_mcp_service(db: DbSession) -> MCPService:
    return MCPService(db)


MCPServiceDep = Annotated[MCPService, Depends(get_mcp_service)]


@router.post("/presets/reload", summary="热加载内置 MCP 预设（Admin）")
async def reload_presets(
    _admin: AdminRequired, service: MCPServiceDep
) -> dict[str, Any]:
    """重新同步代码/YAML 定义的内置 MCP（omichub-platform / omichub-tools /
    omichub-pipelines）工具清单进库，新增内置工具无需重启容器即可被 Agent 使用。"""
    await service.ensure_presets(force_preset_sync=True)
    return {"success": True}


@router.get("/servers", response_model=list[MCPServerDTO], summary="MCP Server 列表")
async def list_servers(
    _admin: AdminRequired,
    service: MCPServiceDep,
    active_only: bool = False,
) -> list[MCPServerDTO]:
    return await service.list_servers(active_only=active_only)


@router.get("/health", summary="审计所有启用 MCP 的实时健康状态（Admin）")
async def audit_health(
    _admin: AdminRequired,
    service: MCPServiceDep,
) -> dict[str, Any]:
    return await service.audit_health()


@router.post(
    "/servers",
    response_model=MCPServerDTO,
    status_code=201,
    summary="注册外部 MCP Server",
)
async def register_server(
    _admin: AdminRequired,
    service: MCPServiceDep,
    req: CreateMCPServerDTO,
) -> MCPServerDTO:
    return await service.register_server(req)


@router.put("/servers/{server_id}", response_model=MCPServerDTO, summary="更新 MCP Server")
async def update_server(
    _admin: AdminRequired,
    current_user_id: CurrentUserId,
    service: MCPServiceDep,
    server_id: UUID,
    req: UpdateMCPServerDTO,
) -> MCPServerDTO:
    return await service.update_server(server_id, req, actor_id=current_user_id)


@router.get(
    "/servers/{server_id}/versions",
    response_model=list[MCPServerVersionDTO],
    summary="MCP Server 版本历史",
)
async def list_server_versions(
    _admin: AdminRequired,
    service: MCPServiceDep,
    server_id: UUID,
) -> list[MCPServerVersionDTO]:
    return await service.list_server_versions(server_id)


@router.post(
    "/servers/{server_id}/rollback",
    response_model=MCPServerDTO,
    summary="回滚 MCP Server 到指定版本",
)
async def rollback_server(
    _admin: AdminRequired,
    current_user_id: CurrentUserId,
    service: MCPServiceDep,
    server_id: UUID,
    req: RollbackMCPServerDTO,
) -> MCPServerDTO:
    return await service.rollback_server(server_id, req.version, actor_id=current_user_id)


@router.get("/servers/{server_id}", response_model=MCPServerDTO, summary="Server 详情")
async def get_server(
    _admin: AdminRequired,
    service: MCPServiceDep,
    server_id: UUID,
) -> MCPServerDTO:
    return await service.get_server(server_id)


@router.delete("/servers/{server_id}", summary="删除 Server")
async def delete_server(
    _admin: AdminRequired,
    service: MCPServiceDep,
    server_id: UUID,
) -> dict[str, bool]:
    ok = await service.delete_server(server_id)
    return {"deleted": ok}


@router.post("/servers/{server_id}/test", summary="测试 MCP Server 连接")
async def test_server(
    _admin: AdminRequired,
    service: MCPServiceDep,
    server_id: UUID,
) -> dict[str, Any]:
    return await service.test_server(server_id)


@router.get(
    "/servers/{server_id}/tools",
    response_model=list[MCPToolDTO],
    summary="发现 Server 工具",
)
async def list_tools(
    _admin: AdminRequired,
    service: MCPServiceDep,
    server_id: UUID,
) -> list[MCPToolDTO]:
    return await service.list_tools(server_id)


@router.post(
    "/servers/{server_id}/tools/{tool_name}/invoke",
    summary="调用 MCP 工具",
)
async def invoke_tool(
    _admin: AdminRequired,
    service: MCPServiceDep,
    server_id: UUID,
    tool_name: str,
    req: InvokeToolDTO,
) -> dict[str, Any]:
    if req.tool_name and req.tool_name != tool_name:
        from omichub.core.exceptions import ValidationError

        raise ValidationError("tool_name 与路径不一致")
    return await service.invoke_tool(server_id, tool_name, req.arguments)


@router.post(
    "/pipelines/tools/{tool_name}/invoke",
    summary="当前用户调用内置分析流水线 MCP 工具",
)
async def invoke_pipeline_tool(
    current_user_id: CurrentUserId,
    service: MCPServiceDep,
    tool_name: str,
    req: InvokeToolDTO,
) -> dict[str, Any]:
    if req.tool_name and req.tool_name != tool_name:
        from omichub.core.exceptions import ValidationError

        raise ValidationError("tool_name 与路径不一致")
    return await service.invoke_pipeline_tool(
        current_user_id,
        tool_name,
        req.arguments,
    )


@router.get(
    "/servers/{server_id}/logs",
    response_model=list[MCPLogEntryDTO],
    summary="MCP Server 运行日志",
)
async def list_logs(
    _admin: AdminRequired,
    service: MCPServiceDep,
    server_id: UUID,
    tail: int = 100,
) -> list[MCPLogEntryDTO]:
    return await service.list_logs(server_id, tail=tail)
