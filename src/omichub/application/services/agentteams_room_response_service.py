"""房间内用户发言的 Manager 响应回路。

用户在团队协作室发出 ``room.user_message`` 后，由 Celery 任务驱动本服务：
以 readonly_consultation 模式调用 Manager agent（默认 agent-general，
无则回退到任意 planner_eligible 的可会诊 agent），把结论落为
``room.agent_message`` Case 级证据事件——SSE 投影与 Matrix 镜像随之自动生效。

同一 Case 同时只允许一个 pending 响应（Redis 互斥锁）；锁被占用时由任务层
短暂重试，避免连续发言被静默丢弃。LLM 或 Bridge 失败只记 warning，绝不影响
用户发言主流程。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.services.agent_consultation_service import AgentConsultationService
from omichub.application.services.agentteams_capability_registry import (
    AgentTeamsCapabilityRegistry,
    get_agentteams_capability_registry,
)
from omichub.application.services.agentteams_execution_intent import (
    GENERAL_PLAN_CONTRACT,
    detect_execution_intent,
)
from omichub.application.services.agentteams_service import (
    AUTO_CONFIRM_CASES_KEY,
    CASE_LEVEL_WORK_ITEM_ID,
    AgentTeamsService,
)
from omichub.infrastructure.cache.redis_client import get_redis
from omichub.infrastructure.database.models.user import UserModel

ROOM_RESPONSE_LOCK_KEY_PREFIX = "agentteams:room-response:lock:"
ROOM_RESPONSE_LOCK_TTL_SECONDS = 180
_CONTEXT_EVENT_LIMIT = 30
_CONTEXT_EVENT_SUMMARY_LINES = 8
_PREFERRED_MANAGER_AGENT_ID = "agent-general"

_RELEASE_LOCK_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


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
    ) -> None:
        self._db = db
        self._agentteams = agentteams
        self._registry = registry or get_agentteams_capability_registry()
        self._redis_getter = redis_getter
        self._lock_ttl = lock_ttl_seconds

    async def respond(self, case_id: str, requester_ref: str, content: str) -> dict[str, str]:
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
            return await self._respond_locked(case_id, requester_ref, content)
        finally:
            if acquired:
                try:
                    await redis.eval(_RELEASE_LOCK_LUA, 1, lock_key, lock_token)
                except Exception as exc:  # noqa: BLE001
                    logger.bind(case_id=case_id).warning(
                        "AgentTeams room response lock release failed: {}", exc
                    )

    async def _respond_locked(self, case_id: str, requester_ref: str, content: str) -> dict[str, str]:
        try:
            case = await self._agentteams.get_case(case_id, requester_ref)
            # 终态 Case 也允许继续对话（只读会诊回复，不改 Case 状态）。
            events = await self._agentteams.get_case_events(
                case_id, requester_ref, limit=_CONTEXT_EVENT_LIMIT
            )
            event_items = [
                item for item in events.get("events", []) if isinstance(item, dict)
            ]
            preferences = await self._manager_preferences(requester_ref)
            execution_started = await self._maybe_start_chat_execution(
                case_id=case_id,
                requester_ref=requester_ref,
                case=case,
                events=event_items,
                content=content,
                preferences=preferences,
            )
            # 触发成功后 Bridge 侧已推进到 planning_running；用拷贝覆盖快照状态，
            # 避免 Manager 按触发前的 received 快照作答。
            question_case = (
                {**case, "status": "planning_running"} if execution_started else case
            )
            question = self._build_question(
                question_case,
                event_items,
                content,
                preferences,
            )
            agent_id = self._manager_agent_id()
            if agent_id is None:
                logger.bind(case_id=case_id).warning(
                    "AgentTeams room response skipped: no manager agent available"
                )
                return {"status": "skipped_no_manager"}
            await self._set_typing(case_id, typing=True)
            try:
                envelope = await AgentConsultationService(
                    self._db, agentteams_service=self._agentteams
                ).run_consultation(
                    case_id=case_id,
                    agent_id=agent_id,
                    question=question,
                    capability="interpretation",
                    evidence_refs=[],
                    requested_tools=[],
                    requester_ref=requester_ref,
                )
                reply = envelope.conclusion.strip()
                if not reply:
                    return {"status": "failed"}
                await self._agentteams.post_case_evidence(
                    case_id,
                    work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                    event_type="room.agent_message",
                    summary=reply[:200],
                    payload={
                        "content": reply[:4_000],
                        "agent_id": agent_id,
                        "role": "bioops-manager",
                    },
                )
                return {"status": "responded"}
            finally:
                await self._set_typing(case_id, typing=False)
        except Exception as exc:  # noqa: BLE001 - 响应失败不得影响用户发言主流程
            logger.bind(case_id=case_id).warning("AgentTeams room response failed: {}", exc)
            return {"status": "failed"}

    async def _maybe_start_chat_execution(
        self,
        *,
        case_id: str,
        requester_ref: str,
        case: dict[str, Any],
        events: list[dict[str, Any]],
        content: str,
        preferences: dict[str, Any] | None = None,
    ) -> bool:
        """聊天式 Case 命中执行意图时自动启动 planning；返回是否已触发。

        仅对无 flow_id、仍处于 received、且尚无 plan-01 的 Case 生效——flow 型
        Case 的人工审批链路绝不旁路。触发失败只记日志，不影响 Manager 回复。
        若用户偏好为 autonomous，将该 Case 加入自动确认集合，以便进入
        approval_pending 后无需人工审批。
        """
        if case.get("flow_id") or case.get("status") != "received":
            return False
        work_items = case.get("work_items")
        if isinstance(work_items, list) and any(
            isinstance(item, dict) and item.get("work_item_id") == "plan-01"
            for item in work_items
        ):
            return False
        refs = self._latest_message_context_refs(events, content)
        if not detect_execution_intent(content, refs):
            return False
        # Bridge objective 上限 1000 字符：用户原话截断后附通用计划契约尾段。
        objective = f"{content.strip()[:600]}\n\n{GENERAL_PLAN_CONTRACT}"
        try:
            await self._agentteams.start_chat_planning(
                case_id=case_id,
                requester_ref=requester_ref,
                objective=objective,
                context_refs=refs,
            )
        except Exception as exc:  # noqa: BLE001 - 触发失败不得影响回复主流程
            logger.bind(case_id=case_id).warning(
                "AgentTeams chat execution trigger failed: {}", exc
            )
            return False
        if preferences.get("autonomy") == "autonomous":
            try:
                redis = self._redis_getter()
                await redis.sadd(AUTO_CONFIRM_CASES_KEY, case_id)
            except Exception as exc:  # noqa: BLE001
                logger.bind(case_id=case_id).warning(
                    "AgentTeams auto-confirm marking failed: {}", exc
                )
        logger.bind(case_id=case_id).info(
            "AgentTeams chat execution intent detected, planning started"
        )
        return True

    async def _set_typing(self, case_id: str, *, typing: bool) -> None:
        """落 ``room.typing`` 瞬时事件驱动房间页"正在输入"指示；失败仅记日志。

        typing 事件只由真正拿到锁并进入响应的流程发出——被锁丢弃的消息不会
        产生 typing 事件，因此不会残留永久"正在输入"态（前端另有新鲜度兜底）。
        """
        try:
            await self._agentteams.post_case_evidence(
                case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type="room.typing",
                summary="Manager 正在输入" if typing else "Manager 输入结束",
                payload={"typing": typing},
            )
        except Exception as exc:  # noqa: BLE001 - typing 指示失败不得影响响应主流程
            logger.bind(case_id=case_id).warning("AgentTeams room typing event failed: {}", exc)

    def _manager_agent_id(self) -> str | None:
        """Manager agent 选法：优先 agent-general（平台指定的通用 planner），
        否则回退到任意 planner_eligible 且可会诊的 agent。"""
        consultation_agents = self._registry.consultation_agents()
        if _PREFERRED_MANAGER_AGENT_ID in consultation_agents:
            return _PREFERRED_MANAGER_AGENT_ID
        capabilities = self._registry.agent_capabilities()
        for role in sorted(capabilities):
            capability = capabilities[role]
            if capability["planner_eligible"] and capability["agent_id"] in consultation_agents:
                return str(capability["agent_id"])
        return None

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

    @classmethod
    def _build_question(
        cls,
        case: dict[str, Any],
        events: list[dict[str, Any]],
        fallback_content: str,
        preferences: dict[str, Any] | None = None,
    ) -> str:
        preferences = preferences or {}
        latest_user_message = fallback_content.strip()
        matching_context_refs: list[str] = []
        for ref in cls._latest_message_context_refs(events, latest_user_message):
            location = str(ref.get("location") or ref.get("id") or "").strip()
            if location:
                matching_context_refs.append(location[:300])
        recent_lines: list[str] = []
        for event in events[-_CONTEXT_EVENT_SUMMARY_LINES:]:
            payload = cls._payload_dict(event)
            summary = str(payload.get("summary") or "").strip()
            event_type = str(event.get("event_type") or "")
            line = f"- {event_type}: {summary}" if summary else f"- {event_type}"
            recent_lines.append(line[:200])
        context_block = "\n".join(recent_lines) or "- （暂无历史动态）"
        refs_block = "、".join(matching_context_refs) or "（无显式文件引用）"
        manager_name = str(preferences.get("managerName") or "Manager")[:24]
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
        return (
            "你在 AgentTeams 协作房间中扮演 Manager，直接回答请求人的最新发言。"
            "必须以‘请求人最新发言’为唯一当前问题，不得重复回答更早的问题。"
            "用中文简洁回答；若问题涉及执行中的任务，结合 Case 状态说明进展。"
            "若用户要求基于文件绘图、运行分析或生成产物，必须明确这是计算执行请求，"
            "不得假装已经产出结果；应说明当前 Case 是否与该目标一致，以及下一步会进入"
            "规划、确认、执行和产物交付中的哪个阶段。\n"
            f"全局回复偏好：称呼自己为「{manager_name}」；沟通语言为{language}；"
            f"沟通风格为{style}；执行偏好为{autonomy}。\n"
            f"Case 目标：{str(case.get('intent') or '')[:200]}\n"
            f"Case 当前状态：{str(case.get('status') or '')}\n"
            f"最近房间动态：\n{context_block}\n"
            f"本条发言引用文件：{refs_block}\n"
            f"请求人最新发言：{latest_user_message}"
        )
