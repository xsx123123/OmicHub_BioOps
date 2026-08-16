from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from omichub.infrastructure.config.agent_loader import load_agent_configs
from omichub.infrastructure.mcp.presets import (
    OMICHUB_PLATFORM_SERVER_ID,
    PLATFORM_HANDLERS,
    PLATFORM_PRESET_TOOLS,
    _platform_admin_health_check,
)


def test_platform_admin_health_tool_is_registered() -> None:
    tool = next(
        item for item in PLATFORM_PRESET_TOOLS if item["name"] == "platform_admin_health_check"
    )

    assert "管理员专用" in tool["description"]
    assert "platform_admin_health_check" in PLATFORM_HANDLERS


def test_cloud_ops_agent_mounts_admin_health_tool() -> None:
    cloud = next(
        config for config in load_agent_configs() if config["agent_id"] == "agent-cloud-ops"
    )
    cloud_pack = next(pack for pack in cloud["features"]["tool_packs"] if pack["id"] == "cloud_ops")

    assert str(OMICHUB_PLATFORM_SERVER_ID) in cloud["mcp_ids"]
    assert "platform_admin_health_check" in cloud_pack["mcp_tools"][str(OMICHUB_PLATFORM_SERVER_ID)]


@pytest.mark.asyncio
async def test_platform_admin_health_tool_rejects_non_admin() -> None:
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(role="user")
    context = SimpleNamespace(db=db)

    result = await _platform_admin_health_check(
        {}, user_id="00000000-0000-0000-0000-000000000001", context=context
    )

    assert result == {"success": False, "error": "仅平台管理员可以执行运维健康检查"}
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_platform_admin_health_tool_returns_read_only_snapshot(tmp_path, monkeypatch) -> None:
    class Result:
        def __init__(self, *, rows=None, scalar=None):
            self._rows = rows or []
            self._scalar = scalar

        def all(self):
            return self._rows

        def scalar_one(self):
            return self._scalar

    class Redis:
        async def ping(self):
            return True

    db = AsyncMock()
    db.get.return_value = SimpleNamespace(role="admin")
    db.execute.side_effect = [
        Result(rows=[("active", 3)]),
        Result(rows=[("running", 2), ("failed", 1)]),
        Result(scalar=4),
        Result(scalar=23),
        Result(scalar=126),
    ]
    monkeypatch.setattr("omichub.infrastructure.cache.redis_client.get_redis", lambda: Redis())
    monkeypatch.setattr(
        "omichub.core.config.get_settings", lambda: SimpleNamespace(storage_path=str(tmp_path))
    )

    result = await _platform_admin_health_check(
        {},
        user_id="00000000-0000-0000-0000-000000000001",
        context=SimpleNamespace(db=db),
    )

    assert result["success"] is True
    assert result["status"] == "healthy"
    assert result["redis"]["status"] == "ok"
    assert result["tasks_by_status"] == {"running": 2, "failed": 1}
    assert result["knowledge"] == {"searchable_bases": 4, "documents": 23, "chunks": 126}
    assert result["storage"]["exists"] is True
