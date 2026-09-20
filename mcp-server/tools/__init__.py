"""工具注册入口 — 基于 config.yaml 的 tool_groups 开关按需加载；注册完成后做启动一致性自校验"""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from client.api_client import CygnusXAPIClient
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
    "seqout": "tools.seqout",
}

_TOOLS_YAML = Path(__file__).resolve().parent.parent / "tools.yaml"


def _verify_tools_yaml_consistency(mcp: FastMCP, registered_groups: set[str]) -> None:
    """启动一致性自校验: tools.yaml 声明 ↔ 实际注册的工具名 / 工具组。

    只输出 warning 日志，不抛异常、不阻断启动。
    FastMCP 3.x 无同步的 tool manager，`mcp.list_tools()` 为协程；
    本函数在模块导入阶段（无运行中事件循环）通过 asyncio.run 收集。
    """
    try:
        import yaml
    except ImportError:
        logger.warning("[自校验] PyYAML 不可用，跳过 tools.yaml 一致性校验")
        return

    try:
        raw: dict[str, Any] = yaml.safe_load(_TOOLS_YAML.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.warning(f"[自校验] 读取 tools.yaml 失败，跳过一致性校验: {e}")
        return

    groups = raw.get("groups") or []
    declared_groups = {str(g["id"]) for g in groups if g.get("id")}
    declared_tools_by_group: dict[str, set[str]] = {
        str(g["id"]): {str(t["name"]) for t in (g.get("tools") or []) if t.get("name")}
        for g in groups
        if g.get("id")
    }

    # 工具组 ↔ _GROUP_REGISTRY keys
    registry_groups = set(_GROUP_REGISTRY)
    only_in_yaml = declared_groups - registry_groups
    only_in_registry = registry_groups - declared_groups
    if only_in_yaml or only_in_registry:
        logger.warning(
            "[自校验] tools.yaml 工具组与 _GROUP_REGISTRY 不一致: "
            f"仅 yaml 声明={sorted(only_in_yaml)}, 仅 registry 注册={sorted(only_in_registry)}"
        )

    try:
        registered_tools = {t.name for t in asyncio.run(mcp.list_tools())}
    except Exception as e:
        logger.warning(f"[自校验] 收集已注册工具失败，跳过工具级校验: {e}")
        return

    # 仅比对本次实际启用（已注册）的工具组，避免禁用组造成误报
    declared_tools: set[str] = set()
    for group_id in registered_groups:
        declared_tools |= declared_tools_by_group.get(group_id, set())

    missing = declared_tools - registered_tools   # yaml 声明但未注册
    extra = registered_tools - declared_tools     # 已注册但 yaml 未声明
    if missing or extra:
        logger.warning(
            "[自校验] tools.yaml 与已注册工具不一致: "
            f"声明未注册={sorted(missing)}, 注册未声明={sorted(extra)}"
        )
    else:
        logger.info(f"[自校验] tools.yaml 与已注册工具一致 ({len(registered_tools)} 个工具)")


def register_all_tools(mcp: FastMCP, api: CygnusXAPIClient) -> None:
    registered_groups: set[str] = set()
    for group_id, module_path in _GROUP_REGISTRY.items():
        if not settings.is_tool_group_enabled(group_id):
            logger.info(f"工具组 [{group_id}] 已禁用，跳过注册")
            continue
        module = importlib.import_module(module_path)
        module.register(mcp, api)
        registered_groups.add(group_id)
        logger.debug(f"工具组 [{group_id}] 注册完成")

    _verify_tools_yaml_consistency(mcp, registered_groups)
