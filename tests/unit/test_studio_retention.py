"""Studio 工作区保留与会话删除行为测试。"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cygnusx.application.services.chat_service import ChatService
from cygnusx.infrastructure.celery_app.tasks import studio as studio_tasks
from cygnusx.infrastructure.database import session as database_session
from cygnusx.infrastructure.studio import manager as manager_module


class _ScalarResult:
    def __init__(self, sessions: list[SimpleNamespace]) -> None:
        self._sessions = sessions

    def scalars(self) -> "_ScalarResult":
        return self

    def all(self) -> list[SimpleNamespace]:
        return self._sessions


class _RowsResult:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def all(self) -> list[tuple]:
        return self._rows


class _FakeDb:
    """依次返回会话列表与消息聚合结果的假 db。"""

    def __init__(
        self,
        sessions: list[SimpleNamespace],
        last_messages: list[tuple] | None = None,
    ) -> None:
        self._sessions = sessions
        self._last_messages = last_messages or []
        self._calls = 0
        self.flush = AsyncMock()
        self.commit = AsyncMock()

    async def execute(self, _statement):
        self._calls += 1
        if self._calls == 1:
            return _ScalarResult(self._sessions)
        return _RowsResult(self._last_messages)

    async def __aenter__(self) -> "_FakeDb":
        return self

    async def __aexit__(self, *_args) -> None:
        return None


def _studio_session(**overrides) -> SimpleNamespace:
    defaults = dict(
        session_id="studio-expired",
        share_token_hash=None,
        share_expires_at=None,
        sandbox_meta=None,
        project_id=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _patch_config(monkeypatch, active_days: int = 14) -> None:
    monkeypatch.setattr(
        manager_module.studio_sandbox_manager,
        "_config",
        lambda: SimpleNamespace(
            retention=SimpleNamespace(active_days=active_days)
        ),
    )


@pytest.mark.unit
async def test_cleanup_expired_workspace_uses_manager(monkeypatch):
    session = _studio_session()
    fake_db = _FakeDb([session])
    purge = AsyncMock(return_value="removed")
    activity = AsyncMock(return_value=None)

    monkeypatch.setattr(
        database_session, "get_session_factory", lambda: lambda: fake_db
    )
    monkeypatch.setattr(
        studio_tasks, "get_settings", lambda: SimpleNamespace(service_name="web")
    )
    _patch_config(monkeypatch)
    monkeypatch.setattr(
        manager_module.studio_sandbox_manager, "last_activity_at", activity
    )
    monkeypatch.setattr(
        manager_module.studio_sandbox_manager, "purge_workspace", purge
    )

    result = await studio_tasks._cleanup_expired_workspaces()

    assert result["active_days"] == 14
    assert result["removed_workspaces"] == 1
    assert result["skipped_active"] == 0
    purge.assert_awaited_once_with("studio-expired")
    fake_db.commit.assert_awaited_once()


@pytest.mark.unit
async def test_cleanup_skips_session_with_recent_message(monkeypatch):
    """active_days 内有消息的会话（如 8 天前、窗口 14 天）豁免 purge。"""
    session = _studio_session(session_id="studio-active")
    last_messages = [("studio-active", datetime.now(UTC) - timedelta(days=8))]
    fake_db = _FakeDb([session], last_messages=last_messages)
    purge = AsyncMock(return_value="removed")
    activity = AsyncMock(return_value=None)

    monkeypatch.setattr(
        database_session, "get_session_factory", lambda: lambda: fake_db
    )
    monkeypatch.setattr(
        studio_tasks, "get_settings", lambda: SimpleNamespace(service_name="web")
    )
    _patch_config(monkeypatch)
    monkeypatch.setattr(
        manager_module.studio_sandbox_manager, "last_activity_at", activity
    )
    monkeypatch.setattr(
        manager_module.studio_sandbox_manager, "purge_workspace", purge
    )

    result = await studio_tasks._cleanup_expired_workspaces()

    assert result["removed_workspaces"] == 0
    assert result["skipped_active"] == 1
    purge.assert_not_awaited()


@pytest.mark.unit
async def test_cleanup_skips_pinned_session(monkeypatch):
    session = _studio_session(
        session_id="studio-pinned", sandbox_meta={"pinned": True}
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
    _patch_config(monkeypatch)
    monkeypatch.setattr(
        manager_module.studio_sandbox_manager, "last_activity_at", activity
    )
    monkeypatch.setattr(
        manager_module.studio_sandbox_manager, "purge_workspace", purge
    )

    result = await studio_tasks._cleanup_expired_workspaces()

    assert result["removed_workspaces"] == 0
    assert result["skipped_pinned"] == 1
    purge.assert_not_awaited()


@pytest.mark.unit
async def test_cleanup_skips_project_bound_session(monkeypatch):
    session = _studio_session(session_id="studio-project", project_id="proj-1")
    fake_db = _FakeDb([session])
    purge = AsyncMock(return_value="removed")
    activity = AsyncMock(return_value=None)

    monkeypatch.setattr(
        database_session, "get_session_factory", lambda: lambda: fake_db
    )
    monkeypatch.setattr(
        studio_tasks, "get_settings", lambda: SimpleNamespace(service_name="web")
    )
    _patch_config(monkeypatch)
    monkeypatch.setattr(
        manager_module.studio_sandbox_manager, "last_activity_at", activity
    )
    monkeypatch.setattr(
        manager_module.studio_sandbox_manager, "purge_workspace", purge
    )

    result = await studio_tasks._cleanup_expired_workspaces()

    assert result["removed_workspaces"] == 0
    assert result["skipped_project"] == 1
    purge.assert_not_awaited()


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
