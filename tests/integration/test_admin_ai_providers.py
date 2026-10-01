"""Admin AI provider runtime reload HTTP contract."""

from types import SimpleNamespace

import pytest

from cygnusx.api.v1.admin import ai_providers
from cygnusx.core.config import ContextCompactionSettings
from cygnusx.core.security import create_access_token
from cygnusx.main import app
from cygnusx.middleware.rbac import require_admin

pytestmark = pytest.mark.integration


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token = create_access_token("test-user")
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_runtime_reload_http_contract(client, auth_headers, monkeypatch) -> None:
    settings = SimpleNamespace(
        context_compaction=ContextCompactionSettings(
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
        )
    )
    monkeypatch.setattr(ai_providers, "reload_settings", lambda: settings)

    async def _allow_admin() -> None:
        return None

    app.dependency_overrides[require_admin] = _allow_admin
    try:
        response = await client.post(
            "/api/v1/admin/ai-providers/runtime/reload",
            headers=auth_headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["reloaded"] is True
    assert body["context_compaction"]["trigger_ratio"] == 0.8
    assert "openai_api_key" not in body
