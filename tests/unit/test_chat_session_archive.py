"""会话归档/取消归档/回收站恢复的状态机测试 + 列表过滤参数传递。

覆盖：
- archive（active→archived）/ unarchive（archived→active）/ restore（deleted→active）
- 非法状态迁移抛 BusinessError（路由层映射 400）
- 会话不存在或越权抛 NotFoundError（404）
- list_sessions 将 status/project_id 透传到持久层
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from cygnusx.application.services.chat.session_management import ChatSessionManagement
from cygnusx.core.exceptions import BusinessError, NotFoundError


class _FakeResult:
    def __init__(self, model):  # noqa: ANN001
        self._model = model

    def scalar_one_or_none(self):  # noqa: ANN202
        return self._model


class _SessionSvc(ChatSessionManagement):
    """最小可实例化的会话服务：DTO 转换原样返回。"""

    @staticmethod
    def _to_session_dto(session):  # noqa: ANN001, ANN202
        return session


def _session(status: str, *, user_id: str = "user-1") -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        session_id="sess-1",
        user_id=user_id,
        status=status,
        mode="chat",
        title="差异分析",
        created_at=now,
        updated_at=now,
    )


def _make_service(session) -> _SessionSvc:  # noqa: ANN001, ANN202
    svc = _SessionSvc()
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_FakeResult(session))
    svc._db = db
    svc._sessions = SimpleNamespace(list=AsyncMock(return_value=[]))
    return svc


@pytest.mark.asyncio
async def test_archive_active_session() -> None:
    svc = _make_service(_session("active"))
    result = await svc.archive_session("sess-1", "user-1")
    assert result.status == "archived"


@pytest.mark.asyncio
async def test_archive_non_active_session_rejected() -> None:
    svc = _make_service(_session("archived"))
    with pytest.raises(BusinessError):
        await svc.archive_session("sess-1", "user-1")

    svc = _make_service(_session("deleted"))
    with pytest.raises(BusinessError):
        await svc.archive_session("sess-1", "user-1")


@pytest.mark.asyncio
async def test_unarchive_archived_session() -> None:
    svc = _make_service(_session("archived"))
    result = await svc.unarchive_session("sess-1", "user-1")
    assert result.status == "active"


@pytest.mark.asyncio
async def test_unarchive_non_archived_session_rejected() -> None:
    svc = _make_service(_session("active"))
    with pytest.raises(BusinessError):
        await svc.unarchive_session("sess-1", "user-1")


@pytest.mark.asyncio
async def test_restore_deleted_session() -> None:
    svc = _make_service(_session("deleted"))
    result = await svc.restore_session("sess-1", "user-1")
    assert result.status == "active"


@pytest.mark.asyncio
async def test_restore_non_deleted_session_rejected() -> None:
    svc = _make_service(_session("active"))
    with pytest.raises(BusinessError):
        await svc.restore_session("sess-1", "user-1")

    svc = _make_service(_session("archived"))
    with pytest.raises(BusinessError):
        await svc.restore_session("sess-1", "user-1")


@pytest.mark.asyncio
async def test_archive_missing_or_foreign_session_is_404() -> None:
    svc = _make_service(None)
    with pytest.raises(NotFoundError):
        await svc.archive_session("sess-x", "user-1")


@pytest.mark.asyncio
async def test_list_sessions_passes_status_and_project_filters() -> None:
    svc = _make_service(None)
    project_id = str(uuid4())

    await svc.list_sessions(
        "user-1", "studio", status="archived", project_id=project_id, limit=10, offset=5
    )

    svc._sessions.list.assert_awaited_once_with(
        "user-1", "studio", limit=10, offset=5, status="archived", project_id=project_id
    )


@pytest.mark.asyncio
async def test_list_sessions_defaults_to_active() -> None:
    svc = _make_service(None)

    await svc.list_sessions("user-1")

    assert svc._sessions.list.await_args.kwargs["status"] == "active"
    assert svc._sessions.list.await_args.kwargs["project_id"] is None
