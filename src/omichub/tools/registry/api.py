"""工具箱注册表路由 —— 前端工具卡片列表 + 热重载。

- GET   /tools         返回 tools_setting.yaml 中 enabled=true 的工具（按 order 升序）
- POST  /tools/reload  管理员强制热重载 YAML

鉴权：列表接口公开（与 /flows 一致，仅展示元数据，无用户数据）；热重载需管理员。
配置集中管理：展示元数据在 tool_configs/tools_setting.yaml，各工具功能配置在 tool_configs/<工具名>/。
"""

from fastapi import APIRouter

from omichub.middleware.rbac import AdminRequired
from omichub.tools.registry.config import config_manager
from omichub.tools.registry.schema import (
    ToolItemDTO,
    ToolListResponse,
    ToolReloadResponse,
)

# 路由元数据：供 omichub.tools.register_tool_routers 自动发现挂载
prefix = "/tools"
tags = ["Tools 工具箱"]

router = APIRouter()


@router.get("", response_model=ToolListResponse, summary="获取工具箱工具列表")
async def list_tools() -> ToolListResponse:
    """返回 tools_setting.yaml 中 enabled=true 的工具，按 order 升序。"""
    tools = [ToolItemDTO(**t.model_dump()) for t in config_manager.list_enabled_tools()]
    return ToolListResponse(data=tools)


@router.post(
    "/reload",
    response_model=ToolReloadResponse,
    summary="热重载工具箱注册表 YAML",
)
async def reload_tools(_admin: AdminRequired) -> ToolReloadResponse:
    """管理员接口：强制重新加载 tools_setting.yaml。"""
    registry = config_manager.reload()
    return ToolReloadResponse(
        message="工具箱注册表已重载",
        tools_count=len(registry.tools),
    )
