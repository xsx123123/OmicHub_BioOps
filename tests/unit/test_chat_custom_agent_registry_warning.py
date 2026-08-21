"""C2 观测项：自建 agent 不在 chat 路由注册表候选时的节流 warning。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from loguru import logger

from omichub.application.services import chat_service


def _db_with_agent_ids(agent_ids: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [(a,) for a in agent_ids]))
    )


@pytest.fixture(autouse=True)
def _reset_warn_throttle(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(chat_service, "_custom_agent_registry_warned_at", 0.0)


@pytest.mark.asyncio
async def test_warns_when_db_custom_agent_missing_from_registry() -> None:
    db = _db_with_agent_ids(["agent-custom-1", "agent-general"])
    logs: list[str] = []
    sink = logger.add(lambda message: logs.append(str(message)), level="WARNING")
    try:
        missing = await chat_service._warn_custom_agents_missing_from_registry(
            db, {"agent-general"}
        )
    finally:
        logger.remove(sink)

    assert missing == ["agent-custom-1"]
    assert any("agent-custom-1" in entry for entry in logs)


@pytest.mark.asyncio
async def test_no_warning_when_all_custom_agents_registered() -> None:
    db = _db_with_agent_ids(["agent-general"])
    logs: list[str] = []
    sink = logger.add(lambda message: logs.append(str(message)), level="WARNING")
    try:
        missing = await chat_service._warn_custom_agents_missing_from_registry(
            db, {"agent-general"}
        )
    finally:
        logger.remove(sink)

    assert missing == []
    assert not any("自建 agent" in entry for entry in logs)


@pytest.mark.asyncio
async def test_warning_is_throttled() -> None:
    db = _db_with_agent_ids(["agent-custom-1"])

    first = await chat_service._warn_custom_agents_missing_from_registry(db, set())
    second = await chat_service._warn_custom_agents_missing_from_registry(db, set())

    assert first == ["agent-custom-1"]
    assert second == []
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_db_failure_is_logged_not_raised() -> None:
    db = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("db down")))
    logs: list[str] = []
    sink = logger.add(lambda message: logs.append(str(message)), level="WARNING")
    try:
        missing = await chat_service._warn_custom_agents_missing_from_registry(db, set())
    finally:
        logger.remove(sink)

    assert missing == []
    assert any("比对失败" in entry for entry in logs)
