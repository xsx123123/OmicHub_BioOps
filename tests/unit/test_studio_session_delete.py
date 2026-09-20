"""DELETE /api/v1/studio/sessions/{id} 测试 —— TestClient + 依赖覆盖，不起 PostgreSQL/Docker。

覆盖：归属与 studio 模式校验（404）、沙盒忙碌拒绝（409）、
空闲会话先休眠回收容器再软删（200），工作区目录保留（走 hibernate 而非 purge）。
"""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from cygnusx.api.deps import get_current_user_id
from cygnusx.api.v1 import studio as studio_module
from cygnusx.core.exceptions import CygnusXError
from cygnusx.infrastructure.database.models.chat import ChatSessionModel

BASE = "/api/v1/studio"
USER_ID = "user-1"


def _session(mode: str = "studio", user_id: str = USER_ID) -> ChatSessionModel:
    return ChatSessionModel(
        id=uuid.uuid4(),
        session_id="studio-session-1",
        user_id=user_id,
        model_id=uuid.uuid4(),
        title="火山图优化",
        status="active",
        mode=mode,
        message_count=2,
        total_tokens=0,
        sandbox_meta={},
    )


class _FakeChatService:
    """最小 ChatService 替身：只实现端点用到的 get_session/delete_session。"""

    def __init__(self, session: ChatSessionModel | None) -> None:
        self._session = session
        self.deleted: list[tuple[str, str]] = []

    async def get_session(self, session_id: str, user_id: str) -> ChatSessionModel | None:
        if (
            self._session is not None
            and self._session.session_id == session_id
            and self._session.user_id == user_id
        ):
            return self._session
        return None

    async def delete_session(self, session_id: str, user_id: str) -> bool:
        self.deleted.append((session_id, user_id))
        return True


@pytest.fixture()
def make_client(monkeypatch):
    def _build(session: ChatSessionModel | None, hibernate_status: str) -> tuple[TestClient, _FakeChatService]:
        service = _FakeChatService(session)

        async def _hibernate(session_id: str) -> str:
            return hibernate_status

        monkeypatch.setattr(studio_module.studio_sandbox_manager, "hibernate", _hibernate)

        app = FastAPI()
        app.include_router(studio_module.router, prefix=BASE)

        @app.exception_handler(CygnusXError)
        async def _omic_error_handler(request, exc):  # noqa: ANN001
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

        app.dependency_overrides[get_current_user_id] = lambda: USER_ID
        app.dependency_overrides[studio_module.get_chat_service] = lambda: service
        return TestClient(app), service

    return _build


@pytest.mark.unit
def test_delete_studio_session_hibernates_sandbox_then_soft_deletes(make_client) -> None:
    client, service = make_client(_session(), hibernate_status="hibernated")

    resp = client.delete(f"{BASE}/sessions/studio-session-1")

    assert resp.status_code == 200
    assert resp.json() == {"success": True}
    assert service.deleted == [("studio-session-1", USER_ID)]


@pytest.mark.unit
def test_delete_studio_session_rejects_busy_sandbox(make_client) -> None:
    client, service = make_client(_session(), hibernate_status="busy")

    resp = client.delete(f"{BASE}/sessions/studio-session-1")

    assert resp.status_code == 409
    assert service.deleted == []


@pytest.mark.unit
def test_delete_studio_session_404_for_other_user(make_client) -> None:
    client, service = make_client(_session(user_id="someone-else"), hibernate_status="hibernated")

    resp = client.delete(f"{BASE}/sessions/studio-session-1")

    assert resp.status_code == 404
    assert service.deleted == []


@pytest.mark.unit
def test_delete_studio_session_404_for_non_studio_session(make_client) -> None:
    """普通聊天会话不能走 Studio 端点删除（与详情端点同一归属/模式语义）。"""
    client, service = make_client(_session(mode="chat"), hibernate_status="hibernated")

    resp = client.delete(f"{BASE}/sessions/studio-session-1")

    assert resp.status_code == 404
    assert service.deleted == []
