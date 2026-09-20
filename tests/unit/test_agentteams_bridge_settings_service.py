"""AgentTeams Bridge 管理配置的脱敏、回退与校验测试。"""

from __future__ import annotations

import pytest

from cygnusx.application.schemas.agentteams_bridge import AgentTeamsBridgeConfigUpdateDTO
from cygnusx.application.services.agentteams_bridge_settings_service import (
    MASKED_SECRET,
    AgentTeamsBridgeSettingsService,
)
from cygnusx.core.config import Settings
from cygnusx.core.exceptions import BusinessError
from cygnusx.infrastructure.database.models.agentteams_bridge import AgentTeamsBridgeSettingsModel


class FakeSession:
    def __init__(self) -> None:
        self.model: AgentTeamsBridgeSettingsModel | None = None

    async def get(self, model_type, identifier):
        assert model_type is AgentTeamsBridgeSettingsModel
        assert identifier == 1
        return self.model

    def add(self, model: AgentTeamsBridgeSettingsModel) -> None:
        self.model = model

    async def flush(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


def bridge_settings(**overrides: object) -> Settings:
    values = {
        "agentteams_bridge_enabled": True,
        "agentteams_bridge_url": "http://bridge.test",
        "agentteams_bridge_manager_token": "manager-env-token",
        "agentteams_bridge_data_steward_token": "steward-env-token",
        "agentteams_bridge_approval_token": "approval-env-token",
        "agentteams_bridge_workflow_operator_token": "operator-env-token",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_public_config_uses_environment_fallback_and_masks_tokens() -> None:
    service = AgentTeamsBridgeSettingsService(FakeSession(), bridge_settings())  # type: ignore[arg-type]

    config = await service.get_public_config()

    assert config.source == "environment"
    assert config.configured is True
    assert config.manager_token == MASKED_SECRET
    assert config.workflow_operator_token == MASKED_SECRET


@pytest.mark.asyncio
async def test_empty_disabled_database_placeholder_keeps_environment_fallback() -> None:
    session = FakeSession()
    session.model = AgentTeamsBridgeSettingsModel(id=1)
    service = AgentTeamsBridgeSettingsService(session, bridge_settings())  # type: ignore[arg-type]

    config = await service.get_public_config()

    assert config.source == "environment"
    assert config.enabled is True
    assert config.configured is True


@pytest.mark.asyncio
async def test_disabled_database_config_with_values_remains_an_explicit_override() -> None:
    session = FakeSession()
    session.model = AgentTeamsBridgeSettingsModel(
        id=1,
        enabled=False,
        bridge_url="http://bridge.database",
        manager_token="encrypted-manager",
        data_steward_token="encrypted-steward",
        approval_token="encrypted-approval",
        workflow_operator_token="encrypted-operator",
        timeout_seconds=10,
    )
    service = AgentTeamsBridgeSettingsService(session, bridge_settings())  # type: ignore[arg-type]

    config = await service.get_public_config()

    assert config.source == "database"
    assert config.enabled is False


@pytest.mark.asyncio
async def test_update_persists_database_config_and_preserves_masked_tokens() -> None:
    session = FakeSession()
    service = AgentTeamsBridgeSettingsService(session, bridge_settings())  # type: ignore[arg-type]
    update = AgentTeamsBridgeConfigUpdateDTO(
        enabled=True,
        bridge_url="http://bridge.database",
        timeout_seconds=15,
        manager_token=MASKED_SECRET,
        data_steward_token=MASKED_SECRET,
        approval_token=MASKED_SECRET,
        workflow_operator_token=MASKED_SECRET,
    )

    result = await service.update_config(update)
    runtime = await service.get_runtime_config()

    assert result.source == "database"
    assert result.manager_token == MASKED_SECRET
    assert runtime.bridge_url == "http://bridge.database"
    assert runtime.manager_token == "manager-env-token"
    assert runtime.timeout_seconds == 15


@pytest.mark.asyncio
async def test_enabled_config_requires_all_worker_tokens() -> None:
    service = AgentTeamsBridgeSettingsService(
        FakeSession(),
        bridge_settings(agentteams_bridge_manager_token=""),  # type: ignore[arg-type]
    )

    with pytest.raises(BusinessError, match="四个 Worker 身份令牌"):
        await service.update_config(
            AgentTeamsBridgeConfigUpdateDTO(
                enabled=True,
                bridge_url="http://bridge.test",
            )
        )


@pytest.mark.asyncio
async def test_update_clears_a_legacy_element_room_url() -> None:
    session = FakeSession()
    session.model = AgentTeamsBridgeSettingsModel(
        id=1,
        element_url="https://element.example/#/room/!legacy:example.org",
    )
    service = AgentTeamsBridgeSettingsService(session, bridge_settings())  # type: ignore[arg-type]

    await service.update_config(AgentTeamsBridgeConfigUpdateDTO(enabled=False))

    assert session.model is not None
    assert session.model.element_url == ""
