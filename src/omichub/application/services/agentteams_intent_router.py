"""AgentTeams 聊天意图 → 分析流程路由。

从协作房间聊天首条消息创建无 ``flow_id`` 的通用 Case 时,按消息内容识别
分析类型(RNA-seq / ATAC-seq / 单细胞等),推导出应接管规划的分析师身份
(``lead_planner``)。识别不了返回 ``None``,调用方保持 ``agent-code`` 兜底。

关键词来源(优先级从高到低,命中后合并去重):
1. 主表:``data/ai/flows/*.yaml`` 的 ``flow.trigger_hints``(与 chat_service
   统一路由复用同一套 YAML 声明,新增流程优先在 YAML 加 hint);
2. 派生注册:``data/ai/domains/*.yaml`` 的 ``routing.flow_aliases`` 把
   domain_markers 派生为指定 flow.id 的补充别名(DomainRegistry
   ``derived_flow_aliases``,O4 关键词单源化);
3. 迁移期兜底:``_LEGACY_EXTRA_HINT_ALIASES`` 按 ``flow.id`` 登记的旧硬编码
   别名,保留一个版本,命中时打 deprecation 日志。

双注册表统一(Part 3.3):trigger_hints 命中结果必须落在
``AgentTeamsCapabilityRegistry`` 快照内已登记 Agent;未登记/无可用目标记入
``blocked`` 并打审计日志,由调用方走统一 fallback(``agent-code`` 兜底)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from omichub.application.services.agentteams_capability_registry import (
    AgentTeamsCapabilityRegistry,
    get_agentteams_capability_registry,
)
from omichub.application.services.flow_registry import FlowRegistry, get_flow_registry

if TYPE_CHECKING:
    from omichub.application.services.domain_registry import DomainRegistry

# DEPRECATED(迁移期 fallback,保留一个版本):flow.id → 补充别名的旧硬编码表。
# 新别名请写到 flow YAML 的 trigger_hints 或 domains/*.yaml 的 routing.flow_aliases。
_LEGACY_EXTRA_HINT_ALIASES: dict[str, tuple[str, ...]] = {
    "rnaseq": ("转录组", "差异表达"),
    "atacseq": ("染色质可及性",),
    # 避免 "单细胞转录组" 与 rnaseq 的 "转录组" 别名打平误判。
    "scrna": ("单细胞转录组", "单细胞测序"),
}

# 兼容旧导入;新代码通过 DomainRegistry.derived_flow_aliases 获取派生别名。
_EXTRA_HINT_ALIASES = _LEGACY_EXTRA_HINT_ALIASES

# 归一化时忽略的分隔字符,使 "rna-seq" / "rna_seq" / "RNA seq" / "rnaseq" 等价。
_IGNORED_CHARS = frozenset("-_ \t\r\n")

_legacy_alias_warned: set[str] = set()
_unknown_alias_target_warned: set[str] = set()


@dataclass(frozen=True)
class IntentRoute:
    """一次意图命中的路由结果。"""

    flow_id: str  # Bridge 工作流 id(flow.bridge_workflow,如 "rna_seq")
    lead_planner: str  # 接管规划的 AgentTeams 身份(如 "agent-rnaseq")
    flow_key: str | None = None
    matched_hints: tuple[str, ...] = ()
    route_input: str = ""
    registry_version: str | None = None


@dataclass(frozen=True)
class RouteCandidate:
    """单个命中流程的评分明细(路由决策卡外显用,不影响选路)。"""

    flow_id: str  # flow.id(registry 键,如 "rnaseq")
    bridge_workflow: str  # flow.bridge_workflow(如 "rna_seq")
    lead_planner: str
    matched_hints: tuple[str, ...]  # 命中的原始 hint 写法(展示用)
    hit_count: int
    hit_chars: int


@dataclass(frozen=True)
class RouteBlocked:
    """关键词命中但无可用 Agent 的流程(O7 fallback 链穷尽时外显"等待资源")。"""

    flow_id: str
    bridge_workflow: str
    matched_hints: tuple[str, ...]


@dataclass(frozen=True)
class RouteExplanation:
    """一次意图路由的完整明细:全部命中候选 + 最终胜出者。"""

    candidates: tuple[RouteCandidate, ...]  # 按评分降序、flow.id 字典序兜底
    winner: RouteCandidate | None
    blocked: tuple[RouteBlocked, ...] = ()  # 命中但 fallback 链全部不可用的流程(O7)


def _normalize(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch not in _IGNORED_CHARS)


def _flow_hint_pairs(
    registry: FlowRegistry,
    flow_id: str,
    domain_registry: DomainRegistry | None = None,
) -> list[tuple[str, str]]:
    """(原始写法, 归一化) 提示词对,按归一化结果去重,保持声明顺序。"""
    meta = registry.flows[flow_id].definition.flow
    derived = domain_registry.derived_flow_aliases().get(meta.id, ()) if domain_registry else ()
    legacy = _LEGACY_EXTRA_HINT_ALIASES.get(meta.id, ())
    if legacy and meta.id not in _legacy_alias_warned:
        _legacy_alias_warned.add(meta.id)
        logger.warning(
            "_EXTRA_HINT_ALIASES 硬编码 fallback 已废弃:flow={} 的补充别名应迁移到 "
            "flow.trigger_hints 或 domains/*.yaml 的 routing.flow_aliases(当前仍由 .py 兜底)",
            meta.id,
        )
    candidates = [
        *meta.trigger_hints,
        *derived,
        *legacy,
        meta.id,
        meta.bridge_workflow,
    ]
    seen: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for candidate in candidates:
        normalized = _normalize(candidate)
        if normalized and normalized not in seen:
            seen.add(normalized)
            pairs.append((candidate, normalized))
    return pairs


def explain_intent_route(
    text: str,
    *,
    flow_registry: FlowRegistry | None = None,
    capability_registry: AgentTeamsCapabilityRegistry | None = None,
    domain_registry: DomainRegistry | None = None,
) -> RouteExplanation:
    """按消息文本给出全部命中候选与胜出者;无命中时 winner 为 None。

    评分规则与 ``infer_intent_route`` 完全一致:命中 hint 数量优先,其次命中
    字符总数(更具体的说法优先),最后按 flow.id 字典序保证确定性。
    命中但无可用 Agent(fallback 链穷尽)的流程记入 ``blocked``,供路由决策卡
    显式提示"等待资源"。
    """
    normalized = _normalize(text)
    if not normalized:
        return RouteExplanation(candidates=(), winner=None)
    registry = flow_registry or get_flow_registry()
    capabilities = capability_registry or get_agentteams_capability_registry()
    if domain_registry is None:
        from omichub.application.services.domain_registry import get_domain_registry

        domain_registry = get_domain_registry()
    # 双注册表统一(Part 3.3):路由目标必须落在注册表快照内已登记 Agent。
    registered_agents = capabilities.registered_agent_ids()
    derived_aliases = domain_registry.derived_flow_aliases()
    for alias_target in sorted(set(derived_aliases) - set(registry.flows)):
        if alias_target not in _unknown_alias_target_warned:
            _unknown_alias_target_warned.add(alias_target)
            logger.warning(
                "intent_router: domains/*.yaml routing.flow_aliases 指向未登记 flow={},"
                "已忽略(路由目标必须在注册表内)",
                alias_target,
            )
    candidates: list[RouteCandidate] = []
    blocked: list[RouteBlocked] = []
    winner: RouteCandidate | None = None
    for flow_id in sorted(registry.flows):
        matched = [
            (display, hint)
            for display, hint in _flow_hint_pairs(registry, flow_id, domain_registry)
            if hint in normalized
        ]
        if not matched:
            continue
        planner = capabilities.agent_for_flow(flow_id)
        if planner is not None and planner not in registered_agents:
            logger.warning(
                "intent_route_target_unregistered: flow={} 路由目标 agent={} 未在注册表快照登记,"
                "降级统一 fallback",
                flow_id,
                planner,
            )
            planner = None
        if planner is None:
            logger.warning(
                "intent_route_blocked: flow={} matched_hints={} 无已登记可用 Agent,"
                "降级统一 fallback(调用方 agent-code 兜底)",
                flow_id,
                [display for display, _ in matched],
            )
            blocked.append(
                RouteBlocked(
                    flow_id=flow_id,
                    bridge_workflow=registry.flows[flow_id].definition.flow.bridge_workflow,
                    matched_hints=tuple(display for display, _ in matched),
                )
            )
            continue
        candidate = RouteCandidate(
            flow_id=flow_id,
            bridge_workflow=registry.flows[flow_id].definition.flow.bridge_workflow,
            lead_planner=planner,
            matched_hints=tuple(display for display, _ in matched),
            hit_count=len(matched),
            hit_chars=sum(len(hint) for _, hint in matched),
        )
        candidates.append(candidate)
        # 与历史实现一致:严格大于才替换,平分保持字典序在前者胜出。
        if winner is None or (candidate.hit_count, candidate.hit_chars) > (
            winner.hit_count,
            winner.hit_chars,
        ):
            winner = candidate
    ordered = tuple(
        sorted(candidates, key=lambda item: (-item.hit_count, -item.hit_chars, item.flow_id))
    )
    return RouteExplanation(candidates=ordered, winner=winner, blocked=tuple(blocked))


def infer_intent_route(
    text: str,
    *,
    flow_registry: FlowRegistry | None = None,
    capability_registry: AgentTeamsCapabilityRegistry | None = None,
    domain_registry: DomainRegistry | None = None,
) -> IntentRoute | None:
    """按消息文本推导分析流程路由;无命中或命中流程无 active Agent 时返回 None。"""
    winner = explain_intent_route(
        text,
        flow_registry=flow_registry,
        capability_registry=capability_registry,
        domain_registry=domain_registry,
    ).winner
    if winner is None:
        return None
    registered = (flow_registry or get_flow_registry()).flows.get(winner.flow_id)
    return IntentRoute(
        flow_id=winner.bridge_workflow,
        lead_planner=winner.lead_planner,
        flow_key=winner.flow_id,
        matched_hints=winner.matched_hints,
        route_input=text,
        registry_version=registered.digest if registered else None,
    )


__all__ = [
    "IntentRoute",
    "RouteBlocked",
    "RouteCandidate",
    "RouteExplanation",
    "explain_intent_route",
    "infer_intent_route",
]
