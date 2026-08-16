"""Load server-owned MAS agent capability declarations."""

from __future__ import annotations

from pathlib import Path

import yaml

from omichub.application.services.flow_registry import get_flow_registry


def load_agent_capabilities(path: str | Path) -> dict[str, set[str]]:
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    agents = raw.get("agents", {}) if isinstance(raw, dict) else {}
    if not isinstance(agents, dict):
        return {}
    capabilities = {
        str(agent_id): {str(capability) for capability in capabilities}
        for agent_id, capabilities in agents.items()
        if isinstance(capabilities, list)
    }
    for agent_id, derived in get_flow_registry().agent_capabilities().items():
        capabilities.setdefault(agent_id, set()).update(derived)
    return capabilities
