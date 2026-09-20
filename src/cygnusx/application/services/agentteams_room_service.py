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
import json
import re
import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.services.agentteams_audit_events import (
    event_stream_sort_key,
    redact_confirm_token,
)
from cygnusx.application.services.agentteams_capability_registry import (
    get_agentteams_capability_registry,
)
from cygnusx.application.services.agentteams_service import (
    CASE_LEVEL_WORK_ITEM_ID,
    AgentTeamsService,
    matrix_identity_for_requester,
    room_namespace_case_id,
)
from cygnusx.application.services.flow_registry import get_flow_registry
from cygnusx.application.services.project_service import ProjectService
from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import AuthorizationError, BusinessError
from cygnusx.application.services.notification_service import NotificationService
from cygnusx.infrastructure.database.models.chat import (
    AgentTeamsRoomMemberModel,
    AgentTeamsRoomModel,
    AgentTeamsTurnRecordModel,
)
from cygnusx.infrastructure.database.models.notification import NotificationModel
from cygnusx.infrastructure.database.models.user import UserModel
from cygnusx.infrastructure.database.repositories.notification_repository import (
    SqlAlchemyNotificationRepository,
)
from cygnusx.infrastructure.storage.minio_store import MinioStore

# 立项确认卡房间级事件类型：payload 契约见 build_room_proposal / _emit_case_proposal。
ROOM_PROPOSAL_EVENT_TYPE = "room.proposal_confirm"
# 立项确认完成后回写绑定的房间级事件。
ROOM_CASE_BOUND_EVENT_TYPE = "room.case_bound"
# 立项确认卡三选项；followup 卡（终态后再立项）为 continue/new/cancel。
PROPOSAL_OPTIONS_NEW_CASE = ["confirm", "modify", "cancel"]
PROPOSAL_OPTIONS_FOLLOWUP = ["continue", "new", "cancel"]

# ------------------------------------------------------------------
# 房间历史气泡回补（思考链 / 内联工具卡）
# ------------------------------------------------------------------
# room.agent_stream 是瞬态事件：Bridge 不写 MinIO，仅经 Redis 热缓存/进程内存
# 分发，进程重建后历史增量即丢失，房间重开时历史气泡丢思考框与内联工具卡。
# 事件聚合出口把两类已持久化数据合并回最终消息载荷（best-effort，失败不影响
# 事件返回）：
# 1. agent.tool_call/started/result 证据事件（审计链已持久化）按 stream_id 归并；
# 2. agentteams_turn_records（DB 索引 + MinIO 全文）的 reasoning_text 按 agent
#    分组、按时间序 FIFO 分配到该 agent 的最终消息，拼为 thought。
_ROOM_TOOL_EVENT_TYPES = frozenset(
    {"agent.tool_call", "agent.tool_started", "agent.tool_result"}
)
_ROOM_THOUGHT_MAX_CHARS = 8_000
_ROOM_TURN_RECORD_MAX_BYTES = 8_000_000
# turn 记录与 Bridge 事件分属不同进程时钟，匹配窗口两侧各留 skew。
_ROOM_TURN_RECORD_SKEW = timedelta(seconds=90)


def _room_event_time(value: Any) -> datetime | None:
    """把事件 recorded_at（ISO 字符串或 datetime）归一化为 tz-aware datetime。"""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _resolve_case_flow_id(flow_id: Any) -> str | None:
    raw_flow_id = str(flow_id or "").strip()
    if not raw_flow_id:
        return None
    return get_flow_registry().resolve_bridge_workflow(raw_flow_id) or raw_flow_id


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
    flow_id = _resolve_case_flow_id(route_decision.get("flow_id"))
    return {
        "proposal_kind": proposal_kind,  # new_case | followup
        "token": secrets.token_urlsafe(24),
        "status": "pending",  # pending | consumed | cancelled
        "objective": objective,
        "flow_id": flow_id,
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


def room_title_from_message(content: str) -> str:
    """从首条发言生成可读的默认房间名称。"""
    cleaned = re.sub(r"@[^\s@，。！？：:；;,、()（）\[\]{}]+", "", content or "")
    cleaned = " ".join(cleaned.split()).strip(" ，。！？；：:,.!?、")
    return (cleaned[:38].rstrip() or "生物信息分析讨论")


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
        # SSE 轮询在同一实例上重复拉取同一页事件：已回补过的最终消息不再重复
        # 做 DB/MinIO 读取（历史加载每次新建实例，不受影响）。
        self._turn_detail_enriched_ids: set[str] = set()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    async def _validate_project_binding(self, owner_id: str, project_id: str) -> None:
        """校验房间绑定的项目存在且属于 owner（与聊天会话同一口径）。"""
        from cygnusx.core.exceptions import NotFoundError
        from cygnusx.infrastructure.database.models.project import ProjectModel

        try:
            project_uuid = UUID(project_id)
        except ValueError as exc:
            raise NotFoundError(f"项目不存在：{project_id}") from exc
        project = await self._db.scalar(
            select(ProjectModel).where(ProjectModel.id == project_uuid)
        )
        if project is None:
            raise NotFoundError(f"项目不存在：{project_id}")
        if str(project.user_id) != str(owner_id):
            raise AuthorizationError("无权绑定其他用户的项目")

    async def create_room(
        self,
        *,
        owner_id: str,
        title: str | None = None,
        origin: str = "manual",
        project_id: str | None = None,
    ) -> AgentTeamsRoomModel:
        """创建房间：主库行 + Bridge 房间命名空间记录 +（best-effort）Matrix 房间。

        ``project_id`` 将房间纳入项目维度（项目总览按它聚合房间）；显式传入时
        校验项目存在且属于 owner，来源会话升级路径由调用方传入会话的 project_id。
        """
        if not self._agentteams.available:
            raise BusinessError("Agent 协作中心尚未接通")
        if project_id:
            await self._validate_project_binding(owner_id, project_id)
        room = AgentTeamsRoomModel(
            room_id=uuid4().hex,
            owner_id=owner_id,
            title=(title or "").strip()[:200] or "和你的生物信息团队聊聊",
            origin=origin.strip()[:20] or "manual",
            project_id=project_id,
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

    async def rename_room(
        self, room: AgentTeamsRoomModel, requester_ref: str, title: str
    ) -> AgentTeamsRoomModel:
        if room.owner_id != requester_ref:
            raise AuthorizationError("只有房间所有者可以重命名协作室")
        normalized = " ".join(title.split()).strip()
        if not normalized:
            raise BusinessError("房间名称不能为空")
        room.title = normalized[:200]
        await self._db.flush()
        return room

    async def list_rooms(self, user_id: str) -> list[AgentTeamsRoomModel]:
        result = await self._db.scalars(
            select(AgentTeamsRoomModel)
            .outerjoin(
                AgentTeamsRoomMemberModel,
                (AgentTeamsRoomMemberModel.room_id == AgentTeamsRoomModel.room_id)
                & (AgentTeamsRoomMemberModel.user_id == user_id)
                & (AgentTeamsRoomMemberModel.status == "accepted"),
            )
            .where(
                (AgentTeamsRoomModel.owner_id == user_id)
                | (AgentTeamsRoomMemberModel.user_id.is_not(None))
            )
            .order_by(AgentTeamsRoomModel.updated_at.desc())
        )
        rooms = list(result)
        for room in rooms:
            room._agentteams_role = "mine" if room.owner_id == user_id else "invited"
        return rooms

    async def get_room(self, room_id: str, owner_id: str) -> AgentTeamsRoomModel:
        room = await self._db.scalar(
            select(AgentTeamsRoomModel).where(AgentTeamsRoomModel.room_id == room_id)
        )
        if room is None:
            raise BusinessError("协作室房间不存在")
        member = await self._db.scalar(
            select(AgentTeamsRoomMemberModel).where(
                AgentTeamsRoomMemberModel.room_id == room_id,
                AgentTeamsRoomMemberModel.user_id == owner_id,
                AgentTeamsRoomMemberModel.status == "accepted",
            )
        )
        # Keep repository mocks and alternate session adapters from treating the
        # room row returned by a broad scalar stub as a membership row.
        if isinstance(member, AgentTeamsRoomModel):
            member = None
        if room.owner_id != owner_id and member is None:
            raise AuthorizationError("无权访问该协作室房间")
        room._agentteams_role = "mine" if room.owner_id == owner_id else "invited"
        return room

    async def invite_member(self, room: AgentTeamsRoomModel, owner_id: str, user_id: str) -> dict[str, Any]:
        if room.owner_id != owner_id:
            raise AuthorizationError("仅房间 owner 可以邀请成员")
        if user_id == owner_id:
            raise BusinessError("房间 owner 无需邀请")
        target = await self._db.get(UserModel, UUID(user_id))
        if target is None or target.status != "active":
            raise BusinessError("受邀用户不存在或已被禁用")
        existing = await self._db.scalar(
            select(AgentTeamsRoomMemberModel).where(
                AgentTeamsRoomMemberModel.room_id == room.room_id,
                AgentTeamsRoomMemberModel.user_id == user_id,
            )
        )
        if existing is not None:
            if existing.status == "pending":
                return self._member_payload(existing)
            if existing.status != "declined":
                raise BusinessError("该用户已经是协作室成员")
            existing.status = "pending"
            existing.invited_by = owner_id
            existing.created_at = datetime.now(UTC)
            existing.responded_at = None
            member = existing
        else:
            member = AgentTeamsRoomMemberModel(
                room_id=room.room_id, user_id=user_id, invited_by=owner_id, status="pending"
            )
            self._db.add(member)
        inviter = await self._db.get(UserModel, UUID(owner_id))
        inviter_name = (
            (inviter.nickname or inviter.username) if inviter is not None else owner_id
        )
        await self._db.flush()
        notification = NotificationService(SqlAlchemyNotificationRepository(self._db))
        await notification.create(
            created_by=owner_id,
            title=f"邀请你加入协作室：{room.title}",
            content=f"{owner_id} 邀请你加入协作室“{room.title}”。",
            level="info",
            is_global=False,
            target_user_id=user_id,
            notification_type="agentteams_room_invite",
            payload={
                "room_id": room.room_id,
                "invitation_id": str(member.id),
                "inviter_id": owner_id,
                "inviter_nickname": inviter_name,
            },
        )
        return self._member_payload(member)

    async def pending_invitations(self, user_id: str) -> list[dict[str, Any]]:
        rows = await self._db.scalars(
            select(AgentTeamsRoomMemberModel)
            .where(AgentTeamsRoomMemberModel.user_id == user_id, AgentTeamsRoomMemberModel.status == "pending")
            .order_by(AgentTeamsRoomMemberModel.created_at.desc())
        )
        return [self._member_payload(row) for row in rows]

    async def list_members(
        self, room: AgentTeamsRoomModel, viewer_id: str
    ) -> list[dict[str, Any]]:
        rows = list(
            await self._db.scalars(
                select(AgentTeamsRoomMemberModel)
                .where(AgentTeamsRoomMemberModel.room_id == room.room_id)
                .where(
                    AgentTeamsRoomMemberModel.status == "accepted"
                    if room.owner_id != viewer_id
                    else True
                )
                .order_by(AgentTeamsRoomMemberModel.created_at.asc())
            )
        )
        owner = {
            "id": None,
            "room_id": room.room_id,
            "user_id": room.owner_id,
            "role": "owner",
            "status": "accepted",
            "invited_by": room.owner_id,
            "created_at": room.created_at.isoformat() if room.created_at else None,
            "responded_at": None,
        }
        return [owner, *(self._member_payload(row) for row in rows)]

    async def respond_invitation(self, invitation_id: str, user_id: str, accepted: bool) -> dict[str, Any]:
        member = await self._db.get(AgentTeamsRoomMemberModel, UUID(invitation_id))
        if member is None or member.user_id != user_id or member.status != "pending":
            raise AuthorizationError("无权处理该邀请")
        room = await self._db.scalar(select(AgentTeamsRoomModel).where(AgentTeamsRoomModel.room_id == member.room_id))
        if room is None:
            raise BusinessError("协作室房间不存在")
        if not accepted:
            member.status = "declined"
            member.responded_at = datetime.now(UTC)
            await self._db.flush()
            await self._record_invitation_decision(member, "declined")
            return self._member_payload(member)

        member.status = "accepted"
        member.responded_at = datetime.now(UTC)
        await self._db.flush()
        if room.matrix_room_id:
            identity = matrix_identity_for_requester(user_id)
            try:
                await self._agentteams.create_element_session(identity, room.matrix_room_id)
            except Exception as exc:  # noqa: BLE001 - platform membership remains authoritative
                logger.warning("Matrix member join failed for room {}: {}", room.room_id, exc)
        member_user = await self._db.get(UserModel, UUID(user_id))
        member_name = (
            (member_user.nickname or member_user.username) if member_user is not None else user_id
        )
        notification = NotificationService(SqlAlchemyNotificationRepository(self._db))
        await notification.create(
            created_by=user_id,
            title=f"{member_name} 已加入协作室：{room.title}",
            content=f"{member_name} 已接受邀请并加入协作室“{room.title}”。",
            level="info",
            is_global=False,
            target_user_id=room.owner_id,
            notification_type="agentteams_room_member_joined",
            payload={"room_id": room.room_id, "user_id": user_id, "member_id": str(member.id)},
        )
        await self._record_invitation_decision(member, "accepted")
        return self._member_payload(member)

    async def _record_invitation_decision(
        self, member: AgentTeamsRoomMemberModel, decision: str
    ) -> None:
        notifications = await self._db.scalars(
            select(NotificationModel).where(
                NotificationModel.target_user_id == UUID(member.user_id),
                NotificationModel.type == "agentteams_room_invite",
            )
        )
        for notification in notifications:
            payload = dict(notification.payload or {})
            if (
                payload.get("room_id") != member.room_id
                or payload.get("invitation_id") != str(member.id)
                or payload.get("decision")
            ):
                continue
            notification.payload = {
                **payload,
                "decision": decision,
                "responded_at": member.responded_at.isoformat() if member.responded_at else None,
            }
        await self._db.flush()

    async def revoke_invitation(self, room: AgentTeamsRoomModel, owner_id: str, user_id: str) -> dict[str, Any]:
        if room.owner_id != owner_id:
            raise AuthorizationError("仅房间 owner 可以撤销邀请")
        member = await self._db.scalar(select(AgentTeamsRoomMemberModel).where(
            AgentTeamsRoomMemberModel.room_id == room.room_id,
            AgentTeamsRoomMemberModel.user_id == user_id,
            AgentTeamsRoomMemberModel.status == "pending",
        ))
        if member is None:
            raise BusinessError("待处理邀请不存在")
        await self._db.delete(member)
        return {"revoked": True, "room_id": room.room_id, "user_id": user_id}

    async def leave_member(self, room: AgentTeamsRoomModel, user_id: str, *, owner_id: str | None = None) -> dict[str, Any]:
        if owner_id is not None and room.owner_id != owner_id:
            raise AuthorizationError("仅房间 owner 可以移除成员")
        if owner_id is None and user_id == room.owner_id:
            raise BusinessError("房间 owner 不能退出，请删除房间")
        member = await self._db.scalar(select(AgentTeamsRoomMemberModel).where(
            AgentTeamsRoomMemberModel.room_id == room.room_id,
            AgentTeamsRoomMemberModel.user_id == user_id,
            AgentTeamsRoomMemberModel.status == "accepted",
        ))
        if member is None:
            raise BusinessError("房间成员不存在")
        await self._db.delete(member)
        if room.matrix_room_id:
            try:
                await self._agentteams.leave_matrix_room(matrix_identity_for_requester(user_id), room.matrix_room_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Matrix member leave failed for room {}: {}", room.room_id, exc)
        return {"room_id": room.room_id, "user_id": user_id, "removed": True}

    @staticmethod
    def _member_payload(member: AgentTeamsRoomMemberModel) -> dict[str, Any]:
        return {
            "id": str(member.id), "room_id": member.room_id, "user_id": member.user_id,
            "role": member.role, "invited_by": member.invited_by, "status": member.status,
            "created_at": member.created_at.isoformat() if member.created_at else None,
            "responded_at": member.responded_at.isoformat() if member.responded_at else None,
        }

    async def delete_room(
        self, room: AgentTeamsRoomModel, requester_ref: str
    ) -> dict[str, Any]:
        """删除协作室房间：清空该会话窗口的全部内容并移除房间记录。

        - 已绑定 Case：经 Bridge ``delete_case`` 先取消未结束工单，再移除 Case
          记录与其审计事件（与旧 Case 房间删除同一口径）；
        - 房间命名空间记录（``room-<room_id>``，承载未立项阶段的房间级会话
          事件流）：同样经 Bridge 删除，保证「删除即清空本窗口全部内容」；
        - 两次 Bridge 删除均容忍「不存在」（超时重试/对账场景幂等），最后删
          主库房间行；Matrix 侧孤儿房间不阻断删除（与 Case 删除保留磁盘产物
          的口径一致，仅清会话与审计数据）；
        - Matrix 房间无法真正删除：让请求者的 Matrix 身份离房，使其从 Element
          房间列表消失；离房失败（Gateway 离线等）不阻断删除。
        """
        if room.owner_id != requester_ref:
            raise AuthorizationError("仅房间 owner 可以删除协作室")
        room_id = room.room_id
        deleted_case_id: str | None = None
        if room.case_id:
            try:
                await self._agentteams.delete_case(room.case_id, requester_ref)
                deleted_case_id = room.case_id
            except BusinessError as exc:
                if "不存在" not in str(exc):
                    raise
        try:
            await self._agentteams.delete_case(
                room_namespace_case_id(room_id), requester_ref
            )
        except BusinessError as exc:
            if "不存在" not in str(exc):
                raise
        if room.matrix_room_id:
            try:
                await self._agentteams.leave_matrix_room(
                    matrix_identity_for_requester(requester_ref), room.matrix_room_id
                )
            except Exception as exc:
                logger.warning(
                    "Matrix 离房失败（房间 {}，身份 {}）：{}",
                    room.matrix_room_id,
                    requester_ref,
                    exc,
                )
            members = await self._db.scalars(select(AgentTeamsRoomMemberModel).where(
                AgentTeamsRoomMemberModel.room_id == room.room_id,
                AgentTeamsRoomMemberModel.status == "accepted",
            ))
            for member in members:
                try:
                    await self._agentteams.leave_matrix_room(
                        matrix_identity_for_requester(member.user_id), room.matrix_room_id
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Matrix member cleanup failed for room {}: {}", room.room_id, exc)
        await self._db.delete(room)
        await self._db.flush()
        return {"room_id": room_id, "deleted": True, "case_id": deleted_case_id}

    # ------------------------------------------------------------------
    # Element 视图免登录会话
    # ------------------------------------------------------------------
    async def create_element_session(
        self, room: AgentTeamsRoomModel, requester_ref: str
    ) -> dict[str, Any]:
        """为房间 owner 签发 Element 视图免登录会话凭据。

        身份取请求者的平台用户动态 Matrix 身份（``cygnusx-user-<slug>``，建房
        时已注册并邀请入房；``get_room`` 已强制请求者即 owner）；经 Gateway 做
        appservice login 签发独立设备 token，as_token 不出 Gateway 进程。返回的
        ``room_url`` 供前端拼自动登录跳板地址。
        """
        if not room.matrix_room_id:
            raise BusinessError("该房间尚未开通 Matrix 协作房间")
        identity = matrix_identity_for_requester(requester_ref)
        # 携带房间 id：Gateway 先幂等入房再签发，避免仅 invited 未 joined 时 Element 卡黑屏。
        session = await self._agentteams.create_element_session(identity, room.matrix_room_id)
        session["matrix_room_id"] = room.matrix_room_id
        element_base_url = str(session.get("element_base_url") or "").strip()
        session["room_url"] = (
            f"{element_base_url.rstrip('/')}/#/room/{room.matrix_room_id}"
            if element_base_url
            else None
        )
        return session

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
        if room.title.strip() in {"协作室会话", "和你的生物信息团队聊聊"}:
            room.title = room_title_from_message(content)
            await self._db.flush()
        stream_case_id = room.case_id or room_namespace_case_id(room.room_id)
        return await self._agentteams.post_room_message(
            stream_case_id,
            room.owner_id,
            content,
            actor_user_id=requester_ref,
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
            room_namespace_case_id(room.room_id), room.owner_id, cursor=ns_cursor, limit=limit
        )
        streams.append(("ns", ns_events))
        case_events: list[dict[str, Any]] = []
        if room.case_id:
            case_events = await self._fetch_stream_page(
                room.case_id, room.owner_id, cursor=case_cursor, limit=limit
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
        # 历史气泡回补：把已持久化的工具事件 / turn 记录 reasoning 合并进最终
        # 消息载荷，房间重开后思考框与内联工具卡不依赖瞬态 room.agent_stream。
        await self._enrich_room_turn_details(room, events)
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

    # ------------------------------------------------------------------
    # 房间历史气泡回补（思考链 / 内联工具卡）
    # ------------------------------------------------------------------
    async def _enrich_room_turn_details(
        self, room: AgentTeamsRoomModel, events: list[dict[str, Any]]
    ) -> None:
        """get_room_events 出口的历史气泡回补入口；任何失败只记日志，不影响返回。"""
        try:
            await self._enrich_room_turn_details_inner(room, events)
        except Exception as exc:  # noqa: BLE001 - 回补失败不得影响房间事件返回
            logger.bind(room_id=room.room_id).warning(
                "AgentTeams room turn-detail enrichment failed: {}", exc
            )

    async def _enrich_room_turn_details_inner(
        self, room: AgentTeamsRoomModel, events: list[dict[str, Any]]
    ) -> None:
        tool_events: dict[str, dict[str, dict[str, Any]]] = {}
        targets: list[tuple[dict[str, Any], dict[str, Any], str]] = []
        for event in events:
            event_type = str(event.get("event_type") or "")
            body = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            inner = body.get("payload") if isinstance(body.get("payload"), dict) else None
            if inner is None:
                continue
            if event_type in _ROOM_TOOL_EVENT_TYPES:
                stream_id = str(inner.get("stream_id") or "")
                call_id = str(inner.get("tool_call_id") or "")
                if not stream_id or not call_id:
                    continue
                calls = tool_events.setdefault(stream_id, {})
                entry = calls.get(call_id)
                if entry is None:
                    entry = {
                        "id": call_id,
                        "name": str(inner.get("tool") or ""),
                        "status": "running",
                    }
                    calls[call_id] = entry
                if event_type == "agent.tool_result":
                    entry["status"] = "failed" if inner.get("success") is False else "ok"
                    duration = inner.get("duration_ms")
                    if isinstance(duration, (int, float)):
                        entry["duration_ms"] = int(duration)
                    result_summary = str(inner.get("result_summary") or "")
                    if result_summary:
                        entry["result_summary"] = result_summary
                else:
                    args_summary = str(inner.get("args_summary") or "")
                    if args_summary:
                        entry["args_summary"] = args_summary
                continue
            if event_type not in ("room.agent_message", "room.ask_user"):
                continue
            stream_id = str(inner.get("stream_id") or "")
            if not stream_id:
                continue
            event_id = str(event.get("event_id") or "")
            if event_id and event_id in self._turn_detail_enriched_ids:
                continue
            targets.append((event, inner, stream_id))
        if not targets:
            return
        for event, inner, stream_id in targets:
            calls = tool_events.get(stream_id)
            if calls and not inner.get("tool_calls"):
                inner["tool_calls"] = list(calls.values())
        pending = [
            (event, inner)
            for event, inner, _ in targets
            if not inner.get("thought")
        ]
        if pending:
            await self._inject_room_thoughts(room, events, pending)
        for event, _, _ in targets:
            event_id = str(event.get("event_id") or "")
            if event_id:
                self._turn_detail_enriched_ids.add(event_id)

    async def _inject_room_thoughts(
        self,
        room: AgentTeamsRoomModel,
        events: list[dict[str, Any]],
        pending: list[tuple[dict[str, Any], dict[str, Any]]],
    ) -> None:
        """把 turn 记录的 reasoning_text 按 agent 时序 FIFO 分配到各最终消息。

        一次应答可能含多轮 LLM 调用（工具回路/分诊/正式回复），其 turn 记录全部
        落在「触发消息（causation_event_id）之后、最终消息之前」的时间窗内；按
        agent 分组顺序消费即可把同一应答的多段思考拼到同一条气泡上。触发事件不
        在当前页时退化为仅按上界匹配（best-effort）。
        """
        case_ids = {room_namespace_case_id(room.room_id)}
        if room.case_id:
            case_ids.add(str(room.case_id))
        stmt = (
            select(AgentTeamsTurnRecordModel)
            .where(AgentTeamsTurnRecordModel.case_id.in_(sorted(case_ids)))
            .order_by(AgentTeamsTurnRecordModel.recorded_at.asc())
        )
        rows = (await self._db.execute(stmt)).scalars().all()
        if not rows:
            return
        by_agent: dict[str, list[AgentTeamsTurnRecordModel]] = {}
        for row in rows:
            by_agent.setdefault(str(row.agent_id), []).append(row)
        event_times: dict[str, datetime] = {}
        for item in events:
            event_id = str(item.get("event_id") or "")
            moment = _room_event_time(item.get("recorded_at"))
            if event_id and moment is not None:
                event_times[event_id] = moment
        minio = MinioStore(probe=False)
        cursors: dict[str, int] = {}
        for event, inner in pending:
            agent_id = str(inner.get("agent_id") or event.get("actor") or "")
            records = by_agent.get(agent_id)
            if not agent_id or not records:
                continue
            upper = _room_event_time(event.get("recorded_at"))
            lower = event_times.get(str(inner.get("causation_event_id") or ""))
            cursor = cursors.get(agent_id, 0)
            picked: list[AgentTeamsTurnRecordModel] = []
            while cursor < len(records):
                record = records[cursor]
                moment = record.recorded_at
                if moment is not None and moment.tzinfo is None:
                    moment = moment.replace(tzinfo=UTC)
                if (
                    upper is not None
                    and moment is not None
                    and moment > upper + _ROOM_TURN_RECORD_SKEW
                ):
                    break
                cursor += 1
                if (
                    lower is not None
                    and moment is not None
                    and moment < lower - _ROOM_TURN_RECORD_SKEW
                ):
                    continue  # 属于更早应答的记录（其消息在先前分页）：消费但不展示
                picked.append(record)
            cursors[agent_id] = cursor
            if not picked:
                continue
            thoughts: list[str] = []
            for record in picked:
                text = await self._read_turn_reasoning(minio, record)
                if text:
                    thoughts.append(text)
            if thoughts:
                inner["thought"] = "\n\n".join(thoughts)[:_ROOM_THOUGHT_MAX_CHARS]

    @staticmethod
    async def _read_turn_reasoning(
        minio: MinioStore, record: AgentTeamsTurnRecordModel
    ) -> str | None:
        uri = str(record.s3_uri or "")
        prefix = f"s3://{minio.bucket}/cases/{record.case_id}/"
        if not uri.startswith(prefix):
            return None
        key = uri[len(prefix):]
        try:
            raw = await asyncio.to_thread(
                minio.read_turn_record,
                str(record.case_id),
                key,
                max_bytes=_ROOM_TURN_RECORD_MAX_BYTES,
            )
            payload = json.loads(raw.decode("utf-8"))
        except Exception:  # noqa: BLE001 - 单条记录读取失败不阻断其他记录
            return None
        text = str(payload.get("reasoning_text") or "").strip()
        return text or None

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
        proposal["flow_id"] = _resolve_case_flow_id(proposal.get("flow_id"))
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
        flow_id = _resolve_case_flow_id(proposal.get("flow_id"))
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
