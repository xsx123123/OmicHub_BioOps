"""Runtime discovery for AgentTeams flows, roles, and worker profiles."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any

from loguru import logger

from omichub.application.services.flow_registry import FlowRegistry, get_flow_registry
from omichub.infrastructure.config.agent_ability_catalog import (
    AgentAbilityCatalog,
    agent_ability_catalog,
)
from omichub.infrastructure.config.agent_loader import load_agent_configs

_REQUIRED_STATUS_LINES = frozenset(
    {"recruited", "queued", "running", "reviewing", "succeeded", "failed", "awaiting_input"}
)
_ROLE_ALIASES = {
    "data-steward": "agent-data",
    "quality-auditor": "agent-qc",
    "delivery-reporter": "agent-delivery",
}


@dataclass(frozen=True)
class WorkerProfile:
    identity: str
    agent_id: str
    capability: str

    def as_dict(self) -> dict[str, str]:
        return {
            "identity": self.identity,
            "agent_id": self.agent_id,
            "capability": self.capability,
        }


class AgentTeamsCapabilityRegistry:
    """Derive AgentTeams routing exclusively from platform-owned YAML registries."""

    def __init__(
        self,
        flow_registry: FlowRegistry | None = None,
        ability_catalog: AgentAbilityCatalog | None = None,
        agent_configs: list[dict[str, Any]] | None = None,
        cache_ttl_seconds: float = 60.0,
    ) -> None:
        self._flow_registry = flow_registry
        self._ability_catalog = ability_catalog or agent_ability_catalog
        self._agent_configs = agent_configs
        self._cache_ttl = cache_ttl_seconds
        self._snapshot_cache: tuple[float, dict[str, Any]] | None = None
        self._active_agents_cache: tuple[float, dict[str, dict[str, Any]]] | None = None
        self._flows_cache: tuple[float, FlowRegistry] | None = None

    def allowed_flow_ids(self) -> set[str]:
        return self._flows().bridge_flow_ids()

    def role_agent_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for agent_id, config in self._active_agents().items():
            role = str((config.get("features") or {}).get("internal_case_role") or "").strip()
            if not role:
                continue
            mapping[role] = agent_id
        return mapping

    def role_alias_map(self) -> dict[str, str]:
        canonical = self.role_agent_map()
        return {
            alias: canonical[role]
            for alias, role in _ROLE_ALIASES.items()
            if role in canonical
        }

    def resolve_agent(self, identity: str) -> str | None:
        return self.role_agent_map().get(identity) or self.role_alias_map().get(identity)

    def agent_capabilities(self) -> dict[str, dict[str, Any]]:
        capabilities: dict[str, dict[str, Any]] = {}
        for agent_id, config in self._active_agents().items():
            features = config.get("features") or {}
            role = str(features.get("internal_case_role") or "").strip()
            agentteams = features.get("agentteams") or {}
            if not role or not isinstance(agentteams, dict):
                continue
            capabilities[role] = {
                "agent_id": agent_id,
                "category": str(agentteams.get("category") or "expert"),
                "recruitable": bool(agentteams.get("recruitable", False)),
                "planner_eligible": bool(agentteams.get("planner_eligible", False)),
                "execution_modes": [str(value) for value in agentteams.get("execution_modes", [])],
                "max_parallel_work_items": int(agentteams.get("max_parallel_work_items", 0)),
                "case_mode_excluded_tool_packs": [
                    str(value) for value in agentteams.get("case_mode_excluded_tool_packs", [])
                ],
                "handoff_in_case_mode": bool(agentteams.get("handoff_in_case_mode", False)),
                "work_item_timeout_sec": int(agentteams.get("work_item_timeout_sec", 0)),
                "capability_scope": [str(value) for value in features.get("capability_scope", [])],
                "capability_tags": [str(value) for value in features.get("capability_tags", [])],
                "accepts_inputs": [str(value) for value in features.get("accepts_inputs", [])],
                "produces_outputs": [str(value) for value in features.get("produces_outputs", [])],
                "worker_capability": self._capability_for(role, agent_id),
            }
        return capabilities

    def consultation_agents(self) -> set[str]:
        abilities = self._ability_catalog.all()
        return {
            item["agent_id"]
            for item in self.agent_capabilities().values()
            if item["recruitable"] and item["agent_id"] in abilities
        }

    def agent_execution_modes(self, agent_id: str) -> list[str]:
        """按 agent_id 读取 YAML 声明的 execution_modes（未声明返回空列表）。"""
        config = self._active_agents().get(agent_id)
        if not config:
            return []
        agentteams = (config.get("features") or {}).get("agentteams") or {}
        return [str(value) for value in agentteams.get("execution_modes", [])]

    def worker_profile(self, identity: str) -> WorkerProfile | None:
        agent_id = self.resolve_agent(identity)
        if not agent_id:
            return None
        return WorkerProfile(
            identity=identity,
            agent_id=agent_id,
            capability=self._capability_for(identity, agent_id),
        )

    def agent_for_flow(self, flow_id: str) -> str | None:
        return self.flow_agent_map().get(flow_id)

    def flow_agent_map(self) -> dict[str, str]:
        active_agents = self._active_agents()
        mapping: dict[str, str] = {}
        for registered in self._flows().flows.values():
            definition = registered.definition.flow
            actor = definition.actor
            if actor not in active_agents:
                fallback = next(
                    (candidate for candidate in ("agent-general", "agent-omics") if candidate in active_agents),
                    None,
                )
                if fallback is None:
                    continue
                logger.warning(
                    "actor_fallback: flow={} configured_actor={} fallback_actor={}",
                    registered.id,
                    actor,
                    fallback,
                )
                actor = fallback
            if actor not in active_agents:
                continue
            mapping[registered.id] = actor
            mapping[definition.bridge_workflow] = actor
        return mapping

    def flow_quality_gate_map(self) -> dict[str, bool]:
        mapping: dict[str, bool] = {}
        for registered in self._flows().flows.values():
            required = bool(registered.definition.delivery.quality_gate)
            mapping[registered.id] = required
            mapping[registered.definition.flow.bridge_workflow] = required
        return mapping

    def role_labels(self) -> dict[str, dict[str, str]]:
        labels: dict[str, dict[str, str]] = {}
        for agent_id, config in self._active_agents().items():
            role = str((config.get("features") or {}).get("internal_case_role") or "").strip()
            if not role:
                continue
            labels[role] = {
                "agent_id": agent_id,
                "name": str(config.get("name") or role),
                "avatar": str(config.get("avatar") or "💬"),
                "color": str(config.get("color") or "#64748b"),
                "role": str(config.get("category") or "worker"),
            }
        return labels

    def snapshot(self) -> dict[str, Any]:
        now = monotonic()
        if self._snapshot_cache is not None:
            ts, cached = self._snapshot_cache
            if now - ts < self._cache_ttl:
                return cached
        role_map = self.role_agent_map()
        aliases = self.role_alias_map()
        routable_role_map = {**role_map, **aliases}
        result = {
            "allowed_flow_ids": sorted(self.allowed_flow_ids()),
            "flow_agent_map": self.flow_agent_map(),
            "flow_quality_gate_map": self.flow_quality_gate_map(),
            "role_agent_map": routable_role_map,
            "canonical_role_agent_map": role_map,
            "role_aliases": aliases,
            "agent_capabilities": self.agent_capabilities(),
            "consultation_agents": sorted(self.consultation_agents()),
            "worker_profiles": {
                identity: profile.as_dict()
                for identity in sorted(routable_role_map)
                if (profile := self.worker_profile(identity)) is not None
            },
            "role_labels": self.role_labels(),
        }
        self._snapshot_cache = (now, result)
        return result

    def _flows(self) -> FlowRegistry:
        registry = self._flow_registry if self._flow_registry is not None else get_flow_registry()
        now = monotonic()
        if self._flows_cache is not None:
            ts, cached = self._flows_cache
            if now - ts < self._cache_ttl and cached is registry:
                return cached
        registry.reload()
        self._flows_cache = (now, registry)
        return registry

    def _active_agents(self) -> dict[str, dict[str, Any]]:
        now = monotonic()
        if self._active_agents_cache is not None:
            ts, cached = self._active_agents_cache
            if now - ts < self._cache_ttl:
                return cached
        configs = self._agent_configs if self._agent_configs is not None else load_agent_configs()
        active = {
            str(config["agent_id"]): config
            for config in configs
            if config.get("agent_id") and config.get("is_active", True) is not False
        }
        missing_role: list[str] = []
        for agent_id, config in active.items():
            self._validate_agentteams_declaration(agent_id, config)
            role = str((config.get("features") or {}).get("internal_case_role") or "").strip()
            if not role:
                missing_role.append(agent_id)
        if missing_role:
            logger.warning(
                "以下 Active Agent 缺少 internal_case_role，不参与 AgentTeams: {}",
                ", ".join(sorted(missing_role)),
            )
        self._active_agents_cache = (now, active)
        return active

    @staticmethod
    def _validate_agentteams_declaration(agent_id: str, config: dict[str, Any]) -> None:
        features = config.get("features") or {}
        role = str(features.get("internal_case_role") or "").strip()
        agentteams = features.get("agentteams")
        if not role and agentteams is None:
            return
        if not role:
            raise ValueError(f"{agent_id} 缺少 features.internal_case_role")
        if not isinstance(agentteams, dict):
            raise ValueError(f"{agent_id} 缺少 features.agentteams 声明")
        if "execution_modes" not in agentteams or not isinstance(agentteams["execution_modes"], list):
            raise ValueError(f"{agent_id} 必须声明 features.agentteams.execution_modes")
        status_lines = ((features.get("persona") or {}).get("status_lines") or {})
        missing = _REQUIRED_STATUS_LINES - set(status_lines)
        if missing:
            raise ValueError(f"{agent_id} persona.status_lines 缺少: {', '.join(sorted(missing))}")

    @staticmethod
    def _capability_for(identity: str, agent_id: str) -> str:
        fixed = {
            "data-steward": "project-preflight",
            "agent-data": "project-preflight",
            "quality-auditor": "quality-gate",
            "agent-qc": "quality-gate",
            "delivery-reporter": "delivery-pack",
            "agent-delivery": "delivery-pack",
            "agent-code": "planning_advice",
            "agent-viz": "result_interpretation",
        }
        return fixed.get(
            identity, "interpretation" if agent_id.startswith("agent-") else "planning_advice"
        )


_capability_registry: AgentTeamsCapabilityRegistry | None = None


def get_agentteams_capability_registry() -> AgentTeamsCapabilityRegistry:
    global _capability_registry
    if _capability_registry is None:
        _capability_registry = AgentTeamsCapabilityRegistry()
    return _capability_registry


__all__ = [
    "AgentTeamsCapabilityRegistry",
    "WorkerProfile",
    "get_agentteams_capability_registry",
]
