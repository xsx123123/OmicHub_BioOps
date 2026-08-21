"""聊天 Case 执行意图判定矩阵：保守策略，宁漏勿错。"""

from __future__ import annotations

import pytest

from omichub.application.services.agentteams_execution_intent import (
    GENERAL_PLAN_CONTRACT,
    ExecutionIntent,
    classify_execution_intent,
    detect_execution_intent,
)


def test_execution_verb_with_context_refs_triggers() -> None:
    refs = [{"kind": "file", "id": "tree-1", "location": "workspace/uploads/example.treefile"}]
    assert detect_execution_intent("对这个 treefile 文件进行可视化并解释", refs) is True


def test_execution_verb_with_filename_in_text_triggers_without_refs() -> None:
    assert detect_execution_intent("把 result.csv 画成热图", []) is True


@pytest.mark.parametrize(
    "content",
    [
        "对已有 Cell Ranger 产物进行小鼠单细胞分析",
        "分析 FASTQ 原始数据并找差异基因",
        "处理表达矩阵并输出细胞注释",
    ],
)
def test_execution_verb_with_known_data_product_triggers_without_file_name(content: str) -> None:
    assert classify_execution_intent(content, []) is ExecutionIntent.EXECUTE


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


@pytest.mark.parametrize(
    "content",
    [
        "对里面的基因做文献检索，整理成文档和网页报告",
        "帮我处理这份数据",
        "把结果汇总一下",
        "检索相关文献",
        "搜索近五年的综述",
        "制作一份结题材料",
        "导出最终结果",
    ],
)
def test_general_purpose_execution_verbs_trigger_with_refs(content: str) -> None:
    refs = [{"kind": "file", "id": "genes-1", "location": "workspace/uploads/genes.xlsx"}]
    assert detect_execution_intent(content, refs) is True


def test_general_purpose_execution_verbs_trigger_with_filename() -> None:
    assert detect_execution_intent("整理 genes.xlsx 里的基因并导出清单", []) is True


def test_general_purpose_verbs_still_require_object_and_respect_veto() -> None:
    assert detect_execution_intent("帮我检索一下", []) is False
    refs = [{"kind": "file", "id": "genes-1"}]
    assert detect_execution_intent("文献检索是什么？", refs) is False


def test_general_plan_contract_targets_workspace_execution_workers() -> None:
    assert "work_items" in GENERAL_PLAN_CONTRACT
    assert "agent-viz" in GENERAL_PLAN_CONTRACT
    assert "agent-code" in GENERAL_PLAN_CONTRACT
    assert "agent-scrna" in GENERAL_PLAN_CONTRACT
    assert "workspace_execution" in GENERAL_PLAN_CONTRACT


def test_classify_execute_with_refs() -> None:
    refs = [{"kind": "file", "id": "tree-1", "location": "workspace/uploads/example.treefile"}]
    assert classify_execution_intent("对这个 treefile 文件进行可视化并解释", refs) is (
        ExecutionIntent.EXECUTE
    )


def test_classify_execute_with_filename_in_text() -> None:
    assert classify_execution_intent("把 result.csv 画成热图", []) is ExecutionIntent.EXECUTE


def test_classify_readonly_request_uses_tool_execute() -> None:
    refs = [{"kind": "file", "id": "result-1", "location": "result.csv"}]
    assert classify_execution_intent("读取 result.csv 并判断是否为空", refs) is (
        ExecutionIntent.TOOL_EXECUTE
    )
    assert classify_execution_intent("检索这个文件的相关文献", refs) is (
        ExecutionIntent.TOOL_EXECUTE
    )


def test_classify_clarify_when_verb_without_object() -> None:
    """执行动词成立但无作用对象 → 新增中间态 clarify（旧语义下一刀切为 False）。"""
    assert classify_execution_intent("帮我做差异分析", []) is ExecutionIntent.CLARIFY
    assert classify_execution_intent("帮我分析一下", []) is ExecutionIntent.CLARIFY
    assert classify_execution_intent("帮我检索一下", []) is ExecutionIntent.CLARIFY


def test_classify_chat_on_veto_even_with_verb_and_refs() -> None:
    refs = [{"kind": "file", "id": "tree-1"}]
    assert classify_execution_intent("可视化能做什么？", refs) is ExecutionIntent.CHAT
    assert classify_execution_intent("什么是RNA-seq", []) is ExecutionIntent.CHAT


def test_classify_chat_without_verb_or_empty() -> None:
    assert classify_execution_intent("今天天气怎么样", []) is ExecutionIntent.CHAT
    assert classify_execution_intent("", [{"kind": "file", "id": "a.csv"}]) is (
        ExecutionIntent.CHAT
    )
    assert classify_execution_intent("   ", []) is ExecutionIntent.CHAT


def test_detect_bool_adapter_only_true_for_execute() -> None:
    """布尔适配层：与旧二元语义一致，仅 execute 为 True，clarify/chat 均为 False。"""
    refs = [{"kind": "file", "id": "genes-1"}]
    assert detect_execution_intent("帮我处理这份数据", refs) is True
    assert detect_execution_intent("帮我做差异分析", []) is False  # clarify
    assert detect_execution_intent("什么是RNA-seq", refs) is False  # chat（否决词）
