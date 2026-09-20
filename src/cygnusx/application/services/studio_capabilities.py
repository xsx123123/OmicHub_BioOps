"""OmicStudio MCP/Skill 渐进式披露与会话能力边界。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from cygnusx.application.services.skill_service import SkillService
from cygnusx.domain.mcp.entities import MCPServer
from cygnusx.domain.skill.entities import Skill
from cygnusx.infrastructure.config.prompt_loader import render_prompt as render_external_prompt
from cygnusx.infrastructure.mcp.conda_meta_preset import CONDA_META_MCP_SERVER_ID

CAPABILITY_LIST_TOOL = "studio_capabilities_list"
CAPABILITY_LOAD_TOOL = "studio_capability_load"
CAPABILITY_TOOL_NAMES = frozenset({CAPABILITY_LIST_TOOL, CAPABILITY_LOAD_TOOL})
MAX_AUDIT_EVENTS = 100

CAPABILITY_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": CAPABILITY_LIST_TOOL,
            "description": (
                "列出当前 Studio 会话有权使用的 MCP/Skill 能力目录。目录只包含元数据；"
                "需要使用某项能力时，再调用 studio_capability_load。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": CAPABILITY_LOAD_TOOL,
            "description": (
                "按能力目录加载一个当前 Agent 已绑定的 MCP Server 或 Skill。"
                "加载后下一轮模型请求才会获得对应工具或详细 Skill 指令。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["mcp", "skill"],
                        "description": "能力类型",
                    },
                    "id": {
                        "type": "string",
                        "description": "目录中的 capability_id；Skill 使用 skill_id，MCP 使用 UUID 字符串",
                    },
                },
                "required": ["kind", "id"],
                "additionalProperties": False,
            },
        },
    },
]


@dataclass(frozen=True)
class CapabilityState:
    loaded_skill_ids: tuple[str, ...] = ()
    loaded_mcp_ids: tuple[str, ...] = ()
    audit: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "loaded_skill_ids": list(self.loaded_skill_ids),
            "loaded_mcp_ids": list(self.loaded_mcp_ids),
            "audit": list(self.audit),
        }


# 新 Studio 会话默认预加载的内置 MCP（现场装包前先查 conda 元数据）。
# 会话一旦有了显式能力状态（含用户主动卸载），保留用户选择，不再重复默认。
_DEFAULT_LOADED_MCP_IDS = frozenset({str(CONDA_META_MCP_SERVER_ID)})


def normalize_state(
    raw: dict[str, Any] | None,
    skills: list[Skill],
    servers: list[MCPServer],
) -> CapabilityState:
    """只保留当前 Agent 绑定能力，防止会话状态跨 Agent/配置漂移越权。"""
    is_new_session = not isinstance(raw, dict)
    raw = raw if isinstance(raw, dict) else {}
    skill_ids = {skill.skill_id for skill in skills if skill.is_active}
    mcp_ids = {str(server.id) for server in servers if server.is_enabled}
    loaded_skills = tuple(
        item for item in _string_list(raw.get("loaded_skill_ids")) if item in skill_ids
    )
    loaded_mcps = tuple(item for item in _string_list(raw.get("loaded_mcp_ids")) if item in mcp_ids)
    if is_new_session:
        defaults = sorted(_DEFAULT_LOADED_MCP_IDS & mcp_ids)
        loaded_mcps = tuple(dict.fromkeys([*loaded_mcps, *defaults]))
    audit = tuple(item for item in raw.get("audit", []) if isinstance(item, dict))[-MAX_AUDIT_EVENTS:]
    return CapabilityState(loaded_skills, loaded_mcps, audit)


def catalog(
    skills: list[Skill], servers: list[MCPServer], state: CapabilityState
) -> dict[str, Any]:
    """构造可见目录；不包含 Skill prompt、MCP 环境变量或命令行。"""
    return {
        "skills": [
            {
                "capability_id": skill.skill_id,
                "name": skill.name,
                "description": skill.description,
                "category": skill.category,
                "loaded": skill.skill_id in state.loaded_skill_ids,
            }
            for skill in skills
            if skill.is_active
        ],
        "mcp": [
            {
                "capability_id": str(server.id),
                "name": server.name,
                "description": server.description,
                "tool_count": len(server.tools),
                "tool_names": [tool.tool_name for tool in server.tools],
                "available": server.is_available(),
                "loaded": str(server.id) in state.loaded_mcp_ids,
            }
            for server in servers
            if server.is_enabled
        ],
        "loaded_skill_ids": list(state.loaded_skill_ids),
        "loaded_mcp_ids": list(state.loaded_mcp_ids),
    }


def render_prompt(
    base_prompt: str,
    skills: list[Skill],
    servers: list[MCPServer],
    state: CapabilityState,
) -> str:
    """渲染 Studio 初始元数据目录与已加载能力，不泄露未加载 prompt。"""
    sections = [base_prompt] if base_prompt else []
    loaded_skills = [skill for skill in skills if skill.skill_id in state.loaded_skill_ids]
    skill_prompt = SkillService.build_skills_prompt(loaded_skills)
    if skill_prompt:
        sections.append(skill_prompt)

    visible = catalog(skills, servers, state)
    skill_lines: list[str] = []
    if visible["skills"]:
        for item in visible["skills"]:
            marker = "（已加载）" if item["loaded"] else ""
            skill_lines.append(
                f"- `{item['capability_id']}`：{item['name']}{marker} — "
                f"{item['description']}"
            )
    mcp_lines: list[str] = []
    if visible["mcp"]:
        for item in visible["mcp"]:
            marker = "（已加载）" if item["loaded"] else ""
            availability = "可用" if item["available"] else "暂不可用"
            mcp_lines.append(
                f"- `{item['capability_id']}`：{item['name']}{marker} — "
                f"{item['description']}；{item['tool_count']} 个工具；{availability}"
            )
    sections.append(
        render_external_prompt(
            "studio.capability_catalog",
            skills_catalog="\n".join(skill_lines) or "当前无可用 Skill。",
            mcp_catalog="\n".join(mcp_lines) or "当前无可用 MCP。",
        )
    )
    return "\n\n".join(section for section in sections if section)


def loaded_servers(servers: list[MCPServer], state: CapabilityState) -> list[MCPServer]:
    """返回已加载且仍可用的 MCP；绑定/启用边界由调用方再次校验。"""
    loaded = set(state.loaded_mcp_ids)
    return [server for server in servers if str(server.id) in loaded and server.is_available()]


def mcp_tools(servers: list[MCPServer]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.tool_name,
                "description": tool.description or "",
                "parameters": tool.input_schema or {"type": "object", "properties": {}},
            },
        }
        for server in servers
        for tool in server.tools
    ]


def load_capability(
    kind: Literal["mcp", "skill"],
    capability_id: str,
    skills: list[Skill],
    servers: list[MCPServer],
    state: CapabilityState,
    reserved_tool_names: set[str],
) -> tuple[CapabilityState | None, dict[str, Any]]:
    """校验并加载单项能力；返回新状态及给 LLM 的结果信封。"""
    capability_id = str(capability_id).strip()
    if kind == "skill":
        skill = next((item for item in skills if item.skill_id == capability_id and item.is_active), None)
        if skill is None:
            return None, {"success": False, "error": "Skill 未绑定、未启用或不存在"}
        loaded = list(state.loaded_skill_ids)
        if capability_id not in loaded:
            loaded.append(capability_id)
        return (
            CapabilityState(tuple(loaded), state.loaded_mcp_ids, state.audit),
            {"success": True, "kind": kind, "capability_id": capability_id, "name": skill.name},
        )

    server = next((item for item in servers if str(item.id) == capability_id and item.is_enabled), None)
    if server is None:
        return None, {"success": False, "error": "MCP 未绑定、未启用或不存在"}
    if not server.is_available():
        return None, {"success": False, "error": "MCP 当前不可用，无法加载"}
    if capability_id in state.loaded_mcp_ids:
        return (
            state,
            {
                "success": True,
                "kind": kind,
                "capability_id": capability_id,
                "name": server.name,
                "tool_names": [tool.tool_name for tool in server.tools],
                "already_loaded": True,
            },
        )
    conflicts = sorted({tool.tool_name for tool in server.tools} & reserved_tool_names)
    if conflicts:
        return None, {"success": False, "error": f"MCP 工具名冲突，拒绝加载: {conflicts}"}
    loaded = list(state.loaded_mcp_ids)
    if capability_id not in loaded:
        loaded.append(capability_id)
    return (
        CapabilityState(state.loaded_skill_ids, tuple(loaded), state.audit),
        {
            "success": True,
            "kind": kind,
            "capability_id": capability_id,
            "name": server.name,
            "tool_names": [tool.tool_name for tool in server.tools],
        },
    )


def audit_event(action: str, kind: str | None, capability_id: str | None, success: bool) -> dict[str, Any]:
    return {
        "action": action,
        "kind": kind,
        "capability_id": capability_id,
        "success": success,
        "at": datetime.now(UTC).isoformat(),
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [str(item) for item in value if str(item).strip()]
