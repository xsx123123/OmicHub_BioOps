"""Best-effort persistent recording for AgentTeams LLM turns."""

from __future__ import annotations

import asyncio
import copy
import json
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.core.agentteams_context import agentteams_ctx_var
from cygnusx.infrastructure.database.models.chat import AgentTeamsTurnRecordModel
from cygnusx.infrastructure.database.session import get_session_factory
from cygnusx.infrastructure.storage.minio_store import MinioStore


class AgentTeamsTurnRecorder:
    """Schedules durable turn capture without coupling LLM latency to storage availability."""

    @staticmethod
    def schedule(
        *,
        messages: list[dict[str, Any]],
        output_text: str,
        reasoning_text: str | None,
        tool_calls: list[dict[str, Any]],
        usage: dict[str, Any] | None,
        duration_ms: int,
        finish_reason: str,
        status: str,
        error: str | None,
        child_session_id: str,
        provider: str,
        model: str,
        sampling: dict[str, Any],
    ) -> str | None:
        context = agentteams_ctx_var.get()
        if not context or not context.get("case_id"):
            return None
        case_id = str(context["case_id"])
        work_item_id = str(context.get("work_item_id") or "case")
        round_number = int(context.get("round_number") or 1)
        record_id = uuid4()
        call_seq = int(context.get("call_seq") or 1)
        key = (
            f"turns/{work_item_id}/{round_number:04d}/"
            f"call-{call_seq:02d}-{record_id}.json"
        )
        span_id = context.get("span_id")
        if not span_id:
            try:
                from opentelemetry import trace

                span_context = trace.get_current_span().get_span_context()
                if span_context.is_valid:
                    span_id = f"{span_context.span_id:016x}"
            except Exception:  # noqa: BLE001 - telemetry must not block process recording
                span_id = None
        uri = f"s3://{MinioStore(probe=False).bucket}/cases/{case_id}/{key}"
        payload = {
            "record_id": str(record_id),
            "recorded_at": datetime.now(UTC).isoformat(),
            "case_id": case_id,
            "work_item_id": work_item_id,
            "agent_id": str(context.get("agent_id") or ""),
            "round_number": round_number,
            "call_seq": call_seq,
            "child_session_id": child_session_id,
            "requester_ref": context.get("requester_ref"),
            "actor_user_id": context.get("actor_user_id"),
            "trace_id": context.get("trace_id"),
            "span_id": span_id,
            "provider": provider,
            "model": model,
            "sampling": copy.deepcopy(sampling),
            "messages": copy.deepcopy(messages),
            "output_text": output_text,
            "reasoning_text": reasoning_text or None,
            "tool_calls": copy.deepcopy(tool_calls),
            "usage": copy.deepcopy(usage) if usage else {},
            "duration_ms": duration_ms,
            "finish_reason": finish_reason,
            "status": status,
            "error": error,
        }
        asyncio.create_task(
            AgentTeamsTurnRecorder._persist(
                payload=payload, record_id=record_id, call_seq=call_seq, key=key, uri=uri
            )
        )
        return uri

    @staticmethod
    async def _persist(
        *, payload: dict[str, Any], record_id: Any, call_seq: int, key: str, uri: str
    ) -> None:
        path: Path | None = None
        try:
            started = time.monotonic()
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False) as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                path = Path(handle.name)
            await asyncio.to_thread(
                MinioStore(probe=False).put_turn_record,
                str(payload["case_id"]),
                key,
                path,
            )
            usage = payload.get("usage") or {}
            async with get_session_factory()() as session:
                session: AsyncSession
                session.add(
                    AgentTeamsTurnRecordModel(
                        record_id=record_id,
                        case_id=str(payload["case_id"]),
                        work_item_id=str(payload["work_item_id"]),
                        round_number=int(payload["round_number"]),
                        call_seq=call_seq,
                        agent_id=str(payload["agent_id"]),
                        actor_user_id=payload.get("actor_user_id"),
                        requester_ref=payload.get("requester_ref"),
                        provider=str(payload.get("provider") or ""),
                        model=str(payload.get("model") or ""),
                        prompt_tokens=usage.get("prompt_tokens"),
                        completion_tokens=usage.get("completion_tokens"),
                        total_tokens=usage.get("total_tokens"),
                        duration_ms=int(payload.get("duration_ms") or 0),
                        status=str(payload["status"]),
                        s3_uri=uri,
                        recorded_at=datetime.fromisoformat(str(payload["recorded_at"])),
                    )
                )
                await session.commit()
            logger.bind(case_id=payload["case_id"], record_id=str(record_id)).debug(
                "AgentTeams turn recorded in {:.1f}ms", (time.monotonic() - started) * 1000
            )
        except Exception as exc:  # noqa: BLE001 - recording must never fail the model path
            logger.bind(case_id=payload.get("case_id"), record_id=str(record_id)).warning(
                "AgentTeams turn record persistence failed (object/index may be incomplete): {}", exc
            )
        finally:
            if path is not None:
                path.unlink(missing_ok=True)
