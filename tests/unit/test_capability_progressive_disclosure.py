"""F5 渐进暴露能力目录的分层契约测试。

断言：
- ``AgentAbilityCatalog`` 支持 summary / detail 两层（detail 子层优先，顶层旧格式回退）；
- 路由/派单注入键集合（``ROUTER_CATALOG_SUMMARY_KEYS``）只含 summary 层字段，
  不含四段契约键；
- 会诊层 ``capability_detail_context`` 只按选中候选渲染 detail 全文；
- 新增能力条目无需改 Manager/路由 prompt，即自动出现在 summary 层并可加载 detail。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cygnusx.application.services.agentteams_capability_registry import (
    AgentTeamsCapabilityRegistry,
)
from cygnusx.application.services.chat_service import ROUTER_CATALOG_SUMMARY_KEYS
from cygnusx.infrastructure.config.agent_ability_catalog import AgentAbilityCatalog

_DETAIL_KEYS = {
    "capabilities",
    "not_suitable_for",
    "handoff_when",
    "preferred_inputs",
    "input_examples",
}


def _write_catalog(path: Path, extra_entry: str = "") -> AgentAbilityCatalog:
    path.write_text(
        "version: 1\nagents:\n"
        "  agent-rnaseq:\n"
        "    summary: Bulk RNA-seq 全流程。单细胞或 ATAC 输入时 Stop and consult——转交对应专家。\n"
        "    detail:\n"
        "      capabilities: [差异表达, 富集分析]\n"
        "      not_suitable_for: [单细胞专属流程]\n"
        "      handoff_when: [输入为单细胞数据]\n"
        "      preferred_inputs: [FASTQ或计数矩阵, 样本表]\n"
        "      input_examples: [\"6v6 小鼠 FASTQ + 分组表\"]\n"
        "    requires_formal_delivery: true\n"
        "  agent-legacy:\n"
        "    summary: 旧格式条目\n"
        "    capabilities: [质控]\n"
        "    not_suitable_for: [执行]\n"
        "    handoff_when: [需要执行]\n"
        "    preferred_inputs: [样本表]\n"
        + extra_entry,
        encoding="utf-8",
    )
    return AgentAbilityCatalog(path)


class _Domains:
    def router_notes_for(self, agent_id: str, domain: str | None = None) -> str:
        return ""

    def derived_flow_aliases(self) -> dict[str, tuple[str, ...]]:
        return {}


def _agent(agent_id: str) -> dict:
    return {
        "agent_id": agent_id,
        "name": agent_id,
        "category": "analysis",
        "features": {
            "internal_case_role": agent_id,
            "agentteams": {
                "category": "expert",
                "recruitable": True,
                "planner_eligible": True,
                "execution_modes": ["readonly_consultation"],
            },
            "persona": {
                "status_lines": {
                    "recruited": ["ready"],
                    "queued": ["queued"],
                    "running": ["running"],
                    "reviewing": ["reviewing"],
                    "succeeded": ["done"],
                    "failed": ["failed"],
                    "awaiting_input": ["waiting"],
                }
            },
        },
    }


@pytest.mark.unit
def test_catalog_normalize_detail_layer_with_legacy_fallback(tmp_path: Path) -> None:
    """detail 子层优先；顶层旧格式条目仍可加载（回退兼容）。"""
    catalog = _write_catalog(tmp_path / "agent_ability.yaml")

    entry = catalog.get("agent-rnaseq")
    assert entry["capabilities"] == ["差异表达", "富集分析"]
    assert entry["input_examples"] == ["6v6 小鼠 FASTQ + 分组表"]
    assert entry["requires_formal_delivery"] is True

    legacy = catalog.get("agent-legacy")
    assert legacy["capabilities"] == ["质控"]
    assert legacy["not_suitable_for"] == ["执行"]
    assert legacy["input_examples"] == []


@pytest.mark.unit
def test_render_detail_contains_full_contract(tmp_path: Path) -> None:
    """detail 层渲染含四段契约全文与输入示例；未登记条目返回空串。"""
    catalog = _write_catalog(tmp_path / "agent_ability.yaml")

    text = catalog.render_detail("agent-rnaseq")
    for fragment in (
        "差异表达",
        "单细胞专属流程",
        "输入为单细胞数据",
        "FASTQ或计数矩阵",
        "6v6 小鼠 FASTQ + 分组表",
        "触发摘要",
    ):
        assert fragment in text

    assert catalog.render_detail("agent-ghost") == ""


@pytest.mark.unit
def test_router_summary_keys_exclude_detail_contract() -> None:
    """路由/派单注入键集合不得包含 detail 层四段契约键。"""
    assert _DETAIL_KEYS.isdisjoint(ROUTER_CATALOG_SUMMARY_KEYS)
    assert "description" in ROUTER_CATALOG_SUMMARY_KEYS


@pytest.mark.unit
def test_consultation_detail_context_only_for_selected(tmp_path: Path) -> None:
    """会诊层只渲染选中候选的 detail；去重；空选择返回空串。"""
    catalog = _write_catalog(tmp_path / "agent_ability.yaml")
    registry = AgentTeamsCapabilityRegistry(
        ability_catalog=catalog,
        agent_configs=[_agent("agent-rnaseq"), _agent("agent-legacy")],
        domain_registry=_Domains(),
    )

    context = registry.capability_detail_context(["agent-rnaseq", "agent-rnaseq", "agent-ghost"])
    assert "差异表达" in context
    assert "agent-rnaseq" in context
    assert context.count("### agent-rnaseq") == 1
    assert "agent-legacy" not in context  # 未选中的候选不加载 detail
    assert "agent-ghost" not in context

    assert registry.capability_detail_context([]) == ""


@pytest.mark.unit
def test_new_ability_auto_discoverable_in_summary_layer(tmp_path: Path) -> None:
    """新增能力条目无需改 Manager/路由 prompt：自动出现在 summary 层候选目录，
    且会诊层可加载其 detail。"""
    catalog = _write_catalog(
        tmp_path / "agent_ability.yaml",
        extra_entry=(
            "  agent-metagenomics:\n"
            "    summary: 宏基因组物种与功能谱分析。单样本培养物或 16S 上游 QC 不属于它。\n"
            "    detail:\n"
            "      capabilities: [物种注释, 功能谱]\n"
            "      not_suitable_for: [单菌基因组组装]\n"
            "      handoff_when: [需要培养物分析]\n"
            "      preferred_inputs: [宏基因组FASTQ]\n"
            "      input_examples: [\"粪便宏基因组 FASTQ + 分组\"]\n"
        ),
    )
    registry = AgentTeamsCapabilityRegistry(
        ability_catalog=catalog,
        agent_configs=[_agent("agent-rnaseq"), _agent("agent-metagenomics")],
        domain_registry=_Domains(),
    )

    router_catalog = {entry["agent_id"]: entry for entry in registry.chat_router_catalog()}
    # summary 层：新条目自动可发现，description 即触发分类器摘要。
    assert "agent-metagenomics" in router_catalog
    assert router_catalog["agent-metagenomics"]["description"].startswith("宏基因组物种与功能谱分析")

    # detail 层：会诊/派单确认时可加载完整契约。
    detail = registry.capability_detail_context(["agent-metagenomics"])
    assert "物种注释" in detail
    assert "粪便宏基因组 FASTQ + 分组" in detail
