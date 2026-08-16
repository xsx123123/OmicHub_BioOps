"""Gateway-owned Matrix Application Service client.

The service token never crosses this process boundary.  The client uses Matrix
Client-Server endpoints with the AppService ``user_id`` impersonation parameter,
which lets OmicHub persist true per-agent room messages without storing Matrix
credentials itself.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import httpx

from .config import GatewaySettings
from .models import RoomMessage


class MatrixGatewayClient:
    def __init__(self, settings: GatewaySettings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(
            base_url=settings.matrix_homeserver_url.rstrip("/"),
            timeout=settings.matrix_request_timeout_seconds,
        )
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def create_room(self, room_name: str, creator_identity: str, invitees: list[str]) -> str:
        await self.ensure_identities([creator_identity, *invitees])
        creator = self._matrix_user(creator_identity)
        body: dict[str, Any] = {
            "name": room_name,
            "preset": "private_chat",
            "is_direct": False,
            "invite": [self._matrix_user(identity) for identity in invitees if identity != creator_identity],
            "initial_state": [{"type": "m.room.history_visibility", "state_key": "", "content": {"history_visibility": "invited"}}],
        }
        response = await self._request("POST", "/_matrix/client/v3/createRoom", user_id=creator, json=body)
        response.raise_for_status()
        room_id = response.json().get("room_id")
        if not isinstance(room_id, str) or not room_id:
            raise RuntimeError("Matrix createRoom returned no room_id")
        return room_id

    async def send_message(
        self,
        room_id: str,
        sender_identity: str,
        content: str,
        sender: dict[str, Any],
        source: str,
    ) -> str:
        await self.ensure_identities([sender_identity])
        matrix_user = self._matrix_user(sender_identity)
        # 本地开发应用服务没有实时事件回调，被邀请用户不会自动入房；发消息前主动加入。
        await self._join_room(room_id, matrix_user)
        txn_id = quote(f"omichub-{asyncio.get_running_loop().time():.6f}".replace(".", "-"), safe="")
        response = await self._request(
            "PUT",
            f"/_matrix/client/v3/rooms/{quote(room_id, safe='')}/send/m.room.message/{txn_id}",
            user_id=matrix_user,
            json={
                "msgtype": "m.text",
                "body": content,
                "com.omichub.source": source,
                "com.omichub.sender": sender,
                "com.omichub.identity": sender_identity,
            },
        )
        response.raise_for_status()
        event_id = response.json().get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise RuntimeError("Matrix room send returned no event_id")
        return event_id

    async def _join_room(self, room_id: str, user_id: str) -> None:
        response = await self._request(
            "POST",
            f"/_matrix/client/v3/rooms/{quote(room_id, safe='')}/join",
            user_id=user_id,
            json={},
        )
        # 已在房内时也会返回 200；其余错误直接抛出。
        response.raise_for_status()

    async def messages(self, room_id: str, since: str | None, limit: int) -> tuple[list[RoomMessage], str | None]:
        params: dict[str, Any] = {"dir": "b", "limit": limit}
        if since:
            params["from"] = since
        response = await self._request(
            "GET", f"/_matrix/client/v3/rooms/{quote(room_id, safe='')}/messages", params=params
        )
        response.raise_for_status()
        payload = response.json()
        chunk = payload.get("chunk") if isinstance(payload, dict) else []
        events = [self._to_message(room_id, event) for event in reversed(chunk) if self._is_text_event(event)]
        next_batch = payload.get("end") if isinstance(payload, dict) else None
        return events, next_batch if isinstance(next_batch, str) else None

    async def sync(self, room_id: str, since: str | None) -> tuple[list[RoomMessage], str | None]:
        params: dict[str, Any] = {"timeout": self._settings.matrix_sync_timeout_ms}
        if since:
            params["since"] = since
        response = await self._request("GET", "/_matrix/client/v3/sync", params=params)
        response.raise_for_status()
        payload = response.json()
        room_events = (((payload.get("rooms") or {}).get("join") or {}).get(room_id) or {}).get("timeline") or {}
        events = [
            self._to_message(room_id, event)
            for event in room_events.get("events", [])
            if self._is_text_event(event)
        ]
        next_batch = payload.get("next_batch")
        return events, next_batch if isinstance(next_batch, str) else None

    async def stream_sync(self, room_id: str, since: str | None) -> AsyncIterator[tuple[list[RoomMessage], str | None]]:
        cursor = since
        while True:
            events, cursor = await self.sync(room_id, cursor)
            yield events, cursor

    async def ensure_identities(self, identities: list[str]) -> None:
        """Register AppService-owned users without passwords when they do not exist."""
        for identity in dict.fromkeys(identities):
            matrix_user = self._matrix_user(identity)
            localpart = matrix_user.removeprefix("@").split(":", maxsplit=1)[0]
            response = await self._request(
                "POST",
                "/_matrix/client/v3/register",
                json={"type": "m.login.application_service", "username": localpart},
            )
            if response.status_code == 200:
                continue
            if response.status_code == 400:
                payload = response.json()
                if isinstance(payload, dict) and payload.get("errcode") == "M_USER_IN_USE":
                    continue
            response.raise_for_status()

    async def _request(self, method: str, path: str, *, user_id: str | None = None, **kwargs: Any) -> httpx.Response:
        params = dict(kwargs.pop("params", {}) or {})
        if user_id:
            params["user_id"] = user_id
        return await self._client.request(
            method,
            path,
            params=params,
            headers={"Authorization": f"Bearer {self._settings.matrix_service_token}"},
            **kwargs,
        )

    def _matrix_user(self, identity: str) -> str:
        user = self._settings.matrix_user_for_identity(identity)
        if not user:
            raise ValueError(f"Matrix identity is not configured: {identity}")
        return user

    def _to_message(self, room_id: str, event: dict[str, Any]) -> RoomMessage:
        content = event.get("content") or {}
        sender_matrix_id = event.get("sender") if isinstance(event.get("sender"), str) else None
        sender_identity = content.get("com.omichub.identity")
        if not isinstance(sender_identity, str):
            sender_identity = self._settings.matrix_identity_by_user_dynamic(sender_matrix_id or "")
        source = content.get("com.omichub.source")
        sender = content.get("com.omichub.sender")
        return RoomMessage(
            event_id=str(event.get("event_id") or ""),
            room_id=room_id,
            sender_identity=sender_identity,
            sender_matrix_id=sender_matrix_id,
            content=str(content.get("body") or ""),
            origin="omichub" if source == "omichub" else "external",
            sender=sender if isinstance(sender, dict) else {},
            created_at=(event.get("origin_server_ts") and str(event["origin_server_ts"])),
        )

    @staticmethod
    def _is_text_event(event: Any) -> bool:
        return isinstance(event, dict) and event.get("type") == "m.room.message" and (event.get("content") or {}).get("msgtype") == "m.text"
