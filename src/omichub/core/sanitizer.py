"""敏感信息脱敏 — 不可逆替换

用途：AI 对话送外部 LLM 前 / 落库前，将配置的敏感词（如品种名）替换为 [REDACTED]，
避免敏感数据外泄到第三方模型或持久化到数据库。

策略：
- 敏感词来源 settings.sensitive_keywords（env SENSITIVE_KEYWORDS，逗号分隔）
- 大小写不敏感匹配；用 re.escape 防止正则注入
- 不可逆：直接替换为 [REDACTED]，不维护映射、不还原
- 空关键词列表时直通，零开销
"""

from __future__ import annotations

import re

_REDACTED = "[REDACTED]"


def _build_pattern(keywords: list[str]) -> re.Pattern[str] | None:
    """根据关键词列表构建一个联合正则；空列表返回 None。"""
    # 过滤空白 + 转义，避免空 alternation 或正则元字符注入
    escaped = [re.escape(k) for k in keywords if k and k.strip()]
    if not escaped:
        return None
    return re.compile("|".join(escaped), re.IGNORECASE)


def sanitize_text(text: str, keywords: list[str]) -> str:
    """将 text 中出现的敏感词替换为 [REDACTED]。无关键词或空串时原样返回。"""
    if not text or not keywords:
        return text
    pattern = _build_pattern(keywords)
    if pattern is None:
        return text
    return pattern.sub(_REDACTED, text)


def sanitize_messages(messages: list[dict], keywords: list[str]) -> list[dict]:
    """深拷贝 messages 并对每条 content 脱敏；返回新列表，不修改入参。"""
    if not keywords:
        return messages
    pattern = _build_pattern(keywords)
    if pattern is None:
        return messages
    sanitized: list[dict] = []
    for msg in messages:
        new_msg = dict(msg)
        content = new_msg.get("content")
        if isinstance(content, str):
            new_msg["content"] = pattern.sub(_REDACTED, content)
        sanitized.append(new_msg)
    return sanitized
