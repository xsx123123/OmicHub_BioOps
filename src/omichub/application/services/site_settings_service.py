"""站点设置应用服务 — 单行配置的读取与更新"""

from __future__ import annotations

import logging
from typing import Any, cast

from pydantic import TypeAdapter
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.schemas.site_settings import (
    CollaborationDegradationLocale,
    CollaborationPreset,
    HomeQuickEntryDTO,
    SiteSettingsDTO,
    TOTPPolicy,
    UpdateSiteSettingsDTO,
)
from omichub.core.exceptions import BusinessError
from omichub.infrastructure.database.models.site_settings import SiteSettingModel

logger = logging.getLogger(__name__)

DEFAULT_COLLABORATION_DEGRADATION_TEMPLATE_ZH = (
    "此请求适合“{intent}”，但当前未启用 {setting}。{alternative}"
)
DEFAULT_COLLABORATION_DEGRADATION_TEMPLATE_EN = (
    "This request is best handled as {intent}, but {setting} is not enabled. {alternative}"
)

DEFAULT_HOME_QUICK_ENTRIES: list[dict[str, str]] = [
    {
        "key": "rna-seq",
        "title": "RNA-seq 分析",
        "desc": "转录组差异表达分析",
        "to": "/flows?type=rna-seq",
        "icon": "FlaskOutline",
        "icon_bg": "blue",
    },
    {
        "key": "atac-seq",
        "title": "ATAC-seq 分析",
        "desc": "染色质开放性分析",
        "to": "/flows?type=atac-seq",
        "icon": "FitnessOutline",
        "icon_bg": "purple",
    },
    {
        "key": "files",
        "title": "数据管理",
        "desc": "上传与管理样本数据",
        "to": "/files",
        "icon": "CloudUploadOutline",
        "icon_bg": "cyan",
    },
    {
        "key": "ai",
        "title": "星尘AI",
        "desc": "对话式生信分析与结果解读",
        "to": "/ai",
        "icon": "SparklesOutline",
        "icon_bg": "violet",
    },
    {
        "key": "tasks",
        "title": "任务中心",
        "desc": "查看分析任务进度",
        "to": "/tasks",
        "icon": "DocumentTextOutline",
        "icon_bg": "orange",
    },
]

_HOME_QUICK_ENTRY_ADAPTER = TypeAdapter(list[HomeQuickEntryDTO])


def _default_home_quick_entries() -> list[dict[str, str]]:
    return [dict(entry) for entry in DEFAULT_HOME_QUICK_ENTRIES]


def _normalize_home_quick_entries(value: Any) -> list[HomeQuickEntryDTO]:
    """校验 DB 中的快捷入口配置；空值或坏数据回退默认值。"""
    if not isinstance(value, list) or not value:
        return _HOME_QUICK_ENTRY_ADAPTER.validate_python(_default_home_quick_entries())
    try:
        entries = _HOME_QUICK_ENTRY_ADAPTER.validate_python(value)
    except Exception:
        return _HOME_QUICK_ENTRY_ADAPTER.validate_python(_default_home_quick_entries())
    normalized = entries[:8]
    return normalized or _HOME_QUICK_ENTRY_ADAPTER.validate_python(_default_home_quick_entries())


class SiteSettingsService:
    """站点设置服务"""

    _SINGLETON_ID = 1

    def __init__(self, db: AsyncSession):
        self._db = db

    async def _get_or_create(self) -> SiteSettingModel:
        try:
            model = await self._db.get(SiteSettingModel, self._SINGLETON_ID)
            if model is None:
                model = SiteSettingModel(
                    id=self._SINGLETON_ID,
                    registration_enabled=True,
                    totp_policy="optional",
                    home_quick_entries=_default_home_quick_entries(),
                )
                self._db.add(model)
                await self._db.flush()
            return model
        except SQLAlchemyError as exc:
            logger.exception(f"读取站点设置数据库错误: {exc}")
            await self._db.rollback()
            raise BusinessError("读取平台配置失败，请稍后重试") from exc

    async def get_settings(self) -> SiteSettingsDTO:
        model = await self._get_or_create()
        policy = (
            model.totp_policy
            if model.totp_policy in ("off", "optional", "required")
            else "optional"
        )
        return SiteSettingsDTO(
            registration_enabled=model.registration_enabled,
            totp_policy=cast(TOTPPolicy, policy),
            home_quick_entries=_normalize_home_quick_entries(model.home_quick_entries),
            subagent_fanout_enabled=model.subagent_fanout_enabled,
            agentteams_chat_entry_enabled=model.agentteams_chat_entry_enabled,
            collaboration_preset=cast(
                CollaborationPreset,
                model.collaboration_preset
                if model.collaboration_preset in ("custom", "light", "parallel", "full")
                else "custom",
            ),
            multi_expert_consultation_enabled=model.multi_expert_consultation_enabled,
            unified_intent_router_enabled=model.unified_intent_router_enabled,
            collaboration_degradation_locale=cast(
                CollaborationDegradationLocale,
                model.collaboration_degradation_locale
                if model.collaboration_degradation_locale in ("zh-CN", "en")
                else "zh-CN",
            ),
            collaboration_degradation_template_zh=(
                model.collaboration_degradation_template_zh
                or DEFAULT_COLLABORATION_DEGRADATION_TEMPLATE_ZH
            ),
            collaboration_degradation_template_en=(
                model.collaboration_degradation_template_en
                or DEFAULT_COLLABORATION_DEGRADATION_TEMPLATE_EN
            ),
            agent_memory_enabled=model.agent_memory_enabled,
        )

    async def is_registration_enabled(self) -> bool:
        model = await self._get_or_create()
        return model.registration_enabled

    async def is_subagent_fanout_enabled(self) -> bool:
        """管理端平台设置中的 fan-out 开关（与 env 开关任一为真即启用）。"""
        model = await self._get_or_create()
        return model.subagent_fanout_enabled

    async def is_agentteams_chat_entry_enabled(self) -> bool:
        model = await self._get_or_create()
        return model.agentteams_chat_entry_enabled

    async def is_agent_memory_enabled(self) -> bool:
        """Agent 长期记忆运行时开关（管理端；与 env MEM0_ENGINE_ENABLED 同时为真才启用）。"""
        model = await self._get_or_create()
        return model.agent_memory_enabled

    async def get_totp_policy(self) -> TOTPPolicy:
        model = await self._get_or_create()
        policy = model.totp_policy
        if policy not in ("off", "optional", "required"):
            return "optional"
        return cast(TOTPPolicy, policy)

    async def update_settings(self, req: UpdateSiteSettingsDTO) -> SiteSettingsDTO:
        try:
            model = await self._get_or_create()
            if req.registration_enabled is not None:
                model.registration_enabled = req.registration_enabled
            if req.totp_policy is not None:
                model.totp_policy = req.totp_policy
            if req.subagent_fanout_enabled is not None:
                model.subagent_fanout_enabled = req.subagent_fanout_enabled
            if req.agentteams_chat_entry_enabled is not None:
                model.agentteams_chat_entry_enabled = req.agentteams_chat_entry_enabled
            if req.multi_expert_consultation_enabled is not None:
                model.multi_expert_consultation_enabled = req.multi_expert_consultation_enabled
            if req.unified_intent_router_enabled is not None:
                model.unified_intent_router_enabled = req.unified_intent_router_enabled
            if req.collaboration_preset is not None:
                model.collaboration_preset = req.collaboration_preset
                if req.collaboration_preset == "light":
                    model.subagent_fanout_enabled = False
                    model.agentteams_chat_entry_enabled = False
                    model.multi_expert_consultation_enabled = True
                    model.unified_intent_router_enabled = True
                elif req.collaboration_preset == "parallel":
                    model.subagent_fanout_enabled = True
                    model.agentteams_chat_entry_enabled = False
                    model.multi_expert_consultation_enabled = True
                    model.unified_intent_router_enabled = True
                elif req.collaboration_preset == "full":
                    model.subagent_fanout_enabled = True
                    model.agentteams_chat_entry_enabled = True
                    model.multi_expert_consultation_enabled = True
                    model.unified_intent_router_enabled = True
            if req.collaboration_degradation_locale is not None:
                model.collaboration_degradation_locale = req.collaboration_degradation_locale
            if req.collaboration_degradation_template_zh is not None:
                model.collaboration_degradation_template_zh = req.collaboration_degradation_template_zh
            if req.collaboration_degradation_template_en is not None:
                model.collaboration_degradation_template_en = req.collaboration_degradation_template_en
            if req.agent_memory_enabled is not None:
                model.agent_memory_enabled = req.agent_memory_enabled
            if req.home_quick_entries is not None:
                model.home_quick_entries = [entry.model_dump() for entry in req.home_quick_entries]
            await self._db.flush()
            return await self.get_settings()
        except SQLAlchemyError as exc:
            logger.exception(f"更新站点设置数据库错误: {exc}")
            await self._db.rollback()
            raise BusinessError("保存平台配置失败，请稍后重试") from exc
