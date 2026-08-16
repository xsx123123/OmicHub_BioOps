"""AI Provider 配置实体"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from omichub.domain.ai_provider.value_objects import ProviderType


class AIProviderConfig(BaseModel):
    """AI Provider 配置聚合根

    管理员可运行时增删改，用于决定 AI Copilot 调用哪个模型/API。
    """

    id: UUID
    name: str
    provider_type: ProviderType = ProviderType.OPENAI_COMPATIBLE
    model: str
    base_url: str = ""
    api_key: str = ""  # 存储时加密
    temperature: float = 0.7
    max_tokens: int = 2048
    top_p: float = 1.0
    timeout: int = 120
    is_active: bool = True
    is_default: bool = False
    extra_params: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def mark_updated(self) -> None:
        self.updated_at = datetime.now()

    def set_default(self, value: bool = True) -> None:
        self.is_default = value
        self.mark_updated()

    @staticmethod
    def create(
        name: str,
        model: str,
        provider_type: ProviderType = ProviderType.OPENAI_COMPATIBLE,
        base_url: str = "",
        api_key: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        top_p: float = 1.0,
        timeout: int = 120,
        extra_params: dict[str, Any] | None = None,
    ) -> "AIProviderConfig":
        return AIProviderConfig(
            id=uuid4(),
            name=name,
            provider_type=provider_type,
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            timeout=timeout,
            extra_params=extra_params or {},
        )
