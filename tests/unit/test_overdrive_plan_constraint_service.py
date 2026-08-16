"""Overdrive authoritative anchor validation tests."""

import pytest

from omichub.application.services.overdrive_plan_constraint_service import (
    apply_authoritative_plan,
    merge_with_authoritative,
    validate_plan,
)
from omichub.domain.domains.schema import AssignmentRule


def _rules() -> list[AssignmentRule]:
    return [
        AssignmentRule(
            id="search",
            when="planning_or_analysis",
            agent_match=["agent-code"],
            authoritative=True,
            required=True,
            allow_split=True,
            task_id="tnpd-homolog-search",
            task="search",
            accepts_inputs=["genomes"],
            produces_outputs=["hits"],
        ),
        AssignmentRule(
            id="tree",
            when="planning_or_analysis",
            agent_match=["agent-viz"],
            authoritative=True,
            required=True,
            task_id="tnpd-phylogeny",
            task="tree",
            depends_on=["tnpd-homolog-search"],
            accepts_inputs=["hits"],
            produces_outputs=["tree"],
        ),
    ]


CATALOG = {
    "agent-code": {"agent_id": "agent-code", "name": "代码助手", "category": "code"},
    "agent-viz": {"agent_id": "agent-viz", "name": "可视化助手", "category": "visualization"},
    "agent-general": {"agent_id": "agent-general", "name": "通用助手", "category": "general"},
}


def test_valid_split_plan_preserves_dynamic_shards() -> None:
    assignments = [
        {
            "task_id": "tnpd-homolog-search-shard-1",
            "agent_id": "agent-code",
            "depends_on": [],
            "accepts_inputs": ["genomes 1-100"],
            "produces_outputs": ["hits"],
        },
        {
            "task_id": "tnpd-homolog-search-shard-2",
            "agent_id": "agent-code",
            "depends_on": [],
            "accepts_inputs": ["genomes 101-200"],
            "produces_outputs": ["hits"],
        },
        {
            "task_id": "tnpd-phylogeny",
            "agent_id": "agent-viz",
            "depends_on": ["tnpd-homolog-search-shard-1", "tnpd-homolog-search-shard-2"],
            "accepts_inputs": ["hits"],
            "produces_outputs": ["tree"],
        },
    ]

    assert validate_plan(assignments, _rules(), CATALOG) == []


def test_plan_validation_reports_missing_anchor_contract_and_agent_boundary() -> None:
    assignments = [
        {
            "task_id": "tnpd-phylogeny",
            "agent_id": "agent-general",
            "depends_on": [],
            "accepts_inputs": [],
            "produces_outputs": [],
        }
    ]

    violations = validate_plan(assignments, _rules(), CATALOG)

    assert "缺失必需锚点 tnpd-homolog-search" in violations
    assert any("agent 超出允许范围" in item for item in violations)
    assert any("缺少 accepts_inputs" in item for item in violations)
    assert any("缺少 produces_outputs" in item for item in violations)


def test_rule_merge_keeps_non_conflicting_llm_tasks() -> None:
    authoritative = [
        {"task_id": "tnpd-homolog-search", "agent_id": "agent-code", "depends_on": []},
        {
            "task_id": "tnpd-phylogeny",
            "agent_id": "agent-viz",
            "depends_on": ["tnpd-homolog-search"],
        },
    ]
    llm = [
        {"task_id": "quality-report", "agent_id": "agent-general", "depends_on": []},
        {"task_id": "tnpd-phylogeny", "agent_id": "agent-general", "depends_on": []},
    ]

    merged = merge_with_authoritative(llm, authoritative, _rules())

    assert [item["task_id"] for item in merged] == [
        "tnpd-homolog-search",
        "tnpd-phylogeny",
        "quality-report",
    ]


def _authoritative_assignments() -> list[dict[str, object]]:
    return [
        {
            "task_id": "tnpd-homolog-search",
            "agent_id": "agent-code",
            "depends_on": [],
            "accepts_inputs": ["genomes"],
            "produces_outputs": ["hits"],
        },
        {
            "task_id": "tnpd-phylogeny",
            "agent_id": "agent-viz",
            "depends_on": ["tnpd-homolog-search"],
            "accepts_inputs": ["hits"],
            "produces_outputs": ["tree"],
        },
    ]


async def _unused_repair(_violations: list[str]) -> tuple[str, list[dict[str, object]]]:
    raise AssertionError("该模式不应触发修复调用")


@pytest.mark.asyncio
async def test_override_replaces_assignments_but_never_overrides_llm_speech() -> None:
    result = await apply_authoritative_plan(
        assignments=[{"task_id": "custom", "agent_id": "agent-general"}],
        speech="LLM 针对本任务生成的原始说明",
        authoritative_assignments=_authoritative_assignments(),
        rules=_rules(),
        catalog_by_id=CATALOG,
        mode="override",
        repair_enabled=True,
        repair_plan=_unused_repair,
    )

    assert result.assignments == _authoritative_assignments()
    assert result.speech == "LLM 针对本任务生成的原始说明"
    assert result.planning_mode == "rule_override"
    assert result.repair_attempted is False


@pytest.mark.asyncio
async def test_off_mode_preserves_llm_plan_without_rule_validation() -> None:
    original = [{"task_id": "custom", "agent_id": "agent-general"}]
    result = await apply_authoritative_plan(
        assignments=original,
        speech="LLM 原文",
        authoritative_assignments=_authoritative_assignments(),
        rules=_rules(),
        catalog_by_id=CATALOG,
        mode="off",
        repair_enabled=True,
        repair_plan=_unused_repair,
    )

    assert result.assignments == original
    assert result.planning_mode == "llm"


@pytest.mark.asyncio
async def test_successful_repair_returns_repaired_plan_and_speech() -> None:
    async def repair(_violations: list[str]) -> tuple[str, list[dict[str, object]]]:
        return "已按实际分片和依赖修正计划", _authoritative_assignments()

    result = await apply_authoritative_plan(
        assignments=[{"task_id": "custom", "agent_id": "agent-general"}],
        speech="原始计划说明",
        authoritative_assignments=_authoritative_assignments(),
        rules=_rules(),
        catalog_by_id=CATALOG,
        mode="constraint",
        repair_enabled=True,
        repair_plan=repair,
    )

    assert result.assignments == _authoritative_assignments()
    assert result.speech == "已按实际分片和依赖修正计划"
    assert result.planning_mode == "llm_repaired"
    assert result.violations == []
    assert result.repair_attempted is True


@pytest.mark.asyncio
async def test_failed_repair_rule_merges_and_preserves_latest_llm_speech() -> None:
    invalid = [{"task_id": "quality-report", "agent_id": "agent-general"}]

    async def repair(_violations: list[str]) -> tuple[str, list[dict[str, object]]]:
        return "修复调用给出的真实说明", invalid

    result = await apply_authoritative_plan(
        assignments=invalid,
        speech="原始说明",
        authoritative_assignments=_authoritative_assignments(),
        rules=_rules(),
        catalog_by_id=CATALOG,
        mode="constraint",
        repair_enabled=True,
        repair_plan=repair,
    )

    assert [item["task_id"] for item in result.assignments] == [
        "tnpd-homolog-search",
        "tnpd-phylogeny",
        "quality-report",
    ]
    assert result.speech == "修复调用给出的真实说明"
    assert result.planning_mode == "rule_merge"
    assert result.violations
    assert result.repair_attempted is True
