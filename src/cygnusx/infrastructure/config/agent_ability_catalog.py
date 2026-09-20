"""Runtime-reloadable catalog of built-in Agent abilities and handoff criteria."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from cygnusx.core.config import get_settings


class AgentAbilityCatalog:
    """Read ``data/ai/agent_ability.yaml`` with mtime-based hot reload."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or get_settings().agent_ability_yaml)
        self._mtime_ns = -1
        self._agents: dict[str, dict[str, Any]] = {}

    def get(self, agent_id: str) -> dict[str, Any]:
        self._reload_if_needed()
        return dict(self._agents.get(agent_id) or {})

    def all(self) -> dict[str, dict[str, Any]]:
        self._reload_if_needed()
        return {agent_id: dict(value) for agent_id, value in self._agents.items()}

    def render_detail(self, agent_id: str) -> str:
        """渲染单条能力的 detail 层文本（四段契约 + 输入示例）。

        F5 渐进暴露第二层：仅在组队会诊/派单确认时按选中候选加载；
        派单/路由上下文只注入 summary 层，不调用本方法。
        未登记的 agent_id 返回空串，由调用方跳过。
        """
        entry = self.get(agent_id)
        if not entry:
            return ""
        sections = [
            ("capabilities", "能力"),
            ("not_suitable_for", "不适用"),
            ("handoff_when", "转交时机"),
            ("preferred_inputs", "偏好输入"),
            ("input_examples", "输入示例"),
        ]
        lines = [f"### {agent_id}"]
        if entry.get("summary"):
            lines.append(f"触发摘要：{entry['summary']}")
        for key, label in sections:
            values = entry.get(key) or []
            if values:
                lines.append(f"{label}：{'；'.join(str(value) for value in values)}")
        return "\n".join(lines)

    def _reload_if_needed(self) -> None:
        try:
            mtime_ns = self.path.stat().st_mtime_ns
        except OSError:
            self._agents = {}
            self._mtime_ns = -1
            return
        if self._agents and mtime_ns <= self._mtime_ns:
            return
        try:
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            self._agents = {}
            self._mtime_ns = mtime_ns
            return
        entries = raw.get("agents") if isinstance(raw, dict) else None
        if not isinstance(entries, dict):
            self._agents = {}
            self._mtime_ns = mtime_ns
            return
        self._agents = {
            str(agent_id): self._normalize(entry)
            for agent_id, entry in entries.items()
            if isinstance(entry, dict)
        }
        self._mtime_ns = mtime_ns

    @staticmethod
    def _normalize(entry: dict[str, Any]) -> dict[str, Any]:
        # F5 渐进暴露：四段契约与输入示例放在 ``detail`` 子层；顶层同名键为
        # 旧格式回退（detail 优先），保证未迁移条目仍可加载。
        raw_detail = entry.get("detail")
        detail = raw_detail if isinstance(raw_detail, dict) else {}

        def strings(key: str) -> list[str]:
            value = detail.get(key, entry.get(key))
            if not isinstance(value, list):
                return []
            return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))

        return {
            "summary": str(entry.get("summary") or "").strip(),
            "chat_entry": entry.get("chat_entry") is not False,
            "capabilities": strings("capabilities"),
            "not_suitable_for": strings("not_suitable_for"),
            "handoff_when": strings("handoff_when"),
            "preferred_inputs": strings("preferred_inputs"),
            "input_examples": strings("input_examples"),
            # L2→L4 升级规则（愿景 Phase D）：命中该 Agent 领域即建议升级协作室。
            "requires_formal_delivery": entry.get("requires_formal_delivery") is True,
        }


agent_ability_catalog = AgentAbilityCatalog()
