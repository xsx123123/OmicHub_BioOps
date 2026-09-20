"""Runtime discovery for AgentTeams flows, roles, and worker profiles."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from time import monotonic
from typing import Any

from loguru import logger

from cygnusx.application.services.flow_registry import FlowRegistry, get_flow_registry
from cygnusx.infrastructure.config.agent_ability_catalog import (
    AgentAbilityCatalog,
    agent_ability_catalog,
)
from cygnusx.infrastructure.config.agent_loader import load_agent_configs

_REQUIRED_STATUS_LINES = frozenset(
    {"recruited", "queued", "running", "reviewing", "succeeded", "failed", "awaiting_input"}
)
_ROLE_ALIASES = {
    "data-steward": "agent-data",
    "quality-auditor": "agent-qc",
    "delivery-reporter": "agent-delivery",
}


def persona_snapshot(agent_features: dict[str, Any] | None) -> dict[str, Any]:
    """Return presentation fields only; never copy tools or permission settings."""
    raw = (agent_features or {}).get("persona")
    if not isinstance(raw, dict):
        return {}
    allowed = {
        "archetype",
        "traits",
        "working_style",
        "communication_style",
        "challenge_style",
        "status_lines",
        "version",
    }
    return {key: deepcopy(value) for key, value in raw.items() if key in allowed}


def persona_routing_summary(agent_features: dict[str, Any] | None) -> dict[str, Any]:
    """Return Persona prose needed by routing and handoff directories."""
    raw = (agent_features or {}).get("persona")
    if not isinstance(raw, dict):
        return {}
    allowed = {
        "archetype",
        "traits",
        "working_style",
        "communication_style",
        "challenge_style",
        "version",
    }
    return {key: deepcopy(value) for key, value in raw.items() if key in allowed}


def persona_status_line(persona: dict[str, Any] | None, phase: str) -> str | None:
    """按状态阶段取 persona.status_lines 的第一条文案;未配置时返回 None。"""
    lines = (persona or {}).get("status_lines")
    if not isinstance(lines, dict):
        return None
    candidates = lines.get(phase)
    if isinstance(candidates, str) and candidates.strip():
        return candidates.strip()
    if isinstance(candidates, list):
        for item in candidates:
            if str(item).strip():
                return str(item).strip()
    return None


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
        domain_registry: Any | None = None,
    ) -> None:
        self._flow_registry = flow_registry
        self._ability_catalog = ability_catalog or agent_ability_catalog
        self._agent_configs = agent_configs
        self._domain_registry = domain_registry
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

    def role_agent_chains(self) -> dict[str, tuple[str, ...]]:
        """role → 有序候选列表 ``(primary, *fallbacks)``(O7 fallback 链)。

        primary 是声明该 ``internal_case_role`` 的 Agent;fallbacks 来自其
        ``features.agentteams.fallback_agents`` 声明。链保留不可用实例,供
        "全部不可用 → 等待资源" 的判定;取可用实例用 ``resolve_agent``。
        """
        chains: dict[str, tuple[str, ...]] = {}
        for agent_id, config in self._all_agents().items():
            features = config.get("features") or {}
            role = str(features.get("internal_case_role") or "").strip()
            if not role:
                continue
            agentteams = features.get("agentteams") or {}
            fallbacks = [
                str(value).strip()
                for value in agentteams.get("fallback_agents", [])
                if str(value).strip()
            ]
            chains[role] = tuple(dict.fromkeys([agent_id, *fallbacks]))
        return chains

    def resolve_agent_chain(self, identity: str) -> tuple[str, ...]:
        """identity(role 或别名)→ 有序候选列表;未注册时返回空元组。"""
        chains = self.role_agent_chains()
        role = identity if identity in chains else _ROLE_ALIASES.get(identity, identity)
        return chains.get(role, ())

    def role_alias_map(self) -> dict[str, str]:
        canonical = self.role_agent_map()
        return {
            alias: canonical[role]
            for alias, role in _ROLE_ALIASES.items()
            if role in canonical
        }

    def resolve_agent(self, identity: str) -> str | None:
        """按 fallback 链取第一个可用(active)实例;全链不可用返回 None(等待资源)。"""
        active = self._active_agents()
        for candidate in self.resolve_agent_chain(identity):
            if candidate in active:
                if candidate != self.resolve_agent_chain(identity)[0]:
                    logger.info(
                        "role_fallback: identity={} resolved_to={} (primary 不可用,走 fallback 链)",
                        identity,
                        candidate,
                    )
                return candidate
        return None

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
                "persona": persona_snapshot(features),
                "subagents_spawnable": bool(features.get("subagents_spawnable", False)),
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

    def internal_consultation_agents(self) -> set[str]:
        """可参与平台内部会诊的 agent：可招募专家 + planner_eligible 的内部角色。

        协作室 Manager（如 agentteams-manager）显式 ``recruitable: false``，
        不进招募面板与 ``consultation_agents()``，但仍是房间内合法的会诊对象。
        """
        abilities = self._ability_catalog.all()
        return {
            item["agent_id"]
            for item in self.agent_capabilities().values()
            if (item["recruitable"] or item["planner_eligible"])
            and item["agent_id"] in abilities
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
        chains = self.role_agent_chains()
        mapping: dict[str, str] = {}
        for registered in self._flows().flows.values():
            definition = registered.definition.flow
            actor = definition.actor
            if actor not in active_agents:
                # O7 fallback 链:先按 actor 声明的 fallback_agents 顺序取第一个可用实例,
                # 再退到历史兜底(agent-general/agent-omics)。
                fallback = next(
                    (
                        candidate
                        for candidate in (*chains.get(actor, ()), "agent-general", "agent-omics")
                        if candidate != actor and candidate in active_agents
                    ),
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

    def flow_standard_work_items(self) -> dict[str, dict[str, str]]:
        """O5:各流程显式声明的标准工作项 target,随 snapshot 派生注册到 Bridge。"""
        flows = self._flows()
        mapping: dict[str, dict[str, str]] = {}
        for registered in flows.flows.values():
            targets = flows.standard_work_item_targets(registered.id)
            if not targets:
                continue
            mapping[registered.id] = targets
            mapping[registered.definition.flow.bridge_workflow] = targets
        return mapping

    def role_labels(self) -> dict[str, dict[str, str]]:
        labels: dict[str, dict[str, str]] = {}
        for agent_id, config in self._active_agents().items():
            features = config.get("features") or {}
            role = str(features.get("internal_case_role") or "").strip()
            if not role:
                continue
            archetype = str((features.get("persona") or {}).get("archetype") or "").strip()
            labels[role] = {
                "agent_id": agent_id,
                "name": str(config.get("name") or role),
                "avatar": str(config.get("avatar") or "💬"),
                "color": str(config.get("color") or "#64748b"),
                "role": str(config.get("category") or "worker"),
                "archetype": archetype,
            }
        return labels

    def chat_router_catalog(self) -> list[dict[str, Any]]:
        """chat 侧 LLM 路由的候选 Agent 目录(双注册表统一,Part 3.3)。

        与房间关键词路由共用同一快照数据源:Agent 清单来自 ``data/ai/{name}.yaml``
        (``_active_agents``),能力描述来自 ``data/ai/agent_ability.yaml``,
        路由提示来自 ``data/ai/domains/*.yaml``。``features.router`` 与
        能力目录 ``chat_entry: false`` 的 Agent 不进候选。
        """
        abilities = self._ability_catalog.all()
        domain_registry = self._domain_registry
        if domain_registry is None:
            from cygnusx.application.services.domain_registry import get_domain_registry

            domain_registry = get_domain_registry()
        catalog: list[dict[str, Any]] = []
        for agent_id, config in sorted(self._active_agents().items()):
            features = config.get("features") or {}
            if features.get("router"):
                continue
            ability = abilities.get(agent_id) or {}
            if not ability.get("chat_entry", True):
                continue
            capability_tags = [str(value) for value in features.get("capability_tags") or []]
            catalog.append(
                {
                    "agent_id": agent_id,
                    "name": str(config.get("name") or agent_id),
                    "description": str(
                        ability.get("summary") or config.get("description") or ""
                    ),
                    "category": str(config.get("category") or "general"),
                    "chat_entry": True,
                    "capabilities": list(ability.get("capabilities") or capability_tags),
                    "not_suitable_for": list(ability.get("not_suitable_for") or []),
                    "handoff_when": list(ability.get("handoff_when") or []),
                    "preferred_inputs": list(ability.get("preferred_inputs") or []),
                    "routing_hints": [str(value) for value in features.get("routing_hints") or []],
                    "capability_tags": capability_tags,
                    # These compact role boundaries are part of the router summary
                    # contract.  Full capability details remain in the detail layer.
                    "default_role": str(features.get("default_role") or ""),
                    "capability_scope": [
                        str(value) for value in features.get("capability_scope") or []
                    ],
                    "routing_notes": domain_registry.router_notes_for(
                        agent_id, features.get("domain")
                    ),
                    "persona": persona_routing_summary(features),
                    "avatar": str(config.get("avatar") or "💬"),
                    "color": str(config.get("color") or "#64748b"),
                }
            )
        return catalog

    def room_consultation_catalog(self) -> list[dict[str, Any]]:
        """协作室会诊/分诊候选目录：全部可会诊 Agent，含 ``chat_entry: false`` 的内部员工。

        ``chat_entry`` 只约束 chat 侧对外路由入口（``chat_router_catalog``）；
        协作室内部员工（如数据管理员、独立质量审计）虽不对外路由，但被用户
        @ 点名或由经理分诊时可以在房间内直接回答用户。基集取
        ``consultation_agents()``（天然排除 ``recruitable: false`` 的 Manager），
        条目优先复用 ``chat_router_catalog``，缺失时由能力目录与 Agent 配置
        兜底合成。
        """
        by_agent_id = {
            str(entry.get("agent_id") or ""): entry for entry in self.chat_router_catalog()
        }
        abilities = self._ability_catalog.all()
        active_agents = self._active_agents()
        catalog: list[dict[str, Any]] = []
        for agent_id in sorted(self.consultation_agents()):
            existing = by_agent_id.get(agent_id)
            if existing is not None:
                catalog.append(existing)
                continue
            config = active_agents.get(agent_id) or {}
            features = config.get("features") or {}
            ability = abilities.get(agent_id) or {}
            catalog.append(
                {
                    "agent_id": agent_id,
                    "name": str(config.get("name") or agent_id),
                    "description": str(
                        ability.get("summary") or config.get("description") or ""
                    ),
                    "category": str(config.get("category") or "general"),
                    "chat_entry": False,
                    "capabilities": list(
                        ability.get("capabilities") or features.get("capability_tags") or []
                    ),
                    "not_suitable_for": list(ability.get("not_suitable_for") or []),
                    "handoff_when": list(ability.get("handoff_when") or []),
                    "preferred_inputs": list(ability.get("preferred_inputs") or []),
                    "routing_hints": [
                        str(value) for value in features.get("routing_hints") or []
                    ],
                    "capability_tags": [
                        str(value) for value in features.get("capability_tags") or []
                    ],
                    "avatar": str(config.get("avatar") or "💬"),
                    "color": str(config.get("color") or "#64748b"),
                }
            )
        return catalog

    def capability_detail_context(self, agent_ids: list[str]) -> str:
        """组队会诊/派单确认时按需加载选中候选的 detail 层文本(F5 渐进暴露第二层)。

        派单/路由上下文只注入 summary 层（``chat_router_catalog`` 的
        ``description``），选中候选后才由会诊分支调用本方法补全四段契约
        与输入示例；未登记或无 detail 的 agent_id 自动跳过。
        """
        active_agents = self._active_agents()
        blocks: list[str] = []
        for agent_id in dict.fromkeys(str(item) for item in agent_ids):
            block = self._ability_catalog.render_detail(agent_id)
            persona = persona_routing_summary(
                (active_agents.get(agent_id) or {}).get("features")
            )
            if persona:
                persona_lines = ["Persona："]
                for key, label in (
                    ("archetype", "角色原型"),
                    ("traits", "稳定特质"),
                    ("working_style", "工作方式"),
                    ("communication_style", "表达风格"),
                    ("challenge_style", "质疑方式"),
                ):
                    value = persona.get(key)
                    if isinstance(value, list):
                        value = "、".join(str(item) for item in value)
                    if value:
                        persona_lines.append(f"{label}：{value}")
                persona_text = "\n".join(persona_lines)
                block = f"{block}\n{persona_text}" if block else persona_text
            if block:
                blocks.append(block)
        if not blocks:
            return ""
        return (
            "## 选中候选的完整能力契约（detail 层，按需加载）\n\n" + "\n\n".join(blocks)
        )

    def flow_router_catalog(self) -> list[dict[str, Any]]:
        """chat 侧 LLM 路由 prompt 注入用的流程目录(与房间关键词路由同源)。

        ``stage_count``/``actor`` 供 L2→L4 升级规则（愿景 Phase D）判定
        "Flow 步骤数 ≥3 / requires_formal_delivery"使用。
        """
        return [
            {
                "flow_id": flow_id,
                "display_name": registered.definition.flow.display_name,
                "bridge_workflow": registered.definition.flow.bridge_workflow,
                "trigger_hints": list(registered.definition.flow.trigger_hints),
                "stage_count": len(registered.definition.stages),
                "actor": registered.definition.flow.actor,
            }
            for flow_id, registered in sorted(self._flows().flows.items())
        ]

    def registered_agent_ids(self) -> set[str]:
        """快照内已登记(可路由)的 Agent 集合,供路由目标成员资格校验。"""
        return set(self.role_agent_map().values()) | set(self.flow_agent_map().values())

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
            "flow_standard_work_items": self.flow_standard_work_items(),
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
            "chat_router_catalog": self.chat_router_catalog(),
            "flow_router_catalog": self.flow_router_catalog(),
            "registered_agent_ids": sorted(self.registered_agent_ids()),
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

    def _all_agents(self) -> dict[str, dict[str, Any]]:
        """全部已配置 Agent(含 inactive),供 fallback 链保留不可用实例。"""
        configs = self._agent_configs if self._agent_configs is not None else load_agent_configs()
        return {str(config["agent_id"]): config for config in configs if config.get("agent_id")}

    def _active_agents(self) -> dict[str, dict[str, Any]]:
        now = monotonic()
        if self._active_agents_cache is not None:
            ts, cached = self._active_agents_cache
            if now - ts < self._cache_ttl:
                return cached
        active = {
            agent_id: config
            for agent_id, config in self._all_agents().items()
            if config.get("is_active", True) is not False
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
        fallbacks = agentteams.get("fallback_agents", [])
        if not isinstance(fallbacks, list) or any(not isinstance(item, str) for item in fallbacks):
            raise ValueError(f"{agent_id} 的 features.agentteams.fallback_agents 必须是字符串列表")
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
    "persona_snapshot",
    "persona_status_line",
]
