"""Agent YAML 加载器 —— 从 data/ai/*.yaml 加载助手配置

启动时由 AgentService 调用，按 OmicHub.yaml 中 agents.enabled 列表加载对应 YAML。
每个 YAML 文件定义一个助手的完整配置（模型、MCP、技能、提示词等）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from omichub.core.config import get_settings
from omichub.infrastructure.config.prompt_loader import get_prompt
from omichub.infrastructure.config.runtime_image_loader import get_runtime_images
from omichub.infrastructure.mcp.presets import (
    OMICHUB_PLATFORM_SERVER_ID,
    OMICHUB_TOOLS_SERVER_ID,
)


def load_agent_configs() -> list[dict[str, Any]]:
    """加载启用的 Agent YAML 配置列表

    读取 OmicHub.yaml 的 agents.enabled，逐个加载 data/ai/{name}.yaml。
    文件不存在或解析失败时跳过并记录日志，不影响其他助手。
    """
    settings = get_settings()
    site_yaml_path = Path(settings.site_content_yaml)

    # 读取 OmicHub.yaml 获取 agents.enabled 列表
    enabled_names = _load_enabled_agents(site_yaml_path)
    if not enabled_names:
        return []

    # 逐个加载 data/ai/{name}.yaml
    agents_dir = site_yaml_path.parent / "ai"
    configs: list[dict[str, Any]] = []

    for name in enabled_names:
        yaml_path = agents_dir / f"{name}.yaml"
        config = _load_single_agent(yaml_path)
        if config:
            configs.append(config)

    return configs


def _load_enabled_agents(site_yaml_path: Path) -> list[str]:
    """从 OmicHub.yaml 读取 agents.enabled 列表"""
    if not site_yaml_path.exists():
        return []
    try:
        with site_yaml_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError):
        return []

    if not isinstance(data, dict):
        return []

    agents_section = data.get("agents", {})
    if not isinstance(agents_section, dict):
        return []

    enabled = agents_section.get("enabled", [])
    return [str(name) for name in enabled if name]


def _load_single_agent(yaml_path: Path) -> dict[str, Any] | None:
    """加载单个 Agent YAML 文件，失败返回 None"""
    if not yaml_path.exists():
        logging.getLogger(__name__).warning(f"Agent YAML 不存在: {yaml_path}")
        return None

    try:
        with yaml_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError) as e:
        logging.getLogger(__name__).warning(f"Agent YAML 解析失败 {yaml_path}: {e}")
        return None

    if not isinstance(data, dict):
        return None

    # 必填字段校验
    if not data.get("agent_id"):
        logging.getLogger(__name__).warning(f"Agent YAML 缺少 agent_id: {yaml_path}")
        return None

    prompt_file = str(data.get("prompt_file") or "").strip()
    prompt_ref = str(data.get("prompt_ref") or "").strip()
    if prompt_file:
        prompt = _load_local_prompt(yaml_path, prompt_file)
        if not prompt:
            logging.getLogger(__name__).warning(
                "Agent prompt_file 无法解析: %s -> %s", yaml_path, prompt_file
            )
            return None
        data["system_prompt"] = _append_shared_sandbox_protocol(prompt, yaml_path)
    elif prompt_ref:
        prompt = get_prompt(prompt_ref)
        if not prompt:
            logging.getLogger(__name__).warning(
                "Agent prompt_ref 无法解析: %s -> %s", yaml_path, prompt_ref
            )
            return None
        data["system_prompt"] = _append_shared_sandbox_protocol(prompt, yaml_path)

    _apply_tool_packs(data, yaml_path)

    # Handoff 是运行时能力声明，统一放入 features 以便内置 Agent 同步到数据库。
    handoff = data.pop("handoff", None)
    if isinstance(handoff, dict):
        features = dict(data.get("features") or {})
        features["handoff"] = handoff
        data["features"] = features

    # 可选 studio 段（OmicStudio 工作台）：{enabled: bool, image?: str}
    # 结构非法时剔除该段，不影响 Agent 本体加载
    studio = data.get("studio")
    if studio is not None:
        if not isinstance(studio, dict):
            data.pop("studio", None)
        else:
            cleaned: dict[str, Any] = {}
            if "enabled" in studio:
                enabled = studio["enabled"]
                cleaned["enabled"] = (
                    enabled.strip().lower() in {"1", "true", "yes", "on"}
                    if isinstance(enabled, str)
                    else bool(enabled)
                )
            runtime_profile = str(studio.get("runtime_profile") or "").strip()
            required_capabilities = {
                str(value).strip()
                for value in studio.get("required_capabilities", [])
                if str(value).strip()
            }
            if runtime_profile:
                try:
                    _, profile = get_runtime_images().select(
                        required_capabilities, "studio", runtime_profile
                    )
                except (KeyError, ValueError, LookupError, RuntimeError) as exc:
                    logging.getLogger(__name__).warning(
                        "Agent Studio 运行时无效 %s: %s", yaml_path, exc
                    )
                    return None
                cleaned["runtime_profile"] = runtime_profile
                cleaned["required_capabilities"] = sorted(required_capabilities)
                cleaned["image"] = profile.image
            elif studio.get("image"):
                cleaned["image"] = str(studio["image"])
            # 默认会话模式：studio 表示选中该 Agent 时直接进入 AI 工作台
            default_mode = str(studio.get("default_mode") or "").strip().lower()
            if default_mode in {"studio", "chat"}:
                cleaned["default_mode"] = default_mode
            data["studio"] = cleaned

    return data


def _load_local_prompt(yaml_path: Path, prompt_file: str) -> str:
    """读取与 Agent YAML 同目录的可编辑 Markdown 提示词。"""
    root = yaml_path.parent.resolve()
    path = (root / prompt_file).resolve()
    if path != root and root not in path.parents:
        logging.getLogger(__name__).warning(
            "Agent prompt_file 路径越界: %s -> %s", yaml_path, prompt_file
        )
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _append_shared_sandbox_protocol(prompt: str, yaml_path: Path) -> str:
    """所有 Agent 只在加载时追加一份共享沙盒协议。"""
    shared_path = (yaml_path.parent / "prompts/shared/sandbox_protocol.md").resolve()
    root = yaml_path.parent.resolve()
    if shared_path != root and root not in shared_path.parents:
        return prompt
    try:
        shared = shared_path.read_text(encoding="utf-8").strip()
    except OSError:
        return prompt
    return f"{prompt}\n\n{shared}" if shared else prompt


def _apply_tool_packs(data: dict[str, Any], yaml_path: Path) -> None:
    """把 data/ai/tools 下的声明式工具包合并为 Agent 绑定。"""
    selected = data.get("tool_packs") or []
    if not selected:
        return
    if not isinstance(selected, list):
        logging.getLogger(__name__).warning("Agent tool_packs 必须为列表: %s", yaml_path)
        data["tool_packs"] = []
        return

    packs: list[dict[str, Any]] = []
    mcp_ids = [str(value) for value in data.get("mcp_ids", []) if str(value).strip()]
    skill_ids = [str(value) for value in data.get("skill_ids", []) if str(value).strip()]
    tools_dir = yaml_path.parent / "tools"
    for raw_name in selected:
        name = str(raw_name).strip()
        if not name or "/" in name or "\\" in name or name in {".", ".."}:
            logging.getLogger(__name__).warning("忽略非法 Agent 工具包名称: %r", raw_name)
            continue
        pack_path = tools_dir / f"{name}.yaml"
        try:
            pack = yaml.safe_load(pack_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            logging.getLogger(__name__).warning("Agent 工具包无法加载 %s: %s", pack_path, exc)
            continue
        if not isinstance(pack, dict):
            logging.getLogger(__name__).warning("Agent 工具包必须为 YAML 对象: %s", pack_path)
            continue

        builtin_tools = [str(value) for value in pack.get("builtin_tools", []) if str(value).strip()]
        platform_tools = [str(value) for value in pack.get("platform_tools", []) if str(value).strip()]
        pack_mcp_ids = [str(value) for value in pack.get("mcp_ids", []) if str(value).strip()]
        pack_skill_ids = [str(value) for value in pack.get("skill_ids", []) if str(value).strip()]
        mcp_tool_names = {
            str(server_id): [str(tool) for tool in tool_names if str(tool).strip()]
            for server_id, tool_names in (pack.get("mcp_tools") or {}).items()
            if isinstance(tool_names, list)
        }
        if builtin_tools:
            mcp_ids.append(str(OMICHUB_TOOLS_SERVER_ID))
        if platform_tools:
            mcp_ids.append(str(OMICHUB_PLATFORM_SERVER_ID))
            mcp_tool_names.setdefault(str(OMICHUB_PLATFORM_SERVER_ID), []).extend(platform_tools)
        mcp_ids.extend(pack_mcp_ids)
        skill_ids.extend(pack_skill_ids)
        packs.append(
            {
                "id": str(pack.get("id") or name),
                "description": str(pack.get("description") or ""),
                "builtin_tools": builtin_tools,
                "mcp_tools": mcp_tool_names,
            }
        )

    data["mcp_ids"] = list(dict.fromkeys(mcp_ids))
    data["skill_ids"] = list(dict.fromkeys(skill_ids))
    features = dict(data.get("features") or {})
    features["tool_packs"] = packs
    data["features"] = features
