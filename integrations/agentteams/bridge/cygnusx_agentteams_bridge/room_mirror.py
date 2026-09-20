"""Fire-and-forget mirror of Case audit events into the case's Matrix room.

CygnusX 建房后经 Case 级证据事件 ``room.created``（payload.room_id）把
case_id → Matrix room_id 的绑定写进 Bridge 审计流；本模块挂在
``AuditStore`` 的 append 钩子上，据此把后续审计事件镜像进房间。

失败仅记录日志，绝不阻断审计写入；Gateway 自身只写本地审计，不回写
Bridge，因此不存在循环镜像（``matrix.*`` 事件类型仍显式跳过兜底）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .client import GatewayClient

logger = logging.getLogger(__name__)

ROOM_BINDING_EVENT_TYPE = "room.created"
USER_MESSAGE_EVENT_TYPE = "room.user_message"
AGENT_MESSAGE_EVENT_TYPE = "room.agent_message"
ASK_USER_EVENT_TYPE = "room.ask_user"
# 瞬时/回源事件不进 Matrix：room.typing 只是前端指示；room.agent_stream 是
# 打字机增量（每 24 字符一条），镜像会让 Matrix 房间刷屏；via=matrix 的事件本就
# 来自 Matrix（反向同步回投），再镜像会造成回声循环。
# worker.inbox_polled 是轮询心跳（历史遗留，新版本已不再产生），绝不进 Matrix。
TRANSIENT_EVENT_TYPES = frozenset({"room.typing", "room.agent_stream", "worker.inbox_polled"})
MATRIX_ORIGIN_MARKER = "matrix"
_USER_SENDER_IDENTITY = "cygnusx-user"
_FALLBACK_SENDER_IDENTITY = "bioops-manager"
_CONTENT_LIMIT = 2_000

# 平台用户动态 Matrix 身份前缀：与主后端 agentteams_service / Gateway 同规则。
_MATRIX_USER_IDENTITY_PREFIX = "cygnusx-user-"
_MATRIX_LOCALPART_ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._=-")
_MATRIX_USER_SLUG_MAX = 48


def matrix_identity_for_requester(requester_ref: str) -> str:
    """平台用户 → Matrix 身份映射；清洗失败时回退共享 cygnusx-user 静态身份。"""
    slug = "".join(
        ch if ch in _MATRIX_LOCALPART_ALLOWED else "-" for ch in requester_ref.strip().lower()
    )
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-.")[:_MATRIX_USER_SLUG_MAX].rstrip("-.")
    if not slug:
        return _USER_SENDER_IDENTITY
    return f"{_MATRIX_USER_IDENTITY_PREFIX}{slug}"


class AuditRoomMirror:
    """Bind Matrix rooms from audit events and mirror subsequent events into them."""

    def __init__(self, gateway: GatewayClient | None) -> None:
        self._gateway = gateway
        self._rooms: dict[str, str] = {}

    @property
    def enabled(self) -> bool:
        return self._gateway is not None and self._gateway.configured

    def room_for(self, case_id: str) -> str | None:
        return self._rooms.get(case_id)

    def rebind(self, events: list[dict[str, Any]]) -> None:
        """Rebuild case → room bindings after a restart from the audit history."""
        for event in events:
            self._observe_binding(event)

    def observe(self, event: dict[str, Any]) -> None:
        """Sync append hook invoked by AuditStore after each recorded event."""
        if self._observe_binding(event):
            return
        if not self.enabled:
            return
        case_id = str(event.get("case_id") or "")
        room_id = self._rooms.get(case_id)
        if not room_id:
            return
        event_type = str(event.get("event_type") or "")
        if event_type.startswith("matrix.") or event_type in TRANSIENT_EVENT_TYPES:
            return
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        inner = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        if inner.get("via") == MATRIX_ORIGIN_MARKER:
            return
        try:
            asyncio.get_running_loop().create_task(self._send(room_id, event))
        except RuntimeError:
            logger.debug("room mirror skipped outside a running event loop (case %s)", case_id)

    def _observe_binding(self, event: dict[str, Any]) -> bool:
        if event.get("event_type") != ROOM_BINDING_EVENT_TYPE:
            return False
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        inner = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
        room_id = str(inner.get("room_id") or "")
        case_id = str(event.get("case_id") or "")
        if case_id and room_id:
            self._rooms[case_id] = room_id
        return True

    async def _send(self, room_id: str, event: dict[str, Any]) -> None:
        case_id = str(event.get("case_id") or "")
        try:
            sender_identity, content, sender = self._render(event)
            if not content:
                return
            await self._gateway.post_room_message(  # type: ignore[union-attr]
                room_id,
                sender_identity=sender_identity,
                content=content[:_CONTENT_LIMIT],
                sender=sender,
            )
        except Exception:
            logger.warning(
                "room mirror failed for case %s (room %s)", case_id, room_id, exc_info=True
            )

    @staticmethod
    def _render(event: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
        event_type = str(event.get("event_type") or "")
        actor = str(event.get("actor") or "")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        inner = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        if event_type == USER_MESSAGE_EVENT_TYPE:
            content = str(inner.get("content") or payload.get("summary") or "").strip()
            name = str(inner.get("actor") or actor or "用户")
            # 平台用户以独立 Matrix 账号发言（cygnusx-user-<slug>），Element 侧可区分发言人。
            return matrix_identity_for_requester(name), content, {"kind": "user", "name": name}
        if event_type == AGENT_MESSAGE_EVENT_TYPE:
            # Manager 回复：统一以 bioops-manager 身份发送（agent 身份未必在 Matrix
            # identity map 中），展示名取 payload 里的 role/agent_id。
            content = str(inner.get("content") or payload.get("summary") or "").strip()
            name = str(inner.get("role") or inner.get("agent_id") or actor or "协作经理")
            return _FALLBACK_SENDER_IDENTITY, content, {"kind": "agent", "name": name}
        if event_type == ASK_USER_EVENT_TYPE:
            # Manager 澄清卡片：Matrix 侧降级为纯文本（引导语 + 编号问题），
            # 交互作答仍在平台房间页进行。
            intro = str(inner.get("content") or "").strip()
            questions = inner.get("questions")
            lines = [
                f"{index}. {str(item.get('question') or '').strip()}"
                for index, item in enumerate(questions or [], start=1)
                if isinstance(item, dict) and str(item.get("question") or "").strip()
            ]
            content = "\n".join(part for part in [intro, *lines] if part)
            if not content:
                content = str(payload.get("summary") or "").strip()
            name = str(inner.get("role") or inner.get("agent_id") or actor or "协作经理")
            return _FALLBACK_SENDER_IDENTITY, content, {"kind": "agent", "name": name}
        summary = str(payload.get("summary") or payload.get("status") or "").strip()
        content = f"{event_type}: {summary}" if summary else event_type
        sender_identity = actor if actor.startswith("agent-") else _FALLBACK_SENDER_IDENTITY
        return sender_identity, content, {"kind": "agent", "name": actor or sender_identity}
