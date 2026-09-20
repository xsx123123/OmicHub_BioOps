"""建议追问 Chips（Suggested Follow-ups）阶段 2 的服务端解析。

与前端 ``frontend/src/utils/nextStepSuggestions.ts`` 的 ``parseNextStepSuggestions``
同规则复刻：从 assistant 回复的 Markdown 中定位"可选下一步"章节，提取其下有序
列表项，拆出短标签（label）与可直接发送的完整文案（prompt），并按关键词判定
点击行为（action：需要用户补充文件/路径等信息的条目用 prefill，其余直接 send）。

解析不到任何条目时返回空列表——调用方据此不在 done 事件上挂载 suggestions 字段，
静默降级（前端会回退到自己的正则解析兜底）。
"""

from __future__ import annotations

import re
from typing import Any, Literal, TypedDict

# 单个消息最多挂载的建议条数
MAX_SUGGESTIONS = 4

# label 最大长度（超出截断并加省略号）
_LABEL_MAX_LENGTH = 12

# 章节标题变体（用于子串匹配）
_SECTION_TITLES = (
    "可选下一步",
    "下一步建议",
    "可选的下一步",
    "下一步可选",
    "后续建议",
    "后续可选",
    "接下来可以",
)

# 命中任一关键词即判定为 prefill（需要用户提供文件/路径等补充信息）
_PREFILL_KEYWORDS = ("提供", "上传", "文件", "路径")

# 有序列表项行：`1. xxx`、`2、xxx`、`3) xxx`，允许引用前缀与全角括号
_ORDERED_ITEM_RE = re.compile(r"^\s*(?:>\s*)?\d{1,2}\s*[.、)）]\s*(.+?)\s*$")

# 章节标题行允许的最大长度（去掉 Markdown 装饰后），避免把正文长句误判为标题
_SECTION_TITLE_MAX_LENGTH = 24

_HEADING_PREFIX_RE = re.compile(r"^[#>\s*-]+")
_INLINE_DECOR_RE = re.compile(r"[*_`]")
_TRAILING_COLON_RE = re.compile(r"[:：\s]+$")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_NEXT_HEADING_RE = re.compile(r"^#{1,6}\s")
_HR_RE = re.compile(r"^(-{3,}|\*{3,})$")

# label 分隔符：冒号/破折号前的短名
_LABEL_SEPARATORS = ("：", ":", "—", "–", " - ")


class SuggestedFollowUp(TypedDict):
    """一条建议追问：胶囊短标签 / 完整发送文案 / 点击行为。"""

    label: str
    prompt: str
    action: Literal["send", "prefill"]


def _normalize_heading_line(line: str) -> str:
    """去掉一行的 Markdown 装饰（标题/加粗/引用/横线符号与首尾冒号），用于标题匹配。"""
    text = _HEADING_PREFIX_RE.sub("", line)
    text = _INLINE_DECOR_RE.sub("", text)
    return _TRAILING_COLON_RE.sub("", text).strip()


def _strip_inline_markdown(text: str) -> str:
    """去掉条目文本中的行内 Markdown（加粗、行内代码、链接保留文字）。"""
    text = _LINK_RE.sub(r"\1", text)
    return _INLINE_DECOR_RE.sub("", text).strip()


def _extract_label(text: str) -> str:
    """label 取冒号/破折号前的短名；无分隔符或前缀超长时截断前 12 字。"""
    cut = -1
    for separator in _LABEL_SEPARATORS:
        idx = text.find(separator)
        if idx > 0 and (cut < 0 or idx < cut):
            cut = idx
    base = text[:cut].strip() if cut > 0 else text
    if not base:
        return text[:_LABEL_MAX_LENGTH]
    return f"{base[:_LABEL_MAX_LENGTH]}…" if len(base) > _LABEL_MAX_LENGTH else base


def _extract_items(section_lines: list[str]) -> list[str]:
    items: list[str] = []
    for line in section_lines:
        trimmed = line.strip()
        item_match = _ORDERED_ITEM_RE.match(line)
        if item_match:
            text = _strip_inline_markdown(item_match.group(1))
            if text:
                items.append(text)
            continue
        if not trimmed:
            continue  # 允许条目间空行
        # 命中下一个标题 / 分割线 / 已开始收集后的普通段落：章节列表到此结束
        if _NEXT_HEADING_RE.match(trimmed) or _HR_RE.match(trimmed):
            break
        if items:
            break
    return items


def parse_next_step_suggestions(markdown: str | None) -> list[SuggestedFollowUp]:
    """解析 assistant 回复 Markdown 末尾的"可选下一步"编号列表。

    任何解析失败（无该章节、无有效条目、异常输入）都返回空列表，不抛错。
    """
    try:
        if not markdown or not isinstance(markdown, str):
            return []
        lines = markdown.split("\n")

        # 定位"可选下一步"章节标题行（取最后一个，正文引用前文标题时以末尾章节为准）
        header_index = -1
        for i, line in enumerate(lines):
            normalized = _normalize_heading_line(line)
            if (
                normalized
                and len(normalized) <= _SECTION_TITLE_MAX_LENGTH
                and any(title in normalized for title in _SECTION_TITLES)
            ):
                header_index = i
        if header_index < 0:
            return []

        items = _extract_items(lines[header_index + 1 :])
        return [
            {
                "label": _extract_label(text),
                "prompt": text,
                "action": (
                    "prefill"
                    if any(keyword in text for keyword in _PREFILL_KEYWORDS)
                    else "send"
                ),
            }
            for text in items[:MAX_SUGGESTIONS]
        ]
    except Exception:  # noqa: BLE001
        return []


def suggestions_metadata(markdown: str | None) -> dict[str, Any]:
    """回复完成时挂载 suggestions 的便捷入口：解析为空则返回空 dict（不留空数组占位）。"""
    suggestions = parse_next_step_suggestions(markdown)
    return {"suggestions": suggestions} if suggestions else {}
