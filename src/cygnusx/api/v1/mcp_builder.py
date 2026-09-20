"""MCP Builder 路由 — AI 自生成 MCP 的构建/审核/生命周期管理.

用户端：提交构建、沙箱测试、查看自己的构建与实验 MCP、续期/删除/调用。
管理端：审核队列、审核决定、全部实验 MCP 概览。

设计文档：docs/26.7.30/mcp_builder_framework.md §5.3
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from cygnusx.api.deps import CurrentUserId, DbSession
from cygnusx.api.v1.admin.users import AdminRequired
from cygnusx.application.schemas.mcp_builder import (
    GenerateCodeRequest,
    MCPBuildDTO,
    RenewRequest,
    ReviewRequest,
    SandboxTestRequest,
    SubmitBuildRequest,
    ToolInvokeRequest,
)
from cygnusx.application.services.mcp_builder_service import MCPBuilderService

router = APIRouter()


def get_builder_service(db: DbSession) -> MCPBuilderService:
    return MCPBuilderService(db)


BuilderDep = Annotated[MCPBuilderService, Depends(get_builder_service)]


# ----------------------------------------------------------------------
# 构建
# ----------------------------------------------------------------------
@router.post("/builds", response_model=MCPBuildDTO, status_code=201, summary="提交 MCP 构建")
async def submit_build(
    user_id: CurrentUserId, req: SubmitBuildRequest, service: BuilderDep
) -> MCPBuildDTO:
    """提交构建请求。``code`` 缺省时由平台 LLM 生成；提供时直接走安全检查。"""
    return await service.submit_build(user_id, req)


@router.post("/generate", summary="仅生成代码（预览，不落库）")
async def generate_code(
    _user: CurrentUserId, req: GenerateCodeRequest, service: BuilderDep
) -> dict[str, Any]:
    return await service.generate_code_only(req.requirement, req.model_name)


@router.get("/builds", response_model=list[MCPBuildDTO], summary="我的构建历史")
async def list_builds(
    user_id: CurrentUserId,
    service: BuilderDep,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
) -> list[MCPBuildDTO]:
    return await service.list_builds(user_id=user_id, status=status, limit=limit)


@router.get("/builds/{build_id}", response_model=MCPBuildDTO, summary="构建详情")
async def get_build(
    user_id: CurrentUserId, build_id: UUID, service: BuilderDep
) -> MCPBuildDTO:
    return await service.get_build(str(build_id), user_id=user_id)


@router.delete("/builds/{build_id}", status_code=204, summary="删除构建（联动删除其实验 MCP）")
async def delete_build(
    user_id: CurrentUserId, build_id: UUID, service: BuilderDep
) -> None:
    await service.delete_build(str(build_id), user_id)


@router.post("/builds/{build_id}/test", response_model=MCPBuildDTO, summary="沙箱内测试构建")
async def test_build(
    user_id: CurrentUserId,
    build_id: UUID,
    req: SandboxTestRequest,
    service: BuilderDep,
) -> MCPBuildDTO:
    """在指定 Studio 会话沙箱内启动构建产物，逐工具验证并记录测试用例。"""
    return await service.test_in_sandbox(
        str(build_id), req.session_id, req.test_arguments, user_id=user_id
    )


# ----------------------------------------------------------------------
# 审核（Admin）
# ----------------------------------------------------------------------
@router.get("/review-queue", response_model=list[MCPBuildDTO], summary="审核队列（Admin）")
async def review_queue(
    _admin: AdminRequired,
    service: BuilderDep,
    status: str = Query(default="reviewing"),
    limit: int = Query(default=50, le=200),
) -> list[MCPBuildDTO]:
    return await service.list_review_queue(status=status, limit=limit)


@router.post("/builds/{build_id}/review", response_model=MCPBuildDTO, summary="提交审核决定（Admin）")
async def review_build(
    user_id: CurrentUserId, _admin: AdminRequired, build_id: UUID, req: ReviewRequest, service: BuilderDep
) -> MCPBuildDTO:
    # AdminRequired 是纯权限闸门（注入值为 None），操作者 ID 取自 CurrentUserId
    return await service.review_build(str(build_id), user_id, req.decision, req.comment)


# ----------------------------------------------------------------------
# 实验 MCP 生命周期
# ----------------------------------------------------------------------
@router.get("/servers/experimental", summary="我的实验 MCP 列表")
async def list_experimental(
    user_id: CurrentUserId, service: BuilderDep
) -> list[dict[str, Any]]:
    return await service.list_experimental_servers(user_id=user_id)


@router.post("/servers/{server_id}/renew", summary="续期实验 MCP")
async def renew_server(
    user_id: CurrentUserId, server_id: UUID, req: RenewRequest, service: BuilderDep
) -> dict[str, Any]:
    return await service.renew_server(str(server_id), user_id, hours=req.hours)


@router.delete("/servers/{server_id}", status_code=204, summary="删除实验 MCP")
async def delete_server(
    user_id: CurrentUserId, server_id: UUID, service: BuilderDep
) -> None:
    await service.delete_experimental_server(str(server_id), user_id)


@router.post("/servers/{server_id}/promote", summary="实验 MCP 转正为正式（Admin）")
async def promote_server(
    user_id: CurrentUserId, _admin: AdminRequired, server_id: UUID, service: BuilderDep
) -> dict[str, Any]:
    """把实验池 MCP 提升为正式池：清除 TTL、打 publish 版本行并写审计日志。"""
    return await service.promote_server(str(server_id), user_id)


@router.post("/servers/{server_id}/invoke", summary="调用实验 MCP 工具（沙箱桥接）")
async def invoke_tool(
    user_id: CurrentUserId,
    server_id: UUID,
    req: ToolInvokeRequest,
    service: BuilderDep,
) -> dict[str, Any]:
    """经 Studio 沙箱 UDS 桥接调用容器内 STDIO 子进程。"""
    return await service.call_experimental_tool(
        str(server_id), req.tool, req.arguments, req.session_id, user_id
    )


@router.get("/servers/{server_id}/versions", summary="MCP 版本历史")
async def list_versions(
    _user: CurrentUserId, server_id: UUID, service: BuilderDep
) -> list[dict[str, Any]]:
    return await service.list_versions(str(server_id))


@router.post("/servers/{server_id}/rollback", summary="回滚到指定版本")
async def rollback_version(
    user_id: CurrentUserId,
    server_id: UUID,
    service: BuilderDep,
    version: str = Query(..., description="目标版本号，如 1.1.0"),
) -> dict[str, Any]:
    return await service.rollback(str(server_id), version, user_id)
