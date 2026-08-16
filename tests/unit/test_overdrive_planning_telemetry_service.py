from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import omichub.application.services.overdrive_planning_telemetry_service as telemetry_module
from omichub.application.services.overdrive_planning_telemetry_service import (
    OverdrivePlanningTelemetryService,
)


class FakePipeline:
    def __init__(self, row: dict[str, int]) -> None:
        self.row = row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def hincrby(self, _key: str, field: str, value: int) -> None:
        self.row[field] = self.row.get(field, 0) + value

    def expire(self, _key: str, _seconds: int) -> None:
        return None

    async def execute(self) -> None:
        return None


class FakeRedis:
    def __init__(self) -> None:
        self.row: dict[str, int] = {}

    def pipeline(self, *, transaction: bool = True) -> FakePipeline:
        assert transaction is True
        return FakePipeline(self.row)

    async def hgetall(self, _key: str) -> dict[str, int]:
        return dict(self.row)

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_planning_telemetry_records_mode_repair_and_zero_speech_override(monkeypatch) -> None:
    redis = FakeRedis()
    monkeypatch.setattr(telemetry_module, "get_redis", lambda: redis)
    service = OverdrivePlanningTelemetryService()

    await service.record(planning_mode="llm_repaired", repair_outcome="success")
    summary = await service.summary(days=1)

    assert summary["overdrive_planning_total:llm_repaired"] == 1
    assert summary["overdrive_plan_repair_total:success"] == 1
    assert summary["overdrive_llm_speech_overridden_total"] == 0


@pytest.mark.asyncio
async def test_planning_telemetry_exposes_ten_run_mode_distribution(monkeypatch) -> None:
    redis = FakeRedis()
    monkeypatch.setattr(telemetry_module, "get_redis", lambda: redis)
    service = OverdrivePlanningTelemetryService()

    for mode in ["llm"] * 6 + ["llm_repaired"] * 2 + ["rule_merge", "rule_preflight"]:
        await service.record(planning_mode=mode)

    summary = await service.summary(days=1)

    assert summary["overdrive_planning_total:llm"] == 6
    assert summary["overdrive_planning_total:llm_repaired"] == 2
    assert summary["overdrive_planning_total:rule_merge"] == 1
    assert summary["overdrive_planning_total:rule_preflight"] == 1
    assert summary["overdrive_llm_speech_overridden_total"] == 0


@pytest.mark.asyncio
async def test_runtime_telemetry_uses_resolved_short_lived_client(monkeypatch) -> None:
    redis = FakeRedis()
    monkeypatch.setattr(telemetry_module, "_resolve_host_fast", lambda _host: "127.0.0.1")
    monkeypatch.setattr(telemetry_module.redis, "Redis", lambda **_kwargs: redis)

    await OverdrivePlanningTelemetryService().record_runtime(
        planning_mode="rule_merge",
        repair_outcome="failed",
    )

    assert redis.row["overdrive_planning_total:rule_merge"] == 1
    assert redis.row["overdrive_plan_repair_total:failed"] == 1
    assert redis.row["overdrive_llm_speech_overridden_total"] == 0


@pytest.mark.asyncio
async def test_runtime_telemetry_skips_unresolved_host_without_redis_client(monkeypatch) -> None:
    monkeypatch.setattr(telemetry_module, "_resolve_host_fast", lambda _host: None)
    constructor = MagicMock()
    monkeypatch.setattr(telemetry_module.redis, "Redis", constructor)

    await OverdrivePlanningTelemetryService().record_runtime(planning_mode="llm")

    constructor.assert_not_called()
