"""历史工具输出的轻量压缩，保留首尾行和可追溯文件提示。"""

from __future__ import annotations

import json
from typing import Any


def _compact_text(value: str, threshold: int) -> str:
    if len(value) <= threshold:
        return value
    lines = value.splitlines()
    if len(lines) <= 100:
        head = value[: threshold // 2]
        tail = value[-threshold // 2 :]
        return f"[输出已压缩：原始 {len(value)} 字符，保留首尾片段]\n{head}\n…\n{tail}"
    kept = lines[:50] + [f"…（共 {len(lines)} 行，历史输出已压缩）…"] + lines[-50:]
    return "\n".join(kept)


def compact_tool_history(
    messages: list[dict[str, Any]], threshold: int = 4000
) -> list[dict[str, Any]]:
    """压缩历史 assistant 的 tool_invocations，不触碰用户消息与最后一条消息。"""
    if threshold <= 0:
        return messages
    compacted: list[dict[str, Any]] = []
    last_index = len(messages) - 1
    for index, message in enumerate(messages):
        item = dict(message)
        invocations = item.get("metadata", {}).get("tool_invocations") if isinstance(item.get("metadata"), dict) else None
        if index == last_index or item.get("role") == "user" or not isinstance(invocations, list):
            compacted.append(item)
            continue
        summaries: list[str] = []
        for invocation in invocations:
            if not isinstance(invocation, dict) or invocation.get("tool_name") == "ask_user":
                continue
            result = invocation.get("result")
            raw = json.dumps(result, ensure_ascii=False, default=str) if result is not None else ""
            if len(raw) <= threshold:
                continue
            path = invocation.get("arguments", {}).get("path") if isinstance(invocation.get("arguments"), dict) else None
            suffix = f"；完整内容见工作区文件 {path}" if path else ""
            summaries.append(
                f"[输出已压缩：共 {len(raw.splitlines())} 行，保留首尾各 50 行{suffix}]\n"
                f"{_compact_text(raw, threshold)}"
            )
        if summaries:
            item["content"] = f"{item.get('content') or ''}\n\n" + "\n\n".join(summaries)
        compacted.append(item)
    return compacted
