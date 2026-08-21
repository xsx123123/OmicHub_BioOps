"""Resolve room @ mentions against the runtime AgentTeams capability directory."""

from __future__ import annotations

import re
from typing import Any

from omichub.application.services.agentteams_capability_registry import (
    AgentTeamsCapabilityRegistry,
)

_MENTION_RE = re.compile(r"(?<![\w@])@([^\s@，。！？：:；;,、()（）\[\]{}]+)")
_MANAGER_ALIASES = {"manager", "mamager", "管家", "客户经理"}
_BROADCAST_ALIASES = {"所有人", "全体", "all", "everyone"}


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
    for role, label in labels.items():
        agent_id = str(label.get("agent_id") or "").strip()
        if not agent_id:
            continue
        aliases[role.casefold()] = agent_id
        aliases[agent_id.casefold()] = agent_id
        name = str(label.get("name") or "").strip()
        if name:
            aliases[name.casefold()] = agent_id

    mentions: list[dict[str, str]] = []
    unknown: list[str] = []
    target_agent_id: str | None = None
    dispatch_mode = "manager"
    for raw in _MENTION_RE.findall(content or ""):
        token = raw.strip()
        normalized = token.casefold()
        if normalized in _MANAGER_ALIASES:
            item = {"kind": "manager", "agent_id": "bioops-manager", "display_name": "Manager"}
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
                dispatch_mode = "manager"
            else:
                target_agent_id = agent_id
                dispatch_mode = "direct"
        else:
            unknown.append(token)
            continue
        if item not in mentions:
            mentions.append(item)

    if any(item["kind"] == "manager" for item in mentions):
        target_agent_id = None
        dispatch_mode = "manager"
    elif any(item["kind"] == "broadcast" for item in mentions):
        target_agent_id = None
        dispatch_mode = "broadcast"
    elif len({item["agent_id"] for item in mentions if item["kind"] == "agent"}) != 1:
        target_agent_id = None
        if mentions:
            dispatch_mode = "manager"

    return {
        "mentions": mentions,
        "unknown_mentions": unknown,
        "target_agent_id": target_agent_id,
        "dispatch_mode": dispatch_mode,
    }
