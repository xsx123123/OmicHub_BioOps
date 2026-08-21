"""AgentTeams 审计事件分级与关联字段规范（统一审计总线，Part 3.4）。

口径（与 Bridge 侧 ``omichub_agentteams_bridge.audit.OPERATIONAL_EVENT_TYPES``
同一份清单，两边各自持有、改动需同步）：

- **operational**（心跳/轮询/typing 等高频运行噪音）：不进持久事件流，
  只做指标计数（Bridge 侧 INCR ``<prefix>:metrics:events:{event_type}``，
  并经 Bridge ``/v1/metrics`` 以 ``operational_events__<event_type>`` 展平暴露）。
- **business**（room.*/case.*/approval.*/work_item.* 等业务事件）：
  进持久事件流（MinIO 事实源，按天分卷 + Redis 热缓存）。

判定规则是"白名单兜底"：凡未显式列入 ``OPERATIONAL_EVENT_TYPES`` 的事件
类型一律按 business 处理——宁可多记一条业务事件，也不误伤取证链路
（风险登记：审计分级误伤业务事件）。

- ``room.agent_stream`` 已移出持久流（手册阶段 0 修复 4）：Bridge MinIO 模式下
  走 Redis/内存瞬态通道 + SSE，历史重放以 ``room.agent_message`` 终态为准；
  非 MinIO 模式维持原行为。此处仍按 business 归类（审计链分类口径不变）。
- ``room.response_timing``：Manager 响应耗时基线，
  ``GET /cases/{case_id}/response-timing`` 聚合读取依赖它，保留在持久流。

关联字段（全部放在事件 payload 内，事件 schema 五字段不变，向后兼容——
老事件没有这些字段不影响查询）：

- ``causation_event_id``：本事件由哪条事件触发（响应 → 用户发言、
  澄清卡 → 原始请求、立项卡 → 用户发言等）；
- ``answer_to_event_id``：本事件是对哪张卡片/哪条事件的答复
  （澄清答复 → 澄清卡、立项确认/取消 → 立项确认卡）；
- ``correlation_id``：跨服务串联预留（与会诊/平台侧事件对齐用）。

敏感字段出口口径（复审清单 B1 闭环）：``room.proposal_confirm`` 事件的
``confirm_token`` 写入后即全出口脱敏——所有事件出口一律置 None，token 只存
房间行 DB 字段供 confirm-proposal 端点一次性校验（见 ``redact_confirm_token``）。
"""

from __future__ import annotations

from typing import Any

EVENT_CLASS_BUSINESS = "business"
EVENT_CLASS_OPERATIONAL = "operational"

CAUSATION_EVENT_ID_FIELD = "causation_event_id"
ANSWER_TO_EVENT_ID_FIELD = "answer_to_event_id"
CORRELATION_ID_FIELD = "correlation_id"

CORRELATION_FIELDS = (
    CAUSATION_EVENT_ID_FIELD,
    ANSWER_TO_EVENT_ID_FIELD,
    CORRELATION_ID_FIELD,
)

# 与 Bridge audit.py 的 OPERATIONAL_EVENT_TYPES 同口径：心跳/轮询/typing
# 只进指标计数，不进持久事件流。
OPERATIONAL_EVENT_TYPES = frozenset({"worker.inbox_polled", "worker.heartbeat", "room.typing"})

# 高频但有在线消费方、显式保留在持久流中的事件类型（见模块 docstring）。
RETAINED_HIGH_FREQUENCY_BUSINESS_TYPES = frozenset({"room.response_timing"})

ROOM_PROPOSAL_CONFIRM_EVENT_TYPE = "room.proposal_confirm"


def event_stream_sort_key(event: dict[str, Any]) -> tuple[str, str]:
    """跨流事件归并的统一排序口径：``(recorded_at, event_id)`` 字符串元组。

    房间视图双流归并（``agentteams_room_service.get_room_events``）与审计链
    （``agentteams_audit_chain_service``）共用本函数，保证同一批事件在两个
    视图里的顺序一致；recorded_at 为 ISO 字符串、event_id 为 uuid 字符串，
    均按字符串序比较（与 audit-chain 既有实现一致）。
    """
    return (str(event.get("recorded_at") or ""), str(event.get("event_id") or ""))


def redact_confirm_token(event: dict[str, Any]) -> dict[str, Any]:
    """room.proposal_confirm 事件的 confirm_token 出口脱敏（复审清单 B1）。

    写入后即全出口脱敏：不分 pending/已消费一律置 None；存活 token 只存房间行
    DB 字段，confirm-proposal 端点凭 owner + pending 状态原子消费（token 退化为
    可选的二次校验 nonce，不再经事件流分发）。返回拷贝，不改原事件。
    """
    if event.get("event_type") != ROOM_PROPOSAL_CONFIRM_EVENT_TYPE:
        return event
    redacted = dict(event)
    payload = dict(event["payload"]) if isinstance(event.get("payload"), dict) else {}

    def _scrub(layer: dict[str, Any]) -> dict[str, Any]:
        if not layer.get("confirm_token"):
            return layer
        return {**layer, "confirm_token": None}

    payload = _scrub(payload)
    if isinstance(payload.get("payload"), dict):
        payload["payload"] = _scrub(payload["payload"])
    redacted["payload"] = payload
    return redacted


def classify_event_type(event_type: str) -> str:
    """返回事件分级：白名单兜底，未显式列入 operational 的一律 business。"""
    return (
        EVENT_CLASS_OPERATIONAL if event_type in OPERATIONAL_EVENT_TYPES else EVENT_CLASS_BUSINESS
    )


def extract_correlation(payload: dict[str, Any]) -> dict[str, str]:
    """从 Bridge 审计事件 payload 中提取关联字段。

    Bridge 证据事件的载荷是双层结构（``payload.payload`` 为业务内层，
    外层是 work_item_id/summary 等信封字段）；关联字段约定写在内层，
    为兼容直写事件同时查外层。缺失字段不出现在返回值中。
    """
    correlation: dict[str, str] = {}
    layers: list[dict[str, Any]] = []
    inner = payload.get("payload")
    if isinstance(inner, dict):
        layers.append(inner)
    layers.append(payload)
    for field in CORRELATION_FIELDS:
        for layer in layers:
            value = layer.get(field)
            if isinstance(value, str) and value:
                correlation[field] = value
                break
    return correlation


__all__ = [
    "ANSWER_TO_EVENT_ID_FIELD",
    "CAUSATION_EVENT_ID_FIELD",
    "CORRELATION_FIELDS",
    "CORRELATION_ID_FIELD",
    "EVENT_CLASS_BUSINESS",
    "EVENT_CLASS_OPERATIONAL",
    "OPERATIONAL_EVENT_TYPES",
    "RETAINED_HIGH_FREQUENCY_BUSINESS_TYPES",
    "ROOM_PROPOSAL_CONFIRM_EVENT_TYPE",
    "classify_event_type",
    "event_stream_sort_key",
    "extract_correlation",
    "redact_confirm_token",
]
