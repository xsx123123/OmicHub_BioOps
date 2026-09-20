"""聊天 Runtime 后台开关测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cygnusx.application.services.chat.runtime_feature_gates import ChatRuntimeFeatureGates


class _Gates(ChatRuntimeFeatureGates):
    def __init__(self, db: object | None) -> None:
        self._db = db


@pytest.mark.asyncio
async def test_memory_gate_short_circuits_when_feature_disabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "cygnusx.core.config.get_settings",
        lambda: SimpleNamespace(memory_v2_enabled=False),
    )

    assert await _Gates(object())._memory_runtime_enabled() is False


@pytest.mark.asyncio
async def test_memory_gate_allows_database_free_runtime(monkeypatch) -> None:
    monkeypatch.setattr(
        "cygnusx.core.config.get_settings",
        lambda: SimpleNamespace(memory_v2_enabled=True),
    )

    assert await _Gates(None)._memory_runtime_enabled() is True


@pytest.mark.asyncio
async def test_subagent_gate_uses_environment_flag_before_site_settings(monkeypatch) -> None:
    monkeypatch.setattr(
        "cygnusx.core.config.get_settings",
        lambda: SimpleNamespace(subagent_fanout_enabled=True),
    )

    assert await _Gates(object())._admin_subagent_fanout_enabled() is True
