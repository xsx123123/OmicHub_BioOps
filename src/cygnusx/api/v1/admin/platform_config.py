"""平台配置管理路由 — 管理员更新。

TOTP 二次校验仅对高敏感字段（注册开关 / TOTP 策略 / 首页快捷入口）强制；
功能灰度开关（如 subagent_fanout_enabled）等非敏感项免验，避免未开 2FA 的
管理员被无法填写的验证码弹窗挡死。
"""

from typing import Annotated

from fastapi import APIRouter, Header, Query

from cygnusx.api.deps import AdminRequired, DbSession, require_admin_totp
from cygnusx.application.schemas.site_settings import SiteSettingsDTO, UpdateSiteSettingsDTO
from cygnusx.application.services.agentteams_consultation_telemetry_service import (
    AgentTeamsConsultationTelemetryService,
)
from cygnusx.application.services.collaboration_observability_service import (
    CollaborationObservabilityService,
)
from cygnusx.application.services.site_settings_service import SiteSettingsService

router = APIRouter()

# 免 TOTP 的非敏感字段：仅这些字段被改动时无需二次校验
_NON_SENSITIVE_PLATFORM_KEYS = frozenset(
    {
        "subagent_fanout_enabled",
        "agentteams_chat_entry_enabled",
        "multi_expert_consultation_enabled",
        "unified_intent_router_enabled",
        "collaboration_preset",
        "collaboration_degradation_locale",
        "collaboration_degradation_template_zh",
        "collaboration_degradation_template_en",
        "agent_memory_enabled",
    }
)


@router.get("/platform-config/collaboration-observability", summary="协作能力近 7 天降级统计")
async def collaboration_observability(
    _admin: AdminRequired,
    db: DbSession,
) -> dict[str, object]:
    return {
        "days": 7,
        "degradation_counts": await CollaborationObservabilityService(db).degradation_counts(days=7),
        "consultation_quality": await AgentTeamsConsultationTelemetryService().summary(days=7),
    }


@router.get("/agentteams/consultation-telemetry", summary="AgentTeams 会诊质量遥测")
async def agentteams_consultation_telemetry(
    _admin: AdminRequired,
    days: int = Query(default=7, ge=1, le=30),
) -> dict[str, object]:
    return await AgentTeamsConsultationTelemetryService().summary(days=days)


@router.patch(
    "/platform-config",
    response_model=SiteSettingsDTO,
    summary="更新平台全局配置（管理员；敏感项需 TOTP）",
)
async def update_platform_config(
    req: UpdateSiteSettingsDTO,
    admin_id: AdminRequired,
    db: DbSession,
    x_totp_code: Annotated[str | None, Header(alias="X-TOTP-Code")] = None,
) -> SiteSettingsDTO:
    """管理员更新平台全局配置。

    本次改动若触及高敏感字段（注册开关 / TOTP 策略 / 首页快捷入口等），
    请求头须附带 X-TOTP-Code；若仅改动功能灰度开关等非敏感项则免验。
    """
    touched = req.model_fields_set
    if touched - _NON_SENSITIVE_PLATFORM_KEYS:
        # 复用既有敏感操作校验：管理员 + 已开 2FA + 验证码正确
        await require_admin_totp(admin_id, db, x_totp_code)
    return await SiteSettingsService(db).update_settings(req)
