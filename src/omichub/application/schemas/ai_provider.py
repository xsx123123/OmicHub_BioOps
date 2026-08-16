"""AI Provider 配置 DTO"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AIProviderConfigBaseDTO(BaseModel):
    name: str
    provider_type: str
    model: str
    base_url: str = ""
    temperature: float = 0.7
    max_tokens: int = 2048
    top_p: float = 1.0
    timeout: int = 120
    is_active: bool = True
    extra_params: dict[str, Any] = Field(default_factory=dict)


class AIProviderConfigCreateDTO(AIProviderConfigBaseDTO):
    api_key: str


class AIProviderConfigUpdateDTO(AIProviderConfigBaseDTO):
    api_key: str = ""  # 空表示不更新密钥


class AIProviderConfigDTO(AIProviderConfigBaseDTO):
    id: UUID
    is_default: bool
    api_key: str = ""  # 脱敏回显：已配置为 "********"，未配置为 ""
    created_at: str | None = None
    updated_at: str | None = None

    class Config:
        from_attributes = True


class AIProviderConfigTestRequest(BaseModel):
    message: str = "你好，请简要介绍一下自己。"


class AIProviderConfigTestResponse(BaseModel):
    success: bool
    response: str = ""
    error: str = ""


class DiscoveredModel(BaseModel):
    id: str
    name: str = ""
    owned_by: str = "unknown"


class AIProviderDiscoverResponse(BaseModel):
    provider_id: UUID
    provider_name: str
    models: list[DiscoveredModel] = Field(default_factory=list)


class AIProviderTemplate(BaseModel):
    name: str
    provider_type: str
    base_url: str
    default_models: list[str] = Field(default_factory=list)
    env_key: str = ""
    exists: bool = False
