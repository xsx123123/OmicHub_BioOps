"""Resolve room @ mentions against the runtime AgentTeams capability directory."""

from __future__ import annotations

import re
from typing import Any

from cygnusx.application.services.agentteams_capability_registry import (
    AgentTeamsCapabilityRegistry,
)

_MENTION_RE = re.compile(r"(?<![\w@])@([^\s@，。！？：:；;,、()（）\[\]{}]+)")
# Manager 的中文称呼也按别名收录：展示名（如「生物信息部门经理」）与常见
# 简称（如「生物信息经理」）都应路由回 Manager 主回路，而不是落成未知提及。
_MANAGER_ALIASES = {
    "manager",
    "mamager",
    "管家",
    "客户经理",
    "生物信息部门经理",
    "生物信息经理",
}
_BROADCAST_ALIASES = {"所有人", "全体", "all", "everyone"}

# 前缀匹配的最短 token 长度：过短的 @ 片段（如 @a）歧义太大，不做前缀兜底。
_MIN_PREFIX_TOKEN_LEN = 2


def resolve_room_mentions(
    content: str,
    *,
    registry: AgentTeamsCapabilityRegistry,
    role_labels: dict[str, dict[str, str]] | None = None,
    allowed_agent_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Return deterministic mention metadata; unknown mentions remain visible but un-routed."""
    labels = role_labels or registry.role_labels()
    aliases: dict[str, str] = {}
    mentions: list[dict[str, str]] = []
    unknown: list[str] = []
    target_agent_id: str | None = None
    target_agent_ids: list[str] = []
    dispatch_mode = "manager"
    # 展示名含空格时（如「RNA-seq 分析师」），_MENTION_RE 只能捕获空格前的
    # 片段（「RNA-seq」）。为此建一份去空白的归一化别名表，做"唯一前缀命中"
    # 兜底：片段必须是且仅是一个 agent 归一化别名的前缀才路由，歧义则保持
    # 未知提及（manager 回路），不做猜测派发。
    normalized_aliases: dict[str, set[str]] = {}

    def _register_alias(key: str, agent_id: str) -> None:
        normalized = re.sub(r"\s+", "", key).casefold()
        if normalized:
            normalized_aliases.setdefault(normalized, set()).add(agent_id)

    for role, label in labels.items():
        agent_id = str(label.get("agent_id") or "").strip()
        if not agent_id:
            continue
        aliases[role.casefold()] = agent_id
        aliases[agent_id.casefold()] = agent_id
        name = str(label.get("name") or "").strip()
        if name:
            aliases[name.casefold()] = agent_id
        _register_alias(role, agent_id)
        _register_alias(agent_id, agent_id)
        if name:
            _register_alias(name, agent_id)

    def _match_by_prefix(token: str) -> str | None:
        normalized = re.sub(r"\s+", "", token).casefold()
        if len(normalized) < _MIN_PREFIX_TOKEN_LEN:
            return None
        hits = {
            agent_id
            for key, agent_ids in normalized_aliases.items()
            if key.startswith(normalized)
            for agent_id in agent_ids
        }
        return next(iter(hits)) if len(hits) == 1 else None

    for raw in _MENTION_RE.findall(content or ""):
        token = raw.strip()
        normalized = token.casefold()
        if normalized in _MANAGER_ALIASES:
            item = {
                "kind": "manager",
                "agent_id": "bioops-manager",
                "display_name": "生物信息部门经理",
            }
            dispatch_mode = "manager"
        elif normalized in _BROADCAST_ALIASES:
            item = {"kind": "broadcast", "agent_id": "broadcast", "display_name": "所有人"}
            dispatch_mode = "broadcast"
        elif normalized in aliases:
            agent_id = aliases[normalized]
            if allowed_agent_ids is not None and agent_id not in allowed_agent_ids:
                unknown.append(token)
                continue
            label = next((value for value in labels.values() if value.get("agent_id") == agent_id), {})
            item = {
                "kind": "agent",
                "agent_id": agent_id,
                "display_name": str(label.get("name") or agent_id),
            }
            if target_agent_id and target_agent_id != agent_id:
                if agent_id not in target_agent_ids:
                    target_agent_ids.append(agent_id)
                dispatch_mode = "manager"
            else:
                target_agent_id = agent_id
                if agent_id not in target_agent_ids:
                    target_agent_ids.append(agent_id)
                dispatch_mode = "direct"
        else:
            # 空格截断兜底：@RNA-seq（来自「@RNA-seq 分析师」）等片段按归一化
            # 前缀唯一命中一个 agent 时按直呼处理；无法唯一命中保持未知提及。
            prefix_agent_id = _match_by_prefix(token)
            if prefix_agent_id is None:
                unknown.append(token)
                continue
            if allowed_agent_ids is not None and prefix_agent_id not in allowed_agent_ids:
                unknown.append(token)
                continue
            label = next(
                (value for value in labels.values() if value.get("agent_id") == prefix_agent_id), {}
            )
            item = {
                "kind": "agent",
                "agent_id": prefix_agent_id,
                "display_name": str(label.get("name") or prefix_agent_id),
            }
            if target_agent_id and target_agent_id != prefix_agent_id:
                if prefix_agent_id not in target_agent_ids:
                    target_agent_ids.append(prefix_agent_id)
                dispatch_mode = "manager"
            else:
                target_agent_id = prefix_agent_id
                if prefix_agent_id not in target_agent_ids:
                    target_agent_ids.append(prefix_agent_id)
                dispatch_mode = "direct"
        if item not in mentions:
            mentions.append(item)

    if any(item["kind"] == "manager" for item in mentions):
        target_agent_id = None
        dispatch_mode = "manager"
    elif any(item["kind"] == "broadcast" for item in mentions):
        target_agent_id = None
        dispatch_mode = "broadcast"
    elif len({item["agent_id"] for item in mentions if item["kind"] == "agent"}) > 1:
        target_agent_id = None
        dispatch_mode = "multi_direct"

    if dispatch_mode == "direct" and target_agent_id and target_agent_id not in target_agent_ids:
        target_agent_ids.append(target_agent_id)

    return {
        "mentions": mentions,
        "unknown_mentions": unknown,
        "target_agent_id": target_agent_id,
        "target_agent_ids": target_agent_ids,
        "dispatch_mode": dispatch_mode,
    }
