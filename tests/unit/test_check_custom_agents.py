"""scripts/check_custom_agents.py（上线前自建 Agent 只读盘点）单元测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "check_custom_agents.py"
)
_spec = importlib.util.spec_from_file_location("check_custom_agents", _SCRIPT_PATH)
check_custom_agents = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_custom_agents)


@pytest.mark.asyncio
async def test_fetch_custom_agents_returns_id_name_active() -> None:
    rows = [("agent-custom-1", "我的助手", True), ("agent-custom-2", "停用助手", False)]
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(all=lambda: rows))
    )

    agents = await check_custom_agents.fetch_custom_agents(session)

    assert agents == [("agent-custom-1", "我的助手", True), ("agent-custom-2", "停用助手", False)]
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_custom_agents_empty() -> None:
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(all=lambda: []))
    )

    assert await check_custom_agents.fetch_custom_agents(session) == []
