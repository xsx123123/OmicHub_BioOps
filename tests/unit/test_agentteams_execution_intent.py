"""聊天 Case 执行意图判定矩阵：保守策略，宁漏勿错。"""

from __future__ import annotations

from omichub.application.services.agentteams_execution_intent import (
    GENERAL_PLAN_CONTRACT,
    detect_execution_intent,
)


def test_execution_verb_with_context_refs_triggers() -> None:
    refs = [{"kind": "file", "id": "tree-1", "location": "workspace/uploads/example.treefile"}]
    assert detect_execution_intent("对这个 treefile 文件进行可视化并解释", refs) is True


def test_execution_verb_with_filename_in_text_triggers_without_refs() -> None:
    assert detect_execution_intent("把 result.csv 画成热图", []) is True


def test_consultation_veto_wins_over_execution_verb() -> None:
    refs = [{"kind": "file", "id": "tree-1"}]
    assert detect_execution_intent("可视化能做什么？", refs) is False
    assert detect_execution_intent("介绍一下 Manager 能做什么", refs) is False


def test_chitchat_never_triggers() -> None:
    assert detect_execution_intent("今天天气怎么样", []) is False
    assert detect_execution_intent("谢谢", []) is False


def test_execution_verb_without_object_or_refs_does_not_trigger() -> None:
    assert detect_execution_intent("帮我分析一下", []) is False


def test_empty_content_never_triggers() -> None:
    assert detect_execution_intent("", [{"kind": "file", "id": "a.csv"}]) is False
    assert detect_execution_intent("   ", []) is False


def test_english_execution_verb_with_filename_triggers() -> None:
    assert detect_execution_intent("please plot tree.nwk for me", []) is True


def test_general_plan_contract_targets_workspace_execution_workers() -> None:
    assert "work_items" in GENERAL_PLAN_CONTRACT
    assert "agent-viz" in GENERAL_PLAN_CONTRACT
    assert "agent-code" in GENERAL_PLAN_CONTRACT
    assert "workspace_execution" in GENERAL_PLAN_CONTRACT
