from unittest.mock import AsyncMock

import pytest

from cygnusx.api.v1.admin import agentteams_bridge
from cygnusx.application.schemas.agentteams_bridge import AgentTeamsWorkerTokenIssueDTO


class _FakeSettingsService:
    def __init__(self, *_args: object) -> None:
        pass

    async def get_runtime_config(self) -> object:
        return object()


@pytest.fixture
def proxy_mocks(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    mocks = {
        "issue": AsyncMock(return_value={"token": "omw_raw", "record": {"token_id": "t-1"}}),
        "list": AsyncMock(return_value=[{"token_id": "t-1", "identity": "agent-code"}]),
        "revoke": AsyncMock(return_value={"token_id": "t-1", "revoked_at": "2026-08-12T00:00:00Z"}),
    }

    class FakeAgentTeamsService:
        def __init__(self, *_args: object) -> None:
            pass

        admin_issue_worker_token = mocks["issue"]
        admin_list_worker_tokens = mocks["list"]
        admin_revoke_worker_token = mocks["revoke"]

    monkeypatch.setattr(agentteams_bridge, "require_admin_totp", AsyncMock())
    monkeypatch.setattr(agentteams_bridge, "AgentTeamsService", FakeAgentTeamsService)
    monkeypatch.setattr(agentteams_bridge, "AgentTeamsBridgeSettingsService", _FakeSettingsService)
    return mocks


@pytest.mark.asyncio
async def test_issue_worker_token_requires_totp_and_proxies(proxy_mocks) -> None:
    require_totp = agentteams_bridge.require_admin_totp
    result = await agentteams_bridge.issue_agentteams_worker_token(
        request=AgentTeamsWorkerTokenIssueDTO(
            identity="agent-code", ttl_seconds=3600, note="pool-1"
        ),
        db=object(),
        _admin_id="admin-1",
        x_totp_code="123456",
    )
    require_totp.assert_awaited_once()
    proxy_mocks["issue"].assert_awaited_once_with(
        identity="agent-code", ttl_seconds=3600, note="pool-1"
    )
    assert result["token"] == "omw_raw"


@pytest.mark.asyncio
async def test_list_worker_tokens_is_read_only_and_proxies(proxy_mocks) -> None:
    require_totp = agentteams_bridge.require_admin_totp
    result = await agentteams_bridge.list_agentteams_worker_tokens(
        _admin="admin-1", service=_FakeSettingsService()
    )
    require_totp.assert_not_awaited()
    proxy_mocks["list"].assert_awaited_once_with()
    assert result == {"items": [{"token_id": "t-1", "identity": "agent-code"}]}


@pytest.mark.asyncio
async def test_revoke_worker_token_requires_totp_and_proxies(proxy_mocks) -> None:
    require_totp = agentteams_bridge.require_admin_totp
    result = await agentteams_bridge.revoke_agentteams_worker_token(
        token_id="t-1",
        db=object(),
        _admin_id="admin-1",
        x_totp_code="123456",
    )
    require_totp.assert_awaited_once()
    proxy_mocks["revoke"].assert_awaited_once_with("t-1")
    assert result["revoked_at"]
