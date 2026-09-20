"""Tests for the native platform clock MCP tool."""

from __future__ import annotations

from datetime import datetime

import pytest

from cygnusx.infrastructure.mcp.presets import PLATFORM_HANDLERS, PLATFORM_PRESET_TOOLS


@pytest.mark.unit
async def test_platform_clock_tool_is_registered_and_returns_requested_timezone() -> None:
    tool = next(
        item for item in PLATFORM_PRESET_TOOLS if item["name"] == "platform_get_current_time"
    )

    assert tool["inputSchema"]["properties"]["timezone"]["type"] == "string"
    assert PLATFORM_HANDLERS[tool["name"]]

    result = await PLATFORM_HANDLERS[tool["name"]]({"timezone": "Asia/Shanghai"})

    assert datetime.fromisoformat(result["datetime"]).utcoffset().total_seconds() == 8 * 3600
    assert result["date"] == result["datetime"][:10]
    assert result["timezone_name"] == "Asia/Shanghai"
    assert result["utc_offset"] == "+0800"
    assert isinstance(result["unix_timestamp"], int)


@pytest.mark.unit
async def test_platform_clock_tool_rejects_unknown_timezone() -> None:
    result = await PLATFORM_HANDLERS["platform_get_current_time"](
        {"timezone": "not/a-real-timezone"}
    )

    assert result["timezone"] == "not/a-real-timezone"
    assert "无效时区" in result["error"]
