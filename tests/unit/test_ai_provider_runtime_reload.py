import pytest

import cygnusx.api.v1.admin.ai_providers as module
from cygnusx.core.config import ContextCompactionSettings


@pytest.mark.asyncio
async def test_reload_runtime_config_returns_only_compaction_settings(monkeypatch) -> None:
    settings = type(
        "SettingsStub",
        (),
        {"context_compaction": ContextCompactionSettings(
            trigger_ratio=0.8,
            large_output_chars=123,
            preview_chars=45,
            keep_recent_min=4,
            tail_ratio=0.25,
            min_yield_ratio=0.1,
            breaker_attempts=2,
            circuit_retry_growth=1.5,
            min_messages=12,
            summary_max_chars=6000,
            legacy_fallback=False,
        )},
    )()
    monkeypatch.setattr(module, "reload_settings", lambda: settings)

    payload = await module.reload_runtime_config(None)

    assert payload == {
        "reloaded": True,
        "context_compaction": settings.context_compaction.model_dump(),
    }
    assert "openai_api_key" not in payload
