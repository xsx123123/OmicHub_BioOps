"""工具注册入口 — 基于 config.yaml 的 tool_groups 开关按需加载"""

from fastmcp import FastMCP

from client.api_client import OmicHubAPIClient
from core.config import settings
from core.logger import logger

_GROUP_REGISTRY: dict[str, str] = {
    "tasks": "tools.tasks",
    "flows": "tools.flows",
    "analysis": "tools.analysis",
    "downloads": "tools.downloads",
    "files": "tools.files",
    "reports": "tools.reports",
    "sandbox": "tools.sandbox",
    "platform": "tools.platform",
    "pipelines": "tools.pipelines",
}


def register_all_tools(mcp: FastMCP, api: OmicHubAPIClient) -> None:
    import importlib

    for group_id, module_path in _GROUP_REGISTRY.items():
        if not settings.is_tool_group_enabled(group_id):
            logger.info(f"工具组 [{group_id}] 已禁用，跳过注册")
            continue
        module = importlib.import_module(module_path)
        module.register(mcp, api)
        logger.debug(f"工具组 [{group_id}] 注册完成")
