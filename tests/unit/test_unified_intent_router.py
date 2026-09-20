from __future__ import annotations

import pytest

from cygnusx.application.services.unified_intent_router import (
    capability_notice,
    execution_routing_record,
    normalize_decision,
)

AGENTS = {"agent-general", "agent-rnaseq", "agent-scrna", "agent-code", "agent-viz"}


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"collaboration_intent": "transfer", "agent_id": "agent-scrna", "confidence": 0.9}, "transfer"),
        ({"collaboration_intent": "fanout", "agent_id": "agent-general", "confidence": 0.9}, "fanout"),
        ({"collaboration_intent": "consult", "agent_id": "agent-rnaseq", "confidence": 0.9}, "consult"),
        ({"collaboration_intent": "case", "agent_id": "agent-rnaseq", "confidence": 0.9}, "case"),
        ({"collaboration_intent": "dag", "agent_id": "agent-rnaseq", "confidence": 0.9}, "dag"),
        ({"collaboration_intent": "chat", "agent_id": "agent-general", "confidence": 0.9}, "chat"),
        ({"intent": "delivery_case", "agent_id": "agent-rnaseq", "confidence": 0.9}, "case"),
        ({"intent": "light_collab", "agent_id": "agent-general", "confidence": 0.9}, "fanout"),
        ({"collaboration_intent": "unknown", "agent_id": "agent-general", "confidence": 0.9}, "chat"),
        ({"collaboration_intent": "fanout", "agent_id": "agent-code", "confidence": 1.2}, "fanout"),
        ({"collaboration_intent": "consult", "agent_id": "agent-viz", "confidence": -1}, "consult"),
        ({"collaboration_intent": "case", "agent_id": "agent-rnaseq", "confidence": "0.8"}, "case"),
        ({"collaboration_intent": "dag", "agent_id": "agent-rnaseq", "confidence": None}, "dag"),
        ({"collaboration_intent": "transfer", "agent_id": "unknown", "confidence": 0.8}, "transfer"),
        ({"collaboration_intent": "fanout", "agent_id": "agent-general", "confidence": 0.8, "fanout_tasks": [{"agent_id": "agent-code", "task": "review code"}, {"agent_id": "agent-viz", "task": "review figure"}]}, "fanout"),
        ({"collaboration_intent": "chat", "agent_id": "agent-general", "confidence": 0.0}, "chat"),
        ({"collaboration_intent": "consult", "agent_id": "agent-scrna", "confidence": 0.59}, "consult"),
        ({"collaboration_intent": "fanout", "agent_id": "agent-general", "confidence": 0.6}, "fanout"),
        ({"collaboration_intent": "case", "agent_id": "agent-rnaseq", "confidence": 0.6}, "case"),
        ({"collaboration_intent": "dag", "agent_id": "agent-rnaseq", "confidence": 0.6}, "dag"),
    ],
)
def test_normalize_decision_covers_collaboration_intents(payload, expected: str) -> None:
    decision = normalize_decision(payload, fallback_agent_id="agent-general", valid_agent_ids=AGENTS)
    assert decision.intent == expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"overdrive_intent": "enable"}, "enable"),
        ({"overdrive_intent": "disable"}, "disable"),
        ({"overdrive_intent": "none"}, "none"),
        ({"overdrive_intent": "unexpected"}, "none"),
    ],
)
def test_normalize_decision_keeps_only_supported_overdrive_intents(payload, expected: str) -> None:
    decision = normalize_decision(payload, fallback_agent_id="agent-general", valid_agent_ids=AGENTS)

    assert decision.overdrive_intent == expected


def test_execution_routing_records_cluster_case_only_when_available() -> None:
    decision = normalize_decision(
        {"collaboration_intent": "case", "confidence": 0.9, "reason": "需要审批交付"},
        fallback_agent_id="agent-general",
        valid_agent_ids=AGENTS,
    )
    available = capability_notice(
        decision,
        fanout_enabled=True,
        consultation_enabled=True,
        case_enabled=True,
        mas_enabled=True,
    )
    unavailable = {**available, "available": False, "degraded": True}

    assert execution_routing_record(decision, available)["mode"] == "cluster_case"
    assert execution_routing_record(decision, unavailable)["mode"] == "local"
    assert decision.target_agent_id in AGENTS


def test_low_confidence_requires_clarification() -> None:
    decision = normalize_decision(
        {"collaboration_intent": "fanout", "agent_id": "agent-general", "confidence": 0.4},
        fallback_agent_id="agent-general",
        valid_agent_ids=AGENTS,
    )
    notice = capability_notice(
        decision,
        fanout_enabled=True,
        consultation_enabled=True,
        case_enabled=True,
        mas_enabled=True,
    )
    assert notice["available"] is False
    assert notice["degraded"] is False
    assert "并行" in notice["message"]


def test_low_confidence_chat_continues_without_collaboration_clarification() -> None:
    decision = normalize_decision(
        {"collaboration_intent": "chat", "agent_id": "agent-general", "confidence": 0.2},
        fallback_agent_id="agent-general",
        valid_agent_ids=AGENTS,
    )

    notice = capability_notice(
        decision,
        fanout_enabled=True,
        consultation_enabled=True,
        case_enabled=True,
        mas_enabled=True,
    )

    assert decision.needs_clarification is False
    assert notice["available"] is True
    assert notice["degraded"] is False
    assert notice["message"] == ""


@pytest.mark.parametrize(
    ("intent", "settings", "expected_setting"),
    [
        ("fanout", dict(fanout_enabled=False, consultation_enabled=True, case_enabled=True, mas_enabled=True), "SUBAGENT_FANOUT_ENABLED"),
        ("consult", dict(fanout_enabled=True, consultation_enabled=False, case_enabled=True, mas_enabled=True), "MULTI_EXPERT_CONSULTATION_ENABLED"),
        ("case", dict(fanout_enabled=True, consultation_enabled=True, case_enabled=False, mas_enabled=True), "AGENTTEAMS_CHAT_ENTRY_ENABLED"),
        ("dag", dict(fanout_enabled=True, consultation_enabled=True, case_enabled=True, mas_enabled=False), "MAS_ENABLED"),
    ],
)
def test_unavailable_capability_is_explicitly_degraded(intent: str, settings: dict[str, bool], expected_setting: str) -> None:
    decision = normalize_decision(
        {"collaboration_intent": intent, "agent_id": "agent-general", "confidence": 0.9},
        fallback_agent_id="agent-general",
        valid_agent_ids=AGENTS,
    )
    notice = capability_notice(decision, **settings)
    assert notice["available"] is False
    assert notice["degraded"] is True
    assert expected_setting in notice["message"]


def test_degradation_message_uses_configured_template() -> None:
    decision = normalize_decision(
        {"collaboration_intent": "fanout", "agent_id": "agent-general", "confidence": 0.9},
        fallback_agent_id="agent-general",
        valid_agent_ids=AGENTS,
    )
    notice = capability_notice(
        decision,
        fanout_enabled=False,
        consultation_enabled=True,
        case_enabled=True,
        mas_enabled=True,
        degradation_template="[{intent}] {setting}: {alternative}",
    )

    assert notice["message"].startswith("[fanout] SUBAGENT_FANOUT_ENABLED:")


def test_english_degradation_template_uses_english_alternative() -> None:
    decision = normalize_decision(
        {"collaboration_intent": "case", "agent_id": "agent-general", "confidence": 0.9},
        fallback_agent_id="agent-general",
        valid_agent_ids=AGENTS,
    )
    notice = capability_notice(
        decision,
        fanout_enabled=True,
        consultation_enabled=True,
        case_enabled=False,
        mas_enabled=True,
        degradation_template="This request needs {setting}. {alternative}",
        degradation_locale="en",
    )

    assert "You can continue with planning" in notice["message"]


@pytest.mark.parametrize(
    ("utterance", "intent"),
    [
        ("请单细胞专家帮我判断细胞注释", "transfer"),
        ("这个问题应该转给代码专家处理", "transfer"),
        ("请同时检查代码、质控和可视化方案", "fanout"),
        ("分别评估差异分析、通路分析和图表", "fanout"),
        ("帮我并行核对这三段脚本", "fanout"),
        ("这个实验设计合理吗，需要多角度看看", "consult"),
        ("这个结果该怎么解读，注释策略是否合理", "consult"),
        ("请多位专家评估这个方案能不能做", "consult"),
        ("这个流程要给客户交付并归档", "case"),
        ("正式跑这个项目，需要审批和质控", "case"),
        ("我要建立一个可追踪的协作交付 Case", "case"),
        ("启动 RNA-seq 上游比对和定量管道", "dag"),
        ("帮我跑完整分析工作流", "dag"),
        ("这个分钟级流程现在可以执行吗", "dag"),
        ("什么是差异表达分析", "chat"),
        ("解释一下 PCA 图", "chat"),
        ("给我一个 STAR 参数建议", "chat"),
        ("这个任务要不要并行还是逐个处理", "fanout"),
        ("设计方案是否需要先找专家会诊", "consult"),
        ("想要正式执行并让团队审批", "case"),
    ],
)
def test_intent_corpus_covers_six_collaboration_routes(utterance: str, intent: str) -> None:
    """20 条上线验收语料的期望 Router JSON 会被统一层稳定消费。"""
    decision = normalize_decision(
        {
            "collaboration_intent": intent,
            "agent_id": "agent-general",
            "confidence": 0.9,
            "reason": utterance,
        },
        fallback_agent_id="agent-general",
        valid_agent_ids=AGENTS,
    )

    assert decision.intent == intent
    assert decision.reason == utterance
