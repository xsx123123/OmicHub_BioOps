"""L2→L4 升级建议（协作室升级规则，愿景落地 Phase D / 协作室升级方案 Part 3.2）。

权威口径（docs/info/26.8.19/L4愿景落地实施计划.md Phase D）：
1. 用户显式要求（"开协作室 / 正式交付"）→ 必出升级建议卡；
2. 规则判定：命中 Flow 且步骤数 ≥3，或命中能力目录 ``requires_formal_delivery``
   标记 → 建议升级，出建议卡；
3. 其余留在 L2（轻量咨询不进协作室）；
4. 每次决策记录触发条件（可审计），并统计建议/接受/拒绝事件（进入率遥测基础）。

交互形态：只出"建议卡"，绝不自动跳转（愿景风险表：规则不强制）。接受时创建
协作室房间（Case 解耦后房间先于 Case 存在，不直接建 Case），房间首条系统
消息携带结构化上下文摘要，文件引用走 context_refs 协议路径（相对用户工作区
根目录的 projects/... 或 workspace/... 路径，废弃裸 file://{uuid}——
《L4协作室与文件系统融合优化实施手册》改造 3）。

会话状态标记存于 ``ChatSessionModel.sandbox_meta["agentteams_upgrade"]``：
- ``suggested``：已出卡待处理（同会话不重复弹卡）；
- ``dismissed``：用户拒绝（同会话不再弹卡）；
- ``upgraded``：已升级至协作室（L2 会话只读标记，含 room_id）。
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.core.telemetry import get_meter
from omichub.infrastructure.database.models.chat import (
    AgentTeamsRoomModel,
    ChatMessageModel,
    ChatSessionModel,
)

# ===== 契约常量 =====
#: 会话 sandbox_meta 中升级状态的键。
UPGRADE_SESSION_META_KEY = "agentteams_upgrade"
#: 建议卡消息 content_type / SSE chunk type（前端据此渲染卡片）。
UPGRADE_SUGGESTION_MESSAGE_TYPE = "agentteams_upgrade"
#: 房间 origin 取值：来源为 L2 会话升级（AgentTeamsRoomModel.origin 上限 20 字符）。
ROOM_ORIGIN_L2_UPGRADE = "l2_upgrade"
#: 房间首条系统消息的房间级事件类型（schema 与既有房间事件五字段一致）。
ROOM_UPGRADE_CONTEXT_EVENT_TYPE = "room.upgrade_context"

# 规则 ID（写入 matched_rules，每次决策可审计）。
RULE_EXPLICIT_REQUEST = "explicit_request"
RULE_FLOW_STEPS_GTE_3 = "flow_steps_gte_3"
RULE_REQUIRES_FORMAL_DELIVERY = "requires_formal_delivery"

#: 愿景 Phase D 规则 2 的 Flow 步骤数门槛（含边界）。
FLOW_STEPS_UPGRADE_THRESHOLD = 3

_upgrade_meter = get_meter("omichub.agentteams.upgrade")
_upgrade_events = _upgrade_meter.create_counter(
    "agentteams.upgrade.events",
    description="L2→L4 升级建议/接受/拒绝事件计数（L4 进入率遥测基础）",
)


def record_upgrade_event(
    event: str,
    *,
    matched_rules: list[str] | tuple[str, ...] = (),
    detail: str = "",
) -> None:
    """记录一次升级决策事件（suggested/accepted/dismissed/vetoed），容错不抛异常。

    ``detail``（命中词、消息摘要、会话 id 等）只进结构化日志，不进 OTel
    counter 属性——计数维度保持 event + rules 低基数，避免高基数标签爆炸。
    """
    with contextlib.suppress(Exception):
        _upgrade_events.add(
            1,
            {"event": event, "rules": ",".join(matched_rules)},
        )
    logger.info(
        "agentteams upgrade {}: rules={} detail={}",
        event,
        list(matched_rules),
        detail,
    )


# ===== 规则 1：用户显式要求（必出建议卡）=====
# 词表保持窄且面向"请求"：只认"开/用/进协作室、正式交付、多专家协作"这类明确的
# 升级诉求；裸"协作室是什么"这类咨询不命中（避免把功能咨询当成升级请求）。
_EXPLICIT_REQUEST_PATTERN = re.compile(
    "开协作室|用协作室|进协作室|去协作室|创建协作室|正式交付|多专家协作|多智能体协作"
    r"|\bagentteams\b|\bcollaboration room\b",
    re.IGNORECASE,
)

# 轻量咨询一票否决（与 execution intent 同一保守哲学：宁漏勿错）。
# 只作用于规则命中（规则 2/3），不否决规则 1 的显式要求。
# C2 词表收窄：裸"介绍"子串过宽——"把结果介绍给导师""文献介绍"等陈述性
# 用法会被误判为咨询而否决升级建议；只保留明确的"请介绍"请求形态
# （介绍一下/介绍下/详细/简单/做个介绍），漏判代价只是多弹一张建议卡。
_CONSULTATION_VETO_PATTERN = re.compile(
    "是什么|怎么用|如何使用|介绍一下|介绍下|详细介绍|简单介绍|做个介绍"
    "|为什么|能做什么|有哪些|区别"
    r"|\bwhat is\b|\bhow to\b|\bexplain\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class UpgradeDecision:
    """一次升级触发判定结果（未命中任何规则时为 None，不构造本对象）。"""

    matched_rules: tuple[str, ...]
    reason: str
    flow_id: str | None = None
    flow_label: str | None = None
    stage_count: int | None = None


def _match_flow(
    text: str, flows: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """按 trigger_hints 子串匹配（与房间关键词路由同一语义），取命中数最多者。"""
    normalized = text.lower()
    best: tuple[int, dict[str, Any]] | None = None
    for flow in flows:
        hints = [str(hint).lower() for hint in flow.get("trigger_hints") or [] if str(hint).strip()]
        score = sum(1 for hint in hints if hint and hint in normalized)
        if score and (best is None or score > best[0]):
            best = (score, flow)
    return best[1] if best else None


def evaluate_upgrade_trigger(
    content: str,
    *,
    flows: list[dict[str, Any]] | None = None,
    ability_catalog: Any | None = None,
    session_id: str | None = None,
) -> UpgradeDecision | None:
    """按愿景 Phase D 规则清单判定是否应出升级建议卡。

    规则（任一命中即建议，matched_rules 记录全部命中项）：
    1. ``explicit_request``：用户显式要求开协作室/正式交付（必出，不受咨询否决影响）；
    2. ``flow_steps_gte_3``：消息命中某 Flow 的 trigger_hints 且该 Flow 阶段数 ≥3；
    3. ``requires_formal_delivery``：命中 Flow 的 actor 在能力目录中标记需要正式交付。
    规则 2/3 命中咨询否决词时不出卡（轻量咨询留在 L2）；否决本身记
    ``vetoed`` 遥测事件（C2：误判可被发现与回溯）。
    """
    text = (content or "").strip()
    if not text:
        return None
    if _EXPLICIT_REQUEST_PATTERN.search(text):
        return UpgradeDecision(
            matched_rules=(RULE_EXPLICIT_REQUEST,),
            reason="你明确要求通过协作室进行正式协作交付，建议升级为协作室协作。",
        )
    veto_match = _CONSULTATION_VETO_PATTERN.search(text)
    if veto_match:
        record_upgrade_event(
            "vetoed",
            matched_rules=("consultation_veto",),
            detail=(
                f"matched={veto_match.group(0)[:30]} "
                f"msg={text[:80]} session={session_id or '-'}"
            ),
        )
        return None

    if flows is None:
        from omichub.application.services.agentteams_capability_registry import (
            get_agentteams_capability_registry,
        )

        flows = get_agentteams_capability_registry().flow_router_catalog()
    matched_flow = _match_flow(text, flows)
    if matched_flow is None:
        return None
    if ability_catalog is None:
        from omichub.infrastructure.config.agent_ability_catalog import agent_ability_catalog

        ability_catalog = agent_ability_catalog

    rules: list[str] = []
    reasons: list[str] = []
    flow_id = str(matched_flow.get("flow_id") or "") or None
    flow_label = str(matched_flow.get("display_name") or flow_id or "")
    stage_count = matched_flow.get("stage_count")
    stage_count = int(stage_count) if isinstance(stage_count, int) else None

    if stage_count is not None and stage_count >= FLOW_STEPS_UPGRADE_THRESHOLD:
        rules.append(RULE_FLOW_STEPS_GTE_3)
        reasons.append(
            f"该需求命中「{flow_label}」流程（{stage_count} 个专业阶段），"
            "属于多步骤真实计算，建议升级为协作室协作。"
        )
    ability = ability_catalog.get(str(matched_flow.get("actor") or ""))
    if isinstance(ability, dict) and ability.get("requires_formal_delivery"):
        rules.append(RULE_REQUIRES_FORMAL_DELIVERY)
        reasons.append(
            f"该需求命中「{flow_label}」领域，其能力目录标记为需要正式交付"
            "（审批与质量闸门），建议升级为协作室协作。"
        )
    if not rules:
        return None
    return UpgradeDecision(
        matched_rules=tuple(rules),
        reason="".join(reasons),
        flow_id=flow_id,
        flow_label=flow_label or None,
        stage_count=stage_count,
    )


# ===== 会话状态标记 =====


def session_upgrade_state(sandbox_meta: dict[str, Any] | None) -> dict[str, Any]:
    """读取会话升级标记（无标记返回空 dict）。"""
    marker = (sandbox_meta or {}).get(UPGRADE_SESSION_META_KEY)
    return dict(marker) if isinstance(marker, dict) else {}


def upgrade_suggestion_allowed(sandbox_meta: dict[str, Any] | None) -> bool:
    """是否允许在本会话出升级建议卡。

    抑制条件：已出卡待处理（suggested）、已拒绝（dismissed）、已升级（upgraded）、
    会话已有进行中的 AgentTeams Case（既有的 chat→Case 入口已接管）。
    """
    marker = session_upgrade_state(sandbox_meta)
    if marker.get("status") in {"suggested", "dismissed", "upgraded"}:
        return False
    meta = sandbox_meta or {}
    statuses = dict(meta.get("agentteams_case_status") or {})
    for case_id in meta.get("agentteams_case_ids") or []:
        if isinstance(case_id, str) and statuses.get(case_id) not in {"closed", "cancelled"}:
            return False
    return True


# ===== 建议卡 =====

#: 建议卡上向用户说明的"协作室将接管什么"。
UPGRADE_TAKEOVER_ITEMS: tuple[str, ...] = (
    "多领域专家分工与协作执行",
    "正式分析流程（多阶段真实计算）",
    "人工审批与质量闸门",
    "可审计的过程记录与交付物",
)


def build_upgrade_suggestion(decision: UpgradeDecision, *, session_id: str) -> dict[str, Any]:
    """构造建议卡 payload（消息 metadata 与 SSE chunk 共用同一 schema）。"""
    return {
        "kind": "agentteams_upgrade_suggestion",
        "suggestion_id": uuid4().hex,
        "source_session_id": session_id,
        "matched_rules": list(decision.matched_rules),
        "reason": decision.reason,
        "flow_id": decision.flow_id,
        "flow_label": decision.flow_label,
        "stage_count": decision.stage_count,
        "takeover": list(UPGRADE_TAKEOVER_ITEMS),
        "actions": ["accept", "dismiss"],
        "created_at": datetime.now(UTC).isoformat(),
    }


def suggestion_message_text(card: dict[str, Any]) -> str:
    """建议卡消息的正文（无前端卡片渲染时的可读降级文本）。"""
    return (
        f"{card['reason']}\n"
        "接受后我会创建协作室房间，并把当前会话的目标、已确认参数和引用文件"
        "一并移交，无需你重新描述；你也可以拒绝，本会话将不再重复提示。"
    )


# ===== 上下文移交摘要 =====

_ATTACHMENT_URL_MARKER = "/chat-upload/"
_SUMMARY_TEXT_LIMIT = 200
_MAX_CLARIFIED_PAIRS = 5
_MAX_CONTEXT_REFS = 20


def _attachment_context_refs(messages: list[ChatMessageModel]) -> list[dict[str, Any]]:
    """从用户消息附件提取 context_refs 协议路径引用。

    聊天附件落盘于 ``workspace/chat-uploads/{file_id}.s{session}{suffix}``，
    协议路径为相对用户工作区根目录的 ``workspace/chat-uploads/...``
    （《L4文件系统融合手册》改造 3 口径；裸 file://{uuid} 已废弃）。
    无法还原协议路径的附件（无 url）直接跳过，不生成不可解析引用。
    """
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for message in messages:
        if message.role != "user":
            continue
        for attachment in (message.metadata_json or {}).get("attachments") or []:
            if not isinstance(attachment, dict):
                continue
            url = str(attachment.get("url") or "")
            if _ATTACHMENT_URL_MARKER not in url:
                continue
            filename = url.rsplit("/", 1)[-1].strip()
            if not filename:
                continue
            location = f"workspace/chat-uploads/{filename}"
            if location in seen:
                continue
            seen.add(location)
            refs.append(
                {
                    "kind": "file",
                    "id": str(attachment.get("file_id") or filename),
                    "location": location,
                    "name": str(attachment.get("name") or filename),
                }
            )
            if len(refs) >= _MAX_CONTEXT_REFS:
                return refs
    return refs


def _clarified_conclusions(messages: list[ChatMessageModel]) -> list[dict[str, str]]:
    """提取已澄清结论：助手提问（含 ?/？）紧随其后用户答复的问答对。"""
    pairs: list[dict[str, str]] = []
    ordered = list(messages)
    for index, message in enumerate(ordered[:-1]):
        if message.role != "assistant":
            continue
        question = (message.content or "").strip()
        if not question or ("?" not in question and "？" not in question):
            continue
        reply = ordered[index + 1]
        if reply.role != "user" or not (reply.content or "").strip():
            continue
        pairs.append(
            {
                "question": question[:_SUMMARY_TEXT_LIMIT],
                "answer": (reply.content or "").strip()[:_SUMMARY_TEXT_LIMIT],
            }
        )
        if len(pairs) >= _MAX_CLARIFIED_PAIRS:
            break
    return pairs


def build_upgrade_context_summary(
    session: ChatSessionModel,
    messages: list[ChatMessageModel],
    *,
    matched_rules: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """构造移交协作室的结构化上下文摘要（目标/已确认参数/引用文件/已澄清结论）。"""
    user_messages = [m for m in messages if m.role == "user" and (m.content or "").strip()]
    objective = (user_messages[-1].content or "").strip()[:500] if user_messages else ""
    if not objective:
        objective = (session.title or "").strip()[:200]
    context_refs = _attachment_context_refs(messages)
    # 协议可解析性预检：只移交通过预检的引用（不带 workspace_root 的协议校验）。
    if context_refs:
        from omichub.application.services.agentteams_context_refs import check_context_refs

        checks = check_context_refs(context_refs)
        context_refs = [
            ref for ref, check in zip(context_refs, checks, strict=True) if check.readable
        ]
    confirmed_parameters: dict[str, Any] = {}
    if session.project_id:
        confirmed_parameters["project_id"] = session.project_id
    if session.mode:
        confirmed_parameters["session_mode"] = session.mode
    return {
        "objective": objective,
        "confirmed_parameters": confirmed_parameters,
        "context_refs": context_refs,
        "clarified_conclusions": _clarified_conclusions(messages),
        "source_session_id": session.session_id,
        "matched_rules": [str(rule) for rule in matched_rules],
    }


# ===== 接受 / 拒绝编排 =====


@dataclass
class AgentTeamsUpgradeService:
    """L2 会话升级决策的编排：接受建房移交上下文 / 拒绝记 dismissed。"""

    db: AsyncSession
    agentteams: Any  # AgentTeamsService；测试可注入同形 stub
    room_service_factory: Any | None = field(default=None)

    def _room_service(self) -> Any:
        if self.room_service_factory is not None:
            return self.room_service_factory(self.db, self.agentteams)
        from omichub.application.services.agentteams_room_service import (
            AgentTeamsRoomService,
        )

        return AgentTeamsRoomService(self.db, self.agentteams)

    async def accept(self, session: ChatSessionModel, user_id: str) -> dict[str, Any]:
        """接受升级：创建协作室房间（不建 Case）→ 首条系统消息带上下文摘要 →
        L2 会话写入"已升级至协作室"只读标记。重复接受幂等返回既有房间。"""
        meta = dict(session.sandbox_meta or {})
        marker = session_upgrade_state(meta)
        if marker.get("status") == "upgraded" and marker.get("room_id"):
            return {
                "status": "upgraded",
                "room_id": str(marker["room_id"]),
                "idempotent_replay": True,
            }
        matched_rules = [str(rule) for rule in marker.get("matched_rules") or []]

        result = await self.db.execute(
            select(ChatMessageModel)
            .where(ChatMessageModel.session_id == session.session_id)
            .order_by(ChatMessageModel.created_at)
        )
        messages = list(result.scalars().all())
        summary = build_upgrade_context_summary(session, messages, matched_rules=matched_rules)

        rooms = self._room_service()
        room: AgentTeamsRoomModel = await rooms.create_room(
            owner_id=user_id,
            title=session.title,
            origin=ROOM_ORIGIN_L2_UPGRADE,
        )
        # 反向链接：房间记录来源 L2 会话 id（origin 字段仅 20 字符，放不下 session id）。
        room.origin_ref = session.session_id
        meta[UPGRADE_SESSION_META_KEY] = {
            "status": "upgraded",
            "room_id": room.room_id,
            "suggestion_id": marker.get("suggestion_id"),
            "matched_rules": matched_rules,
            "upgraded_at": datetime.now(UTC).isoformat(),
        }
        session.sandbox_meta = meta
        session.updated_at = datetime.now(UTC)
        await self.db.flush()

        try:
            await rooms.post_system_message(
                room,
                event_type=ROOM_UPGRADE_CONTEXT_EVENT_TYPE,
                summary=f"从 L2 会话 {session.session_id} 升级：{summary['objective'][:120]}",
                payload=summary,
            )
        except Exception as exc:  # noqa: BLE001 - 摘要事件失败不影响已完成的升级
            logger.bind(room_id=room.room_id).warning(
                "AgentTeams upgrade context event failed: {}", exc
            )
        record_upgrade_event("accepted", matched_rules=matched_rules)
        return {
            "status": "upgraded",
            "room_id": room.room_id,
            "context_summary": summary,
        }

    async def dismiss(self, session: ChatSessionModel) -> dict[str, Any]:
        """拒绝升级：记录 dismissed，同一会话不再重复弹卡。"""
        from omichub.core.exceptions import BusinessError

        meta = dict(session.sandbox_meta or {})
        marker = session_upgrade_state(meta)
        if marker.get("status") == "upgraded":
            raise BusinessError("会话已升级至协作室，无需拒绝")
        if marker.get("status") != "suggested":
            raise BusinessError("当前会话没有待处理的升级建议")
        matched_rules = [str(rule) for rule in marker.get("matched_rules") or []]
        meta[UPGRADE_SESSION_META_KEY] = {
            "status": "dismissed",
            "suggestion_id": marker.get("suggestion_id"),
            "matched_rules": matched_rules,
            "dismissed_at": datetime.now(UTC).isoformat(),
        }
        session.sandbox_meta = meta
        session.updated_at = datetime.now(UTC)
        await self.db.flush()
        record_upgrade_event("dismissed", matched_rules=matched_rules)
        return {"status": "dismissed"}


__all__ = [
    "FLOW_STEPS_UPGRADE_THRESHOLD",
    "ROOM_ORIGIN_L2_UPGRADE",
    "ROOM_UPGRADE_CONTEXT_EVENT_TYPE",
    "RULE_EXPLICIT_REQUEST",
    "RULE_FLOW_STEPS_GTE_3",
    "RULE_REQUIRES_FORMAL_DELIVERY",
    "UPGRADE_SESSION_META_KEY",
    "UPGRADE_SUGGESTION_MESSAGE_TYPE",
    "UPGRADE_TAKEOVER_ITEMS",
    "AgentTeamsUpgradeService",
    "UpgradeDecision",
    "build_upgrade_context_summary",
    "build_upgrade_suggestion",
    "evaluate_upgrade_trigger",
    "record_upgrade_event",
    "session_upgrade_state",
    "suggestion_message_text",
    "upgrade_suggestion_allowed",
]
