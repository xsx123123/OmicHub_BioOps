"""AgentTeams 路由决策卡(优化项 O1):把意图路由与 Planner 评分外显为结构化决策。

本模块只读观察现有路由组件(intent_router / flow registry / Lead Planner
Selector 的 ``select_lead_planner`` 与派生注册的 ``get_domain_hints``),不改变
任何路由与规划逻辑;输出供 ``room.route_decision`` 事件载荷与结构化日志使用。
O7:fallback 链穷尽时在决策载荷中显式标记 ``resource_status=waiting``。
"""

from __future__ import annotations

from typing import Any

from cygnusx.application.services.agentteams_capability_registry import (
    AgentTeamsCapabilityRegistry,
    get_agentteams_capability_registry,
)
from cygnusx.application.services.agentteams_intent_router import (
    IntentRoute,
    RouteCandidate,
    RouteExplanation,
    explain_intent_route,
)
from cygnusx.application.services.flow_registry import FlowRegistry, get_flow_registry
from cygnusx.application.services.overdrive_planning_service import (
    OverdrivePlanningService,
    get_domain_hints,
)
from cygnusx.core.exceptions import ValidationError

ROUTE_DECISION_EVENT_TYPE = "room.route_decision"

# Overdrive/通用路径没有 YAML 阶段声明,外显固定的三段式估计。
_OVERDRIVE_STAGES: tuple[tuple[str, str], ...] = (
    ("planning", "规划"),
    ("execution", "执行"),
    ("delivery", "交付"),
)
# 用户可见的路由卡选项文案：编排经理对外统一用中文称呼，不用英文 Manager。
_GENERAL_OPTION_LABEL = "通用分析(由生物信息部门经理自由规划)"
_MAX_OPTIONS = 4


def _planner_scores(text: str) -> dict[str, int]:
    """按派生注册的关键词表统计各规划 Agent 的命中数(只读,与评分公式无关)。"""
    normalized = text.casefold()
    scores: dict[str, int] = {}
    for agent_id, hints in get_domain_hints().items():
        hits = sum(1 for hint in hints if hint and hint.casefold() in normalized)
        if hits:
            scores[agent_id] = hits
    return scores


def _select_planner(text: str, capabilities: AgentTeamsCapabilityRegistry) -> dict[str, Any] | None:
    """复用 Lead Planner Selector 给通用路径选规划者;选不出来时返回 None。"""
    catalog = [
        {
            "agent_id": capability["agent_id"],
            "is_active": True,
            "features": {
                "capability_scope": capability.get("capability_scope") or [],
                "capability_tags": capability.get("capability_tags") or [],
            },
        }
        for capability in capabilities.agent_capabilities().values()
        if capability.get("planner_eligible")
    ]
    if not catalog:
        return None
    try:
        return OverdrivePlanningService.select_lead_planner(text, catalog)
    except ValidationError:
        return None


def _flow_stages(registry: FlowRegistry, flow_id: str) -> list[dict[str, str]]:
    return [
        {"key": stage.key, "title": stage.title}
        for stage in registry.flows[flow_id].definition.stages
    ]


def _flow_participants(registry: FlowRegistry, candidate: RouteCandidate) -> list[str]:
    definition = registry.flows[candidate.flow_id].definition
    participants: list[str] = []
    for agent in [
        candidate.lead_planner,
        definition.flow.actor,
        *(stage.assistant_agent_id for stage in definition.stages),
    ]:
        if agent and agent not in participants:
            participants.append(agent)
    return participants


def _option_for_flow(registry: FlowRegistry, flow_id: str, lead_planner: str) -> dict[str, Any]:
    meta = registry.flows[flow_id].definition.flow
    return {
        "flow_id": flow_id,
        "label": meta.display_name,
        "lead_planner": lead_planner,
        "stages": len(registry.flows[flow_id].definition.stages),
    }


def _build_options(
    explanation_candidates: tuple[RouteCandidate, ...],
    registry: FlowRegistry,
    capabilities: AgentTeamsCapabilityRegistry,
    general_planner: str,
) -> list[dict[str, Any]]:
    """ambiguous 时的候选项:命中候选优先,无命中时列出全部可路由流程;末尾附通用选项。"""
    options: list[dict[str, Any]] = []
    if explanation_candidates:
        for candidate in explanation_candidates[:_MAX_OPTIONS]:
            options.append(_option_for_flow(registry, candidate.flow_id, candidate.lead_planner))
    else:
        for flow_id in sorted(registry.flows):
            if len(options) >= _MAX_OPTIONS:
                break
            planner = capabilities.agent_for_flow(flow_id)
            if planner is None:
                continue
            options.append(_option_for_flow(registry, flow_id, planner))
    options.append(
        {
            "flow_id": None,
            "label": _GENERAL_OPTION_LABEL,
            "lead_planner": general_planner,
            "stages": len(_OVERDRIVE_STAGES),
        }
    )
    return options


def build_route_decision(
    content: str,
    *,
    flow_registry: FlowRegistry | None = None,
    capability_registry: AgentTeamsCapabilityRegistry | None = None,
    resolved_route: IntentRoute | None = None,
    fallback_lead_planner: str = "agent-code",
) -> dict[str, Any] | None:
    """构建路由决策卡载荷;空文本返回 None。

    confidence 判定:唯一明确胜出者为 ``high``;领域规划者已有明确关键词命中但
    没有注册流程时也直接落通用路径，不要求用户在候选 Agent 之间裁决；只有
    完全无领域信号或前两名评分持平时才附带 options。
    """
    text = (content or "").strip()
    if not text:
        return None
    registry = flow_registry or get_flow_registry()
    capabilities = capability_registry or get_agentteams_capability_registry()
    explanation = explain_intent_route(text, flow_registry=registry, capability_registry=capabilities)
    planner = _select_planner(text, capabilities) or {}
    general_planner = str(planner.get("lead_planner_agent_id") or "agent-general")
    planner_scores = _planner_scores(text)
    planner_scores.setdefault(general_planner, 0)

    candidates = explanation.candidates
    tied = len(candidates) > 1 and (candidates[0].hit_count, candidates[0].hit_chars) == (
        candidates[1].hit_count,
        candidates[1].hit_chars,
    )
    domain_signal = any(
        agent_id != general_planner and score > 0
        for agent_id, score in planner_scores.items()
    )
    confidence = "high" if (candidates and not tied) or (not candidates and domain_signal) else "ambiguous"

    winner = explanation.winner
    if resolved_route is not None and resolved_route.flow_key in registry.flows:
        winner = next(
            (candidate for candidate in explanation.candidates if candidate.flow_id == resolved_route.flow_key),
            winner,
        )
    configured_actor = ""
    if winner is not None:
        path = "bridge_workflow"
        flow_id: str | None = winner.flow_id
        flow_label = registry.flows[winner.flow_id].definition.flow.display_name
        lead_planner = winner.lead_planner
        matched_hints = list(winner.matched_hints)
        estimated_stages = _flow_stages(registry, winner.flow_id)
        participants = _flow_participants(registry, winner)
        configured_actor = registry.flows[winner.flow_id].definition.flow.actor
    else:
        path = "overdrive"
        flow_id = None
        flow_label = "通用分析"
        lead_planner = resolved_route.lead_planner if resolved_route else fallback_lead_planner
        matched_hints = list(resolved_route.matched_hints) if resolved_route else [
            str(item) for item in planner.get("matched_capabilities") or []
        ]
        estimated_stages = [{"key": key, "title": title} for key, title in _OVERDRIVE_STAGES]
        participants = [lead_planner]

    registry_version = ",".join(
        f"{flow_id}:{registry.flows[flow_id].digest[:12]}" for flow_id in sorted(registry.flows)
    )
    decision: dict[str, Any] = {
        "path": path,
        "flow_id": flow_id,
        "flow_label": flow_label,
        "matched_hints": matched_hints,
        "lead_planner": lead_planner,
        "planner_scores": planner_scores,
        "estimated_stages": estimated_stages,
        "participants": participants,
        "confidence": confidence,
        "route_input": text[:500],
        "registry_version": resolved_route.registry_version or registry_version
        if resolved_route
        else registry_version,
    }
    if resolved_route is None and explanation.winner is None:
        decision["fallback"] = True
        decision["fallback_reason"] = "未命中已注册领域路由"
        decision["flow_label"] = "通用分析（未识别到领域专家，回退通用代码助手）"
    # O7:命中流程但 actor/fallback 链全不可用(blocked)时同样给出 options,
    # 由 _annotate_resource_status 把阻塞流程标注为 waiting,让用户看见"等待资源"。
    if confidence == "ambiguous" or explanation.blocked:
        decision["options"] = _build_options(
            candidates,
            registry,
            capabilities,
            fallback_lead_planner if resolved_route is None and winner is None else general_planner,
        )
    _annotate_resource_status(
        decision, explanation, participants, configured_actor, registry, capabilities
    )
    return decision


def _annotate_resource_status(
    decision: dict[str, Any],
    explanation: RouteExplanation,
    participants: list[str],
    configured_actor: str,
    registry: FlowRegistry,
    capabilities: AgentTeamsCapabilityRegistry,
) -> None:
    """O7:fallback 链使用情况外显——全部不可用显式提示"等待资源",降级则标记 degraded。"""
    # 配置 actor 经 fallback 链降级时由 lead_planner 兜底,不算 waiting;其余参与者
    # (stage 助手等)链穷尽才算等待资源。
    waiting = [
        item
        for item in participants
        if item != configured_actor and capabilities.resolve_agent(item) is None
    ]
    blocked_labels = [blocked.flow_id for blocked in explanation.blocked]
    if waiting or (decision["flow_id"] is None and blocked_labels):
        names = sorted({*waiting, *blocked_labels})
        decision["resource_status"] = "waiting"
        decision["resource_notice"] = (
            f"等待资源:{', '.join(names)} 暂无可用实例,任务将在资源就绪后派发"
        )
    elif (
        configured_actor
        and decision["lead_planner"] != configured_actor
        and capabilities.resolve_agent(configured_actor) is None
    ):
        decision["resource_status"] = "degraded"
        decision["resource_notice"] = (
            f"{configured_actor} 暂不可用,已由 fallback 链降级到 {decision['lead_planner']}"
        )
    # ambiguous 裁决选项中标注资源阻塞的流程,避免用户点选一个派不下去的选项。
    options = decision.get("options")
    if options and explanation.blocked:
        for blocked in explanation.blocked:
            option = _option_for_flow(registry, blocked.flow_id, "")
            option["resource_status"] = "waiting"
            options.append(option)


def summarize_route_decision(decision: dict[str, Any]) -> str:
    """决策卡的一行摘要(事件 summary 与前端折叠态共用同一措辞)。"""
    label = str(decision.get("flow_label") or "通用分析")
    planner = str(decision.get("lead_planner") or "")
    stages = decision.get("estimated_stages")
    stage_count = len(stages) if isinstance(stages, list) else 0
    if decision.get("confidence") == "ambiguous":
        summary = f"路由待确认:存在多种可能路径(倾向「{label}」 · 规划者 {planner}),请点选裁决"
    else:
        summary = f"已选择「{label}」 · 规划者 {planner} · 预计 {stage_count} 个阶段"
    if decision.get("resource_status") == "waiting":
        notice = str(decision.get("resource_notice") or "等待资源")
        summary = f"{summary} · {notice}"
    return summary


__all__ = ["ROUTE_DECISION_EVENT_TYPE", "build_route_decision", "summarize_route_decision"]
