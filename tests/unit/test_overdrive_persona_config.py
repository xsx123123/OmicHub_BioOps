"""Overdrive v2 Persona 与预算配置的纯 YAML 契约测试。"""

from __future__ import annotations

from pathlib import Path

import yaml

AI_DIR = Path("data/ai")
PERSONA_FIELDS = {
    "archetype",
    "traits",
    "working_style",
    "communication_style",
    "challenge_style",
    "status_lines",
}
ASSISTANT_STATUSES = {
    "recruited",
    "queued",
    "running",
    "reviewing",
    "succeeded",
    "failed",
    "awaiting_input",
}

# Persona 只能影响提示词和展示，不能顺带改变已有的工具、MCP 或 Skill 权限。
EXPECTED_TOOL_DECLARATIONS = {
    "router": {
        "tool_packs": ["workspace", "agentteams_case"],
        "mcp_ids": [],
        "skill_ids": [],
    },
    "orchestrator": {
        "tool_packs": ["workspace", "research"],
        "mcp_ids": [],
        "skill_ids": [],
    },
    "general": {
        "tool_packs": [
            "workspace",
            "research",
            "memory",
            "handoff",
            "subagents",
            "agentteams_case",
            "cloud_ops",
        ],
        "mcp_ids": [],
        "skill_ids": [
            "blast",
            "genome-tools",
            "atac-tools",
            "maftools-gistic2",
            "mutational-patterns",
        ],
    },
    "data": {
        "tool_packs": ["workspace", "research", "memory", "handoff", "agentteams_case"],
        "mcp_ids": [],
        "skill_ids": ["md5"],
    },
    "qc": {
        "tool_packs": ["workspace", "research", "memory", "handoff", "agentteams_case"],
        "mcp_ids": [],
        "skill_ids": ["fastq-screen", "genome-tools", "md5"],
    },
    "code": {
        "tool_packs": ["workspace", "handoff", "subagents", "agentteams_case"],
        "mcp_ids": [],
        "skill_ids": ["software-manager", "logger-plugin", "md5", "data-deliver"],
    },
    "viz": {
        "tool_packs": ["workspace", "visualization", "handoff", "agentteams_case"],
        "mcp_ids": [],
        "skill_ids": ["r-plot-library", "dotplot"],
    },
    "delivery": {
        "tool_packs": ["workspace", "research", "memory", "handoff", "agentteams_case"],
        "mcp_ids": [],
        "skill_ids": ["md5"],
    },
    "rnaseq": {
        "tool_packs": ["workspace", "research", "rnaseq", "memory", "handoff", "subagents", "agentteams_case"],
        "mcp_ids": [],
        "skill_ids": ["rnaflow", "deg", "enrichments", "gene-matrix", "library-type", "wgcna", "rmats", "tissue-specific-genes", "gffconvert", "gaf2go", "go-annotation", "kegg-pull", "fastq-screen", "data-deliver", "md5"],
    },
    "atacseq": {
        "tool_packs": ["workspace", "research", "atacseq", "memory", "handoff", "subagents", "agentteams_case"],
        "mcp_ids": [],
        "skill_ids": ["atacflow", "atac-tools", "genome-tools", "deg", "enrichments", "fastq-screen", "gffconvert", "go-annotation", "kegg-pull", "data-deliver", "md5"],
    },
    "scrna": {
        "tool_packs": ["workspace", "research", "memory", "handoff", "agentteams_case"],
        "mcp_ids": [],
        "skill_ids": ["human-mouse-cell-annotation", "plant-cell-annotation", "scrna-pipeline-overview", "scrna-object-convert", "scrna-recluster", "scrna-annotation-ref", "scrna-tcell-projectils", "scrna-deg-analysis", "scrna-annotation-stats", "scrna-quarto-report", "scrna-seq"],
    },
    "scrna_upstream": {
        "tool_packs": ["workspace", "research", "memory", "handoff", "agentteams_case"],
        "mcp_ids": [],
        "skill_ids": [],
    },
    "scrna_integration": {
        "tool_packs": ["workspace", "research", "memory", "handoff", "agentteams_case"],
        "mcp_ids": [],
        "skill_ids": [],
    },
    "scrna_advanced": {
        "tool_packs": ["workspace", "research", "memory", "handoff", "agentteams_case"],
        "mcp_ids": [],
        "skill_ids": ["human-mouse-cell-annotation", "plant-cell-annotation", "scrna-object-convert", "scrna-recluster", "scrna-annotation-ref", "scrna-tcell-projectils", "scrna-deg-analysis", "scrna-annotation-stats", "scrna-quarto-report"],
    },
    "shania": {
        "tool_packs": ["workspace", "research", "memory", "handoff"],
        "mcp_ids": [],
        "skill_ids": [],
    },
    "cloud_ops": {
        "tool_packs": ["cloud_ops", "research", "memory", "handoff", "subagents", "agentteams_case"],
        "mcp_ids": [],
        "skill_ids": [],
    },
    "mcp_builder": {
        "tool_packs": ["workspace", "memory", "handoff"],
        "mcp_ids": [],
        "skill_ids": [],
    },
}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _enabled_agent_names() -> tuple[str, ...]:
    config = _load(Path("data/OmicHub.yaml"))
    return tuple(config["agents"]["enabled"])


def test_enabled_agent_personas_are_complete_deterministic_and_permission_neutral() -> None:
    """每个启用 Agent 都有人格契约，且人格不改变既有权限。"""
    enabled_agents = _enabled_agent_names()
    # orchestrator 是 MAS 显式开关下的可选 Agent，不在默认 enabled 清单中，
    # 但仍需保持与其他内置 Agent 相同的人格契约。
    assert set(enabled_agents) == set(EXPECTED_TOOL_DECLARATIONS) - {"orchestrator"}
    for agent_name in (*enabled_agents, "orchestrator"):
        config = _load(AI_DIR / f"{agent_name}.yaml")
        persona = config["features"]["persona"]

        assert set(persona) == PERSONA_FIELDS, f"{agent_name} Persona 字段不完整"
        assert isinstance(persona["traits"], list) and persona["traits"]
        for field in PERSONA_FIELDS - {"traits", "status_lines"}:
            assert isinstance(persona[field], str) and persona[field].strip()

        status_lines = persona["status_lines"]
        assert set(status_lines) == ASSISTANT_STATUSES
        for status, lines in status_lines.items():
            assert isinstance(lines, list) and len(lines) == 1, (
                f"{agent_name}.{status} 必须只有一条稳定文案，避免刷新时随机变化"
            )
            assert isinstance(lines[0], str) and lines[0].strip()

        actual_tools = {
            key: config.get(key, []) for key in ("tool_packs", "mcp_ids", "skill_ids")
        }
        assert actual_tools == EXPECTED_TOOL_DECLARATIONS[agent_name]


def test_overdrive_v2_planning_research_and_review_budgets_are_explicit() -> None:
    limits = _load(AI_DIR / "_overdrive_limits.yaml")

    assert limits["planning"]["max_revision_rounds"] == 3
    assert limits["research"] == {
        "source_timeout_seconds": 20,
        # model_knowledge 是 LLM 流式调用,与检索类源共用 20s 必超时,单独预算。
        "model_timeout_seconds": 45,
        "max_evidence_items_per_source": 8,
        "wall_timeout_seconds": 75,
    }
    assert limits["manager_review"] == {
        "rule_fast_path": True,
        "max_tokens": 1200,
        "timeout_seconds": 30,
    }

    # Keep the declaration safe even while runtime consumers are being wired in.
    assert isinstance(limits["manager_review"]["rule_fast_path"], bool)
    assert limits["planning"]["max_revision_rounds"] >= 1
    assert limits["research"]["source_timeout_seconds"] > 0
    assert limits["research"]["wall_timeout_seconds"] >= limits["research"]["source_timeout_seconds"]
    assert limits["research"]["max_evidence_items_per_source"] >= 1
    assert limits["manager_review"]["max_tokens"] >= 1
    assert limits["manager_review"]["timeout_seconds"] > 0
