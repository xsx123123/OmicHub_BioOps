"""房间内用户发言的 Manager 响应回路。

用户在团队协作室发出 ``room.user_message`` 后，由 Celery 任务驱动本服务：
以 readonly_consultation 模式调用 Manager agent（默认取配置项
``agentteams_manager_agent_id`` = agentteams-manager，不可用时降级
agent-general 并写 ``room.manager_persona_fallback`` 审计事件），把结论落为
``room.agent_message`` Case 级证据事件——SSE 投影与 Matrix 镜像随之自动生效。

同一 Case 同时只允许一个 pending 响应（Redis 互斥锁）；锁被占用时由任务层
短暂重试，避免连续发言被静默丢弃。LLM 或 Bridge 失败只记 warning，绝不影响
用户发言主流程。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.services.agent_consultation_service import AgentConsultationService
from cygnusx.application.services.agentteams_capability_registry import (
    AgentTeamsCapabilityRegistry,
    get_agentteams_capability_registry,
)
from cygnusx.application.services.agentteams_execution_intent import (
    GENERAL_PLAN_CONTRACT,
    ExecutionIntent,
    classify_execution_intent,
    has_explicit_object,
    requested_readonly_capabilities,
)
from cygnusx.application.services.agentteams_intent_router import IntentRoute, infer_intent_route
from cygnusx.application.services.agentteams_interruption_coordinator import (
    AgentTeamsInterruptionCoordinator,
)
from cygnusx.application.services.agentteams_room_service import (
    PROPOSAL_OPTIONS_FOLLOWUP,
    PROPOSAL_OPTIONS_NEW_CASE,
    ROOM_PROPOSAL_EVENT_TYPE,
    build_room_proposal,
    persist_room_proposal,
)
from cygnusx.application.services.agentteams_route_decision import (
    ROUTE_DECISION_EVENT_TYPE,
    build_route_decision,
    summarize_route_decision,
)
from cygnusx.application.services.agentteams_service import (
    CASE_LEVEL_WORK_ITEM_ID,
    DEFAULT_LEAD_PLANNER,
    AgentTeamsService,
    room_namespace_case_id,
)
from cygnusx.application.services.flow_registry import FlowRegistry, get_flow_registry
from cygnusx.core.config import get_settings
from cygnusx.core.telemetry import get_meter
from cygnusx.infrastructure.cache.redis_client import get_redis
from cygnusx.infrastructure.database.models.chat import AgentTeamsRoomModel
from cygnusx.infrastructure.database.models.user import UserModel
from cygnusx.infrastructure.database.repositories.file_repository import FileRepositoryImpl

ROOM_RESPONSE_LOCK_KEY_PREFIX = "agentteams:room-response:lock:"
ROOM_RESPONSE_LOCK_TTL_SECONDS = 180
# 同一用户发言的响应幂等标记：任务重试/broker 重投递/重复调度时，
# 已应答过的 room.user_message 不再生成第二份 Manager 回复。
ROOM_RESPONSE_DEDUP_KEY_PREFIX = "agentteams:room-response:done:"
ROOM_RESPONSE_DEDUP_TTL_SECONDS = 24 * 60 * 60
# 产出过真实响应的终态（失败/跳过不落幂等标记，允许后续重试）。
_RESPONSE_SUCCESS_STATUSES = frozenset(
    {
        "responded",
        "asked",
        "planning_started",
        "tool_executed",
        "proposal_pending",
        "direct_responded",
        "triage_responded",
    }
)
# Case 终态（含已取消）后房间继续对话时，新的 execute 意图转为"继续/新建"选择卡。
ROOM_FOLLOWUP_CASE_STATUSES = frozenset({"closed", "delivery_ready", "cancelled"})
_CONTEXT_EVENT_LIMIT = 30
_CONTEXT_EVENT_SUMMARY_LINES = 8
# 协作室 Manager 的审计/投影身份（Bridge 安全身份，非 LLM agent，禁止改名）。
MANAGER_ROOM_ROLE = "bioops-manager"
# Manager 人格 agent 的固定降级点：配置的首选 agent 不可用时回退通用助手。
_FALLBACK_MANAGER_AGENT_ID = "agent-general"
# Manager 展示名的最后兜底：唯一权威来源是 manager agent YAML 的 name
# （经协作室配置接口下发），仅在该 YAML 未加载时使用本常量保持展示名不变。
DEFAULT_MANAGER_DISPLAY_NAME = "生物信息部门经理"
_ROOM_STREAM_FLUSH_CHARS = 24
# 房间内 Manager 回复正文的落库上限：结构化长文（分析方案等）容易超过 4k，
# 截断会让用户误以为"没生成完"，放宽到 10k。
_ROOM_REPLY_CONTENT_MAX_CHARS = 10_000
# 思考链随最终消息载荷一并落库的上限：room.agent_stream 是瞬态事件（不持久化），
# 思考链写入 room.agent_message / room.ask_user 载荷后，房间重开仍能渲染思考框。
_ROOM_REPLY_THOUGHT_MAX_CHARS = 8_000
_INTERNAL_CAPABILITY_RISK_MARKER = "未获准调用能力目录类只读工具"
_INTERNAL_CAPABILITY_RISK_SECTION = re.compile(
    r"(?is)(?:^|\n)\s*(?:#{1,6}\s*)?风险\s*[:：]?\s*"
    r"本轮未获准调用能力目录类只读工具，.*?平台能力目录实况为准。?\s*(?=\n|$)"
)

_memory_meter = get_meter("cygnusx.memory")
# L4 记忆装配异常降级计数（operational 级：仅指标计数，进 /metrics）；
# 静默降级是本平台反复打过的模式，必须可观测。
_l4_inject_degraded = _memory_meter.create_counter(
    "memory.l4_inject_degraded",
    description="L4 房间记忆装配异常降级为空注入的次数（operational 级指标）",
)

# 执行对象澄清（O6 阶段 2）：clarify 态下 Manager 直发选项式追问卡片，
# 复用 room.ask_user / AskUserCard 的渲染与【澄清回复】回填链路。
CLARIFY_KIND_EXECUTION_OBJECT = "execution_object"
MAX_EXECUTION_CLARIFY_ROUNDS = 2
# 领域路由澄清（P0-1 硬约束）：execute 意图路由无命中时禁止静默直达兜底
# planner（agent-code）——先落选项式领域澄清卡请用户指明分析类型；追问轮次
# 耗尽仍未命中则降级为 Manager 会诊对话，全程不静默派发兜底 planner。
CLARIFY_KIND_ROUTE_DOMAIN = "route_domain"
MAX_ROUTE_CLARIFY_ROUNDS = 2
ROOM_ASK_REPLY_MARKER = "【澄清回复】"
# 纯咨询分诊（CHAT 意图）：Manager 直答前先用一次轻量 LLM 调用判断是否有
# 更合适的领域专家；命中则落 room.route_transition 事件并转专家直答（复用
# direct 直答链路），置信度不足或任何失败都静默回落 Manager 主回路。
ROOM_ROUTE_TRANSITION_EVENT_TYPE = "room.route_transition"
_ROOM_TRIAGE_MIN_CONFIDENCE = 0.75
_ROOM_TRIAGE_CATALOG_KEYS = (
    "agent_id",
    "name",
    "description",
    "category",
    "routing_hints",
    "routing_notes",
    "not_suitable_for",
)
_ROOM_TRIAGE_SYSTEM_PROMPT = """你是 AgentTeams 协作室的消息分诊器。房间由「{manager_name}」担任编排经理，
默认由经理直接回答用户问题。你的唯一职责是判断：用户这条纯咨询消息是否明显更
适合由某个领域专家回答；是则选出该专家，否则输出经理本人（即不分诊）。

候选专家目录（JSON 数组，唯一有效候选集；description 含适用与不适用场景，
不适用场景命中时不要硬选）：
{catalog}

规则：
1. 直接输出一行 JSON：{{"agent_id": "...", "reason": "...", "confidence": 0.0}}；
   第一个字符必须是 {{，禁止输出思考过程、复述用户消息或任何其他文字。
2. agent_id 必须来自候选目录，或 "{manager_agent_id}"（经理本人）。
3. 寒暄、平台使用问题、需要统筹协调或跨多个领域的问题，一律选经理本人。
4. 原理/概念/方法类问题若明显属于某专家领域（如 RNA-seq 原理 → RNA-seq 方向
   专家、单细胞问题 → 单细胞专家），选该专家。
5. 拿不准时选经理本人；confidence 低于 {min_confidence} 的选择等同拿不准。"""
_CLARIFY_OPT_OUT_MARKERS = ("先不执行", "暂不执行", "先讨论", "继续讨论", "不用了", "取消")
_CLARIFY_EXHAUSTED_NOTE = (
    "系统提示：就该执行请求已进行 "
    f"{MAX_EXECUTION_CLARIFY_ROUNDS} 轮选项式追问，仍未获得可执行的作用对象（输入文件/数据）。"
    "本轮按纯对话处理：请向用户说明暂时无法直接执行的原因，"
    "并建议其上传文件、引用工作区已有数据或给出公共数据库 accession 后重试。"
)


def _sanitize_manager_reply(reply: str) -> str:
    cleaned = _INTERNAL_CAPABILITY_RISK_SECTION.sub("\n", reply).strip()
    if _INTERNAL_CAPABILITY_RISK_MARKER in cleaned:
        cleaned = re.sub(r"\s*本轮未获准调用能力目录类只读工具，.*?平台能力目录实况为准。?", "", cleaned, flags=re.DOTALL)
    return cleaned.strip()


def _visible_manager_risks(risks: Any) -> list[str]:
    return [
        str(risk).strip()
        for risk in (risks or [])
        if str(risk).strip() and _INTERNAL_CAPABILITY_RISK_MARKER not in str(risk)
    ]
_HANDOFF_LANGUAGE_REPLACEMENTS = {
    "已交接": "待确认交接",
    "已派发": "待确认派发",
    "已开始分析": "等待确认后开始分析",
    "已经开始分析": "等待确认后开始分析",
    "已启动分析": "等待确认后启动分析",
}
_INTAKE_SAMPLE_COUNT_RE = re.compile(r"(?:有|共)?\s*(\d+)\s*个?(?:样本|小鼠.*?样本)")
_INTAKE_GROUP_RE = re.compile(r"(\d+)\s*(?:vs|v|对)\s*(\d+)", re.IGNORECASE)
_INTAKE_COMPARISON_RE = re.compile(r"([\w\-]+\s*(?:mutation|mutant|突变))\s*(?:vs|v|对)\s*([\w\-]+\s*(?:WT|wild\s*type|野生型))", re.IGNORECASE)
_WORKSPACE_DATA_SUFFIXES = frozenset({
    ".csv", ".tsv", ".xlsx", ".fastq", ".fq", ".h5ad", ".loom", ".bam", ".txt",
})


def _normalize_route_text(text: str) -> str:
    """与意图路由同口径的归一化（忽略大小写与 ``-_``/空白分隔符）。"""
    return "".join(ch for ch in text.lower() if ch not in "-_ \t\r\n")

_RELEASE_LOCK_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class _RoomResponseStreamProjector:
    """将 Manager 的底层模型增量映射为可由房间 SSE 消费的审计事件。"""

    _TOOL_EVENT_TYPES = frozenset({
        "worker_tool_call",
        "worker_tool_started",
        "worker_tool_result",
        "agent_loop_guard_triggered",
    })

    def __init__(
        self,
        service: AgentTeamsService,
        *,
        case_id: str,
        agent_id: str,
        stream_id: str,
        role: str = "bioops-manager",
        display_name: str = "生物信息部门经理",
    ) -> None:
        self._service = service
        self._case_id = case_id
        self._agent_id = agent_id
        self._stream_id = stream_id
        self._role = role
        self._display_name = display_name
        self._buffers = {"reasoning": "", "content": ""}
        # 完整思考链累积（截断封顶）：flush 只清增量缓冲，最终消息落库时随载荷
        # 一并持久化，房间重开后历史气泡仍可渲染思考框。
        self._reasoning_full = ""

    @property
    def reasoning_text(self) -> str:
        return self._reasoning_full[:_ROOM_REPLY_THOUGHT_MAX_CHARS]

    async def __call__(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        if event_type in self._TOOL_EVENT_TYPES:
            await self._emit_tool_event(event_type, event)
            return
        channel = (
            "reasoning"
            if event_type == "worker_reasoning_delta"
            else "content"
            if event_type == "worker_text_delta"
            else ""
        )
        content = str(event.get("content") or "")
        if not channel or not content:
            return
        if channel == "content" and self._buffers["reasoning"]:
            await self.flush("reasoning")
        self._buffers[channel] += content
        if channel == "reasoning" and len(self._reasoning_full) < _ROOM_REPLY_THOUGHT_MAX_CHARS:
            self._reasoning_full += content
        if len(self._buffers[channel]) >= _ROOM_STREAM_FLUSH_CHARS or "\n" in content:
            await self.flush(channel)

    async def _emit_tool_event(self, event_type: str, event: dict[str, Any]) -> None:
        """把应答过程中的工具/MCP 调用投影为房间证据事件，供前端在气泡内展示。"""
        tool = str(event.get("tool_name") or "")
        payload: dict[str, Any] = {
            "stream_id": self._stream_id,
            "agent_id": self._agent_id,
            "role": self._role,
            "tool": tool,
            "tool_call_id": str(event.get("tool_call_id") or ""),
            "round": int(event.get("round") or 0),
            "execution_path": str(
                event.get("execution_path") or "agentteams_worker_react"
            ),
        }
        if event_type == "worker_tool_call":
            evidence_type = "agent.tool_call"
            summary = f"{self._display_name} 调用工具 {tool}"
            payload["args_summary"] = str(event.get("args_summary") or "")[:500]
        elif event_type == "worker_tool_started":
            evidence_type = "agent.tool_started"
            summary = f"{self._display_name} 开始执行工具 {tool}"
        elif event_type == "worker_tool_result":
            success = bool(event.get("success"))
            evidence_type = "agent.tool_result"
            summary = f"工具 {tool} 执行{'成功' if success else '失败'}"
            payload["result_summary"] = str(event.get("result_summary") or "")[:500]
            payload["success"] = success
            payload["duration_ms"] = int(event.get("duration_ms") or 0)
        else:
            reason = str(event.get("reason") or "unknown")
            evidence_type = "agent.loop_guard_triggered"
            summary = f"{self._display_name} 运行保护已触发：{reason}"
            payload["reason"] = reason
        try:
            await self._service.post_case_evidence(
                self._case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type=evidence_type,
                summary=summary,
                payload=payload,
            )
        except Exception as exc:  # noqa: BLE001 - 工具事件投影失败不能打断模型回复
            logger.bind(case_id=self._case_id).warning(
                "AgentTeams room tool event failed: {}", exc
            )

    async def flush(self, channel: str | None = None) -> None:
        channels = (channel,) if channel else ("reasoning", "content")
        for current in channels:
            delta = self._buffers[current]
            if not delta:
                continue
            self._buffers[current] = ""
            try:
                await self._service.post_case_evidence(
                    self._case_id,
                    work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                    event_type="room.agent_stream",
                    summary=(
                        f"{self._display_name} 正在思考"
                        if current == "reasoning"
                        else f"{self._display_name} 正在回复"
                    ),
                    payload={
                        "stream_id": self._stream_id,
                        "channel": current,
                        "delta": delta,
                        "agent_id": self._agent_id,
                        "role": self._role,
                    },
                )
            except Exception as exc:  # noqa: BLE001 - 增量投影失败不能打断模型回复
                logger.bind(case_id=self._case_id).warning(
                    "AgentTeams room stream event failed: {}", exc
                )


class AgentTeamsRoomResponseService:
    """Generate one Manager reply per room user message, at most one per case at a time."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        agentteams: AgentTeamsService,
        registry: AgentTeamsCapabilityRegistry | None = None,
        redis_getter: Callable[[], Any] = get_redis,
        lock_ttl_seconds: int = ROOM_RESPONSE_LOCK_TTL_SECONDS,
        flow_registry: FlowRegistry | None = None,
    ) -> None:
        self._db = db
        self._agentteams = agentteams
        self._registry = registry or get_agentteams_capability_registry()
        self._redis_getter = redis_getter
        self._lock_ttl = lock_ttl_seconds
        self._flow_registry = flow_registry

    async def respond(
        self,
        case_id: str,
        requester_ref: str,
        content: str,
        *,
        actor_user_id: str | None = None,
        target_agent_id: str | None = None,
        target_agent_ids: list[str] | None = None,
        room: AgentTeamsRoomModel | None = None,
        model_id: UUID | None = None,
    ) -> dict[str, str]:
        lock_key = f"{ROOM_RESPONSE_LOCK_KEY_PREFIX}{case_id}"
        lock_token = uuid4().hex
        redis = self._redis_getter()
        acquired = False
        try:
            acquired = bool(await redis.set(lock_key, lock_token, nx=True, ex=self._lock_ttl))
            if not acquired:
                logger.bind(case_id=case_id).info(
                    "AgentTeams room response skipped: another response is pending"
                )
                return {"status": "skipped_locked"}
            return await self._respond_locked(
                case_id,
                requester_ref,
                content,
                actor_user_id=actor_user_id or requester_ref,
                target_agent_id=target_agent_id,
                target_agent_ids=target_agent_ids,
                room=room,
                model_id=model_id,
            )
        finally:
            if acquired:
                try:
                    await redis.eval(_RELEASE_LOCK_LUA, 1, lock_key, lock_token)
                except Exception as exc:  # noqa: BLE001
                    logger.bind(case_id=case_id).warning(
                        "AgentTeams room response lock release failed: {}", exc
                    )

    async def respond_room(
        self,
        room: AgentTeamsRoomModel,
        requester_ref: str,
        content: str,
        *,
        actor_user_id: str | None = None,
        target_agent_id: str | None = None,
        target_agent_ids: list[str] | None = None,
        model_id: UUID | None = None,
    ) -> dict[str, str]:
        """房间级响应入口（会话-工单解耦 Part 2）。

        未立项房间：事件与对话全部发生在房间命名空间流（case_id=room-<room_id>），
        execute 意图只落"立项确认卡"，确认前不创建 Case。
        已绑定 Case 的房间：完全复用既有 Case 响应链路；仅当 Case 已到终态且
        新的发言是 execute 意图时，先落"基于上一 Case 继续 / 新建工单"选择卡。
        """
        bound_case_id = str(room.case_id or "").strip() or None
        if bound_case_id is None:
            return await self.respond(
                room_namespace_case_id(room.room_id),
                requester_ref,
                content,
                actor_user_id=actor_user_id or requester_ref,
                target_agent_id=target_agent_id,
                target_agent_ids=target_agent_ids,
                room=room,
                model_id=model_id,
            )
        try:
            case = await self._agentteams.get_case(bound_case_id, requester_ref)
        except Exception as exc:  # noqa: BLE001 - 绑定 Case 读取失败不阻断对话
            logger.bind(case_id=bound_case_id).warning(
                "AgentTeams bound case lookup failed: {}", exc
            )
            return {"status": "failed"}
        if str(case.get("status") or "") in ROOM_FOLLOWUP_CASE_STATUSES:
            try:
                events_page = await self._agentteams.get_case_events(
                    bound_case_id, requester_ref, limit=_CONTEXT_EVENT_LIMIT
                )
                event_items = [
                    item for item in events_page.get("events", []) if isinstance(item, dict)
                ]
                refs = self._latest_message_context_refs(event_items, content)
                if classify_execution_intent(content, refs) is ExecutionIntent.EXECUTE:
                    emitted = await self._emit_case_proposal(
                        room=room,
                        content=content,
                        refs=refs,
                        proposal_kind="followup",
                        source_case_id=bound_case_id,
                    )
                    if emitted:
                        return {"status": "proposal_pending"}
            except Exception as exc:  # noqa: BLE001 - 选择卡失败回退到普通对话
                logger.bind(case_id=bound_case_id).warning(
                    "AgentTeams follow-up proposal emission failed: {}", exc
                )
        return await self.respond(
            bound_case_id,
            requester_ref,
            content,
            actor_user_id=actor_user_id or requester_ref,
            target_agent_id=target_agent_id,
            target_agent_ids=target_agent_ids,
            room=room,
            model_id=model_id,
        )

    async def _respond_locked(
        self,
        case_id: str,
        requester_ref: str,
        content: str,
        *,
        actor_user_id: str,
        target_agent_id: str | None = None,
        target_agent_ids: list[str] | None = None,
        room: AgentTeamsRoomModel | None = None,
        model_id: UUID | None = None,
    ) -> dict[str, str]:
        started = time.monotonic()
        stage_ms: dict[str, int] = {}
        response_status = "failed"
        dedup_key: str | None = None
        causation_event_id: str | None = None
        multi_direct_context = False
        try:
            stage_started = time.monotonic()
            case = await self._agentteams.get_case(case_id, requester_ref)
            stage_ms["case"] = round((time.monotonic() - stage_started) * 1000)
            # 终态 Case 也允许继续对话（只读会诊回复，不改 Case 状态）。
            stage_started = time.monotonic()
            events = await self._agentteams.get_case_events(
                case_id, requester_ref, limit=_CONTEXT_EVENT_LIMIT
            )
            event_items = [
                item for item in events.get("events", []) if isinstance(item, dict)
            ]
            if room is not None and room.case_id:
                namespace_events = await self._agentteams.get_case_events(
                    room_namespace_case_id(room.room_id), requester_ref, limit=_CONTEXT_EVENT_LIMIT
                )
                event_items = sorted(
                    [
                        *event_items,
                        *(
                            item
                            for item in namespace_events.get("events", [])
                            if isinstance(item, dict)
                        ),
                    ],
                    key=lambda item: (
                        str(item.get("recorded_at") or ""), str(item.get("event_id") or "")
                    ),
                )
            # 幂等去重：同一条用户发言已产出过响应（任务重试、broker 重投递、
            # post_case_message 与房间同步双通道重复调度）时直接跳过，
            # 避免房间里出现两张相同的 Manager 回复/澄清卡片。
            dedup_event_id = self._current_message_event_id(event_items, content)
            causation_event_id = dedup_event_id
            dedup_key = (
                f"{ROOM_RESPONSE_DEDUP_KEY_PREFIX}{case_id}:{dedup_event_id}"
                if dedup_event_id
                else None
            )
            if dedup_key:
                try:
                    if await self._redis_getter().get(dedup_key):
                        logger.bind(case_id=case_id).info(
                            "AgentTeams room response skipped: message already answered"
                        )
                        return {"status": "skipped_duplicate"}
                except Exception as exc:  # noqa: BLE001 - 幂等检查故障不得影响响应主流程
                    logger.bind(case_id=case_id).warning(
                        "AgentTeams room response dedup check failed: {}", exc
                    )
                    await self._record_dedup_degraded(
                        case_id,
                        reason=f"dedup_read_failed:{type(exc).__name__}",
                        causation_event_id=causation_event_id,
                    )
                    dedup_key = None
            if target_agent_ids:
                results = []
                for agent_id in target_agent_ids:
                    # 每个领域 Agent 都要看到前一个 Agent 已经落库的回复；
                    # 不能把用户发言开始时的旧快照一直传给后续 Agent。
                    results.append(await self._respond_to_direct_agent(
                        case_id,
                        requester_ref,
                        content,
                        case,
                        event_items,
                        agent_id,
                        actor_user_id=actor_user_id,
                        model_id=model_id,
                        causation_event_id=causation_event_id,
                        room_id=room.room_id if room is not None else None,
                    ))
                    refreshed = await self._agentteams.get_case_events(
                        case_id, requester_ref, limit=_CONTEXT_EVENT_LIMIT
                    )
                    event_items = [
                        item for item in refreshed.get("events", [])
                        if isinstance(item, dict)
                    ]
                if all(str(item.get("status") or "") == "direct_responded" for item in results):
                    # 领域 Agent 先分别发言，随后由 Manager 读取这些新事件并做
                    # 一次可见汇总；不能在 worker 回复后直接 return，否则房间没有经理答复。
                    response_status = "multi_directed_to_manager"
                    multi_direct_context = True
            if target_agent_id:
                manager_agent_id = self._manager_agent_id()
                if manager_agent_id and target_agent_id == manager_agent_id:
                    # 按展示名 @Manager 本人（如 @生物信息部门经理）时回归 Manager
                    # 主回路，而不是把 Manager 当被点名的领域 Worker 处理。
                    target_agent_id = None
                else:
                    direct_result = await self._respond_to_direct_agent(
                        case_id,
                        requester_ref,
                        content,
                        case,
                        event_items,
                        target_agent_id,
                        actor_user_id=actor_user_id,
                        model_id=model_id,
                        causation_event_id=causation_event_id,
                        room_id=room.room_id if room is not None else None,
                    )
                    if str(direct_result.get("status") or "") not in {
                        "direct_failed",
                        "direct_agent_unavailable",
                    }:
                        response_status = str(direct_result.get("status") or "")
                        return direct_result
                    # A3（Part 2.7 失败降级路径）：直答失败/超时/目标不可用时禁止
                    # 静默——先落 Manager 可见降级消息与 room.agent_timeout 审计
                    # 事件，随后不 return、继续走下方 Manager 主回路生成正式回复。
                    await self._emit_direct_agent_fallback(
                        case_id,
                        target_agent_id=target_agent_id,
                        reason=str(
                            direct_result.get("reason") or direct_result.get("status") or ""
                        ),
                        causation_event_id=causation_event_id,
                    )
                    target_agent_id = None
            stage_ms["events"] = round((time.monotonic() - stage_started) * 1000)
            stage_started = time.monotonic()
            preferences = await self._manager_preferences(requester_ref)
            stage_ms["preferences"] = round((time.monotonic() - stage_started) * 1000)
            stage_started = time.monotonic()
            latest_refs = self._latest_message_context_refs(event_items, content)
            direct_consultation_intent = classify_execution_intent(content, latest_refs)
            defer_execution_gate = multi_direct_context and direct_consultation_intent in {
                ExecutionIntent.CHAT,
                ExecutionIntent.CLARIFY,
            }
            execution_outcome = "none" if defer_execution_gate else await self._maybe_start_chat_execution(
                case_id=case_id,
                requester_ref=requester_ref,
                actor_user_id=actor_user_id,
                case=case,
                events=event_items,
                content=content,
                preferences=preferences,
                causation_event_id=causation_event_id,
                room=room,
            )
            stage_ms["execution_gate"] = round((time.monotonic() - stage_started) * 1000)
            if execution_outcome == "proposal_pending":
                # 未立项房间的 execute 态：立项确认卡已落房间级事件流，
                # 等用户在 confirm-proposal 端点确认后才创建 Case。
                response_status = "proposal_pending"
                return {"status": response_status}
            if execution_outcome == "clarified":
                # clarify 态：选项式追问卡片已落 room.ask_user，本轮不再跑
                # LLM 会诊，避免与澄清卡片重复回复；答案将作为下一条
                # room.user_message 回到本回路。
                response_status = "asked"
                return {"status": response_status}
            if execution_outcome == "tool_executed":
                # 受控工具链已经生成了唯一房间回复；不要再跑一次 Manager
                # 普通会诊，否则用户会收到与工具结果无关的重复答复。
                response_status = "responded"
                return {"status": response_status}
            if execution_outcome == "started":
                # 领域流程已接手规划。继续调用 Manager 会在用户刚完成澄清后再生成一轮
                # 泛化追问，造成“已经交接却仍要求确认”的重复交互。
                response_status = "planning_started"
                return {"status": response_status}
            if (
                execution_outcome == "none"
                and not multi_direct_context
                and direct_consultation_intent is ExecutionIntent.CHAT
            ):
                # 纯咨询分诊：Manager 直答前先判断是否有更合适的领域专家；
                # 命中则落 room.route_transition 事件并转专家直答。返回 None
                # 表示不分诊或分诊失败（已按 A3 口径落可见降级），继续 Manager 主回路。
                triage_status = await self._try_consultation_triage(
                    case_id,
                    requester_ref,
                    content,
                    case=case,
                    event_items=event_items,
                    actor_user_id=actor_user_id,
                    model_id=model_id,
                    causation_event_id=causation_event_id,
                    room=room,
                )
                if triage_status is not None:
                    response_status = triage_status
                    return {"status": response_status}
            # 触发成功后 Bridge 侧已推进到 planning_running；用拷贝覆盖快照状态，
            # 避免 Manager 按触发前的 received 快照作答。
            question_case = (
                {**case, "status": "planning_running"}
                if execution_outcome == "started"
                else case
            )
            consultation = multi_direct_context or self._is_consultation_reply(
                case, event_items, content, execution_outcome
            )
            agent_id = await self._manager_agent_with_audit(case_id)
            if agent_id is None:
                logger.bind(case_id=case_id).warning(
                    "AgentTeams room response skipped: no manager agent available"
                )
                response_status = "skipped_no_manager"
                return {"status": response_status}
            memory_context = await self._build_memory_context(
                requester_ref=requester_ref, agent_id=agent_id, current_message=content
            )
            question = self._build_question(
                question_case,
                event_items,
                content,
                preferences,
                system_note=(
                    f"请先阅读最近动态中各领域 Agent 的真实回复，明确标注各自姓名并用一段简洁内容汇总；"
                    f"不要把领域 Agent 的发言写成 {self._manager_display_name()} 自己的经历。"
                    if multi_direct_context
                    else (_CLARIFY_EXHAUSTED_NOTE if execution_outcome == "degraded" else None)
                ),
                manager_display_name=self._manager_display_name(),
                consultation=consultation,
                memory_context=memory_context,
                room_message_history=self._room_message_history(
                    event_items, current_content=content
                ),
            )
            await self._set_typing(case_id, typing=True)
            try:
                stream_id = uuid4().hex
                stream_projector = _RoomResponseStreamProjector(
                    self._agentteams,
                    case_id=case_id,
                    agent_id=agent_id,
                    stream_id=stream_id,
                    display_name=self._manager_display_name(),
                )
                try:
                    stage_started = time.monotonic()
                    envelope = await AgentConsultationService(
                        self._db, agentteams_service=self._agentteams
                    ).run_consultation(
                        case_id=case_id,
                        agent_id=agent_id,
                        question=question,
                        capability="interpretation",
                        evidence_refs=[],
                        requested_tools=["room_messages_read"],
                        requester_ref=requester_ref,
                        actor_user_id=actor_user_id,
                        model_id=model_id,
                        causation_event_id=causation_event_id,
                        on_event=stream_projector,
                        room_id=(
                            room.room_id
                            if room is not None
                            else (case_id[5:] if case_id.startswith("room-") else None)
                        ),
                    )
                    stage_ms["llm"] = round((time.monotonic() - stage_started) * 1000)
                finally:
                    await stream_projector.flush()
                reply = _sanitize_manager_reply(envelope.conclusion)
                if multi_direct_context:
                    reply = self._ensure_multi_direct_coordination_reply(reply, event_items)
                visible_risks = _visible_manager_risks(getattr(envelope, "risks", []))
                if case.get("flow_id") and not self._has_handoff_started(event_items):
                    reply = self._gate_unstarted_handoff_language(reply)
                    if handoff_failure := self._handoff_failure_reason(event_items):
                        reply = (
                            f"当前暂未完成专项交接：{handoff_failure}。"
                            "可补齐凭证后重试，或先改为方案咨询。\n\n"
                            f"{reply}"
                        )
                manager_report = {
                    "conclusion": reply,
                    "recommendations": list(getattr(envelope, "recommendations", []) or []),
                    "evidence_refs": list(getattr(envelope, "evidence_refs", []) or []),
                    "risks": visible_risks,
                    "hard_gate": getattr(envelope, "hard_gate", None),
                    "proposed_submission": getattr(envelope, "proposed_submission", None),
                }
                questions = [
                    {"question": item.question.strip(), "options": item.options}
                    for item in (getattr(envelope, "ask_user", None) or [])
                    if item.question.strip()
                ]
                if consultation and questions:
                    # 纯咨询禁止澄清卡片（A1）：prompt 已要求 ask_user 留空；
                    # 模型仍输出时降级为纯文本回复，不落 room.ask_user 卡片。
                    questions = []
                if not reply and not questions:
                    response_status = "failed"
                    return {"status": response_status}
                if questions:
                    # 澄清问题走可交互卡片：前端渲染 ask_user 弹窗，答案作为下一条
                    # room.user_message 回到本响应回路。
                    stage_started = time.monotonic()
                    await self._agentteams.post_case_evidence(
                        case_id,
                        work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                        event_type="room.ask_user",
                        summary=(reply or questions[0]["question"])[:200],
                        payload={
                            "content": reply[:_ROOM_REPLY_CONTENT_MAX_CHARS],
                            "agent_id": agent_id,
                            "role": "bioops-manager",
                            "stream_id": stream_id,
                            "thought": stream_projector.reasoning_text,
                            "manager_report": manager_report,
                            "causation_event_id": causation_event_id,
                            "questions": questions,
                        },
                    )
                    stage_ms["event_write"] = round((time.monotonic() - stage_started) * 1000)
                    response_status = "asked"
                    return {"status": response_status}
                stage_started = time.monotonic()
                await self._agentteams.post_case_evidence(
                    case_id,
                    work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                    event_type="room.agent_message",
                    summary=reply[:200],
                    payload={
                        "content": reply[:_ROOM_REPLY_CONTENT_MAX_CHARS],
                        "agent_id": agent_id,
                        "role": "bioops-manager",
                        "stream_id": stream_id,
                        "thought": stream_projector.reasoning_text,
                        "manager_report": manager_report,
                        "causation_event_id": causation_event_id,
                        },
                    )
                stage_ms["event_write"] = round((time.monotonic() - stage_started) * 1000)
                response_status = "responded"
                return {"status": response_status}
            finally:
                await self._set_typing(case_id, typing=False)
        except Exception as exc:  # noqa: BLE001 - 响应失败不得影响用户发言主流程
            logger.bind(case_id=case_id).warning("AgentTeams room response failed: {}", exc)
            response_status = "failed"
            return {"status": response_status}
        finally:
            if dedup_key and response_status in _RESPONSE_SUCCESS_STATUSES:
                try:
                    await self._redis_getter().set(
                        dedup_key, "1", ex=ROOM_RESPONSE_DEDUP_TTL_SECONDS
                    )
                except Exception as exc:  # noqa: BLE001 - 幂等标记丢失只允许安全重试
                    logger.bind(case_id=case_id).warning(
                        "AgentTeams room response dedup mark failed: {}", exc
                    )
                    await self._record_dedup_degraded(
                        case_id,
                        reason=f"dedup_mark_failed:{type(exc).__name__}",
                        causation_event_id=causation_event_id,
                    )
            record_timing = getattr(self._agentteams, "record_room_response_timing", None)
            if record_timing is not None:
                try:
                    await record_timing(
                        case_id,
                        requester_ref=requester_ref,
                        response_status=response_status,
                        duration_ms=round((time.monotonic() - started) * 1000),
                        stage_ms=stage_ms,
                    )
                except Exception as exc:  # noqa: BLE001 - telemetry must not alter reply status
                    logger.bind(case_id=case_id).warning(
                        "AgentTeams room response timing persistence failed: {}", exc
                    )
            logger.bind(
                case_id=case_id,
                requester_ref=requester_ref,
                response_status=response_status,
                duration_ms=round((time.monotonic() - started) * 1000),
                stage_ms=stage_ms,
            ).info("AgentTeams room response timing")

    async def _try_consultation_triage(
        self,
        case_id: str,
        requester_ref: str,
        content: str,
        *,
        case: dict[str, Any],
        event_items: list[dict[str, Any]],
        actor_user_id: str,
        model_id: UUID | None,
        causation_event_id: str | None,
        room: AgentTeamsRoomModel | None,
    ) -> str | None:
        """纯咨询分诊：CHAT 意图下判断是否有更合适的领域专家。

        返回最终响应状态（分诊成功或专家已接管）或 ``None``（不分诊/分诊失败，
        调用方继续 Manager 主回路）。直答失败按 A3 口径落可见降级后同样返回
        ``None``，由 Manager 接管正式回复。
        """
        manager_agent_id = await self._manager_agent_with_audit(case_id)
        if manager_agent_id is None:
            return None
        decision = await self._triage_consultation_agent(
            content, manager_agent_id=manager_agent_id, model_id=model_id, user_id=requester_ref
        )
        if decision is None:
            return None
        target_agent_id = decision["agent_id"]
        target_name = self._agent_display_name(target_agent_id)
        try:
            await self._agentteams.post_case_evidence(
                case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type=ROOM_ROUTE_TRANSITION_EVENT_TYPE,
                summary=(
                    f"{self._manager_display_name()} 将问题分诊给「{target_name}」："
                    f"{decision['reason']}"
                )[:200],
                payload={
                    "from_agent_id": manager_agent_id,
                    "from_name": self._manager_display_name(),
                    "target_agent_id": target_agent_id,
                    "target_name": target_name,
                    "reason": decision["reason"],
                    "confidence": decision["confidence"],
                    "trigger": "consultation_triage",
                    "causation_event_id": causation_event_id,
                },
            )
        except Exception as exc:  # noqa: BLE001 - 分诊事件失败不得阻断专家答复
            logger.bind(case_id=case_id, target_agent_id=target_agent_id).warning(
                "AgentTeams consultation triage event failed: {}", exc
            )
        direct_result = await self._respond_to_direct_agent(
            case_id,
            requester_ref,
            content,
            case,
            event_items,
            target_agent_id,
            actor_user_id=actor_user_id,
            causation_event_id=causation_event_id,
            model_id=model_id,
            room_id=room.room_id if room is not None else None,
            origin="manager_triage",
        )
        status = str(direct_result.get("status") or "")
        if status in {"direct_failed", "direct_agent_unavailable"}:
            await self._emit_direct_agent_fallback(
                case_id,
                target_agent_id=target_agent_id,
                reason=str(direct_result.get("reason") or status),
                causation_event_id=causation_event_id,
            )
            return None
        return "triage_responded" if status == "direct_responded" else status

    async def _triage_consultation_agent(
        self,
        content: str,
        *,
        manager_agent_id: str,
        model_id: UUID | None,
        user_id: str,
    ) -> dict[str, Any] | None:
        """一次轻量 LLM 调用为纯咨询消息选择最合适的领域专家。

        候选集 = ``room_consultation_catalog()``（全部可会诊 Agent，含
        ``chat_entry: false`` 的房间内部员工；chat_entry 仅约束 chat 侧对外
        路由入口），剔除 Manager 本人。
        任何失败（模型报错、解析失败、候选为空）都返回 None，静默回落 Manager。
        """
        try:
            from cygnusx.application.services.agent_service import AgentService
            from cygnusx.application.services.chat.utils import _extract_route_json
            from cygnusx.infrastructure.ai_provider.openai_compatible import provider_manager

            catalog = [
                {key: entry.get(key) for key in _ROOM_TRIAGE_CATALOG_KEYS}
                for entry in self._registry.room_consultation_catalog()
                if str(entry.get("agent_id") or "") != manager_agent_id
            ]
            if not catalog:
                return None
            assemble_kwargs: dict[str, Any] = {"user_id": user_id}
            if model_id is not None:
                assemble_kwargs["model_id"] = model_id
            manager_ctx = await AgentService(self._db).assemble_context(
                manager_agent_id, **assemble_kwargs
            )
            if manager_ctx is None or manager_ctx.model_config is None:
                return None
            system_prompt = (
                _ROOM_TRIAGE_SYSTEM_PROMPT.replace(
                    "{catalog}", json.dumps(catalog, ensure_ascii=False)
                )
                .replace("{manager_name}", self._manager_display_name())
                .replace("{manager_agent_id}", manager_agent_id)
                .replace("{min_confidence}", str(_ROOM_TRIAGE_MIN_CONFIDENCE))
            )
            route_text = ""
            async for chunk in provider_manager.chat_stream(
                config=manager_ctx.model_config,
                messages=[{"role": "user", "content": content.strip()[:2_000]}],
                system_prompt=system_prompt,
                temperature=0,
                max_tokens=150,
                tools=None,
                deep_thinking=False,
            ):
                if chunk.type == "text":
                    route_text += chunk.content
            decision = _extract_route_json(route_text)
            if not decision:
                return None
            target_id = str(decision.get("agent_id") or "").strip()
            if not target_id or target_id == manager_agent_id:
                return None
            valid_ids = {str(entry["agent_id"]) for entry in catalog}
            if target_id not in valid_ids:
                return None
            try:
                confidence = float(decision.get("confidence") or 0.0)
            except (TypeError, ValueError):
                return None
            if confidence < _ROOM_TRIAGE_MIN_CONFIDENCE:
                return None
            return {
                "agent_id": target_id,
                "reason": str(decision.get("reason") or "")[:200],
                "confidence": confidence,
            }
        except Exception as exc:  # noqa: BLE001 - 分诊失败静默回落 Manager 主回路
            logger.warning("AgentTeams consultation triage failed, fallback to manager: {}", exc)
            return None

    async def _respond_to_direct_agent(
        self,
        case_id: str,
        requester_ref: str,
        content: str,
        case: dict[str, Any],
        events: list[dict[str, Any]],
        target_agent_id: str,
        actor_user_id: str,
        causation_event_id: str | None = None,
        model_id: UUID | None = None,
        room_id: str | None = None,
        origin: str = "direct_mention",
    ) -> dict[str, str]:
        """Phase 1 direct mention: readonly domain answer, without execution or approval bypass.

        失败/超时/目标不可用时返回带 ``reason`` 的失败状态（不抛异常），由调用方
        执行 A3 降级（可见降级消息 + room.agent_timeout 审计 + Manager 接管）。
        ``origin`` 为 ``manager_triage`` 时表示由纯咨询分诊转入（话术与事件载荷
        与用户直接点名区分）。
        """
        if target_agent_id not in self._registry.consultation_agents():
            return {
                "status": "direct_agent_unavailable",
                "reason": "agent_not_in_consultation_registry",
            }
        if self._has_running_work_item(case, target_agent_id):
            assessment = await AgentTeamsInterruptionCoordinator(
                self._agentteams, self._db
            ).request_assessment(
                case_id=case_id,
                requester_ref=requester_ref,
                agent_id=target_agent_id,
                content=content,
                causation_event_id=causation_event_id,
            )
            return {"status": str(assessment.get("status") or "assessment_pending")}
        manager_name = self._manager_display_name()
        agent_label = next(
            (
                value
                for value in self._registry.role_labels().values()
                if value.get("agent_id") == target_agent_id
            ),
            {},
        )
        agent_display_name = str(agent_label.get("name") or target_agent_id)
        if origin == "manager_triage":
            intro = (
                f"你是 AgentTeams 房间中的领域 Agent：{agent_display_name}"
                f"（{target_agent_id}）。请以该身份用第一人称回复。\n"
                f"房间由「{manager_name}」担任编排经理；你与房间内其他领域 Agent 是平级同事。\n"
                f"「{manager_name}」判断用户当前的咨询问题更适合由你回答，已将其分诊给你。"
                f"对外提及编排经理时一律使用「{manager_name}」，禁止使用英文 Manager 称呼。\n"
            )
        else:
            intro = (
                f"你是被用户在 AgentTeams 房间中直接点名的领域 Agent：{agent_display_name}"
                f"（{target_agent_id}）。请以该身份用第一人称回复。\n"
                f"房间由「{manager_name}」担任编排经理；你与房间内其他领域 Agent 是平级同事。"
                f"对外提及编排经理时一律使用「{manager_name}」，禁止使用英文 Manager 称呼。\n"
            )
        question = (
            f"{intro}"
            f"请只回答当前领域问题，不代表 {manager_name} 承诺范围、预算或审批。\n"
            f"如果用户要求真实计算、写入或改变执行计划，只说明影响并等待用户与"
            f"{manager_name} 确认后再推进，禁止自行执行。\n"
            f"Case 目标：{str(case.get('intent') or '')[:500]}\n"
            f"Case 状态：{str(case.get('status') or '')}\n"
            f"最近房间事件：{self._recent_event_context(events)}\n"
            f"{self._room_message_history(events, current_content=content)}"
            f"用户点名消息：{content.strip()[:4_000]}"
        )
        timeout_seconds = get_settings().agentteams_direct_timeout_seconds
        await self._set_typing(
            case_id,
            typing=True,
            agent_id=target_agent_id,
            agent_name=agent_display_name,
        )
        try:
            stream_id = uuid4().hex
            stream_projector = _RoomResponseStreamProjector(
                self._agentteams,
                case_id=case_id,
                agent_id=target_agent_id,
                stream_id=stream_id,
                role="worker",
                display_name=agent_display_name,
            )
            try:
                envelope = await asyncio.wait_for(
                    AgentConsultationService(
                        self._db,
                        agentteams_service=self._agentteams,
                    ).run_consultation(
                        case_id=case_id,
                        agent_id=target_agent_id,
                        question=question,
                        capability="interpretation",
                        evidence_refs=[],
                        requested_tools=["room_messages_read"],
                        requester_ref=requester_ref,
                        actor_user_id=actor_user_id,
                        model_id=model_id,
                        causation_event_id=causation_event_id,
                        on_event=stream_projector,
                        room_id=room_id or (case_id[5:] if case_id.startswith("room-") else None),
                    ),
                    timeout=timeout_seconds,
                )
            finally:
                await stream_projector.flush()
            await self._agentteams.post_case_evidence(
                case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type="room.agent_message",
                summary=envelope.conclusion[:200],
                payload={
                    "content": envelope.conclusion[:_ROOM_REPLY_CONTENT_MAX_CHARS],
                    "agent_id": target_agent_id,
                    "role": "worker",
                    "direct_mention": origin == "direct_mention",
                    "routed_by": origin,
                    "stream_id": stream_id,
                    "thought": stream_projector.reasoning_text,
                    "causation_event_id": causation_event_id,
                    "manager_report": {
                        "conclusion": envelope.conclusion,
                        "recommendations": envelope.recommendations,
                        "evidence_refs": envelope.evidence_refs,
                        "risks": envelope.risks,
                        "hard_gate": envelope.hard_gate,
                        "proposed_submission": envelope.proposed_submission,
                    },
                },
            )
            return {"status": "direct_responded"}
        except TimeoutError:
            # A3：30s（可配）无响应与报错同口径降级，绝不静默丢失用户消息。
            logger.bind(case_id=case_id, target_agent_id=target_agent_id).warning(
                "AgentTeams direct mention response timed out after {}s", timeout_seconds
            )
            return {
                "status": "direct_failed",
                "reason": f"timeout_after_{timeout_seconds:g}s",
            }
        except Exception as exc:  # noqa: BLE001 - direct mention must degrade to Manager
            logger.bind(case_id=case_id, target_agent_id=target_agent_id).warning(
                "AgentTeams direct mention response failed: {}", exc
            )
            return {
                "status": "direct_failed",
                "reason": f"{type(exc).__name__}: {exc}"[:300],
            }
        finally:
            await self._set_typing(
                case_id,
                typing=False,
                agent_id=target_agent_id,
                agent_name=agent_display_name,
            )

    async def _emit_direct_agent_fallback(
        self,
        case_id: str,
        *,
        target_agent_id: str,
        reason: str,
        causation_event_id: str | None,
    ) -> None:
        """A3 降级（Part 2.7）：direct 直答失败/超时的可见提示与审计。

        先落一条 Manager 身份的可见降级消息（用户侧绝不"发消息后无任何回复"），
        再落 ``room.agent_timeout`` 审计事件（target_agent_id + 失败原因 +
        触发发言的 causation_event_id）；随后由调用方继续 Manager 主回路生成
        正式回复。降级消息写失败只记 warning，不阻断 Manager 接管。
        """
        display_name = self._agent_display_name(target_agent_id)
        notice = f"「{display_name}」暂时无法响应，已记录，由我转达或稍后重试。"
        try:
            await self._agentteams.post_case_evidence(
                case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type="room.agent_message",
                summary=notice[:200],
                payload={
                    "content": notice,
                    "agent_id": self._manager_agent_id() or "bioops-manager",
                    "role": "bioops-manager",
                    "direct_fallback": True,
                    "target_agent_id": target_agent_id,
                    "causation_event_id": causation_event_id,
                },
            )
            await self._agentteams.post_case_evidence(
                case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type="room.agent_timeout",
                summary=f"领域 Agent {target_agent_id} 直答失败/超时，{self._manager_display_name()} 已降级接管",
                payload={
                    "target_agent_id": target_agent_id,
                    "reason": reason[:300],
                    "causation_event_id": causation_event_id,
                },
            )
        except Exception as exc:  # noqa: BLE001 - 降级提示失败不得阻断 Manager 接管
            logger.bind(case_id=case_id, target_agent_id=target_agent_id).warning(
                "AgentTeams direct fallback notice failed: {}", exc
            )

    def _agent_display_name(self, agent_id: str) -> str:
        """领域 Agent 的展示名（注册表 role_labels 快照），缺失时回退 agent_id。"""
        for label in self._registry.role_labels().values():
            if label.get("agent_id") == agent_id:
                name = str(label.get("name") or "").strip()
                if name:
                    return name
        return agent_id

    @staticmethod
    def _has_running_work_item(case: dict[str, Any], target_agent_id: str) -> bool:
        running_statuses = {
            "claimed",
            "running",
            "in_progress",
            "awaiting_approval",
            "planning_running",
        }
        work_items = case.get("work_items")
        if not isinstance(work_items, list):
            return False
        return any(
            isinstance(item, dict)
            and item.get("target") == target_agent_id
            and str(item.get("status") or "").lower() in running_statuses
            for item in work_items
        )

    @staticmethod
    def _recent_event_context(events: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for event in events[-8:]:
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            nested = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
            agent_id = str(nested.get("agent_id") or event.get("actor") or "").strip()
            content = str(nested.get("content") or "").strip()
            summary = str(payload.get("summary") or event.get("event_type") or "").strip()
            if content:
                summary = f"{agent_id or 'Agent'}：{content[:600]}"
            elif agent_id:
                summary = f"{agent_id}：{summary}"
            if summary:
                lines.append(summary[:700])
        return "；".join(lines) or "暂无历史动态"

    @staticmethod
    def _room_message_history(
        events: list[dict[str, Any]], *, current_content: str
    ) -> str:
        settings = get_settings()
        limit = max(1, min(int(settings.room_context_message_limit), 100))
        max_chars = max(500, int(settings.room_context_max_chars))
        messages: list[dict[str, str]] = []
        for event in events:
            if event.get("event_type") not in {"room.user_message", "room.agent_message"}:
                continue
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            nested = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
            content = str(nested.get("content") or "").strip()
            if not content or content == current_content.strip():
                continue
            actor = str(nested.get("agent_id") or event.get("actor") or "用户").strip()
            label = actor if event.get("event_type") == "room.agent_message" else "用户"
            messages.append({"label": label, "content": content})
        if not messages:
            return ""
        omitted = max(0, len(messages) - limit)
        selected = messages[-limit:]
        lines = ["房间消息历史（仅正文）："]
        if omitted:
            lines.append(f"更早的 {omitted} 条消息已省略。")
        used = sum(len(line) for line in lines)
        for message in selected:
            line = f"- {message['label']}：{message['content']}"
            if used + len(line) + 1 > max_chars:
                omitted += 1
                continue
            lines.append(line)
            used += len(line) + 1
        if len(lines) == 1:
            return ""
        logger.info(
            "AgentTeams room context injected: messages=%d omitted=%d include_thinking=%s",
            len(selected),
            omitted,
            settings.room_context_include_thinking,
        )
        logger.debug("AgentTeams room context history:\n{}", "\n".join(lines))
        return "\n".join(lines) + "\n"

    async def _maybe_start_chat_execution(
        self,
        *,
        case_id: str,
        requester_ref: str,
        actor_user_id: str,
        case: dict[str, Any],
        events: list[dict[str, Any]],
        content: str,
        preferences: dict[str, Any] | None = None,
        causation_event_id: str | None = None,
        room: AgentTeamsRoomModel | None = None,
    ) -> str:
        """聊天式 Case 的执行意图三态处理；返回处理结果。

        返回值：``started``（execute 态，已触发 planning）/ ``clarified``
        （clarify 态，已落选项式追问卡片）/ ``degraded``（追问轮次耗尽，
        降级为纯对话）/ ``proposal_pending``（未立项房间的 execute 态，
        已落立项确认卡）/ ``none``（chat 态或触发失败，走正常 Manager 回复）。

        仅对无 flow_id、仍处于 received、且尚无 plan-01 的 Case 生效——flow 型
        Case 的人工审批链路绝不旁路。触发失败只记日志，不影响 Manager 回复。
        用户偏好 autonomy 只影响沟通与低风险只读建议；真实计算仍必须在
        approval_pending 后由用户显式审批。clarify 态不推送 route_decision
        执行卡片（O1 兼容约束）。
        """
        if case.get("flow_id") or case.get("status") != "received":
            return "none"
        work_items = case.get("work_items")
        if isinstance(work_items, list) and any(
            isinstance(item, dict) and item.get("work_item_id") == "plan-01"
            for item in work_items
        ):
            return "none"
        refs = self._latest_message_context_refs(events, content)
        await self._record_intake_if_present(case_id, content)
        pending_clarify_event = self._pending_execution_clarify_event(events, content)
        pending_clarify = pending_clarify_event is not None
        workspace_candidates = (
            await self._workspace_data_candidates(requester_ref, case)
            if not refs and not pending_clarify
            else []
        )
        if pending_clarify_event is not None:
            await self._record_clarify_answer(
                case_id,
                content,
                pending_clarify_event,
                answer_to_event_id=str(pending_clarify_event.get("event_id") or "") or None,
                context_refs=refs,
            )
        pending_route_event = self._pending_route_clarify_event(events, content)
        if pending_route_event is not None:
            await self._record_clarify_answer(
                case_id,
                content,
                pending_route_event,
                answer_to_event_id=str(pending_route_event.get("event_id") or "") or None,
                context_refs=refs,
            )
        structured_answer = self._ask_reply_answer_text(content)
        # 意图分类只基于用户真正的答案文本：结构化答复里嵌套的问题原文常含
        # “执行”等动词与示例文件名，直接对全文分类会把“先讨论方案（暂不执行）”
        # 误判为 clarify/execute，造成无限追问。
        intent_source = structured_answer or content
        if structured_answer is not None and any(
            marker in structured_answer for marker in _CLARIFY_OPT_OUT_MARKERS
        ):
            # 结构化澄清答复中明确放弃执行：不依赖 pending 卡检测（事件流异常时
            # 也必须能终止追问），直接按纯对话处理。
            return "none"
        if (
            structured_answer is None
            and (pending_clarify or pending_route_event is not None)
            and any(marker in content for marker in _CLARIFY_OPT_OUT_MARKERS)
        ):
            # 自由文本发言在澄清中明确放弃执行：按纯对话处理，不再追问。
            return "none"
        intent = classify_execution_intent(intent_source, refs)
        origin_content: str | None = None
        if pending_clarify and intent not in {
            ExecutionIntent.EXECUTE,
            ExecutionIntent.TOOL_EXECUTE,
        }:
            if has_explicit_object(intent_source, refs):
                # 澄清回复补全了作用对象：沿用原始执行请求，自动转入 execute。
                intent = ExecutionIntent.EXECUTE
                origin_content = self._pending_clarify_origin(events, content)
            elif intent is ExecutionIntent.CHAT and content.strip().startswith(
                ROOM_ASK_REPLY_MARKER
            ):
                # 结构化澄清答复仍未给出对象：推进追问轮次（受轮次上限约束）。
                intent = ExecutionIntent.CLARIFY
        if (
            pending_route_event is not None
            and intent not in {ExecutionIntent.EXECUTE, ExecutionIntent.TOOL_EXECUTE}
        ):
            # P0-1：领域澄清答复——与原始执行请求拼接后重跑路由；仍无命中时由
            # 下方 route is None 分支按轮次上限继续追问或降级 Manager 会诊。
            intent = ExecutionIntent.EXECUTE
            route_origin = self._route_clarify_origin(pending_route_event)
            origin_content = (
                f"{route_origin}\n用户补充的分析领域：{content.strip()[:200]}"
                if route_origin
                else content
            )
        if intent is ExecutionIntent.CHAT:
            return "none"
        if intent is ExecutionIntent.CLARIFY:
            rounds = self._execution_clarify_rounds(events)
            if rounds >= MAX_EXECUTION_CLARIFY_ROUNDS:
                logger.bind(case_id=case_id).info(
                    "AgentTeams execution clarify exhausted after {} rounds, degraded to chat",
                    rounds,
                )
                return "degraded"
            emitted = await self._emit_execution_clarify(
                case_id,
                self._pending_clarify_origin(events, content) or content,
                round_no=rounds + 1,
                causation_event_id=causation_event_id,
                workspace_candidates=workspace_candidates,
            )
            return "clarified" if emitted else "none"
        if intent is ExecutionIntent.TOOL_EXECUTE:
            return await self._run_room_tool_execution(
                case_id=case_id,
                requester_ref=requester_ref,
                actor_user_id=actor_user_id,
                content=content,
                refs=refs,
                capabilities=requested_readonly_capabilities(content),
                causation_event_id=causation_event_id,
            )
        # execute 态：路由决策卡（O1）：优先使用最初的执行请求做路由，
        # 避免用户回答“只有 FASTQ / 尚未上传”等澄清信息后丢失单细胞、RNA-seq 等领域上下文。
        route_input = origin_content or content
        try:
            route = infer_intent_route(
                route_input,
                flow_registry=self._flow_registry,
                capability_registry=self._registry,
            )
        except Exception as exc:  # noqa: BLE001 - fallback is audited and safe
            logger.bind(case_id=case_id).warning("AgentTeams route resolution failed: {}", exc)
            route = None
        if room is not None:
            # 会话-工单解耦（Part 2）：未立项房间的 execute 意图不直接建 Case、
            # 不启动 planning，先落"立项确认卡"（房间级事件流）；用户经
            # confirm-proposal 端点确认后才创建 Case 并回写绑定。
            emitted = await self._emit_case_proposal(
                room=room,
                content=route_input,
                refs=refs,
                resolved_route=route,
                proposal_kind="new_case",
                source_case_id=None,
                causation_event_id=causation_event_id,
            )
            return "proposal_pending" if emitted else "none"
        if route is None:
            # P0-1 硬约束：路由无命中禁止静默直达 DEFAULT_LEAD_PLANNER 兜底。
            # 先落领域澄清卡请用户指明分析类型；追问轮次耗尽则降级为 Manager
            # 会诊对话（返回 none 走正常 LLM 回复），同样不派发执行。
            route_rounds = self._route_clarify_rounds(events)
            if route_rounds >= MAX_ROUTE_CLARIFY_ROUNDS:
                logger.bind(case_id=case_id).info(
                    "AgentTeams route unresolved after {} clarify rounds, degraded to manager consultation",
                    route_rounds,
                )
                return "none"
            emitted = await self._emit_route_clarify(
                case_id,
                route_input,
                round_no=route_rounds + 1,
                causation_event_id=causation_event_id,
            )
            return "clarified" if emitted else "none"
        await self._emit_route_decision(
            case_id, route_input, resolved_route=route, causation_event_id=causation_event_id
        )
        # Bridge objective 上限 1000 字符：用户原话截断后附通用计划契约尾段；
        # 经澄清补全的执行沿用原始请求，并附用户补充的作用对象说明。
        if origin_content is not None:
            objective = (
                f"{origin_content[:600]}\n\n"
                f"用户补充的作用对象：{content.strip()[:200]}\n\n"
                f"{GENERAL_PLAN_CONTRACT}"
            )
        else:
            objective = f"{content.strip()[:600]}\n\n{GENERAL_PLAN_CONTRACT}"
        try:
            await self._agentteams.start_chat_planning(
                case_id=case_id,
                requester_ref=requester_ref,
                objective=objective,
                context_refs=refs,
                # P0-1：能走到这里路由必定已命中（无命中在上方被澄清卡/会诊拦截）。
                target_agent_id=route.lead_planner,
            )
        except Exception as exc:  # noqa: BLE001 - 触发失败不得影响回复主流程
            logger.bind(case_id=case_id).warning(
                "AgentTeams chat execution trigger failed: {}", exc
            )
            return "none"
        logger.bind(case_id=case_id).info(
            "AgentTeams chat execution intent detected, planning started"
        )
        return "started"

    async def _run_room_tool_execution(
        self,
        *,
        case_id: str,
        requester_ref: str,
        actor_user_id: str,
        content: str,
        refs: list[dict[str, Any]],
        capabilities: list[str],
        causation_event_id: str | None = None,
        model_id: UUID | None = None,
    ) -> str:
        """执行单步只读房间请求，并把结果明确回传，不伪造 Case 完成。"""
        agent_id = await self._manager_agent_with_audit(case_id)
        if agent_id is None:
            return "none"
        await self._agentteams.post_case_evidence(
            case_id,
            work_item_id=CASE_LEVEL_WORK_ITEM_ID,
            event_type="room.route_decision",
            summary="已路由到受控只读工具执行",
            payload={
                "route": "tool_execute",
                "reason": "用户明确要求读取、检索或只读复核",
                "requires_tool": True,
                "requested_capabilities": capabilities,
                "execution_path": "agentteams_tool_execution",
                "causation_event_id": causation_event_id,
            },
        )
        memory_context = await self._build_memory_context(
            requester_ref=requester_ref, agent_id=agent_id, current_message=content
        )
        question = self._build_question(
            {"intent": "受控只读工具执行", "status": "tool_execute"},
            [],
            content,
            None,
            system_note=(
                "本轮只允许受控只读工具；工具失败必须如实说明，"
                "不得把未执行的动作表述为已完成。"
            ),
            manager_display_name=self._manager_display_name(),
            memory_context=memory_context,
        )
        await self._set_typing(case_id, typing=True)
        try:
            stream_id = uuid4().hex
            stream_projector = _RoomResponseStreamProjector(
                self._agentteams, case_id=case_id, agent_id=agent_id, stream_id=stream_id
            )
            try:
                envelope = await AgentConsultationService(
                    self._db, agentteams_service=self._agentteams
                ).run_consultation(
                    case_id=case_id,
                    agent_id=agent_id,
                    question=question,
                    capability="readonly_tool_execution",
                    evidence_refs=[],
                    requested_tools=capabilities,
                    requester_ref=requester_ref,
                    actor_user_id=actor_user_id,
                    model_id=model_id,
                    execution_mode="readonly_consultation",
                    causation_event_id=causation_event_id,
                    on_event=stream_projector,
                    room_id=(case_id[5:] if case_id.startswith("room-") else None),
                )
            finally:
                await stream_projector.flush()
            reply = _sanitize_manager_reply(envelope.conclusion)
            visible_risks = _visible_manager_risks(getattr(envelope, "risks", []))
            if not reply:
                return "none"
            await self._agentteams.post_case_evidence(
                case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type="room.agent_message",
                summary=reply[:200],
                payload={
                    "content": reply[:_ROOM_REPLY_CONTENT_MAX_CHARS],
                    "agent_id": agent_id,
                    "role": "bioops-manager",
                    "stream_id": stream_id,
                    "thought": stream_projector.reasoning_text,
                    "execution_path": "agentteams_tool_execution",
                    "route": "tool_execute",
                    "causation_event_id": causation_event_id,
                    "requested_capabilities": capabilities,
                    "tool_result_refs": list(getattr(envelope, "evidence_refs", []) or []),
                    "risks": visible_risks,
                    "manager_report": {
                        "conclusion": reply,
                        "recommendations": list(getattr(envelope, "recommendations", []) or []),
                        "evidence_refs": list(getattr(envelope, "evidence_refs", []) or []),
                        "risks": visible_risks,
                        "hard_gate": getattr(envelope, "hard_gate", None),
                        "proposed_submission": getattr(envelope, "proposed_submission", None),
                    },
                },
            )
            return "tool_executed"
        except Exception as exc:  # noqa: BLE001 - failure must be visible to user
            logger.bind(case_id=case_id).warning("Room tool execution failed: {}", exc)
            await self._agentteams.post_case_evidence(
                case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type="room.agent_message",
                summary="只读工具执行失败",
                payload={
                    "content": f"只读工具执行失败：{exc}",
                    "agent_id": agent_id,
                    "role": "bioops-manager",
                    "execution_path": "agentteams_tool_execution",
                    "route": "tool_execute",
                    "causation_event_id": causation_event_id,
                    "failed": True,
                },
            )
            return "tool_executed"
        finally:
            await self._set_typing(case_id, typing=False)

    async def _emit_execution_clarify(
        self,
        case_id: str,
        content: str,
        *,
        round_no: int,
        causation_event_id: str | None = None,
        workspace_candidates: list[dict[str, str]] | None = None,
    ) -> bool:
        """clarify 态：落 ``room.ask_user`` 选项式追问卡片（AskUserCard 渲染）。

        复用 phylo 域 intake questions 的同一条渲染与回答回收链路：前端把答案
        格式化为带【澄清回复】前缀的下一条 room.user_message 回到响应回路。
        卡片发送失败时返回 False，调用方回退到正常 Manager 回复。
        """
        brief = content.strip().replace("\n", " ")[:80]
        if round_no <= 1:
            if workspace_candidates:
                question = (
                    f"收到你的执行请求「{brief}」。如需立即执行，可任选一个候选文件，"
                    "或上传/填写其它输入；也可以先讨论分析方案："
                )
                options = [item["location"] for item in workspace_candidates]
            else:
                question = (
                    f"收到你的执行请求「{brief}」。如需立即执行，请上传文件或填写工作区路径；"
                    "也可以先讨论分析方案。"
                )
                options = []
        else:
            question = (
                "仍未拿到可执行的作用对象：请直接上传文件，或回复工作区文件名/路径"
                "（如 genes.xlsx），或公共数据库 accession/检索关键词。"
            )
            options = ["我去上传文件", "回复文件名或路径", "先不执行了"]
        try:
            await self._agentteams.post_case_evidence(
                case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type="room.ask_user",
                summary=question[:200],
                payload={
                    "content": "需要你先确认数据来源，再启动执行。",
                    "agent_id": self._manager_agent_id() or "bioops-manager",
                    "role": "bioops-manager",
                    "questions": [{"question": question, "options": options}],
                    "clarify_kind": CLARIFY_KIND_EXECUTION_OBJECT,
                    "round": round_no,
                    "origin_content": content.strip()[:600],
                    "causation_event_id": causation_event_id,
                    "workspace_candidates": workspace_candidates or [],
                },
            )
        except Exception as exc:  # noqa: BLE001 - 澄清卡片失败回退到正常回复
            logger.bind(case_id=case_id).warning(
                "AgentTeams execution clarify event failed: {}", exc
            )
            return False
        logger.bind(case_id=case_id).info(
            "AgentTeams execution intent unclear (no object), clarify round {} asked",
            round_no,
        )
        return True

    async def _emit_route_clarify(
        self,
        case_id: str,
        content: str,
        *,
        round_no: int,
        causation_event_id: str | None = None,
    ) -> bool:
        """P0-1：execute 意图路由无命中时落 ``room.ask_user`` 领域澄清卡。

        选项来自流程注册表的 display_name（必要时附主 hint 保证答复可被路由
        再次命中）；答复经【澄清回复】链路与原始请求拼接后重跑路由，仍无命中
        则由轮次上限降级到 Manager 会诊。卡片发送失败返回 False，调用方回退
        到正常 Manager 回复。
        """
        brief = content.strip().replace("\n", " ")[:80]
        flow_options = self._route_domain_options()
        if round_no <= 1 and flow_options:
            question = (
                f"收到你的执行请求「{brief}」，但没能识别出要做哪类分析。"
                "请确认分析类型，或补充说明研究领域："
            )
        else:
            question = (
                f"仍未识别出「{brief}」要做哪类分析：请直接回复分析类型"
                "（如 RNA-seq 差异分析、单细胞转录组、ATAC-seq），或选择先讨论方案。"
            )
        manager_name = self._manager_display_name()
        options = [*flow_options, f"以上都不是，先和{manager_name}讨论方案"]
        try:
            await self._agentteams.post_case_evidence(
                case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type="room.ask_user",
                summary=question[:200],
                payload={
                    "content": "需要你先确认分析类型，再启动执行。",
                    "agent_id": self._manager_agent_id() or "bioops-manager",
                    "role": "bioops-manager",
                    "questions": [{"question": question, "options": options}],
                    "clarify_kind": CLARIFY_KIND_ROUTE_DOMAIN,
                    "round": round_no,
                    "origin_content": content.strip()[:600],
                    "causation_event_id": causation_event_id,
                },
            )
        except Exception as exc:  # noqa: BLE001 - 澄清卡片失败回退到正常回复
            logger.bind(case_id=case_id).warning(
                "AgentTeams route clarify event failed: {}", exc
            )
            return False
        logger.bind(case_id=case_id).info(
            "AgentTeams route unresolved (no domain hit), clarify round {} asked",
            round_no,
        )
        return True

    def _route_domain_options(self) -> list[str]:
        """领域澄清卡候选项：流程注册表 display_name（至多 4 个）。

        display_name 不含任何 trigger hint 时附主 hint，保证用户点选后的
        【澄清回复】文本能被意图路由再次命中。
        """
        try:
            registry = self._flow_registry or get_flow_registry()
        except Exception:  # noqa: BLE001 - 注册表不可用时只给自由补充项
            logger.warning("AgentTeams route clarify options: flow registry unavailable")
            return []
        options: list[str] = []
        for flow_id in sorted(registry.flows):
            meta = registry.flows[flow_id].definition.flow
            label = str(meta.display_name or "").strip()
            if not label:
                continue
            hints = [str(hint).strip() for hint in meta.trigger_hints if str(hint).strip()]
            normalized_label = _normalize_route_text(label)
            if hints and not any(
                _normalize_route_text(hint) in normalized_label for hint in hints
            ):
                label = f"{label}（{hints[0]}）"
            if label not in options:
                options.append(label)
            if len(options) >= 4:
                break
        return options

    async def _emit_case_proposal(
        self,
        *,
        room: AgentTeamsRoomModel,
        content: str,
        refs: list[dict[str, Any]],
        resolved_route: IntentRoute | None = None,
        proposal_kind: str,
        source_case_id: str | None,
        causation_event_id: str | None = None,
    ) -> bool:
        """execute 态（未立项/终态后再立项）：落"立项确认卡"房间级事件。

        事件类型 ``room.proposal_confirm``，payload 含分析目标/涉及部门/预计
        流程摘要 + confirm/modify/cancel（followup 卡为 continue/new/cancel）
        三选项与一次性 confirm_token；确认动作走 confirm-proposal 端点，
        确认前的澄清对话全部留在房间维度。卡片发送失败返回 False，
        调用方回退到正常 Manager 回复。
        """
        try:
            decision = build_route_decision(
                content,
                flow_registry=self._flow_registry,
                capability_registry=self._registry,
                resolved_route=resolved_route,
                fallback_lead_planner=DEFAULT_LEAD_PLANNER,
            )
        except Exception as exc:  # noqa: BLE001 - 路由摘要缺失不阻断立项卡
            logger.bind(room_id=room.room_id).warning(
                "AgentTeams proposal route decision build failed: {}", exc
            )
            decision = None
        proposal = build_room_proposal(
            proposal_kind=proposal_kind,
            content=content,
            route_decision=decision or {},
            context_refs=refs,
            source_case_id=source_case_id,
        )
        options = (
            PROPOSAL_OPTIONS_NEW_CASE if proposal_kind == "new_case" else PROPOSAL_OPTIONS_FOLLOWUP
        )
        try:
            await persist_room_proposal(self._db, room, proposal)
            evidence = await self._agentteams.post_case_evidence(
                room_namespace_case_id(room.room_id),
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type=ROOM_PROPOSAL_EVENT_TYPE,
                summary=f"立项确认：{proposal['objective'][:80]}",
                payload={
                    "agent_id": self._manager_agent_id() or "bioops-manager",
                    "role": "bioops-manager",
                    "causation_event_id": causation_event_id,
                    "confirm_token": proposal["token"],
                    "options": options,
                    **{key: value for key, value in proposal.items() if key != "token"},
                },
            )
            # 回写卡片事件 id：确认/取消动作落事件时以 answer_to_event_id 指回
            # 本卡片，与澄清答复的 answer_to_event_id 口径统一（Part 3.4）。
            card_event_id = str(evidence.get("event_id") or "")
            if card_event_id:
                proposal["card_event_id"] = card_event_id
                await persist_room_proposal(self._db, room, proposal)
        except Exception as exc:  # noqa: BLE001 - 立项卡失败回退到正常回复
            logger.bind(room_id=room.room_id).warning(
                "AgentTeams case proposal event failed: {}", exc
            )
            return False
        logger.bind(room_id=room.room_id, proposal_kind=proposal_kind).info(
            "AgentTeams case proposal emitted, awaiting user confirmation"
        )
        return True

    @staticmethod
    def _has_handoff_started(events: list[dict[str, Any]]) -> bool:
        return any(event.get("event_type") == "case.handoff_started" for event in events)

    @staticmethod
    def _gate_unstarted_handoff_language(reply: str) -> str:
        """未观测到运行时交接事件时，不允许 Manager 把计划说成已经派发。"""
        guarded = reply
        for phrase, replacement in _HANDOFF_LANGUAGE_REPLACEMENTS.items():
            guarded = guarded.replace(phrase, replacement)
        return guarded

    @staticmethod
    def _handoff_failure_reason(events: list[dict[str, Any]]) -> str | None:
        """Read the latest persisted pre-handoff failure for the Manager reply."""
        for event in reversed(events):
            if event.get("event_type") != "case.handoff_failed":
                continue
            payload = AgentTeamsRoomResponseService._payload_dict(event)
            reason = str(payload.get("reason") or payload.get("summary") or "").strip()
            if reason:
                return reason[:500]
        return None

    @classmethod
    def _is_execution_clarify_event(cls, event: dict[str, Any]) -> bool:
        if event.get("event_type") != "room.ask_user":
            return False
        payload = cls._payload_dict(event)
        inner_raw = payload.get("payload")
        inner = dict(inner_raw) if isinstance(inner_raw, dict) else {}
        return inner.get("clarify_kind") == CLARIFY_KIND_EXECUTION_OBJECT

    @classmethod
    def _execution_clarify_rounds(cls, events: list[dict[str, Any]]) -> int:
        """已发出的执行对象澄清轮次（按澄清卡片计数）。"""
        return sum(1 for event in events if cls._is_execution_clarify_event(event))

    @classmethod
    def _is_route_clarify_event(cls, event: dict[str, Any]) -> bool:
        if event.get("event_type") != "room.ask_user":
            return False
        payload = cls._payload_dict(event)
        inner_raw = payload.get("payload")
        inner = dict(inner_raw) if isinstance(inner_raw, dict) else {}
        return inner.get("clarify_kind") == CLARIFY_KIND_ROUTE_DOMAIN

    @classmethod
    def _route_clarify_rounds(cls, events: list[dict[str, Any]]) -> int:
        """已发出的领域路由澄清轮次（P0-1，按澄清卡片计数）。"""
        return sum(1 for event in events if cls._is_route_clarify_event(event))

    @classmethod
    def _pending_route_clarify_event(
        cls, events: list[dict[str, Any]], content: str
    ) -> dict[str, Any] | None:
        """当前发言是否是对最近一张领域澄清卡的回答（P0-1）。

        口径与 ``_pending_execution_clarify_event`` 一致：当前发言之前最近的
        一张领域澄清卡之后没有其他用户发言，则当前发言就是对它的回答。
        """
        current_index = cls._current_message_index(events, content)
        scan = events[:current_index] if current_index is not None else events
        pending: dict[str, Any] | None = None
        for event in scan:
            if event.get("event_type") == "room.user_message":
                pending = None
            elif cls._is_route_clarify_event(event):
                pending = event
        return pending

    @classmethod
    def _route_clarify_origin(cls, clarify_event: dict[str, Any]) -> str | None:
        """取领域澄清卡记录的原始执行请求（供答复拼接后重跑路由）。"""
        payload = cls._payload_dict(clarify_event)
        inner_raw = payload.get("payload")
        inner = dict(inner_raw) if isinstance(inner_raw, dict) else {}
        origin = str(inner.get("origin_content") or "").strip()
        return origin or None

    @classmethod
    def _current_message_event_id(
        cls, events: list[dict[str, Any]], content: str
    ) -> str | None:
        """当前发言对应的 room.user_message 事件 ID（按内容倒序匹配最近一条）。

        与 _current_message_index 同一匹配规则；事件缺 event_id 时返回 None，
        调用方据此跳过幂等去重（无法定位消息时不伪造去重键）。
        """
        target = content.strip()
        for event in reversed(events):
            if event.get("event_type") != "room.user_message":
                continue
            payload = cls._payload_dict(event)
            inner_raw = payload.get("payload")
            inner = dict(inner_raw) if isinstance(inner_raw, dict) else {}
            event_content = str(inner.get("content") or payload.get("summary") or "").strip()
            if event_content == target:
                return str(event.get("event_id") or "") or None
        return None

    @classmethod
    def _current_message_index(
        cls, events: list[dict[str, Any]], content: str
    ) -> int | None:
        target = content.strip()
        for index in range(len(events) - 1, -1, -1):
            event = events[index]
            if event.get("event_type") != "room.user_message":
                continue
            payload = cls._payload_dict(event)
            inner_raw = payload.get("payload")
            inner = dict(inner_raw) if isinstance(inner_raw, dict) else {}
            event_content = str(inner.get("content") or payload.get("summary") or "").strip()
            if event_content == target:
                return index
        return None

    @classmethod
    def _pending_execution_clarify(
        cls, events: list[dict[str, Any]], content: str
    ) -> bool:
        """当前发言是否处于“执行对象澄清待补全”状态。

        即：当前发言之前最近的一张执行对象澄清卡之后没有其他用户发言——
        当前发言就是对那张卡片的回答。
        """
        return cls._pending_execution_clarify_event(events, content) is not None

    @classmethod
    def _pending_execution_clarify_event(
        cls, events: list[dict[str, Any]], content: str
    ) -> dict[str, Any] | None:
        current_index = cls._current_message_index(events, content)
        scan = events[:current_index] if current_index is not None else events
        pending: dict[str, Any] | None = None
        for event in scan:
            if event.get("event_type") == "room.user_message":
                pending = None
            elif cls._is_execution_clarify_event(event):
                pending = event
        return pending

    async def _record_clarify_answer(
        self,
        case_id: str,
        content: str,
        clarify_event: dict[str, Any],
        *,
        answer_to_event_id: str | None = None,
        context_refs: list[dict[str, Any]] | None = None,
    ) -> None:
        """将澄清回复写成 Case 上下文中的已收集答案清单。"""
        payload = self._payload_dict(clarify_event)
        inner_raw = payload.get("payload")
        inner = dict(inner_raw) if isinstance(inner_raw, dict) else {}
        questions = inner.get("questions")
        question = ""
        options: list[str] = []
        if isinstance(questions, list) and questions and isinstance(questions[0], dict):
            question = str(questions[0].get("question") or "")
            raw_options = questions[0].get("options")
            if isinstance(raw_options, list):
                options = [str(option) for option in raw_options if str(option).strip()]
        object_supplied = has_explicit_object(content, context_refs or [])
        answer_status = (
            "collected"
            if object_supplied
            else "waiting_upload"
            if "上传" in content
            else "missing_object"
        )
        try:
            await self._agentteams.post_case_evidence(
                case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type="room.ask_user_answered",
                summary=f"已收集澄清答案：{content.strip()[:160]}",
                payload={
                    "clarify_kind": inner.get("clarify_kind"),
                    "round": inner.get("round"),
                    "question": question,
                    "options": options,
                    "answer": content.strip()[:4_000],
                    "origin_content": str(inner.get("origin_content") or "")[:600],
                    "source_event_type": "room.user_message",
                    "answer_to_event_id": answer_to_event_id,
                    "answer_status": answer_status,
                },
            )
        except Exception as exc:  # noqa: BLE001 - answer audit must not block execution
            logger.bind(case_id=case_id).warning(
                "AgentTeams execution clarify answer evidence failed: {}", exc
            )

    async def _record_dedup_degraded(
        self,
        case_id: str,
        *,
        reason: str,
        causation_event_id: str | None,
    ) -> None:
        """Record Redis dedup degradation without blocking the user response."""
        try:
            await self._agentteams.post_case_evidence(
                case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type="room.dedup_degraded",
                summary="房间响应幂等保护降级，已继续处理消息",
                payload={
                    "reason": reason,
                    "causation_event_id": causation_event_id,
                    "fallback": "continue_without_redis_dedup",
                },
            )
        except Exception as exc:  # noqa: BLE001 - never mask the original Redis degradation
            logger.bind(case_id=case_id).warning(
                "AgentTeams dedup degradation audit failed: {}", exc
            )

    async def _record_intake_if_present(self, case_id: str, content: str) -> None:
        """Persist a compact, reusable intake fact without replacing the original message evidence."""
        intake = self._extract_intake(content)
        if not intake:
            return
        try:
            await self._agentteams.post_case_evidence(
                case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type="room.intake_extracted",
                summary="已提取研究设计：" + "；".join(
                    f"{key}={value}" for key, value in intake.items()
                )[:180],
                payload={"intake": intake, "source_content": content.strip()[:600]},
            )
        except Exception as exc:  # noqa: BLE001 - intake evidence cannot block the response
            logger.bind(case_id=case_id).warning("AgentTeams intake evidence failed: {}", exc)

    async def _workspace_data_candidates(
        self,
        requester_ref: str,
        case: dict[str, Any],
    ) -> list[dict[str, str]]:
        """Prefer Case-authorized refs, then supplement with recent active user data files."""
        candidates: list[dict[str, str]] = []
        seen_locations: set[str] = set()

        for raw_ref in case.get("context_refs") or []:
            if not isinstance(raw_ref, dict):
                continue
            kind = str(raw_ref.get("kind") or "").strip()
            ref_id = str(raw_ref.get("id") or "").strip()
            location = str(raw_ref.get("location") or raw_ref.get("path") or "").strip()
            if kind not in {"file", "workspace"} or not ref_id or not location:
                continue
            if not any(location.lower().endswith(suffix) for suffix in _WORKSPACE_DATA_SUFFIXES):
                continue
            candidates.append({"kind": kind, "id": ref_id, "location": location})
            seen_locations.add(location)
            if len(candidates) >= 5:
                return candidates

        try:
            user_id = UUID(requester_ref)
        except (TypeError, ValueError):
            return candidates
        try:
            files = await FileRepositoryImpl(self._db).list_by_user(user_id, status="active")
        except Exception as exc:  # noqa: BLE001 - preflight must not delay or block clarification
            logger.bind(requester_ref=requester_ref).warning(
                "AgentTeams workspace candidate preflight failed: {}", exc
            )
            return candidates
        for item in files:
            location = str(item.path or item.original_name).strip()
            if not location or not any(location.lower().endswith(suffix) for suffix in _WORKSPACE_DATA_SUFFIXES):
                continue
            if location in seen_locations:
                continue
            candidates.append({"kind": "file", "id": str(item.id), "location": location})
            seen_locations.add(location)
            if len(candidates) >= 5:
                break
        return candidates

    @staticmethod
    def _extract_intake(content: str) -> dict[str, Any]:
        """Conservatively extract only explicit study-design facts from the user's wording."""
        text = content.strip()
        if not text:
            return {}
        intake: dict[str, Any] = {}
        if "小鼠" in text:
            intake["species"] = "mouse"
        if "肺" in text:
            intake["tissue"] = "lung"
        if "单细胞" in text:
            intake["modality"] = "single_cell_rna"
        if match := _INTAKE_SAMPLE_COUNT_RE.search(text):
            intake["sample_count"] = int(match.group(1))
        if match := _INTAKE_GROUP_RE.search(text):
            intake["group_sizes"] = [int(match.group(1)), int(match.group(2))]
        if match := _INTAKE_COMPARISON_RE.search(text):
            intake["comparison"] = f"{match.group(1).strip()} vs {match.group(2).strip()}"
        return intake

    @staticmethod
    def _ask_reply_answer_text(content: str) -> str | None:
        """从【澄清回复】结构化答复中提取纯答案文本（剥离嵌套的问题原文）。

        前端 ``formatRoomAskReply`` 的格式为 marker 首行 + ``N. {question}：{answer}``
        逐行拼接；问题原文可能自带「：」，故答案取每行最后一个「：」之后的文本，
        与前端 ``parseRoomAskReply`` 的解析口径对齐。非结构化答复返回 None。
        """
        stripped = content.strip()
        if not stripped.startswith(ROOM_ASK_REPLY_MARKER):
            return None
        answers: list[str] = []
        for raw in stripped[len(ROOM_ASK_REPLY_MARKER):].split("\n"):
            line = re.sub(r"^\d+[.、)]\s*", "", raw.strip())
            if line:
                answers.append(line.rsplit("：", 1)[-1].strip())
        return "；".join(answer for answer in answers if answer) or None

    @classmethod
    def _pending_clarify_origin(
        cls, events: list[dict[str, Any]], content: str
    ) -> str | None:
        """取待补全澄清卡记录的原始执行请求（供补全后拼接执行目标）。"""
        current_index = cls._current_message_index(events, content)
        scan = events[:current_index] if current_index is not None else events
        for event in reversed(scan):
            if not cls._is_execution_clarify_event(event):
                continue
            payload = cls._payload_dict(event)
            inner_raw = payload.get("payload")
            inner = dict(inner_raw) if isinstance(inner_raw, dict) else {}
            origin = str(inner.get("origin_content") or "").strip()
            if origin.startswith(ROOM_ASK_REPLY_MARKER):
                # 兼容历史异常数据：origin 本身不应是澄清答复，剥掉 marker 首行。
                origin = origin[len(ROOM_ASK_REPLY_MARKER):].strip()
            return origin or None
        return None

    async def _emit_route_decision(
        self,
        case_id: str,
        content: str,
        *,
        resolved_route: IntentRoute | None = None,
        causation_event_id: str | None = None,
    ) -> None:
        """落 ``room.route_decision`` 事件并写结构化日志；任何失败仅记 warning。

        只外显决策结果（路径 / 命中关键词 / Planner 评分 / 预计阶段 / 置信度），
        不改变意图路由与规划逻辑；卡片发送失败绝不影响执行触发主流程。
        """
        try:
            decision = build_route_decision(
                content,
                flow_registry=self._flow_registry,
                capability_registry=self._registry,
                resolved_route=resolved_route,
                fallback_lead_planner=DEFAULT_LEAD_PLANNER,
            )
        except Exception as exc:  # noqa: BLE001 - 决策构建失败不得影响执行触发
            logger.bind(case_id=case_id).warning("AgentTeams route decision build failed: {}", exc)
            return
        if decision is None:
            return
        try:
            await self._agentteams.post_case_evidence(
                case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type=ROUTE_DECISION_EVENT_TYPE,
                summary=summarize_route_decision(decision)[:200],
                payload={
                    **decision,
                    "causation_event_id": causation_event_id,
                    "audit": {
                        "input_summary": content[:500],
                        "matched_hints": decision.get("matched_hints", []),
                        "display_lead_planner": decision["lead_planner"],
                        "actual_plan_target": resolved_route.lead_planner
                        if resolved_route
                        else DEFAULT_LEAD_PLANNER,
                        "route_input": content[:500],
                        "registry_version": decision.get("registry_version"),
                        "level": "WARN"
                        if decision["lead_planner"]
                        != (resolved_route.lead_planner if resolved_route else DEFAULT_LEAD_PLANNER)
                        else "INFO",
                        "reason": (
                            "展示路由与实际派发目标不一致"
                            if decision["lead_planner"]
                            != (resolved_route.lead_planner if resolved_route else DEFAULT_LEAD_PLANNER)
                            else decision.get("fallback_reason")
                        ),
                    },
                },
            )
        except Exception as exc:  # noqa: BLE001 - 卡片发送失败不得影响执行触发
            logger.bind(case_id=case_id).warning("AgentTeams route decision event failed: {}", exc)
            return
        logger.bind(case_id=case_id, route_decision=decision).info(
            "AgentTeams route decision: path={} flow={} lead_planner={} confidence={}",
            decision["path"],
            decision["flow_id"],
            decision["lead_planner"],
            decision["confidence"],
        )

    async def _set_typing(
        self,
        case_id: str,
        *,
        typing: bool,
        agent_id: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        """落 ``room.typing`` 瞬时事件驱动房间页"正在输入"指示；失败仅记日志。

        typing 事件只由真正拿到锁并进入响应的流程发出——被锁丢弃的消息不会
        产生 typing 事件，因此不会残留永久"正在输入"态（前端另有新鲜度兜底）。
        领域 Agent 直答时携带 agent_id/agent_name，前端据此显示真实响应者，
        而不是一律显示经理"正在输入"。
        """
        name = agent_name or self._manager_display_name()
        payload: dict[str, Any] = {"typing": typing}
        if agent_id:
            payload["agent_id"] = agent_id
        if agent_name:
            payload["agent_name"] = agent_name
        try:
            await self._agentteams.post_case_evidence(
                case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type="room.typing",
                summary=f"{name} 正在输入" if typing else f"{name} 输入结束",
                payload=payload,
            )
        except Exception as exc:  # noqa: BLE001 - typing 指示失败不得影响响应主流程
            logger.bind(case_id=case_id).warning("AgentTeams room typing event failed: {}", exc)

    def _resolve_manager_agent(self) -> tuple[str | None, dict[str, str] | None]:
        """选定房间内 Manager 的 LLM agent，返回 ``(agent_id, fallback_info)``。

        优先取配置项 ``agentteams_manager_agent_id``（默认 agentteams-manager，
        独立部门经理人格）；配置值非法时 Settings 构造直接报错，不做静默回退。
        首选不可用（未加载/未启用/不在能力目录）时按 agent-general → 任意
        planner_eligible 可内部会诊 agent 的顺序降级，并在 fallback_info 中
        带回原因与目标 agent_id，由调用方落 ``room.manager_persona_fallback``
        审计事件——降级只影响能力与人格底座，Manager 话术与展示名不变。
        """
        preferred = get_settings().agentteams_manager_agent_id
        candidates = self._registry.internal_consultation_agents()
        if preferred in candidates:
            return preferred, None
        reason = f"配置的 Manager agent {preferred} 不可用（未加载、未启用或缺少 planner 能力）"
        if _FALLBACK_MANAGER_AGENT_ID in candidates:
            return _FALLBACK_MANAGER_AGENT_ID, {
                "reason": reason,
                "preferred_agent_id": preferred,
                "target_agent_id": _FALLBACK_MANAGER_AGENT_ID,
            }
        capabilities = self._registry.agent_capabilities()
        for role in sorted(capabilities):
            capability = capabilities[role]
            if capability["planner_eligible"] and capability["agent_id"] in candidates:
                target = str(capability["agent_id"])
                return target, {
                    "reason": f"{reason}，且 {_FALLBACK_MANAGER_AGENT_ID} 也不可用",
                    "preferred_agent_id": preferred,
                    "target_agent_id": target,
                }
        return None, None

    def _manager_agent_id(self) -> str | None:
        """仅取 Manager agent id（不写审计）；供不落 LLM 的载荷填充使用。"""
        return self._resolve_manager_agent()[0]

    async def _manager_agent_with_audit(self, case_id: str) -> str | None:
        """选定 Manager agent；发生人格降级时写 ``room.manager_persona_fallback`` 审计事件。"""
        agent_id, fallback = self._resolve_manager_agent()
        if agent_id is None or fallback is None:
            return agent_id
        try:
            await self._agentteams.post_case_evidence(
                case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type="room.manager_persona_fallback",
                summary=(
                    f"Manager 人格降级：由 {fallback['target_agent_id']} 代答，"
                    "话术与展示名保持部门经理身份不变"
                ),
                payload={
                    "reason": fallback["reason"],
                    "preferred_agent_id": fallback["preferred_agent_id"],
                    "target_agent_id": fallback["target_agent_id"],
                    "case_id": case_id,
                },
            )
        except Exception as exc:  # noqa: BLE001 - 审计写入失败不得阻断房间回复
            logger.bind(case_id=case_id).warning(
                "AgentTeams manager persona fallback audit failed: {}", exc
            )
        logger.bind(case_id=case_id).warning(
            "AgentTeams manager persona fallback: {} -> {} ({})",
            fallback["preferred_agent_id"],
            fallback["target_agent_id"],
            fallback["reason"],
        )
        return agent_id

    def _manager_display_name(self) -> str:
        """Manager 称呼的唯一权威来源：manager agent YAML 的 name（bioops-manager 角色标签）。

        YAML 未加载时回退 ``DEFAULT_MANAGER_DISPLAY_NAME``，保证降级期间展示名不变。
        """
        label = self._registry.role_labels().get(MANAGER_ROOM_ROLE) or {}
        name = str(label.get("name") or "").strip()
        return name or DEFAULT_MANAGER_DISPLAY_NAME

    def _ensure_multi_direct_coordination_reply(
        self, reply: str, events: list[dict[str, Any]]
    ) -> str:
        """Guarantee a readable Manager handoff after multiple expert replies.

        The model is instructed to summarize the worker events, but a malformed or stale
        model response must not reintroduce the execution-object template that this path
        deliberately bypassed.
        """
        worker_summaries: list[tuple[str, str, str]] = []
        labels = self._registry.role_labels()
        for event in events:
            if event.get("event_type") != "room.agent_message":
                continue
            payload = self._payload_dict(event)
            nested_raw = payload.get("payload")
            nested = dict(nested_raw) if isinstance(nested_raw, dict) else payload
            if str(nested.get("role") or "") != "worker":
                continue
            agent_id = str(nested.get("agent_id") or "").strip()
            content = str(nested.get("content") or "").strip()
            if not agent_id or not content or any(item[0] == agent_id for item in worker_summaries):
                continue
            label = next(
                (
                    value
                    for value in labels.values()
                    if str(value.get("agent_id") or "") == agent_id
                ),
                {},
            )
            display_name = str(label.get("name") or agent_id).strip()
            if display_name == agent_id and "：" in content:
                inferred_name = content.split("：", 1)[0].strip()
                if inferred_name and len(inferred_name) <= 40:
                    display_name = inferred_name
            worker_summaries.append((agent_id, display_name, content))
        if not worker_summaries:
            return reply

        legacy_template = any(
            marker in reply
            for marker in ("收到你的执行请求", "请上传文件或填写工作区路径")
        )
        has_all_experts = all(
            display_name in reply or agent_id in reply
            for agent_id, display_name, _ in worker_summaries
        )
        result = "" if legacy_template else reply.strip()
        if not has_all_experts or legacy_template:
            summary_lines = [
                f"- {display_name}：{content.replace(chr(10), ' ')[:600]}"
                for _, display_name, content in worker_summaries
            ]
            summary = "两位专家已完成初步协作判断：\n" + "\n".join(summary_lines)
            result = f"{summary}\n\n{result}" if result else summary
        if not any(marker in result for marker in ("是否需要进行实际", "是否需要实际")):
            result = (
                f"{result}\n\n是否需要进行实际的数据分析？如果需要，我会按上述两位专家的分工来组织协作派单。"
            )
        return result[:_ROOM_REPLY_CONTENT_MAX_CHARS]

    async def _manager_preferences(self, requester_ref: str) -> dict[str, Any]:
        try:
            user_id = UUID(str(requester_ref))
        except (ValueError, TypeError, AttributeError):
            return {}
        try:
            result = await self._db.execute(
                select(UserModel.preferences).where(UserModel.id == user_id)
            )
            preferences = result.scalar_one_or_none()
        except Exception as exc:  # noqa: BLE001 - 偏好读取失败不阻断房间回复
            logger.bind(requester_ref=requester_ref).warning(
                "AgentTeams manager preferences lookup failed: {}", exc
            )
            return {}
        if not isinstance(preferences, dict):
            return {}
        agentteams = preferences.get("agentteams")
        return dict(agentteams) if isinstance(agentteams, dict) else {}

    @staticmethod
    def _payload_dict(event: dict[str, Any]) -> dict[str, Any]:
        payload = event.get("payload")
        return dict(payload) if isinstance(payload, dict) else {}

    @classmethod
    def _latest_message_context_refs(
        cls, events: list[dict[str, Any]], latest_content: str
    ) -> list[dict[str, Any]]:
        """取本条 room.user_message 事件携带的 context_refs（供意图判定与 prompt 复用）。"""
        for event in reversed(events):
            if event.get("event_type") != "room.user_message":
                continue
            payload = cls._payload_dict(event)
            inner_raw = payload.get("payload")
            inner = dict(inner_raw) if isinstance(inner_raw, dict) else {}
            event_content = str(inner.get("content") or payload.get("summary") or "").strip()
            if event_content != latest_content:
                continue
            refs = inner.get("context_refs")
            if not isinstance(refs, list):
                return []
            return [dict(ref) for ref in refs if isinstance(ref, dict)]
        return []

    def _is_consultation_reply(
        self,
        case: dict[str, Any],
        events: list[dict[str, Any]],
        content: str,
        execution_outcome: str,
    ) -> bool:
        """判定本轮 Manager 主回路是否纯咨询/闲聊（chat 态）。

        与 ``_maybe_start_chat_execution`` 的门闸口径保持一致：仅无 flow_id、
        仍处 received、且尚无 plan-01 的 Case 才可能进入意图分类；
        execution_outcome 为 none/degraded、Case 尚未提取研究目标（intent 为空）
        且执行意图分类为 CHAT 时，本轮按纯咨询构建问题——不注入 Case 状态与
        接单阶段引导，避免咨询回复被推入接单话锋（"能力咨询误入接单流程"修复 A1）。
        """
        if execution_outcome not in {"none", "degraded"}:
            return False
        if case.get("flow_id") or case.get("status") != "received":
            return False
        if str(case.get("intent") or "").strip():
            # Case 已提取研究目标：房间处于接单/澄清语境，Manager 针对目标要素的
            # 选项式追问是合法接单流程而非咨询误入，保留结构化 ask_user 卡片。
            return False
        work_items = case.get("work_items")
        if isinstance(work_items, list) and any(
            isinstance(item, dict) and item.get("work_item_id") == "plan-01"
            for item in work_items
        ):
            return False
        refs = self._latest_message_context_refs(events, content)
        return classify_execution_intent(content, refs) is ExecutionIntent.CHAT

    @classmethod
    def _build_question(
        cls,
        case: dict[str, Any],
        events: list[dict[str, Any]],
        fallback_content: str,
        preferences: dict[str, Any] | None = None,
        system_note: str | None = None,
        manager_display_name: str | None = None,
        consultation: bool = False,
        memory_context: str | None = None,
        room_message_history: str | None = None,
    ) -> str:
        preferences = preferences or {}
        latest_user_message = fallback_content.strip()
        matching_context_refs: list[str] = []
        for ref in cls._latest_message_context_refs(events, latest_user_message):
            location = str(ref.get("location") or ref.get("id") or "").strip()
            if location:
                matching_context_refs.append(location[:300])
        recent_lines: list[str] = []
        latest_intake: dict[str, Any] = {}
        for event in events[-_CONTEXT_EVENT_SUMMARY_LINES:]:
            payload = cls._payload_dict(event)
            nested_raw = payload.get("payload")
            nested = dict(nested_raw) if isinstance(nested_raw, dict) else payload
            agent_id = str(nested.get("agent_id") or event.get("actor") or "").strip()
            content = str(nested.get("content") or "").strip()
            summary = content or str(payload.get("summary") or "").strip()
            event_type = str(event.get("event_type") or "")
            prefix = f"{agent_id}：" if agent_id and event_type in {
                "room.agent_message",
                "room.agent_stream",
            } else ""
            line = f"- {event_type}: {prefix}{summary}" if summary else f"- {event_type}"
            recent_lines.append(line[:1_200])
        for event in reversed(events):
            if event.get("event_type") != "room.intake_extracted":
                continue
            payload = cls._payload_dict(event)
            inner_raw = payload.get("payload")
            inner = dict(inner_raw) if isinstance(inner_raw, dict) else {}
            candidate = inner.get("intake")
            if isinstance(candidate, dict):
                latest_intake = candidate
            break
        context_block = "\n".join(recent_lines) or "- （暂无历史动态）"
        refs_block = "、".join(matching_context_refs) or "（无显式文件引用）"
        intake_block = (
            "；".join(f"{key}={value}" for key, value in latest_intake.items())
            if latest_intake
            else "（尚未提取到结构化研究设计）"
        )
        # 称呼注入优先级：用户改名偏好 > manager agent YAML 的 display_name
        # （由调用方从注册表读取）> 平台兜底名；不再单独硬编码。
        manager_name = str(
            preferences.get("managerName")
            or manager_display_name
            or DEFAULT_MANAGER_DISPLAY_NAME
        )[:24]
        style = {
            "friendly": "亲切友好：语气自然、有温度，但不使用夸张措辞",
            "concise": "极简高效：先给结论和下一步，减少背景铺陈",
            "professional": "正式专业：表述严谨、结构清晰、术语准确",
        }.get(str(preferences.get("communicationStyle")), "正式专业：表述严谨、结构清晰、术语准确")
        language = "English" if preferences.get("language") == "en-US" else "中文"
        autonomy = (
            "自主模式：对低风险只读分析可主动给出下一步并推进；"
            "真实计算、写入、费用、提交和审批仍必须遵守系统安全闸门"
            if preferences.get("autonomy") == "autonomous"
            else "谨慎模式：涉及执行选择或信息不足时优先说明影响并请求用户确认"
        )
        if consultation:
            # 纯咨询/闲聊专用话术（A1）：不注入 Case 状态与接单阶段引导，
            # 澄清协议替换为"直接作答、禁止 ask_user"。内部状态机语言是管道
            # 不是科学——请求人看到「已接收」只会困惑。
            directive = (
                f"你在 AgentTeams 协作房间中代表「{manager_name}」履行生物信息部门经理职责，"
                "直接回答请求人的最新发言。"
                f"面向用户的自然语言中只能自称「{manager_name}」或「我」；"
                "禁止以英文 Manager、协作室 Manager 或系统 Manager 自称。"
                "必须以‘请求人最新发言’为唯一当前问题，不得重复回答更早的问题。"
                "用中文简洁回答。\n"
                "本轮是纯咨询/闲聊：直接回答请求人的问题即可。"
                "禁止提及 Case 状态、房间状态等内部状态机语言；"
                "不得主动引导进入规划、立项或交付流程——只有当请求人明确提出"
                "研究需求或分析任务时，才讨论后续阶段。\n"
                "澄清协议（强制）：纯咨询直接作答，JSON 信封的 ask_user 字段"
                "必须留空数组，禁止对闲聊/咨询输出结构化追问。\n"
            )
            case_block = (
                f"Case 目标：{str(case.get('intent') or '')[:200]}\n"
                if str(case.get("intent") or "").strip()
                else ""
            )
        else:
            directive = (
                f"你在 AgentTeams 协作房间中代表「{manager_name}」履行生物信息部门经理职责，"
                "直接回答请求人的最新发言。"
                f"面向用户的自然语言中只能自称「{manager_name}」或「我」；"
                "禁止以英文 Manager、协作室 Manager 或系统 Manager 自称。"
                "必须以‘请求人最新发言’为唯一当前问题，不得重复回答更早的问题。"
                "用中文简洁回答；若问题涉及执行中的任务，结合 Case 状态说明进展。"
                "若用户要求基于文件绘图、运行分析或生成产物，必须明确这是计算执行请求，"
                "不得假装已经产出结果；应说明当前 Case 是否与该目标一致，以及下一步会进入"
                "规划、确认、执行和产物交付中的哪个阶段。\n"
                "澄清协议（强制）：若最新发言缺少继续推进所需的关键信息（如输入数据形式、"
                "物种与参考基因组、样本分组与生物学重复、分析目标、交付物），禁止只在 "
                "conclusion 正文里罗列编号问题；必须在 JSON 信封的 ask_user 字段输出结构化"
                "问题数组（最多 5 个），每项形如 "
                '{"question":"...","options":["候选 A","候选 B"]}，options 给 2-4 个可点选'
                "候选（有推荐项时放第一位并以（推荐）标注），无法预设选项的问题 options 留空数组。"
                "使用 ask_user 时 conclusion 只写一句简短引导语，不得重复问题正文；"
                "信息充分、无需澄清时 ask_user 必须留空数组。\n"
            )
            case_block = (
                f"Case 目标：{str(case.get('intent') or '')[:200]}\n"
                f"Case 当前状态：{str(case.get('status') or '')}\n"
                f"已提取研究设计（仅引用其中已有事实，不要重复追问）：{intake_block}\n"
            )
        return (
            directive
            + (f"{system_note}\n" if system_note else "")
            + f"全局回复偏好：称呼自己为「{manager_name}」；沟通语言为{language}；"
            f"沟通风格为{style}；执行偏好为{autonomy}。\n"
            + case_block
            + f"最近房间动态：\n{context_block}\n"
            + (f"{room_message_history}\n" if room_message_history else "")
            + f"本条发言引用文件：{refs_block}\n"
            # L4 读取面记忆注入（M2）：共享层 + Manager 分区，<user_memory> 不可信包装
            + (f"{memory_context}\n" if memory_context else "")
            + f"请求人最新发言：{latest_user_message}"
        )

    async def _build_memory_context(
        self, *, requester_ref: str, agent_id: str, current_message: str
    ) -> str:
        """L4 房间读取面记忆装配（M2）：共享层（profile/preference）+ Manager 分区。

        仅 memory_v2 开启时注入；v2 off 或装配失败返回空串，行为与接入前一致。
        3200 字节预算与 <user_memory> 不可信包装由 build_prompt_context_v2 保证。
        """
        if not get_settings().memory_v2_enabled:
            return ""
        try:
            from cygnusx.application.services.agent_memory_service import AgentMemoryService

            return await AgentMemoryService(self._db).build_prompt_context_v2(
                requester_ref, agent_id, current_message
            )
        except Exception as exc:  # noqa: BLE001 - 记忆装配失败不得阻断房间回复
            # 静默降级必须可观测：operational 级指标计数 + 警告日志
            _l4_inject_degraded.add(1, {"agent_id": agent_id})
            logger.bind(agent_id=agent_id).warning(
                "AgentTeams 房间记忆装配失败，本轮不注入: {}", exc
            )
            return ""
