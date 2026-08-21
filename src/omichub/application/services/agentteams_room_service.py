"""协作室房间（轻量会话实体）的 CRUD 与立项确认编排（会话-工单解耦 Part 2）。

核心语义：
- 房间是持久的轻量会话实体，先于 Case 存在；纯聊天/澄清阶段只有房间。
- 房间级事件流承载于 Bridge 的 room 命名空间记录（``room-<room_id>``），
  事件 schema 与 Case 事件完全一致（五字段），经同一 events 接口拉取。
- 意图为 execute 时不直接建 Case：先落"立项确认卡"（``room.proposal_confirm``
  房间级事件 + 房间行的 pending proposal），用户确认后才创建 Case 并回写绑定。
- Case 终态（closed/delivery_ready/cancelled）后房间可继续对话；新的 execute
  意图给"基于上一 Case 继续（关联引用 source_case_id）还是新建工单"选择卡。

审批/质控/契约/审计仍只在 Case 存在后激活，本模块不改任何 Case 内逻辑。
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.services.agentteams_audit_events import (
    event_stream_sort_key,
    redact_confirm_token,
)
from omichub.application.services.agentteams_capability_registry import (
    get_agentteams_capability_registry,
)
from omichub.application.services.agentteams_service import (
    CASE_LEVEL_WORK_ITEM_ID,
    AgentTeamsService,
    room_namespace_case_id,
)
from omichub.application.services.flow_registry import get_flow_registry
from omichub.application.services.project_service import ProjectService
from omichub.core.config import get_settings
from omichub.core.exceptions import AuthorizationError, BusinessError
from omichub.infrastructure.database.models.chat import AgentTeamsRoomModel

# 立项确认卡房间级事件类型：payload 契约见 build_room_proposal / _emit_case_proposal。
ROOM_PROPOSAL_EVENT_TYPE = "room.proposal_confirm"
# 立项确认完成后回写绑定的房间级事件。
ROOM_CASE_BOUND_EVENT_TYPE = "room.case_bound"
# 立项确认卡三选项；followup 卡（终态后再立项）为 continue/new/cancel。
PROPOSAL_OPTIONS_NEW_CASE = ["confirm", "modify", "cancel"]
PROPOSAL_OPTIONS_FOLLOWUP = ["continue", "new", "cancel"]


def build_room_proposal(
    *,
    proposal_kind: str,
    content: str,
    route_decision: dict[str, Any],
    context_refs: list[dict[str, Any]],
    source_case_id: str | None,
) -> dict[str, Any]:
    """构造待确认立项卡（房间行 ``proposal`` JSONB 的存储结构）。

    ``token`` 是一次性确认令牌：confirm-proposal 端点凭它原子消费，
    重复/并发确认不会重复建 Case。
    """
    objective = content.strip()[:600]
    return {
        "proposal_kind": proposal_kind,  # new_case | followup
        "token": secrets.token_urlsafe(24),
        "status": "pending",  # pending | consumed | cancelled
        "objective": objective,
        "flow_id": route_decision.get("flow_id"),
        "flow_label": route_decision.get("flow_label"),
        "lead_planner": route_decision.get("lead_planner"),
        "route_path": route_decision.get("path"),
        "participants": list(route_decision.get("participants") or []),
        "estimated_stages": list(route_decision.get("estimated_stages") or []),
        "confidence": route_decision.get("confidence"),
        "origin_content": objective,
        "context_refs": [dict(ref) for ref in context_refs if isinstance(ref, dict)],
        "source_case_id": source_case_id,
        "created_at": datetime.now(UTC).isoformat(),
    }


async def persist_room_proposal(
    db: AsyncSession, room: AgentTeamsRoomModel, proposal: dict[str, Any]
) -> None:
    """把立项卡写到房间行（同一房间同时只有一张 pending 卡，新卡覆盖旧卡）。"""
    room.proposal = proposal
    await db.flush()


def proposal_project_name(objective: str, room_title: str) -> str:
    """立项 Case 的项目名：与旧直建路径前端 ``buildCaseProjectName`` 同一口径。

    取需求文本前 30 个字符、收敛空白、剥除目录名非法字符；需求为空时退到
    房间标题，再兜底 ``agentteams-case``。
    """
    name = " ".join(objective.split())
    for char in '/\\:*?"<>|':
        name = name.replace(char, "")
    name = name.strip()[:30].strip()
    if name:
        return name
    fallback = " ".join(room_title.split())[:30].strip()
    return fallback or "agentteams-case"


def _project_ref_from(context_refs: list[dict[str, Any]]) -> tuple[str, str | None] | None:
    """从 context_refs 提取首个合法 kind=project 引用的 (project_id, project_name)。"""
    for ref in context_refs:
        if ref.get("kind") != "project":
            continue
        project_id = str(ref.get("id") or "").strip()
        try:
            UUID(project_id)
        except ValueError:
            continue
        meta = ref.get("meta") if isinstance(ref.get("meta"), dict) else {}
        return project_id, str(meta.get("project_name") or "").strip() or None
    return None


def _assert_flow_allowed_for_room_case(flow_id: str) -> None:
    """与直接建 Case 端点同一口径：flow 白名单 + 存在可用 active Agent。"""
    settings = get_settings()
    configured = {
        item.strip() for item in settings.agentteams_chat_flow_whitelist.split(",") if item.strip()
    }
    if flow_id not in configured | get_flow_registry().bridge_flow_ids():
        raise BusinessError("该流程不在 AgentTeams Case 白名单中")
    if get_agentteams_capability_registry().agent_for_flow(flow_id) is None:
        raise BusinessError("该流程没有可用的 active Agent，无法创建协作 Case")


class AgentTeamsRoomService:
    """协作室房间的 CRUD、消息路由、事件聚合与立项确认。"""

    def __init__(self, db: AsyncSession, agentteams: AgentTeamsService) -> None:
        self._db = db
        self._agentteams = agentteams

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    async def create_room(
        self, *, owner_id: str, title: str | None = None, origin: str = "manual"
    ) -> AgentTeamsRoomModel:
        """创建房间：主库行 + Bridge 房间命名空间记录 +（best-effort）Matrix 房间。"""
        if not self._agentteams.available:
            raise BusinessError("Agent 协作中心尚未接通")
        room = AgentTeamsRoomModel(
            room_id=uuid4().hex,
            owner_id=owner_id,
            title=(title or "").strip()[:200] or "协作室会话",
            origin=origin.strip()[:20] or "manual",
        )
        self._db.add(room)
        await self._db.flush()
        await self._agentteams.create_room_namespace(
            room_id=room.room_id, title=room.title, requester_ref=owner_id
        )
        # Matrix 建房复用 Case 建房链路：room.created 证据落房间命名空间事件流，
        # bridge 房间镜像钩子据此把房间级事件镜像进 Matrix；失败降级为纯事件流模式。
        matrix_room = await self._agentteams.provision_case_room(
            room_namespace_case_id(room.room_id), requester_ref=owner_id
        )
        if matrix_room and matrix_room.get("room_id"):
            room.matrix_room_id = str(matrix_room["room_id"])
            await self._db.flush()
            # BUG-E2E-01：updated_at 的 onupdate=func.now() 使该属性在 UPDATE flush
            # 后被 expire；端点 _room_payload 在 async 上下文同步读列会触发懒加载
            # IO（MissingGreenlet → 500）。显式 refresh 把所有列重新加载为已加载态。
            await self._db.refresh(room)
        return room

    async def list_rooms(self, owner_id: str) -> list[AgentTeamsRoomModel]:
        result = await self._db.scalars(
            select(AgentTeamsRoomModel)
            .where(AgentTeamsRoomModel.owner_id == owner_id)
            .order_by(AgentTeamsRoomModel.updated_at.desc())
        )
        return list(result)

    async def get_room(self, room_id: str, owner_id: str) -> AgentTeamsRoomModel:
        room = await self._db.scalar(
            select(AgentTeamsRoomModel).where(AgentTeamsRoomModel.room_id == room_id)
        )
        if room is None:
            raise BusinessError("协作室房间不存在")
        if room.owner_id != owner_id:
            raise AuthorizationError("无权访问该协作室房间")
        return room

    # ------------------------------------------------------------------
    # 房间消息与事件流
    # ------------------------------------------------------------------
    async def post_room_message(
        self,
        room: AgentTeamsRoomModel,
        requester_ref: str,
        content: str,
        *,
        context_refs: list[dict[str, str]] | None = None,
        client_message_id: str | None = None,
    ) -> dict[str, Any]:
        """记录一条用户发言：未立项落房间命名空间流，已绑定落 Case 事件流。"""
        stream_case_id = room.case_id or room_namespace_case_id(room.room_id)
        return await self._agentteams.post_room_message(
            stream_case_id,
            requester_ref,
            content,
            context_refs=context_refs,
            client_message_id=client_message_id,
        )

    async def get_room_events(
        self,
        room: AgentTeamsRoomModel,
        requester_ref: str,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """聚合房间视图事件：房间命名空间流 +（已绑定时）Case 流，按
        ``(recorded_at, event_id)`` 归并（与 audit-chain 共用
        ``event_stream_sort_key``，同一批事件两视图顺序一致）。

        事件结构与既有 Case 事件 schema 完全一致。游标为复合游标
        ``ns:<event_id>|case:<event_id>``（每条流各自"已读到的最后一条"），
        对前端不透明。两流各取 limit 条归并后**截断到 limit**，游标按截断后
        实际保留的各流最后一条重算——被截掉的事件下一页从各流新游标续拉，
        全程不重不漏（复审清单 A2）。
        """
        ns_cursor, case_cursor = self._parse_room_cursor(cursor)
        streams: list[tuple[str, list[dict[str, Any]]]] = []
        ns_events = await self._fetch_stream_page(
            room_namespace_case_id(room.room_id), requester_ref, cursor=ns_cursor, limit=limit
        )
        streams.append(("ns", ns_events))
        case_events: list[dict[str, Any]] = []
        if room.case_id:
            case_events = await self._fetch_stream_page(
                room.case_id, requester_ref, cursor=case_cursor, limit=limit
            )
            streams.append(("case", case_events))
        merged = [(stream, event) for stream, events in streams for event in events]
        merged.sort(key=lambda item: event_stream_sort_key(item[1]))
        kept = merged[:limit]
        # 游标重算：每流取"页内最长保留前缀"的最后一条（流内顺序遍历，遇到
        # 第一条被截掉的事件即停），保证被截事件下一页必被续拉（不重不漏）。
        kept_ids = {str(event.get("event_id") or "") for _, event in kept}
        lasts = {"ns": ns_cursor or "", "case": case_cursor or ""}
        for stream, events in streams:
            for event in events:
                event_id = str(event.get("event_id") or "")
                if not event_id or event_id not in kept_ids:
                    break
                lasts[stream] = event_id
        # B1：confirm_token 写入后即全出口脱敏（含 pending 卡）；存活 token 只存
        # 房间行 DB 字段，不再经事件流分发。
        events = [redact_confirm_token(event) for _, event in kept]
        # BUG-E2E-09 终止条件：本页保留数 < limit 说明两流各返不足 limit 条、
        # 均已耗尽（被截事件只在保留数 == limit 时存在），游标清空让调用方判停；
        # 否则按截断后保留的各流最后一条推进游标（A2 不重不漏语义不变）。
        next_cursor = (
            None if len(kept) < limit else f"ns:{lasts['ns']}|case:{lasts['case']}"
        )
        return {
            "room_id": room.room_id,
            "case_id": room.case_id,
            "events": events,
            "next_cursor": next_cursor,
        }

    async def stream_room_events(
        self,
        room: AgentTeamsRoomModel,
        requester_ref: str,
        *,
        cursor: str | None = None,
        watch_seconds: int = 60,
    ) -> AsyncIterator[dict[str, Any]]:
        """轮询式聚合事件流（与 Bridge 原生 SSE 同语义的有界流）。"""
        next_cursor = cursor
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(1, min(watch_seconds, 60))
        while loop.time() < deadline:
            page = await self.get_room_events(room, requester_ref, cursor=next_cursor, limit=100)
            for event in page["events"]:
                yield event
            next_cursor = str(page.get("next_cursor") or "") or next_cursor
            await asyncio.sleep(0.5)

    @staticmethod
    def _parse_room_cursor(cursor: str | None) -> tuple[str | None, str | None]:
        if not cursor:
            return None, None
        ns_cursor: str | None = None
        case_cursor: str | None = None
        for part in cursor.split("|"):
            key, _, value = part.partition(":")
            if key == "ns":
                ns_cursor = value or None
            elif key == "case":
                case_cursor = value or None
        return ns_cursor, case_cursor

    async def _fetch_stream_page(
        self, case_id: str, requester_ref: str, *, cursor: str | None, limit: int
    ) -> list[dict[str, Any]]:
        page = await self._agentteams.get_case_events(
            case_id, requester_ref, cursor=cursor, limit=limit
        )
        return [event for event in page.get("events", []) if isinstance(event, dict)]

    async def _post_room_event(
        self,
        room: AgentTeamsRoomModel,
        event_type: str,
        summary: str,
        payload: dict[str, Any],
    ) -> None:
        """落一条房间级事件（房间命名空间流）。"""
        await self._agentteams.post_case_evidence(
            room_namespace_case_id(room.room_id),
            work_item_id=CASE_LEVEL_WORK_ITEM_ID,
            event_type=event_type,
            summary=summary,
            payload=payload,
        )

    async def post_system_message(
        self,
        room: AgentTeamsRoomModel,
        *,
        event_type: str,
        summary: str,
        payload: dict[str, Any],
    ) -> None:
        """向房间写一条系统消息（房间级事件流）。

        供房间生命周期外的系统注入使用（如 L2→L4 升级移交的首条上下文摘要），
        事件 schema 与既有房间事件五字段一致。
        """
        await self._post_room_event(room, event_type, summary, payload)

    # ------------------------------------------------------------------
    # 立项确认
    # ------------------------------------------------------------------
    async def confirm_proposal(
        self,
        room: AgentTeamsRoomModel,
        requester_ref: str,
        *,
        confirm_token: str | None = None,
        decision: str,
        followup_mode: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """消费立项确认卡：confirm 建 Case 并绑定；modify/cancel 关闭卡片。

        幂等与并发：先按 pending 状态（带 token 时连 token 一起）原子更新消费，
        未命中即"令牌无效或已使用"；房间已绑定 Case 时重复确认幂等返回既有绑定；
        建 Case 失败会把提案回滚为 pending（可重试），房间保持未绑定的一致状态。

        confirm_token 口径（复审清单 B1）：token 不再经事件流分发，owner 身份 +
        房间存在 pending 立项卡即视为确认意图；token 退化为可选的 API 级
        防重放/幂等 nonce——携带则必须比对通过，不带则仅凭 owner+pending 消费。
        """
        if decision not in {"confirm", "modify", "cancel"}:
            raise BusinessError("不支持的立项确认操作")
        # B3：消费一次性 token 前的显式 owner 断言（get_room 已强制 owner，
        # 此处再断言一次并落审计，防御上层绕过）。
        if room.owner_id != requester_ref:
            raise AuthorizationError("只有房间所有者可消费立项确认令牌")
        if room.case_id:
            return {
                "status": "already_bound",
                "case_id": room.case_id,
                "idempotent_replay": True,
            }
        proposal = dict(room.proposal or {})
        token = str(proposal.get("token") or "")
        if (
            proposal.get("status") != "pending"
            or not token
            or (confirm_token and not hmac.compare_digest(token, confirm_token))
        ):
            # B3：令牌无效/已使用的拒绝动作也落审计（actor=owner），便于取证。
            try:
                await self._post_room_event(
                    room,
                    "room.proposal_confirm_rejected",
                    "立项确认令牌无效或已使用",
                    {"actor": requester_ref, "decision": decision},
                )
            except Exception as exc:  # noqa: BLE001 - 拒绝审计失败不影响拒绝语义
                logger.bind(room_id=room.room_id).warning(
                    "AgentTeams room proposal rejection audit failed: {}", exc
                )
            raise BusinessError("立项确认令牌无效或已使用")
        if decision in {"modify", "cancel"}:
            await self._close_proposal(
                room,
                proposal,
                requester_ref=requester_ref,
                note=note,
                event_type="room.proposal_modify_requested"
                if decision == "modify"
                else "room.proposal_cancelled",
                summary=(
                    "用户要求调整立项内容，请补充说明"
                    if decision == "modify"
                    else "用户取消了本次立项"
                ),
            )
            return {"status": "modify_requested" if decision == "modify" else "cancelled"}
        # confirm：followup 卡需确认是"基于上一 Case 继续"还是"新建工单"。
        source_case_id: str | None = None
        if proposal.get("proposal_kind") == "followup":
            mode = followup_mode or "continue"
            if mode not in {"continue", "new"}:
                raise BusinessError("不支持的继续方式")
            if mode == "continue":
                source_case_id = str(proposal.get("source_case_id") or "") or None
        consumed = {
            **proposal,
            "status": "consumed",
            "consumed_at": datetime.now(UTC).isoformat(),
            "source_case_id": source_case_id,
        }
        consume_stmt = (
            update(AgentTeamsRoomModel)
            .where(AgentTeamsRoomModel.id == room.id)
            .where(AgentTeamsRoomModel.proposal["status"].astext == "pending")
        )
        if confirm_token:
            # 携带 token 时连 token 一起做原子比对（可选的二次校验 nonce）。
            consume_stmt = consume_stmt.where(
                AgentTeamsRoomModel.proposal["token"].astext == confirm_token
            )
        result = await self._db.execute(consume_stmt.values(proposal=consumed))
        if getattr(result, "rowcount", 0) != 1:
            # 并发双确认：原子更新落败方不直接报错——刷新房间后若已被胜出方
            # 绑定 Case，按幂等口径返回首次结果（任务书 Part 0.2：并发/双击/
            # 重试下第二次确认返回首次结果，绝不重复建 Case）。
            with contextlib.suppress(Exception):
                # 刷新失败按原拒绝语义处理
                await self._db.refresh(room)
            if room.case_id:
                return {
                    "status": "already_bound",
                    "case_id": room.case_id,
                    "idempotent_replay": True,
                }
            raise BusinessError("立项确认令牌无效或已使用")
        room.proposal = consumed
        try:
            case = await self._create_confirmed_case(
                room, requester_ref, proposal, source_case_id
            )
        except Exception:
            # 建单失败可重试：提案回滚 pending，房间保持未绑定。
            room.proposal = proposal
            await self._db.flush()
            raise
        room.case_id = str(case["case_id"])
        await self._db.flush()
        await self._agentteams.bind_case_room(
            room.case_id,
            room_id=room.room_id,
            matrix_room_id=room.matrix_room_id,
            requester_ref=requester_ref,
        )
        try:
            await self._post_room_event(
                room,
                ROOM_CASE_BOUND_EVENT_TYPE,
                "立项已确认，协作 Case 创建完成",
                {
                    "case_id": room.case_id,
                    "source_case_id": source_case_id,
                    # B3：确认动作的审计 actor 为房间 owner（token 消费者）。
                    "actor": requester_ref,
                    # 指回立项确认卡事件，与澄清答复的 answer_to_event_id 口径统一。
                    "answer_to_event_id": str(proposal.get("card_event_id") or "") or None,
                },
            )
        except Exception as exc:  # noqa: BLE001 - 绑定事件失败不影响已完成的建单
            logger.bind(room_id=room.room_id).warning(
                "AgentTeams room case_bound event failed: {}", exc
            )
        return {
            "status": "confirmed",
            "case_id": room.case_id,
            "source_case_id": source_case_id,
        }

    async def _close_proposal(
        self,
        room: AgentTeamsRoomModel,
        proposal: dict[str, Any],
        *,
        requester_ref: str,
        note: str | None,
        event_type: str,
        summary: str,
    ) -> None:
        room.proposal = {
            **proposal,
            "status": "cancelled",
            "closed_at": datetime.now(UTC).isoformat(),
            "note": (note or "")[:1_000],
        }
        await self._db.flush()
        try:
            await self._post_room_event(
                room,
                event_type,
                summary,
                {
                    "actor": requester_ref,
                    "proposal_kind": proposal.get("proposal_kind"),
                    "objective": proposal.get("objective"),
                    "note": (note or "")[:1_000],
                    # 指回立项确认卡事件（老卡片无 card_event_id 时为 None，向后兼容）。
                    "answer_to_event_id": str(proposal.get("card_event_id") or "") or None,
                },
            )
        except Exception as exc:  # noqa: BLE001 - 卡片关闭事件失败不影响主流程
            logger.bind(room_id=room.room_id).warning(
                "AgentTeams room proposal close event failed: {}", exc
            )

    async def _create_confirmed_case(
        self,
        room: AgentTeamsRoomModel,
        requester_ref: str,
        proposal: dict[str, Any],
        source_case_id: str | None,
    ) -> dict[str, Any]:
        flow_id = str(proposal.get("flow_id") or "").strip() or None
        if flow_id:
            _assert_flow_allowed_for_room_case(flow_id)
        context_refs = [
            dict(ref) for ref in proposal.get("context_refs") or [] if isinstance(ref, dict)
        ]
        if not context_refs:
            # 与聊天式直发同一缺省：绑定发起人工作区只读引用。
            context_refs = [{"kind": "workspace", "id": requester_ref}]
        # A1：接入与旧直建路径一致的交付物化链路——立项 Case 必须落到项目，
        # create_case 据此经 _prepare_case_run 建运行目录并把 run_ref 写进
        # context_refs，交付时 _materialize_case_delivery 才能正常触发。
        project_id, project_name = await self._resolve_case_project(
            room, requester_ref, proposal, context_refs, source_case_id
        )
        return await self._agentteams.create_case(
            case_id=f"bioops_{uuid4().hex}",
            project_id=project_id,
            project_name=project_name,
            context_refs=context_refs,
            intent=str(proposal.get("objective") or "").strip()[:256] or room.title,
            requester_ref=requester_ref,
            flow_id=flow_id,
            source_case_id=source_case_id,
            db=self._db,
        )

    async def _resolve_case_project(
        self,
        room: AgentTeamsRoomModel,
        requester_ref: str,
        proposal: dict[str, Any],
        context_refs: list[dict[str, Any]],
        source_case_id: str | None,
    ) -> tuple[str | None, str | None]:
        """立项 Case 的项目归属解析（优先级与旧路径口径对齐）。

        1. 立项卡 context_refs 自带 kind=project 引用 → 直接复用；
        2. followup 关联上一 Case → 继承源 Case 的项目归属（新项目运行目录仍由
           ``_prepare_case_run`` 独立创建，不复用旧 run 目录）；
        3. 否则按立项卡 objective 摘要 ``get_or_create_project_by_name``
           （与旧直建路径"项目名由需求文本生成、同名复用"同口径）。
        requester_ref 非平台用户 UUID 时返回 (None, None)，退回无项目旧行为。
        """
        try:
            user_uuid = UUID(requester_ref)
        except ValueError:
            return None, None
        own_ref = _project_ref_from(context_refs)
        if own_ref is not None:
            return own_ref
        if source_case_id:
            inherited = await self._source_case_project(source_case_id, requester_ref)
            if inherited is not None:
                return inherited
        project = await ProjectService(self._db).get_or_create_project_by_name(
            user_uuid, proposal_project_name(str(proposal.get("objective") or ""), room.title)
        )
        return str(project["id"]), str(project["name"])

    async def _source_case_project(
        self, source_case_id: str, requester_ref: str
    ) -> tuple[str, str | None] | None:
        """followup 场景继承源 Case 的项目归属；源 Case 无项目或不可读时返回 None。"""
        try:
            case = await self._agentteams.get_case(source_case_id, requester_ref)
        except Exception as exc:  # noqa: BLE001 - 源 Case 不可读不阻断立项，退化为新建项目
            logger.bind(source_case_id=source_case_id).warning(
                "AgentTeams room followup source case lookup failed: {}", exc
            )
            return None
        return _project_ref_from(
            [ref for ref in case.get("context_refs") or [] if isinstance(ref, dict)]
        )


__all__ = [
    "PROPOSAL_OPTIONS_FOLLOWUP",
    "PROPOSAL_OPTIONS_NEW_CASE",
    "ROOM_CASE_BOUND_EVENT_TYPE",
    "ROOM_PROPOSAL_EVENT_TYPE",
    "AgentTeamsRoomService",
    "build_room_proposal",
    "persist_room_proposal",
    "proposal_project_name",
]
