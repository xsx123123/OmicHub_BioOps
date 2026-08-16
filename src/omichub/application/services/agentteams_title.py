"""AgentTeams Case 的稳定展示标题派生。"""

from __future__ import annotations

import re

_TITLE_MAX_CHARS = 20
_WORKSPACE_REF_RE = re.compile(r"@workspace/\S+", re.IGNORECASE)
_LEADING_REQUEST_RE = re.compile(
    r"^(?:请(?:你)?|麻烦(?:你)?|能否|可以)?(?:帮我|给我)?"
    r"(?:创建一个|创建|做一个|做一下|进行|使用(?:这个|该)?文件)?",
    re.IGNORECASE,
)
_TRAILING_PARTICLE_RE = re.compile(r"(?:一下|呀|啊|吧|呢|可以吗|好吗)[。！？!?：:]*$")


def derive_agentteams_case_title(intent: str) -> str:
    """从完整 Case intent 派生列表与页头使用的短主题标题。"""
    value = _WORKSPACE_REF_RE.sub("", str(intent or ""))
    value = re.sub(r"\s+", " ", value).strip(" \t\r\n「」『』\"'：:，,。.!！?？")
    value = _LEADING_REQUEST_RE.sub("", value).strip(" \t\r\n：:，,。.!！?？")
    value = _TRAILING_PARTICLE_RE.sub("", value).strip(" \t\r\n：:，,。.!！?？")
    if not value:
        return "新协作任务"
    if len(value) <= _TITLE_MAX_CHARS:
        return value
    return f"{value[: _TITLE_MAX_CHARS - 1].rstrip()}…"


__all__ = ["derive_agentteams_case_title"]
