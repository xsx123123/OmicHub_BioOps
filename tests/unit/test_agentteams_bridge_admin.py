from unittest.mock import AsyncMock

import pytest

from cygnusx.api.v1.admin import agentteams_bridge


@pytest.mark.asyncio
async def test_generate_agentteams_bridge_tokens_returns_distinct_one_time_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_totp = AsyncMock()
    monkeypatch.setattr(agentteams_bridge, "require_admin_totp", require_totp)
    db = object()

    tokens = await agentteams_bridge.generate_agentteams_bridge_tokens(
        db=db,
        _admin_id="admin-1",
        x_totp_code="123456",
    )

    require_totp.assert_awaited_once_with("admin-1", db, "123456")
    values = {
        tokens.manager_token,
        tokens.data_steward_token,
        tokens.approval_token,
        tokens.workflow_operator_token,
    }
    assert len(values) == 4
    assert all(len(value) >= 40 for value in values)
