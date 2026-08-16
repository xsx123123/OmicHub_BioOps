"""AgentTeams 聊天 Case 的执行意图判定（保守策略，宁漏勿错）。

设计背景：历史上曾因关键词误触发，把纯咨询问题（如“介绍一下 Manager 能做什么”）
送进 planning 流水线。因此本模块只在“明确执行动词 + 明确作用对象”同时成立、
且未命中咨询/寒暄否决词时才返回 True；任何歧义都判 False，宁可漏触发也不误启动
真实的规划与沙盒执行。
"""

from __future__ import annotations

import re
from typing import Any

# 触发 planning 时附在 objective 尾部的通用计划契约：约束规划者输出可被
# execute_general_plan 直接消费的 proposed_submission 结构。
GENERAL_PLAN_CONTRACT = (
    "请输出 proposed_submission，结构为 "
    '{"name": "...", "parameters": {"work_items": ['
    '{"work_item_id": "exec-01", "target": "agent-viz", "objective": "...", '
    '"skill_name": "...", "execution_mode": "workspace_execution", "depends_on": []}]}, '
    '"quality_gate_required": false}；'
    "target 只能是声明了 workspace_execution 的 worker（可视化/绘图用 agent-viz，"
    "通用脚本用 agent-code）；"
    "工作项 objective 必须写清输入文件引用与期望产物文件名。"
)

# 一票否决：咨询/寒暄模式，命中即 False（中英文，词表保持窄）。
_VETO_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        "能做什么",
        "你会什么",
        "介绍一下",
        "是什么",
        "怎么用",
        "如何使用",
        "如何理解",
        "为什么",
        "你好",
        "谢谢",
        r"\bwhat can you\b",
        r"\bwho are you\b",
        r"\bhow to use\b",
        r"^\s*(hi|hello|hey)\b",
        r"\bthank(s| you)\b",
    )
)

# 必要条件 1：明确的执行动词（中文子串匹配；英文整词匹配避免误伤）。
_EXECUTION_VERB_PATTERN = re.compile(
    "可视化|绘图|画|绘制|渲染|出图|运行|执行|跑|分析|生成|统计|比对|建树|转换|计算"
    r"|\bvisuali[sz]e\b|\bplot\b|\brender\b|\brun\b|\bgenerate\b",
    re.IGNORECASE,
)

# 必要条件 2（文本侧）：出现带常见扩展名的文件名片段。
_FILE_NAME_PATTERN = re.compile(
    r"[\w.\-]+\.(?:nwk|treefile|tree|csv|tsv|xlsx|fastq|fq|bam|png|jpe?g|svg|txt|json|bed|gtf|gff)\b",
    re.IGNORECASE,
)


def detect_execution_intent(content: str, context_refs: list[dict[str, Any]]) -> bool:
    """判断用户发言是否构成“现在就执行”的计算请求。

    判定规则（全部满足才 True）：
    1. 未命中一票否决词（咨询/寒暄）；
    2. 文本含明确执行动词；
    3. 有明确作用对象——context_refs 非空，或文本含带扩展名的文件名片段。
    """
    text = (content or "").strip()
    if not text:
        return False
    if any(pattern.search(text) for pattern in _VETO_PATTERNS):
        return False
    if not _EXECUTION_VERB_PATTERN.search(text):
        return False
    if context_refs:
        return True
    return bool(_FILE_NAME_PATTERN.search(text))
