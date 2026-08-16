"""Unified, reversible collaboration intent policy for Router conversations.

This module deliberately does not replace handoff, fan-out, consultation, Case, or MAS.
It only normalizes the Router decision and explains whether the selected capability is
available, so callers can reuse the existing execution paths safely.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

CollaborationIntent = Literal["transfer", "fanout", "consult", "case", "dag", "chat"]
OverdriveIntent = Literal["enable", "disable", "none"]

_VALID_INTENTS = frozenset({"transfer", "fanout", "consult", "case", "dag", "chat"})
_VALID_OVERDRIVE_INTENTS = frozenset({"enable", "disable", "none"})


@dataclass(frozen=True)
class CollaborationDecision:
    intent: CollaborationIntent
    confidence: float
    reason: str
    target_agent_id: str | None = None
    fanout_tasks: tuple[dict[str, str], ...] = ()
    overdrive_intent: OverdriveIntent = "none"

    @property
    def needs_clarification(self) -> bool:
        return self.confidence < 0.6


def normalize_decision(
    payload: dict[str, Any] | None,
    *,
    fallback_agent_id: str,
    valid_agent_ids: set[str],
) -> CollaborationDecision:
    """Normalize imperfect model JSON without allowing an unsupported route."""
    payload = payload or {}
    raw_intent = str(payload.get("collaboration_intent") or payload.get("intent") or "chat")
    if raw_intent == "light_collab":
        raw_intent = "fanout"
    elif raw_intent == "delivery_case":
        raw_intent = "case"
    intent: CollaborationIntent = raw_intent if raw_intent in _VALID_INTENTS else "chat"  # type: ignore[assignment]
    try:
        confidence = min(1.0, max(0.0, float(payload.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0
    target = str(payload.get("agent_id") or fallback_agent_id)
    target_agent_id = target if target in valid_agent_ids else fallback_agent_id
    reason = " ".join(str(payload.get("reason") or "").split())[:180]
    if not reason:
        reason = _default_reason(intent)
    tasks = _normalize_tasks(payload.get("fanout_tasks"), valid_agent_ids)
    raw_overdrive_intent = str(payload.get("overdrive_intent") or "none").strip().lower()
    overdrive_intent: OverdriveIntent = (
        raw_overdrive_intent if raw_overdrive_intent in _VALID_OVERDRIVE_INTENTS else "none"
    )  # type: ignore[assignment]
    return CollaborationDecision(
        intent=intent,
        confidence=confidence,
        reason=reason,
        target_agent_id=target_agent_id,
        fanout_tasks=tuple(tasks),
        overdrive_intent=overdrive_intent,
    )


def capability_notice(
    decision: CollaborationDecision,
    *,
    fanout_enabled: bool,
    consultation_enabled: bool,
    case_enabled: bool,
    mas_enabled: bool,
    degradation_template: str | None = None,
    degradation_locale: str = "zh-CN",
) -> dict[str, Any]:
    """Return UI-safe routing/availability data; never execute a capability here."""
    intent = decision.intent
    route_labels = {
        "transfer": "已转交专家",
        "fanout": "并行子任务",
        "consult": "多专家会诊",
        "case": "协作 Case",
        "dag": "分析工作流",
        "chat": "直接回答",
    }
    notice: dict[str, Any] = {
        "intent": intent,
        "label": route_labels[intent],
        "reason": decision.reason,
        "confidence": decision.confidence,
        "available": True,
        "degraded": False,
        "message": "",
    }
    if decision.needs_clarification:
        notice.update(
            available=False,
            degraded=False,
            message=_clarification(intent),
        )
        return notice
    required = {
        "fanout": (fanout_enabled, "SUBAGENT_FANOUT_ENABLED"),
        "consult": (consultation_enabled, "MULTI_EXPERT_CONSULTATION_ENABLED"),
        "case": (case_enabled, "AGENTTEAMS_CHAT_ENTRY_ENABLED 与 AgentTeams Bridge"),
        "dag": (mas_enabled, "MAS_ENABLED"),
    }.get(intent)
    if required and not required[0]:
        notice.update(
            available=False,
            degraded=True,
            message=_degraded_message(
                intent,
                required[1],
                degradation_template,
                degradation_locale,
            ),
        )
    return notice


def execution_routing_record(decision: CollaborationDecision, notice: dict[str, Any]) -> dict[str, Any]:
    """Return the durable route metadata shared by Chat and AgentTeams Case creation."""
    cluster_case = decision.intent == "case" and bool(notice.get("available"))
    return {
        "mode": "cluster_case" if cluster_case else "local",
        "intent": decision.intent,
        "reason": decision.reason,
        "confidence": decision.confidence,
        "status": "proposed" if cluster_case else "selected",
        "degraded": bool(notice.get("degraded")),
    }


def _normalize_tasks(raw_tasks: Any, valid_agent_ids: set[str]) -> list[dict[str, str]]:
    if not isinstance(raw_tasks, list):
        return []
    tasks: list[dict[str, str]] = []
    for item in raw_tasks[:5]:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agent_id") or "").strip()
        task = " ".join(str(item.get("task") or "").split())[:2000]
        if agent_id in valid_agent_ids and task:
            tasks.append({"agent_id": agent_id, "task": task})
    return tasks


def _default_reason(intent: CollaborationIntent) -> str:
    return {
        "transfer": "需要更匹配的专业领域能力",
        "fanout": "请求包含可独立推进的多个子任务",
        "consult": "需要多个专业视角交叉判断",
        "case": "请求涉及正式执行、审批或可追溯交付",
        "dag": "请求涉及分钟到小时级分析工作流",
        "chat": "当前助手可直接处理该问题",
    }[intent]


def _clarification(intent: CollaborationIntent) -> str:
    prompts = {
        "fanout": "你是想让我并行处理这些事项，还是按顺序逐项处理？",
        "consult": "你希望先征询多位专家意见，还是由当前专家直接给出建议？",
        "case": "这是需要审批、正式执行并交付归档的协作任务吗？",
        "dag": "你是想启动正式分析工作流，还是先了解流程与参数？",
        "transfer": "你希望我转交给哪类专家继续处理？",
    }
    return prompts.get(intent, "请补充你希望采用的协作方式。")


def _degraded_message(
    intent: CollaborationIntent,
    setting: str,
    template: str | None = None,
    locale: str = "zh-CN",
) -> str:
    alternatives_zh = {
        "fanout": "当前可由已路由专家按顺序处理；如需真正并行，请联系管理员开启后重试。",
        "consult": "当前可由已路由专家直接给出单一专业建议；如需多方意见，请联系管理员开启后重试。",
        "case": "当前可先完成方案咨询或转交专家；正式协作、审批与交付需要管理员接通 AgentTeams 后重试。",
        "dag": "当前可先咨询流程设计或准备输入；正式工作流执行需要管理员启用 MAS 后重试。",
    }
    alternatives_en = {
        "fanout": "The routed expert can handle the tasks sequentially; ask an administrator to enable parallel execution and retry.",
        "consult": "The routed expert can provide a single-perspective recommendation; ask an administrator to enable multi-expert consultation and retry.",
        "case": "You can continue with planning or an expert handoff; formal collaboration, approval, and delivery require an administrator to connect AgentTeams.",
        "dag": "You can prepare inputs or discuss workflow design first; formal workflow execution requires an administrator to enable MAS.",
    }
    alternatives = alternatives_en if locale == "en" else alternatives_zh
    default_template = "此请求适合“{intent}”，但当前未启用 {setting}。{alternative}"
    selected_template = template or default_template
    try:
        return selected_template.format(
            intent=intent,
            setting=setting,
            alternative=alternatives[intent],
        )
    except (KeyError, ValueError):
        return default_template.format(
            intent=intent,
            setting=setting,
            alternative=alternatives[intent],
        )
