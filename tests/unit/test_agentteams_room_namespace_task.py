"""BUG-E2E-02 回归：房间命名空间响应任务必须提交 DB。

修复前 ``_respond_to_room_namespace_message`` 全程无 ``db.commit()``，
``persist_room_proposal`` 只 flush，会话关闭即回滚 → 立项卡永不落库，
confirm-proposal 恒 400，房间 → Case 链路断裂。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import omichub.infrastructure.celery_app.tasks.agentteams as task_module
from omichub.application.services import agentteams_room_service as room_service_module


class _FakeSession:
    """``async with get_session_factory()() as db`` 的最小替身。"""

    def __init__(self, db: AsyncMock) -> None:
        self._db = db

    async def __aenter__(self) -> AsyncMock:
        return self._db

    async def __aexit__(self, *_args: object) -> bool:
        return False


def _patch_task_runtime(
    monkeypatch: pytest.MonkeyPatch, db: AsyncMock, *, respond_status: str
) -> None:
    monkeypatch.setattr(task_module, "get_session_factory", lambda: lambda: _FakeSession(db))
    monkeypatch.setattr(
        task_module.AgentTeamsBridgeSettingsService,
        "get_runtime_config",
        AsyncMock(return_value=SimpleNamespace()),
    )
    monkeypatch.setattr(
        task_module,
        "AgentTeamsService",
        MagicMock(return_value=SimpleNamespace(available=True)),
    )
    room_service = SimpleNamespace(
        get_room=AsyncMock(return_value=SimpleNamespace(room_id="room-1"))
    )
    monkeypatch.setattr(
        room_service_module, "AgentTeamsRoomService", MagicMock(return_value=room_service)
    )
    response_service = SimpleNamespace(
        respond_room=AsyncMock(return_value={"status": respond_status})
    )
    monkeypatch.setattr(
        task_module,
        "AgentTeamsRoomResponseService",
        MagicMock(return_value=response_service),
    )


@pytest.mark.asyncio
async def test_room_namespace_task_commits_persisted_proposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """成功路径（立项卡待确认）必须 commit，立项卡才能落库。"""
    db = AsyncMock()
    _patch_task_runtime(monkeypatch, db, respond_status="proposal_pending")

    result = await task_module._respond_to_room_namespace_message("room-1", "user-a", "内容")

    assert result == {"status": "proposal_pending"}
    db.commit.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_room_namespace_task_does_not_commit_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """失败态不提交，随会话关闭回滚，避免半成品立项卡落库。"""
    db = AsyncMock()
    _patch_task_runtime(monkeypatch, db, respond_status="failed")

    result = await task_module._respond_to_room_namespace_message("room-1", "user-a", "内容")

    assert result == {"status": "failed"}
    db.commit.assert_not_awaited()
