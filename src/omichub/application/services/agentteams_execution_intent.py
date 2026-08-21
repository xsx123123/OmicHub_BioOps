"""AgentTeams 聊天 Case 的执行意图判定（保守策略，宁漏勿错）。

设计背景：历史上曾因关键词误触发，把纯咨询问题（如“介绍一下 Manager 能做什么”）
送进 planning 流水线。因此本模块只在“明确执行动词 + 明确作用对象”同时成立、
且未命中咨询/寒暄否决词时才判 execute；任何歧义都判 chat/clarify，宁可漏触发也
不误启动真实的规划与沙盒执行。

四态语义（优化项 O6，阶段 2）：
- execute：执行动词 + 明确作用对象，且未命中否决词——可直接启动 planning；
- tool_execute：明确要求读取/检索/只读复核，进入受控工具会诊，不启动 Case planning；
- clarify：执行动词成立但无作用对象——由调用方发起选项式追问补全对象；
- chat：命中否决词或无执行动词——纯对话。

``detect_execution_intent`` 保留旧布尔语义（仅 execute 为 True），作为兼容适配层；
新调用方应使用 ``classify_execution_intent`` 获取三态。
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

# 触发 planning 时附在 objective 尾部的通用计划契约：约束规划者输出可被
# execute_general_plan 直接消费的 proposed_submission 结构。
GENERAL_PLAN_CONTRACT = (
    "请输出 proposed_submission，结构为 "
    '{"name": "...", "parameters": {"work_items": ['
    '{"work_item_id": "exec-01", "target": "agent-viz", "objective": "...", '
    '"skill_name": "...", "execution_mode": "workspace_execution", "depends_on": []}]}, '
    '"quality_gate_required": false}；'
    "target 只能是声明了 workspace_execution 的 worker（单细胞用 agent-scrna，"
    "RNA-seq 用 agent-rnaseq，可视化/绘图用 agent-viz，通用脚本用 agent-code）；"
    "工作项 objective 必须写清输入文件引用与期望产物文件名。"
)

# 一票否决：咨询/寒暄模式，命中即 chat（中英文，词表保持窄）。
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
    "读取|查看|打开|列出|预览|检索|搜索|查询|复核|核对|检查|判断|可视化|绘图|画|绘制|渲染|出图|运行|执行|跑|分析|生成|统计|比对|建树|转换|计算"
    "|处理|整理|汇总|检索|搜索|制作|导出"
    r"|\bvisuali[sz]e\b|\bplot\b|\brender\b|\brun\b|\bgenerate\b|\bsearch\b|\bexport\b",
    re.IGNORECASE,
)

# 必要条件 2（文本侧）：出现带常见扩展名的文件名片段。
_FILE_NAME_PATTERN = re.compile(
    r"[\w.\-]+\.(?:nwk|treefile|tree|csv|tsv|xlsx|fastq|fq|bam|png|jpe?g|svg|txt|json|bed|gtf|gff)\b",
    re.IGNORECASE,
)

# 未必带文件扩展名、但已能作为正式领域 Flow 输入的常见数据产物。
# 保持词表窄：仅识别可执行的原始数据或上游标准产物，不把泛化的“数据”视为对象。
_DATA_OBJECT_PATTERN = re.compile(
    r"fastq|cell\s*ranger|cellranger|starsolo|count\s*matrix|"
    r"表达矩阵|计数矩阵|原始(?:测序)?数据|比对结果|bam\b|h5ad\b|loom\b",
    re.IGNORECASE,
)


class ExecutionIntent(StrEnum):
    """聊天 Case 执行意图三态（O6）。"""

    EXECUTE = "execute"
    TOOL_EXECUTE = "tool_execute"
    CLARIFY = "clarify"
    CHAT = "chat"


def has_explicit_object(content: str, context_refs: list[dict[str, Any]]) -> bool:
    """是否存在明确作用对象：上下文引用或可执行数据产物/文件名。"""
    if context_refs:
        return True
    text = (content or "").strip()
    return bool(_FILE_NAME_PATTERN.search(text) or _DATA_OBJECT_PATTERN.search(text))


def classify_execution_intent(
    content: str, context_refs: list[dict[str, Any]]
) -> ExecutionIntent:
    """三态判定用户发言的执行意图。

    判定规则：
    1. 命中一票否决词（咨询/寒暄）→ chat；
    2. 无明确执行动词 → chat；
    3. 执行动词 + 明确作用对象（context_refs 或文件名）→ execute；
    4. 执行动词但无作用对象 → clarify（由调用方追问补全对象后再判）。
    """
    text = (content or "").strip()
    if not text:
        return ExecutionIntent.CHAT
    if any(pattern.search(text) for pattern in _VETO_PATTERNS):
        return ExecutionIntent.CHAT
    if not _EXECUTION_VERB_PATTERN.search(text):
        return ExecutionIntent.CHAT
    if has_explicit_object(text, context_refs):
        if _is_readonly_tool_request(text):
            return ExecutionIntent.TOOL_EXECUTE
        return ExecutionIntent.EXECUTE
    return ExecutionIntent.CLARIFY


_READONLY_TOOL_PATTERN = re.compile(
    "读取|查看|打开|列出|检索|搜索|查询|复核|核对|检查|判断|预览"
    r"|\bread\b|\binspect\b|\bsearch\b|\bcheck\b|\breview\b",
    re.IGNORECASE,
)
_NON_READONLY_EXECUTION_PATTERN = re.compile(
    "生成|运行|执行|分析|绘图|可视化|建树|计算|转换|导出|制作|提交|写入|修改|删除"
    r"|\brun\b|\bexecute\b|\banaly[sz]e\b|\bplot\b|\bexport\b|\bwrite\b",
    re.IGNORECASE,
)


def _is_readonly_tool_request(text: str) -> bool:
    """识别可由受控只读工具完成的单步请求，避免把复杂任务旁路到会诊。"""
    return bool(_READONLY_TOOL_PATTERN.search(text)) and not bool(
        _NON_READONLY_EXECUTION_PATTERN.search(text)
    )


def requested_readonly_capabilities(content: str) -> list[str]:
    """把用户可见的只读意图映射为审计用能力名。"""
    text = (content or "").lower()
    capabilities: list[str] = []
    if any(marker in text for marker in ("读取", "查看", "打开", "预览", "文件", "read", "inspect")):
        capabilities.append("workspace_read")
    if any(marker in text for marker in ("检索", "搜索", "查询", "search", "query")):
        capabilities.append("knowledge_search")
    if any(marker in text for marker in ("复核", "核对", "检查", "判断", "review", "check")):
        capabilities.append("readonly_review")
    return list(dict.fromkeys(capabilities)) or ["readonly_review"]


def detect_execution_intent(content: str, context_refs: list[dict[str, Any]]) -> bool:
    """布尔兼容适配层：execute/tool_execute 均表示明确执行请求。"""
    return classify_execution_intent(content, context_refs) in {
        ExecutionIntent.EXECUTE,
        ExecutionIntent.TOOL_EXECUTE,
    }
