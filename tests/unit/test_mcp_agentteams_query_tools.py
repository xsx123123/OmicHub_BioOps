"""协作室只读平台工具测试：ability_catalog_query / room_state_query（修复 B4）。"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cygnusx.application.schemas.tool_invocation import ToolInvocationContext
from cygnusx.infrastructure.config.agent_ability_catalog import agent_ability_catalog
from cygnusx.infrastructure.mcp.presets import PLATFORM_HANDLERS, PLATFORM_PRESET_TOOLS

_TOOL_NAMES = {"ability_catalog_query", "room_state_query"}


def test_tools_registered_with_readonly_annotations() -> None:
    tools = {tool["name"]: tool for tool in PLATFORM_PRESET_TOOLS}
    for name in _TOOL_NAMES:
        assert name in PLATFORM_HANDLERS
        annotations = tools[name]["annotations"]
        assert annotations["readOnlyHint"] is True
        assert annotations["destructiveHint"] is False
        assert annotations["idempotentHint"] is True
        assert annotations["openWorldHint"] is False


def test_room_state_query_schema_has_no_room_id_input() -> None:
    """scope 锁当前房间：工具 schema 不暴露 room_id 入参。"""
    tools = {tool["name"]: tool for tool in PLATFORM_PRESET_TOOLS}
    assert "room_id" not in tools["room_state_query"]["inputSchema"]["properties"]


@pytest.mark.asyncio
async def test_ability_catalog_query_summary_matches_catalog() -> None:
    result = await PLATFORM_HANDLERS["ability_catalog_query"]({})

    assert result["success"] is True
    expected = agent_ability_catalog.all()
    by_id = {item["agent_id"]: item for item in result["agents"]}
    assert set(by_id) == set(expected)
    for agent_id, item in by_id.items():
        assert item["summary"] == (expected[agent_id].get("summary") or "")
        assert "name" in item
        assert "enabled" in item
        assert "internal_case_role" in item
        assert "recruitable" in item
        assert "planner_eligible" in item
        assert "skill_ids" in item
        assert "mcp_ids" in item
        assert "mcp_tools" in item


@pytest.mark.asyncio
async def test_ability_catalog_query_includes_all_enabled_agent_entries() -> None:
    result = await PLATFORM_HANDLERS["ability_catalog_query"]({})

    assert result["success"] is True
    agents = result["agents"]
    enabled = [item for item in agents if item["enabled"]]
    assert len(enabled) == len(agents)
    assert {item["agent_id"] for item in enabled} >= {
        "agent-atacseq",
        "agent-rnaseq",
        "agent-scrna",
        "agent-viz",
        "agent-code",
        "agent-qc",
    }
    assert any(
        item["agent_id"] == "agent-qc" and item["chat_entry"] is False
        for item in enabled
    )
    assert any(
        item["agent_id"] == "agent-scrna-advanced"
        and item["name"] == "单细胞注释与高级分析专家"
        and item["recruitable"] is True
        for item in enabled
    )


@pytest.mark.asyncio
async def test_ability_catalog_query_detail_by_agent_id() -> None:
    expected = agent_ability_catalog.all()
    agent_id = sorted(expected)[0]

    result = await PLATFORM_HANDLERS["ability_catalog_query"]({"agent_id": agent_id})

    assert result["success"] is True
    assert result["agent_id"] == agent_id
    detail = result["detail"]
    for key in ("capabilities", "not_suitable_for", "handoff_when", "preferred_inputs"):
        assert detail[key] == expected[agent_id][key]
    assert "bindings" in result


@pytest.mark.asyncio
async def test_ability_catalog_query_reports_manager_mcp_whitelist() -> None:
    result = await PLATFORM_HANDLERS["ability_catalog_query"](
        {"agent_id": "agentteams-manager"}
    )

    assert result["success"] is True
    assert result["bindings"]["skill_ids"] == []
    assert result["bindings"]["mcp_ids"] == [
        "4197a87e-1c04-5680-b89f-06d0d85cb84c",
        "dda1f524-339b-5131-8ca3-46caedeeeb29",
    ]
    assert result["bindings"]["mcp_tools"]["4197a87e-1c04-5680-b89f-06d0d85cb84c"][-2:] == [
        "ability_catalog_query",
        "room_state_query",
    ]


@pytest.mark.asyncio
async def test_ability_catalog_query_unknown_agent_errors() -> None:
    result = await PLATFORM_HANDLERS["ability_catalog_query"]({"agent_id": "agent-ghost"})

    assert result["success"] is False
    assert "agent-ghost" in result["error"]


def _context(session_id: str, db: object) -> ToolInvocationContext:
    # model_construct 绕过 db 的 AsyncSession 类型校验，仅供单测注入假会话。
    return ToolInvocationContext.model_construct(
        user_id="user-a", agent_id="agentteams-manager", session_id=session_id, db=db
    )


def _fake_db(room: object) -> AsyncMock:
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: room)
    return db


def _room(**overrides: object) -> SimpleNamespace:
    room = SimpleNamespace(
        room_id="r-1",
        title="协作室会话",
        status="active",
        origin="manual",
        origin_ref=None,
        case_id=None,
        matrix_room_id=None,
        proposal={"status": "pending"},
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
        updated_at=None,
    )
    for key, value in overrides.items():
        setattr(room, key, value)
    return room


@pytest.mark.asyncio
async def test_room_state_query_without_context_errors() -> None:
    result = await PLATFORM_HANDLERS["room_state_query"]({}, context=None)

    assert result["success"] is False
    assert "上下文" in result["error"]


@pytest.mark.asyncio
async def test_room_state_query_outside_room_context_errors() -> None:
    result = await PLATFORM_HANDLERS["room_state_query"](
        {}, context=_context("chat-session-1", _fake_db(None))
    )

    assert result["success"] is False
    assert "协作室上下文" in result["error"]


@pytest.mark.asyncio
async def test_room_state_query_room_namespace_session() -> None:
    """未立项房间：session_id 中的 room-<room_id> 命名空间解析回房间。"""
    room = _room(room_id="r-9")
    context = _context("agentteams:room-r-9:sub:run-1:0", _fake_db(room))

    result = await PLATFORM_HANDLERS["room_state_query"]({}, context=context)

    assert result["success"] is True
    assert result["room_id"] == "r-9"
    assert result["status"] == "active"
    assert result["case_id"] is None
    assert result["has_pending_proposal"] is True
    assert result["created_at"] == "2026-08-21T00:00:00+00:00"
    assert result["updated_at"] is None


@pytest.mark.asyncio
async def test_room_state_query_bound_case_session() -> None:
    """已立项房间：session_id 中的真实 case_id 反查房间。"""
    room = _room(room_id="r-1", case_id="bioops_1", proposal={"status": "confirmed"})
    context = _context("agentteams:bioops_1:sub:run-1:0", _fake_db(room))

    result = await PLATFORM_HANDLERS["room_state_query"]({}, context=context)

    assert result["success"] is True
    assert result["room_id"] == "r-1"
    assert result["case_id"] == "bioops_1"
    assert result["has_pending_proposal"] is False


@pytest.mark.asyncio
async def test_room_state_query_ignores_room_id_argument() -> None:
    """即使调用方传入 room_id 也只返回当前上下文房间（scope 锁不可绕过）。"""
    room = _room(room_id="r-ctx")
    context = _context("agentteams:room-r-ctx:sub:run-1:0", _fake_db(room))

    result = await PLATFORM_HANDLERS["room_state_query"]({"room_id": "r-other"}, context=context)

    assert result["success"] is True
    assert result["room_id"] == "r-ctx"


@pytest.mark.asyncio
async def test_room_state_query_unknown_room_errors() -> None:
    context = _context("agentteams:room-ghost:sub:run-1:0", _fake_db(None))

    result = await PLATFORM_HANDLERS["room_state_query"]({}, context=context)

    assert result["success"] is False
    assert "room-ghost" in result["error"]
