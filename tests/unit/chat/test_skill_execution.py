"""Skill tool event-stream execution tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest

from cygnusx.application.services.chat.skill_execution import (
    SkillExecutionResult,
    stream_skill_execution,
)


async def _collect(**kwargs: object) -> list[object]:
    return [item async for item in stream_skill_execution(**kwargs)]


@pytest.mark.asyncio
async def test_skill_execution_streams_lifecycle_and_records_success() -> None:
    execute = AsyncMock(
        return_value={"success": True, "result": {"resources": ["one", "two"]}}
    )
    record = AsyncMock()

    items = await _collect(
        tool_name="use_skill",
        arguments={"skill_id": "skill-1"},
        tool_call_id="call-1",
        message_id="message-1",
        agent_name="Researcher",
        bound_skills=[
            SimpleNamespace(
                skill_id="skill-1",
                name="Skill one",
                version="1.0",
                source_type="builtin",
                icon="sparkles",
            )
        ],
        skill_pins={"skill-1": "1.0"},
        session_id="session-1",
        user_id="user-1",
        execute_skill_tool=execute,
        record_skill_invocation=record,
    )

    assert [item.type for item in items[:-1]] == ["skill", "skill"]
    assert items[0].metadata["phase"] == "invoked"
    assert items[1].metadata["phase"] == "completed"
    assert items[1].metadata["summary"] == "已加载技能指令正文（含 2 个资源文件）"
    assert items[-1] == SkillExecutionResult(
        result={"success": True, "result": {"resources": ["one", "two"]}}
    )
    execute.assert_awaited_once_with(
        "use_skill",
        {"skill_id": "skill-1"},
        ANY,
        skill_pins={"skill-1": "1.0"},
    )
    record.assert_awaited_once()
    assert record.await_args.kwargs["status"] == "completed"


@pytest.mark.asyncio
async def test_skill_execution_records_failure_then_reraises() -> None:
    execute = AsyncMock(side_effect=RuntimeError("skill failed"))
    record = AsyncMock()

    with pytest.raises(RuntimeError, match="skill failed"):
        await _collect(
            tool_name="use_skill",
            arguments={"name": "skill-1"},
            tool_call_id="call-1",
            message_id="message-1",
            agent_name="Researcher",
            bound_skills=[],
            skill_pins=None,
            session_id="session-1",
            user_id="user-1",
            execute_skill_tool=execute,
            record_skill_invocation=record,
        )

    record.assert_awaited_once()
    assert record.await_args.kwargs["status"] == "failed"
    assert record.await_args.kwargs["error"] == "skill failed"
