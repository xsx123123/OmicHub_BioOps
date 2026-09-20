"""Low-overhead AgentTeams consultation quality telemetry."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger

from cygnusx.infrastructure.cache.redis_client import get_redis

_KEY_PREFIX = "cygnusx:agentteams:consultation_quality:"


class AgentTeamsConsultationTelemetryService:
    async def record_artifact_fetch(self, *, size_bytes: int) -> None:
        key = f"{_KEY_PREFIX}{datetime.now(UTC).date().isoformat()}"
        try:
            async with asyncio.timeout(0.1):
                async with get_redis().pipeline(transaction=True) as pipe:
                    pipe.hincrby(key, "evidence_verified", 1)
                    pipe.hincrby(key, "artifact_fetch_success", 1)
                    pipe.hincrby(key, "artifact_fetch_bytes", max(0, int(size_bytes)))
                    pipe.expire(key, 8 * 24 * 60 * 60)
                    await pipe.execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning("AgentTeams artifact fetch telemetry record failed: {}", exc)

    async def record(
        self,
        *,
        parse_success: bool,
        tool_call_count: int,
        evidence_requested: int,
        evidence_verified: int,
        qc_checked: bool,
        qc_consistent: bool,
    ) -> None:
        key = f"{_KEY_PREFIX}{datetime.now(UTC).date().isoformat()}"
        values = {
            "total": 1,
            "parse_success": int(parse_success),
            "tool_calls": max(0, tool_call_count),
            "evidence_requested": max(0, evidence_requested),
            "evidence_verified": max(0, evidence_verified),
            "qc_checked": int(qc_checked),
            "qc_consistent": int(qc_consistent),
        }
        try:
            async with asyncio.timeout(0.1):
                async with get_redis().pipeline(transaction=True) as pipe:
                    for field, value in values.items():
                        pipe.hincrby(key, field, value)
                    pipe.expire(key, 8 * 24 * 60 * 60)
                    await pipe.execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning("AgentTeams consultation telemetry record failed: {}", exc)

    async def summary(self, *, days: int = 7) -> dict[str, Any]:
        totals = {field: 0 for field in (
            "total", "parse_success", "tool_calls", "evidence_requested",
            "evidence_verified", "qc_checked", "qc_consistent",
        )}
        try:
            async with asyncio.timeout(0.5):
                redis = get_redis()
                for offset in range(max(1, min(days, 30))):
                    date = (datetime.now(UTC).date() - timedelta(days=offset)).isoformat()
                    row = await redis.hgetall(f"{_KEY_PREFIX}{date}")
                    for field in totals:
                        totals[field] += int(row.get(field) or 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("AgentTeams consultation telemetry summary failed: {}", exc)
        total = totals["total"]
        requested = totals["evidence_requested"]
        qc_checked = totals["qc_checked"]
        return {
            **totals,
            "parse_success_rate": totals["parse_success"] / total if total else 0.0,
            "evidence_hit_rate": totals["evidence_verified"] / requested if requested else 0.0,
            "qc_consistency_rate": totals["qc_consistent"] / qc_checked if qc_checked else 0.0,
            "average_tool_calls": totals["tool_calls"] / total if total else 0.0,
        }


__all__ = ["AgentTeamsConsultationTelemetryService"]
