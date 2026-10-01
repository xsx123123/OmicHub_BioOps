"""Worker 工具剥离与上下文裁剪规则（纯函数，可单测）。

- strip_worker_tools(features)：剥离 parallel_subagents / transfer_to_agent（防递归）
- build_worker_messages(room_history, fold_summary, limit)：手册 2.4 裁剪规则
- truncate_for_supervisor(text)：Worker 产出回灌 Supervisor 前截断（对齐 TOOL_RESULT_MAX_CHARS）
"""

from __future__ import annotations

from typing import Any

WORKER_FORBIDDEN_FEATURES = ("parallel_subagents", "transfer_to_agent")
DEFAULT_HISTORY_LIMIT = 10
SUPERVISOR_RESULT_MAX_CHARS = 4000


def strip_worker_tools(features: dict[str, Any] | None) -> dict[str, Any]:
    """剥离 Worker 的递归/交接特性，返回新 dict（不修改入参）。"""
    stripped = dict(features or {})
    for key in WORKER_FORBIDDEN_FEATURES:
        stripped.pop(key, None)
    return stripped


def build_worker_messages(
    room_history: list[dict[str, Any]],
    fold_summary: str | None = None,
    limit: int = DEFAULT_HISTORY_LIMIT,
) -> list[dict[str, Any]]:
    """构造 Worker 收到的裁剪后历史（手册 2.4）：

    1. 更早历史折叠为一段 Supervisor 摘要（system 消息，≤500 字）；
    2. 最近 N 条房间消息（剔除 mas_trace / plan_card 系统消息，防污染对话）；
    3. 原始 user 问题在最近窗口内自然保留。
    """
    # 只保留 user / assistant 发言，剔除 mas_trace / plan_card
    speakable = [
        m for m in room_history if m.get("role") in ("user", "assistant")
    ]
    recent = speakable[-limit:]
    older_count = len(speakable) - len(recent)

    messages: list[dict[str, Any]] = []
    if older_count > 0 and fold_summary:
        summary = fold_summary[:500]
        messages.append({"role": "system", "name": "mas_summary", "content": summary})
    messages.extend(recent)
    return messages


def truncate_for_supervisor(text: str, max_chars: int = SUPERVISOR_RESULT_MAX_CHARS) -> str:
    """Worker 产出回灌 Supervisor 前截断（对齐 TOOL_RESULT_MAX_CHARS 语义）。"""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n…[已截断]"


def filter_trace_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """注入 Supervisor 自己的上下文时剔除 mas_trace / plan_card 消息。"""
    return [
        m
        for m in messages
        if m.get("role") not in ("mas_trace", "plan_card")
        and m.get("name") not in ("mas_trace", "plan_card")
    ]
