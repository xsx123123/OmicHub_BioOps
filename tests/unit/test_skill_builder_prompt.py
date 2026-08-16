"""Skill Builder Agent 提示词与产物规范回归。"""

from __future__ import annotations

from pathlib import Path

import yaml

AI_DIR = Path("data/ai")
PROMPT = AI_DIR / "prompts" / "skill_builder.md"
YAML = AI_DIR / "skill_builder.yaml"

STANDARD_SECTIONS = (
    "角色与职责边界",
    "对话与执行模式",
    "输入确认",
    "知识检索与证据规则",
    "方法论与专业决策",
    "工具、Skill 与工作区协议",
    "执行确认与安全边界",
    "输出与交付规范",
    "失败、降级与诚实约束",
    "转介、交接与协作",
)


def test_skill_builder_prompt_within_guardrail():
    """mcp_builder 之后第二个被瘦身的提示词，必须遵守 120 行护栏。"""
    lines = PROMPT.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 120, f"skill_builder.md {len(lines)} 行，超过 120 行护栏"


def test_skill_builder_prompt_has_standard_sections_in_order():
    text = PROMPT.read_text(encoding="utf-8")
    positions = []
    for section in STANDARD_SECTIONS:
        heading = f"## {section}"
        assert heading in text, f"skill_builder.md 缺少统一章节：{section}"
        positions.append(text.index(heading))
    assert positions == sorted(positions), "skill_builder.md 统一章节顺序不正确"


def test_skill_builder_prompt_has_key_red_lines():
    text = PROMPT.read_text(encoding="utf-8")
    assert "不代为提交" in text
    assert "不" in text and "自动挂载" in text
    assert "禁止" in text and "宿主机" in text
    assert "CANDIDATE_MANIFEST.json" in text
    assert "OSDP" in text


def test_skill_builder_yaml_is_valid_and_enabled():
    cfg = yaml.safe_load(YAML.read_text(encoding="utf-8"))
    assert cfg["agent_id"] == "agent-skill-builder"
    assert cfg["model"] == "deepseek-v4-flash"
    assert "skill-candidates" in cfg.get("welcome_message", "")
    # 模型分级注释不是运行时强制，但保留作为文档约定
    assert "workspace" in cfg["tool_packs"]
    assert "handoff" in cfg["tool_packs"]


def test_skill_builder_does_not_target_router():
    cfg = yaml.safe_load(YAML.read_text(encoding="utf-8"))
    targets = cfg.get("handoff", {}).get("allowed_targets", [])
    assert "agent-router" not in targets
    assert "agent-skill-builder" not in targets
