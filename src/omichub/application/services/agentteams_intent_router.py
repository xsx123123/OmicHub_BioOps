"""AgentTeams 聊天意图 → 分析流程路由。

从协作房间聊天首条消息创建无 ``flow_id`` 的通用 Case 时,按消息内容识别
分析类型(RNA-seq / ATAC-seq / 单细胞等),推导出应接管规划的分析师身份
(``lead_planner``)。识别不了返回 ``None``,调用方保持 ``agent-code`` 兜底。

关键词来源:
1. 主表:``data/ai/flows/*.yaml`` 的 ``flow.trigger_hints``(与 chat_service
   统一路由复用同一套 YAML 声明,新增流程优先在 YAML 加 hint);
2. 补充:``_EXTRA_HINT_ALIASES`` 按 ``flow.id`` 登记的常见中英文别名,
   仅放尚未写入 YAML 的高频说法。
"""

from __future__ import annotations

from dataclasses import dataclass

from omichub.application.services.agentteams_capability_registry import (
    AgentTeamsCapabilityRegistry,
    get_agentteams_capability_registry,
)
from omichub.application.services.flow_registry import FlowRegistry, get_flow_registry

# flow.id → YAML trigger_hints 之外的补充别名(小写,匹配前会做归一化)。
_EXTRA_HINT_ALIASES: dict[str, tuple[str, ...]] = {
    "rnaseq": ("转录组", "差异表达"),
    "atacseq": ("染色质可及性",),
    # 避免 "单细胞转录组" 与 rnaseq 的 "转录组" 别名打平误判。
    "scrna": ("单细胞转录组", "单细胞测序"),
}

# 归一化时忽略的分隔字符,使 "rna-seq" / "rna_seq" / "RNA seq" / "rnaseq" 等价。
_IGNORED_CHARS = frozenset("-_ \t\r\n")


@dataclass(frozen=True)
class IntentRoute:
    """一次意图命中的路由结果。"""

    flow_id: str  # Bridge 工作流 id(flow.bridge_workflow,如 "rna_seq")
    lead_planner: str  # 接管规划的 AgentTeams 身份(如 "agent-rnaseq")


def _normalize(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch not in _IGNORED_CHARS)


def _flow_hints(registry: FlowRegistry, flow_id: str) -> list[str]:
    meta = registry.flows[flow_id].definition.flow
    candidates = [
        *meta.trigger_hints,
        *_EXTRA_HINT_ALIASES.get(meta.id, ()),
        meta.id,
        meta.bridge_workflow,
    ]
    seen: set[str] = set()
    hints: list[str] = []
    for candidate in candidates:
        normalized = _normalize(candidate)
        if normalized and normalized not in seen:
            seen.add(normalized)
            hints.append(normalized)
    return hints


def infer_intent_route(
    text: str,
    *,
    flow_registry: FlowRegistry | None = None,
    capability_registry: AgentTeamsCapabilityRegistry | None = None,
) -> IntentRoute | None:
    """按消息文本推导分析流程路由;无命中或命中流程无 active Agent 时返回 None。

    评分规则:命中 hint 数量优先,其次命中字符总数(更具体的说法优先),
    最后按 flow.id 字典序保证确定性。
    """
    normalized = _normalize(text)
    if not normalized:
        return None
    registry = flow_registry or get_flow_registry()
    capabilities = capability_registry or get_agentteams_capability_registry()
    best: tuple[int, int, str, str] | None = None  # (命中数, 命中字符数, flow.id, planner)
    for flow_id in sorted(registry.flows):
        matched = [hint for hint in _flow_hints(registry, flow_id) if hint in normalized]
        if not matched:
            continue
        planner = capabilities.agent_for_flow(flow_id)
        if planner is None:
            continue
        score = (len(matched), sum(len(hint) for hint in matched))
        if best is None or score > best[:2]:
            best = (*score, flow_id, planner)
    if best is None:
        return None
    meta = registry.flows[best[2]].definition.flow
    return IntentRoute(flow_id=meta.bridge_workflow, lead_planner=best[3])


__all__ = ["IntentRoute", "infer_intent_route"]
