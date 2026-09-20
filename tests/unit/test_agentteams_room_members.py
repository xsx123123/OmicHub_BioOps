"""协作室成员邀请终态回归测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from cygnusx.application.services.agentteams_room_service import AgentTeamsRoomService
from cygnusx.infrastructure.database.models.chat import (
    AgentTeamsRoomMemberModel,
    AgentTeamsRoomModel,
)


@pytest.mark.asyncio
async def test_declining_invitation_persists_member_and_notification_terminal_state() -> None:
    user_id = str(uuid4())
    member = AgentTeamsRoomMemberModel(
        id=uuid4(), room_id="room-1", user_id=user_id, invited_by="owner-1", status="pending"
    )
    room = AgentTeamsRoomModel(
        room_id="room-1", owner_id="owner-1", title="协作室", status="active", origin="manual"
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=member)
    db.scalar = AsyncMock(return_value=room)
    notification = SimpleNamespace(
        payload={"room_id": "room-1", "invitation_id": str(member.id)}
    )
    db.scalars = AsyncMock(return_value=[notification])
    db.delete = AsyncMock()
    db.flush = AsyncMock()
    service = AgentTeamsRoomService(db, SimpleNamespace())

    response = await service.respond_invitation(str(member.id), user_id, accepted=False)

    assert response["status"] == "declined"
    assert member.status == "declined"
    assert member.responded_at is not None
    assert notification.payload["decision"] == "declined"
    db.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_reinviting_declined_member_resets_pending_state_and_creates_notification() -> None:
    owner_id = str(uuid4())
    member = AgentTeamsRoomMemberModel(
        id=uuid4(),
        room_id="room-1",
        user_id=str(uuid4()),
        invited_by=owner_id,
        status="declined",
    )
    member.responded_at = member.created_at
    room = AgentTeamsRoomModel(
        room_id="room-1", owner_id=owner_id, title="协作室", status="active", origin="manual"
    )
    db = AsyncMock()
    db.get = AsyncMock(
        side_effect=[
            SimpleNamespace(status="active"),
            SimpleNamespace(nickname="房主", username="owner"),
        ]
    )
    db.scalar = AsyncMock(return_value=member)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    service = AgentTeamsRoomService(db, SimpleNamespace())

    response = await service.invite_member(room, owner_id, member.user_id)

    assert response["status"] == "pending"
    assert member.status == "pending"
    assert member.invited_by == owner_id
    assert member.responded_at is None
    created_notification = db.add.call_args.args[0]
    assert created_notification.payload["invitation_id"] == str(member.id)
