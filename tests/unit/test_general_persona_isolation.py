"""Manager 人格分层红线守卫（实施手册 §3.3，验收表 #7）。

/api/v1/chat 与 /api/v1/studio 的通用助手（agent-general）人格必须保持原样：
对两个入口各固定一条最小请求对应的 system prompt 组装方式，断言：

1. 组装后的 system prompt 不含任何 Manager/部门经理相关片段
   （关键词表：「部门经理」「客户经理」「协作室」「扮演 Manager」）；
2. persona 段与基线快照逐字一致；
3. 通用助手的共享配置源（general.yaml 的 name/persona/prompt_file 与
   prompts/general.md）未被 Manager 个性化污染；
4. 协作室 Manager 拥有独立人格文件，且不复用 prompts/general.md。

任何 PR 修改 general.yaml 的 name/persona/prompt_file 或 prompts/general.md
导致 chat/studio 人格变化时，本测试失败即拦截。纯文件层 + 纯函数组装，
不触库、不起真实服务。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import yaml

from omichub.application.services.agent_service import (
    AgentService,
    render_persona_system_prompt,
)
from omichub.application.services.studio_tools import STUDIO_SYSTEM_PROMPT_SUFFIX
from omichub.infrastructure.config.agent_loader import load_agent_configs

AI_DIR = Path("data/ai")
GENERAL_YAML = AI_DIR / "general.yaml"
GENERAL_PROMPT = AI_DIR / "prompts" / "general.md"
MANAGER_YAML = AI_DIR / "agentteams_manager.yaml"
MANAGER_PROMPT = AI_DIR / "prompts" / "agentteams_manager.md"

# 手册 §3.3 关键词表：Manager/部门经理相关片段不得出现在 chat/studio 的 system prompt。
FORBIDDEN_MANAGER_FRAGMENTS = ("部门经理", "客户经理", "协作室", "扮演 Manager")

# agent-general persona 段基线快照（render_persona_system_prompt 输出，逐字一致）。
# 修改 general.yaml 的 persona 段必须先更新本快照并说明理由。
GENERAL_PERSONA_SNAPSHOT = (
    "## Agent Persona（仅影响表达与协作方式）\n"
    "- 角色原型：好奇而结构化的研究顾问\n"
    "- 工作方式：先澄清研究目标和数据契约，再连接跨领域信息并形成可执行方案\n"
    "- 表达风格：用清晰层次解释问题，主动标注假设、证据和待确认事项\n"
    "- 质疑与追问方式：遇到目标含糊或输入不完整时主动追问，不用臆测填补关键条件\n"
    "- 稳定特质：好奇、结构化、善于追问、擅长综合\n"
    "\n"
    "表达边界：\n"
    "- 以上内容只用于调整表达、解释顺序、追问方式和风险提醒。\n"
    "- 不得据此新增、移除或扩大工具、MCP、Skill、审批、配额或数据访问权限。\n"
    "- 不得把 Persona 偏好当作事实、证据、质量标准或执行结果；事实仍以工具和真实结果为准。"
)


def _general_config() -> dict:
    configs = [cfg for cfg in load_agent_configs() if cfg.get("agent_id") == "agent-general"]
    assert configs, "agent-general 未被 agents.enabled 加载"
    return configs[0]


def _assemble_chat_system_prompt(config: dict) -> str:
    """/api/v1/chat 最小请求的系统 prompt 组装：角色 prompt + persona + 沟通契约。"""
    agent = SimpleNamespace(features=config.get("features") or {})
    prompt = AgentService._append_persona_prompt(str(config.get("system_prompt") or ""), agent)
    return AgentService._append_communication_contract(prompt, agent)


def _assemble_studio_system_prompt(config: dict) -> str:
    """/api/v1/studio 最小请求的系统 prompt 组装：chat 基座 + Studio 后缀。"""
    base = _assemble_chat_system_prompt(config)
    return f"{base}\n\n{STUDIO_SYSTEM_PROMPT_SUFFIX}" if base else STUDIO_SYSTEM_PROMPT_SUFFIX


def test_chat_system_prompt_has_no_manager_persona() -> None:
    prompt = _assemble_chat_system_prompt(_general_config())
    for fragment in FORBIDDEN_MANAGER_FRAGMENTS:
        assert fragment not in prompt, f"/api/v1/chat system prompt 混入 Manager 片段: {fragment}"


def test_studio_system_prompt_has_no_manager_persona() -> None:
    prompt = _assemble_studio_system_prompt(_general_config())
    for fragment in FORBIDDEN_MANAGER_FRAGMENTS:
        assert fragment not in prompt, f"/api/v1/studio system prompt 混入 Manager 片段: {fragment}"


def test_general_persona_section_matches_baseline_snapshot() -> None:
    config = _general_config()
    persona_prompt = render_persona_system_prompt(config.get("features") or {})
    assert persona_prompt == GENERAL_PERSONA_SNAPSHOT, (
        "agent-general persona 段与基线快照不一致；若确为有意修改，"
        "请同步更新本快照并在 PR 中说明理由"
    )
    # persona 段真实进入组装后的 chat system prompt。
    assert persona_prompt in _assemble_chat_system_prompt(config)


def test_general_shared_config_source_untouched() -> None:
    """禁区红线：general.yaml 的身份字段与 prompt 文件指针不得被 Manager 化。"""
    raw = yaml.safe_load(GENERAL_YAML.read_text(encoding="utf-8"))
    assert raw["name"] == "通用助手"
    assert raw["prompt_file"] == "prompts/general.md"
    persona = (raw.get("features") or {}).get("persona") or {}
    assert persona.get("archetype") == "好奇而结构化的研究顾问"
    # 通用助手人格源文件本身不得含 Manager 片段。
    text = GENERAL_PROMPT.read_text(encoding="utf-8")
    for fragment in FORBIDDEN_MANAGER_FRAGMENTS:
        assert fragment not in text, f"prompts/general.md 混入 Manager 片段: {fragment}"


def test_manager_persona_is_isolated_from_general() -> None:
    """协作室 Manager 人格独立成文件，禁止复用通用助手 prompt。"""
    raw = yaml.safe_load(MANAGER_YAML.read_text(encoding="utf-8"))
    assert raw["agent_id"] == "agentteams-manager"
    assert raw["name"] == "生物信息部门经理"
    assert raw["prompt_file"] != "prompts/general.md"
    assert raw["prompt_file"] == "prompts/agentteams_manager.md"
    agentteams = (raw.get("features") or {}).get("agentteams") or {}
    assert agentteams.get("recruitable") is False
    assert agentteams.get("planner_eligible") is True
    manager_prompt = MANAGER_PROMPT.read_text(encoding="utf-8")
    assert manager_prompt.strip()
    assert "好奇而结构化的研究顾问" not in manager_prompt
