"""Tests for the platform user-info / cookie-balance tool and the no-tool fallback sanitizer."""

from __future__ import annotations

import pytest

from omichub.infrastructure.mcp.presets import PLATFORM_HANDLERS, PLATFORM_PRESET_TOOLS


@pytest.mark.unit
def test_platform_get_user_info_tool_is_registered() -> None:
    tool = next(
        (item for item in PLATFORM_PRESET_TOOLS if item["name"] == "platform_get_user_info"),
        None,
    )
    assert tool is not None, "platform_get_user_info 必须注册进 omichub-platform 预设"
    # 余额查询无需入参；确保模型可零参调用
    assert tool["inputSchema"]["type"] == "object"
    assert tool["inputSchema"].get("properties") == {}
    assert PLATFORM_HANDLERS["platform_get_user_info"] is not None


@pytest.mark.unit
def test_platform_get_user_info_description_forbids_guessing() -> None:
    tool = next(
        item for item in PLATFORM_PRESET_TOOLS if item["name"] == "platform_get_user_info"
    )
    # 描述需明确引导模型在余额类问题时调用本工具而非凭空作答
    assert "饼干" in tool["description"]
    assert "余额" in tool["description"]


@pytest.mark.unit
def test_strip_tool_artifacts_removes_tool_messages_and_fields() -> None:
    from omichub.infrastructure.ai_provider.openai_compatible import _strip_tool_artifacts

    messages = [
        {"role": "user", "content": "我还有多少饼干？"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1", "function": {"name": "platform_get_user_info"}}],
        },
        {"role": "tool", "tool_call_id": "c1", "content": '{"balance": 1}'},
        {"role": "assistant", "content": "你的余额是 1。", "tool_call_id": "c1"},
    ]

    cleaned = _strip_tool_artifacts(messages)

    roles = [m.get("role") for m in cleaned]
    # tool 角色消息被丢弃；只有工具调用没有正文的 assistant 消息被丢弃
    assert "tool" not in roles
    assert cleaned[1]["content"] == "你的余额是 1。"
    # 保留消息里的 tool_calls / tool_call_id 字段被清掉
    assert all("tool_calls" not in m for m in cleaned)
    assert all("tool_call_id" not in m for m in cleaned)
    assert cleaned[0]["content"] == "我还有多少饼干？"
