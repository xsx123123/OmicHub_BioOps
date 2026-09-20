"""Studio Worker -> Web 内部控制面协议测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from cygnusx.api.v1 import studio as studio_api
from cygnusx.core.exceptions import AuthenticationError
from cygnusx.infrastructure.studio.control_client import (
    StudioControlClient,
    resolve_studio_control_token,
)


@pytest.mark.unit
def test_control_token_is_scoped_derivation_with_explicit_override():
    derived = resolve_studio_control_token(
        SimpleNamespace(studio_control_token="", app_secret_key="app-secret")
    )
    assert derived == resolve_studio_control_token(
        SimpleNamespace(studio_control_token="", app_secret_key="app-secret")
    )
    assert derived != "app-secret"
    assert resolve_studio_control_token(
        SimpleNamespace(studio_control_token="explicit", app_secret_key="app-secret")
    ) == "explicit"


@pytest.mark.unit
def test_internal_control_token_rejects_missing_or_wrong_value(monkeypatch):
    monkeypatch.setattr(
        studio_api, "get_settings", lambda: SimpleNamespace(studio_control_token="secret")
    )

    with pytest.raises(AuthenticationError):
        studio_api._validate_studio_control_token(None)
    with pytest.raises(AuthenticationError):
        studio_api._validate_studio_control_token("wrong")
    studio_api._validate_studio_control_token("secret")


@pytest.mark.unit
async def test_control_client_streams_ndjson_and_sends_token():
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.headers.get("X-CygnusX-Studio-Control-Token")
        seen["path"] = request.url.path
        return httpx.Response(
            200,
            content=(
                b'{"type":"stdout","data":"hello"}\n'
                b'{"type":"result","exit_code":0,"artifacts":[]}\n'
            ),
            headers={"content-type": "application/x-ndjson"},
        )

    client = StudioControlClient(
        base_url="http://web/api/v1/studio/internal",
        token="secret",
        transport=httpx.MockTransport(handler),
    )
    events = [
        event
        async for event in client.exec(
            "sess-1", "python", "print(1)", 601, "sandbox:bio", "user-1"
        )
    ]

    assert seen == {
        "token": "secret",
        "path": "/api/v1/studio/internal/sessions/sess-1/exec",
    }
    assert events[0] == {"type": "stdout", "data": "hello"}
    assert events[1]["exit_code"] == 0


@pytest.mark.unit
async def test_control_client_recycle_idle():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-CygnusX-Studio-Control-Token"] == "secret"
        return httpx.Response(200, json={"recycled": 2})

    client = StudioControlClient(
        base_url="http://web/api/v1/studio/internal",
        token="secret",
        transport=httpx.MockTransport(handler),
    )
    assert await client.recycle_idle() == 2


@pytest.mark.unit
async def test_control_client_purges_workspace():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/api/v1/studio/internal/sessions/sess-1/workspace"
        assert request.headers["X-CygnusX-Studio-Control-Token"] == "secret"
        return httpx.Response(200, json={"status": "removed"})

    client = StudioControlClient(
        base_url="http://web/api/v1/studio/internal",
        token="secret",
        transport=httpx.MockTransport(handler),
    )
    assert await client.purge_workspace("sess-1") == "removed"


@pytest.mark.unit
async def test_internal_exec_delegates_to_web_manager(monkeypatch):
    async def events(*args, **kwargs):
        yield {"type": "result", "exit_code": 0, "artifacts": []}

    monkeypatch.setattr(
        studio_api, "get_settings", lambda: SimpleNamespace(studio_control_token="secret")
    )
    monkeypatch.setattr(studio_api.studio_sandbox_manager, "exec", events)
    response = await studio_api.internal_studio_exec(
        "sess-1",
        studio_api.StudioInternalExecRequest(
            user_id="user-1",
            language="python",
            code="print(1)",
            timeout_sec=601,
            image=None,
        ),
        "secret",
    )
    body = b""
    async for chunk in response.body_iterator:
        body += chunk.encode() if isinstance(chunk, str) else chunk
    assert b'"exit_code": 0' in body


@pytest.mark.unit
async def test_internal_recycle_delegates_to_web_manager(monkeypatch):
    monkeypatch.setattr(
        studio_api, "get_settings", lambda: SimpleNamespace(studio_control_token="secret")
    )
    recycle = AsyncMock(return_value=3)
    monkeypatch.setattr(studio_api.studio_sandbox_manager, "recycle_idle", recycle)

    assert await studio_api.internal_recycle_idle_studio_sandboxes("secret") == {
        "recycled": 3
    }
    recycle.assert_awaited_once()


@pytest.mark.unit
async def test_internal_workspace_cleanup_delegates_to_web_manager(monkeypatch):
    monkeypatch.setattr(
        studio_api, "get_settings", lambda: SimpleNamespace(studio_control_token="secret")
    )
    purge = AsyncMock(return_value="removed")
    monkeypatch.setattr(studio_api.studio_sandbox_manager, "purge_workspace", purge)

    assert await studio_api.internal_cleanup_studio_workspace("sess-1", "secret") == {
        "status": "removed"
    }
    purge.assert_awaited_once_with("sess-1")
