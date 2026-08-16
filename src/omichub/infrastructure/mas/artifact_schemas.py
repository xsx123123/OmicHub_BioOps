"""Load server-owned MAS artifact type declarations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from omichub.application.services.flow_registry import get_flow_registry


def load_artifact_schemas(path: str | Path) -> dict[str, dict[str, Any]]:
    """返回以 artifact type 为 key 的注册表；畸形配置安全降级为空。"""
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    entries = raw.get("artifacts", raw) if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return {}
    registry: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        artifact_type = str(entry.get("type") or "").strip()
        if artifact_type:
            registry[artifact_type] = dict(entry)
    # Flow definitions are the authoritative source when they intentionally
    # overlap legacy hand-maintained schema entries.
    registry.update(get_flow_registry().artifact_schemas())
    return registry
