"""持久化的 AgentTeams Bridge 配置与安全运行时解析。"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.schemas.agentteams_bridge import (
    AgentTeamsBridgeConfigDTO,
    AgentTeamsBridgeConfigUpdateDTO,
)
from omichub.core.config import Settings
from omichub.core.exceptions import BusinessError
from omichub.core.security import decrypt_value, encrypt_value
from omichub.infrastructure.database.models.agentteams_bridge import AgentTeamsBridgeSettingsModel

MASKED_SECRET = "********"


@dataclass(frozen=True)
class AgentTeamsBridgeRuntimeConfig:
    enabled: bool
    bridge_url: str
    manager_token: str
    data_steward_token: str
    approval_token: str
    workflow_operator_token: str
    timeout_seconds: float
    source: str

    @classmethod
    def from_settings(cls, settings: Settings) -> AgentTeamsBridgeRuntimeConfig:
        return cls(
            enabled=settings.agentteams_bridge_enabled,
            bridge_url=settings.agentteams_bridge_url,
            manager_token=settings.agentteams_bridge_manager_token,
            data_steward_token=settings.agentteams_bridge_data_steward_token,
            approval_token=settings.agentteams_bridge_approval_token,
            workflow_operator_token=settings.agentteams_bridge_workflow_operator_token,
            timeout_seconds=settings.agentteams_bridge_timeout_seconds,
            source="environment",
        )

    @property
    def configured(self) -> bool:
        return bool(
            self.bridge_url
            and self.manager_token
            and self.data_steward_token
            and self.approval_token
            and self.workflow_operator_token
        )


class AgentTeamsBridgeSettingsService:
    """读取并保存全局 Bridge 配置；浏览器只看到脱敏后的凭证状态。"""

    _SINGLETON_ID = 1

    def __init__(self, db: AsyncSession, settings: Settings):
        self._db = db
        self._settings = settings

    async def get_runtime_config(self) -> AgentTeamsBridgeRuntimeConfig:
        model = await self._db.get(AgentTeamsBridgeSettingsModel, self._SINGLETON_ID)
        if model is None or self._is_empty_initial_model(model):
            return AgentTeamsBridgeRuntimeConfig.from_settings(self._settings)
        return self._runtime_from_model(model)

    async def get_public_config(self) -> AgentTeamsBridgeConfigDTO:
        return self._to_dto(await self.get_runtime_config())

    async def update_config(
        self,
        request: AgentTeamsBridgeConfigUpdateDTO,
    ) -> AgentTeamsBridgeConfigDTO:
        try:
            model = await self._db.get(AgentTeamsBridgeSettingsModel, self._SINGLETON_ID)
            existing = (
                self._runtime_from_model(model)
                if model is not None
                else AgentTeamsBridgeRuntimeConfig.from_settings(self._settings)
            )
            runtime = AgentTeamsBridgeRuntimeConfig(
                enabled=request.enabled,
                bridge_url=request.bridge_url.strip(),
                manager_token=self._resolve_secret(request.manager_token, existing.manager_token),
                data_steward_token=self._resolve_secret(
                    request.data_steward_token, existing.data_steward_token
                ),
                approval_token=self._resolve_secret(
                    request.approval_token, existing.approval_token
                ),
                workflow_operator_token=self._resolve_secret(
                    request.workflow_operator_token,
                    existing.workflow_operator_token,
                ),
                timeout_seconds=request.timeout_seconds,
                source="database",
            )
            self._validate(runtime)
            if model is None:
                model = AgentTeamsBridgeSettingsModel(id=self._SINGLETON_ID)
                self._db.add(model)
            model.enabled = runtime.enabled
            model.bridge_url = runtime.bridge_url
            model.manager_token = encrypt_value(runtime.manager_token)
            model.data_steward_token = encrypt_value(runtime.data_steward_token)
            model.approval_token = encrypt_value(runtime.approval_token)
            model.workflow_operator_token = encrypt_value(runtime.workflow_operator_token)
            model.timeout_seconds = runtime.timeout_seconds
            model.element_url = ""
            await self._db.flush()
            return self._to_dto(runtime)
        except SQLAlchemyError as exc:
            await self._db.rollback()
            raise BusinessError("保存 AgentTeams Bridge 配置失败，请稍后重试") from exc

    @staticmethod
    def _resolve_secret(value: str, existing: str) -> str:
        normalized = value.strip()
        return existing if not normalized or normalized == MASKED_SECRET else normalized

    @staticmethod
    def _is_empty_initial_model(model: AgentTeamsBridgeSettingsModel) -> bool:
        """Treat an all-default legacy/admin placeholder row as absent.

        A user can intentionally disable a configured Bridge: that row retains its URL and
        encrypted identities and must continue to override environment settings. Only a fully
        blank, disabled row is safe to treat as an unconfigured placeholder.
        """
        return bool(
            not model.enabled
            and not (model.bridge_url or "").strip()
            and not model.manager_token
            and not model.data_steward_token
            and not model.approval_token
            and not model.workflow_operator_token
        )

    @staticmethod
    def _validate(config: AgentTeamsBridgeRuntimeConfig) -> None:
        if not config.enabled:
            return
        parsed = urlparse(config.bridge_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise BusinessError("Bridge 地址必须是完整的 http 或 https 地址")
        if not config.configured:
            raise BusinessError("启用 AgentTeams 前必须配置四个 Worker 身份令牌")

    @staticmethod
    def _runtime_from_model(model: AgentTeamsBridgeSettingsModel) -> AgentTeamsBridgeRuntimeConfig:
        return AgentTeamsBridgeRuntimeConfig(
            enabled=model.enabled,
            bridge_url=model.bridge_url,
            manager_token=decrypt_value(model.manager_token),
            data_steward_token=decrypt_value(model.data_steward_token),
            approval_token=decrypt_value(model.approval_token),
            workflow_operator_token=decrypt_value(model.workflow_operator_token),
            timeout_seconds=model.timeout_seconds,
            source="database",
        )

    @staticmethod
    def _to_dto(config: AgentTeamsBridgeRuntimeConfig) -> AgentTeamsBridgeConfigDTO:
        return AgentTeamsBridgeConfigDTO(
            enabled=config.enabled,
            bridge_url=config.bridge_url,
            timeout_seconds=config.timeout_seconds,
            manager_token=MASKED_SECRET if config.manager_token else "",
            data_steward_token=MASKED_SECRET if config.data_steward_token else "",
            approval_token=MASKED_SECRET if config.approval_token else "",
            workflow_operator_token=MASKED_SECRET if config.workflow_operator_token else "",
            source=config.source,
            configured=config.configured,
        )
