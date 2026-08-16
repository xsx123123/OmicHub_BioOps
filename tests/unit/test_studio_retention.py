"""Studio 工作区保留与会话删除行为测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from omichub.application.services.chat_service import ChatService
from omichub.infrastructure.celery_app.tasks import studio as studio_tasks
from omichub.infrastructure.database import session as database_session
from omichub.infrastructure.studio import manager as manager_module


class _ScalarResult:
    def __init__(self, sessions: list[SimpleNamespace]) -> None:
        self._sessions = sessions

    def scalars(self) -> "_ScalarResult":
        return self

    def all(self) -> list[SimpleNamespace]:
        return self._sessions


class _FakeDb:
    def __init__(self, sessions: list[SimpleNamespace]) -> None:
        self._sessions = sessions
        self.flush = AsyncMock()
        self.commit = AsyncMock()

    async def execute(self, _statement):
        return _ScalarResult(self._sessions)

    async def __aenter__(self) -> "_FakeDb":
        return self

    async def __aexit__(self, *_args) -> None:
        return None


@pytest.mark.unit
async def test_cleanup_expired_workspace_uses_manager(monkeypatch):
    session = SimpleNamespace(
        session_id="studio-expired",
        share_token_hash=None,
        share_expires_at=None,
    )
    fake_db = _FakeDb([session])
    purge = AsyncMock(return_value="removed")
    activity = AsyncMock(return_value=None)

    monkeypatch.setattr(
        database_session, "get_session_factory", lambda: lambda: fake_db
    )
    monkeypatch.setattr(
        studio_tasks, "get_settings", lambda: SimpleNamespace(service_name="web")
    )
    monkeypatch.setattr(
        manager_module.studio_sandbox_manager,
        "_config",
        lambda: SimpleNamespace(
            session=SimpleNamespace(workspace_retention_days=7)
        ),
    )
    monkeypatch.setattr(
        manager_module.studio_sandbox_manager, "last_activity_at", activity
    )
    monkeypatch.setattr(
        manager_module.studio_sandbox_manager, "purge_workspace", purge
    )

    result = await studio_tasks._cleanup_expired_workspaces()

    assert result["retention_days"] == 7
    assert result["removed_workspaces"] == 1
    purge.assert_awaited_once_with("studio-expired")
    fake_db.commit.assert_awaited_once()


@pytest.mark.unit
async def test_delete_studio_session_releases_container(monkeypatch):
    session = SimpleNamespace(session_id="studio-delete", mode="studio", status="active")
    db = SimpleNamespace(flush=AsyncMock())
    service = ChatService(db)
    stop = AsyncMock(return_value=True)

    monkeypatch.setattr(service, "get_session", AsyncMock(return_value=session))
    monkeypatch.setattr(service, "_enqueue_memory_summary", AsyncMock())
    monkeypatch.setattr(manager_module.studio_sandbox_manager, "stop", stop)

    assert await service.delete_session("studio-delete", "user-1") is True
    assert session.status == "deleted"
    stop.assert_awaited_once_with("studio-delete")
    db.flush.assert_awaited_once()
