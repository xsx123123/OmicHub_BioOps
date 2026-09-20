"""Studio 会话级沙盒预热调度测试。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cygnusx.api.v1 import studio as studio_api


@pytest.fixture(autouse=True)
def clear_prewarm_tasks():
    studio_api._prewarm_tasks.clear()
    yield
    studio_api._prewarm_tasks.clear()


@pytest.mark.unit
async def test_schedule_prewarm_starts_dedicated_session_container(monkeypatch):
    ensure_running = AsyncMock()
    monkeypatch.setattr(
        studio_api,
        "get_studio_config",
        lambda: SimpleNamespace(session=SimpleNamespace(prewarm_on_create=True)),
    )
    monkeypatch.setattr(studio_api.studio_sandbox_manager, "ensure_running", ensure_running)

    studio_api._schedule_sandbox_prewarm("sess-1", "user-1", "sandbox:bio")
    await asyncio.gather(*list(studio_api._prewarm_tasks))

    ensure_running.assert_awaited_once_with(
        "sess-1",
        image="sandbox:bio",
        user_id="user-1",
        agent_id=None,
        capabilities_requested=None,
    )


@pytest.mark.unit
async def test_schedule_prewarm_respects_disabled_config(monkeypatch):
    ensure_running = AsyncMock()
    monkeypatch.setattr(
        studio_api,
        "get_studio_config",
        lambda: SimpleNamespace(session=SimpleNamespace(prewarm_on_create=False)),
    )
    monkeypatch.setattr(studio_api.studio_sandbox_manager, "ensure_running", ensure_running)

    studio_api._schedule_sandbox_prewarm("sess-1", "user-1", None)

    assert studio_api._prewarm_tasks == set()
    ensure_running.assert_not_awaited()


def test_session_sandbox_capabilities_defaults_legacy_sessions_to_code():
    session = SimpleNamespace(sandbox_meta=None)
    assert studio_api._session_sandbox_capabilities(session) == ["code"]


def test_session_sandbox_capabilities_reads_runtime_capability_metadata():
    session = SimpleNamespace(sandbox_meta={"sandbox_capabilities": ["browser", "code"]})
    assert studio_api._session_sandbox_capabilities(session) == ["browser", "code"]
