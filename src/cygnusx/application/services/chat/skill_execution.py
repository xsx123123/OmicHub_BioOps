"""Skill tool execution and lifecycle event streaming."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from cygnusx.domain.skill.services import USE_SKILL_TOOL_NAME
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk


@dataclass(frozen=True)
class SkillExecutionResult:
    """Final tool result emitted after any Skill lifecycle chunks."""

    result: dict[str, Any]


async def stream_skill_execution(
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    tool_call_id: str,
    message_id: str,
    agent_name: str,
    bound_skills: Sequence[Any],
    skill_pins: Any,
    session_id: str,
    user_id: str,
    execute_skill_tool: Callable[..., Awaitable[dict[str, Any]]],
    record_skill_invocation: Callable[..., Awaitable[None]],
) -> AsyncIterator[ChatChunk | SkillExecutionResult]:
    """Execute a Skill tool while preserving its existing user-visible lifecycle."""
    skill_key = str(arguments.get("skill_id") or arguments.get("name") or "").strip()
    bound_skill = next(
        (
            skill
            for skill in bound_skills
            if skill.skill_id == skill_key or skill.name == skill_key
        ),
        None,
    )
    skill_metadata = {
        "skill_id": bound_skill.skill_id if bound_skill else skill_key,
        "name": bound_skill.name if bound_skill else skill_key,
        "version": (bound_skill.version if bound_skill else "") or "",
        "source": (bound_skill.source_type if bound_skill else "") or "",
        "icon": (bound_skill.icon if bound_skill else "") or "",
    }
    emit_event = tool_name == USE_SKILL_TOOL_NAME
    if emit_event:
        yield ChatChunk(
            type="skill",
            metadata={
                "phase": "invoked",
                "tool_call_id": tool_call_id,
                "message_id": message_id,
                "agent": agent_name,
                **skill_metadata,
            },
        )

    started = time.perf_counter()
    execution_error: Exception | None = None
    try:
        result = await execute_skill_tool(
            tool_name,
            dict(arguments),
            bound_skills,
            skill_pins=skill_pins,
        )
    except Exception as exc:  # noqa: BLE001
        execution_error = exc
        result = {"success": False, "error": str(exc)}

    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    if emit_event:
        succeeded = bool(result.get("success"))
        resources = ((result.get("result") or {}).get("resources")) or []
        summary = (
            "已加载技能指令正文"
            + (f"（含 {len(resources)} 个资源文件）" if resources else "")
            if succeeded
            else ""
        )
        error = "" if succeeded else str(result.get("error") or "")
        yield ChatChunk(
            type="skill",
            metadata={
                "phase": "completed" if succeeded else "failed",
                "tool_call_id": tool_call_id,
                "message_id": message_id,
                "duration_ms": duration_ms,
                "summary": summary,
                "error": error,
                **skill_metadata,
            },
        )
        await record_skill_invocation(
            skill_meta=skill_metadata,
            status="completed" if succeeded else "failed",
            duration_ms=duration_ms,
            summary=summary,
            error=error,
            session_id=session_id,
            message_id=message_id,
            user_id=user_id,
        )

    if execution_error is not None:
        raise execution_error
    yield SkillExecutionResult(result=result)
