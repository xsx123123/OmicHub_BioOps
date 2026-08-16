"""协作档位与降级文案平台设置测试。"""

from __future__ import annotations

import pytest

from omichub.application.schemas.site_settings import UpdateSiteSettingsDTO
from omichub.application.services.site_settings_service import (
    DEFAULT_COLLABORATION_DEGRADATION_TEMPLATE_EN,
    DEFAULT_COLLABORATION_DEGRADATION_TEMPLATE_ZH,
    SiteSettingsService,
)
from omichub.infrastructure.database.models.site_settings import SiteSettingModel


class FakeSession:
    def __init__(self) -> None:
        self.model = SiteSettingModel(
            id=1,
            registration_enabled=True,
            totp_policy="optional",
            home_quick_entries=[],
            subagent_fanout_enabled=False,
            agentteams_chat_entry_enabled=False,
            multi_expert_consultation_enabled=False,
            unified_intent_router_enabled=False,
            collaboration_preset="custom",
            collaboration_degradation_locale="zh-CN",
            collaboration_degradation_template_zh="",
            collaboration_degradation_template_en="",
        )

    async def get(self, model_type, identifier):
        assert model_type is SiteSettingModel
        assert identifier == 1
        return self.model

    def add(self, model) -> None:
        self.model = model

    async def flush(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("preset", "fanout", "case_entry"),
    [
        ("light", False, False),
        ("parallel", True, False),
        ("full", True, True),
    ],
)
async def test_collaboration_presets_write_expected_switches(
    preset: str, fanout: bool, case_entry: bool
) -> None:
    session = FakeSession()
    result = await SiteSettingsService(session).update_settings(  # type: ignore[arg-type]
        UpdateSiteSettingsDTO(collaboration_preset=preset)
    )

    assert result.collaboration_preset == preset
    assert result.unified_intent_router_enabled is True
    assert result.multi_expert_consultation_enabled is True
    assert result.subagent_fanout_enabled is fanout
    assert result.agentteams_chat_entry_enabled is case_entry


@pytest.mark.asyncio
async def test_degradation_templates_have_safe_defaults_and_persist() -> None:
    session = FakeSession()
    service = SiteSettingsService(session)  # type: ignore[arg-type]

    defaults = await service.get_settings()
    assert defaults.collaboration_degradation_template_zh == DEFAULT_COLLABORATION_DEGRADATION_TEMPLATE_ZH
    assert defaults.collaboration_degradation_template_en == DEFAULT_COLLABORATION_DEGRADATION_TEMPLATE_EN

    result = await service.update_settings(
        UpdateSiteSettingsDTO(
            collaboration_degradation_locale="en",
            collaboration_degradation_template_zh="ZH {intent}",
            collaboration_degradation_template_en="EN {intent} {setting} {alternative}",
        )
    )
    assert result.collaboration_degradation_locale == "en"
    assert result.collaboration_degradation_template_zh == "ZH {intent}"
    assert result.collaboration_degradation_template_en.startswith("EN {intent}")
