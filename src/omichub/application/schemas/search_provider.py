"""联网搜索服务商 DTO。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SearchProviderDTO(BaseModel):
    id: str
    name: str
    provider_type: str
    api_key: str = ""
    base_url: str = ""
    is_enabled: bool = False
    is_default: bool = False
    params: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = 10
    key_url: str = ""
    is_local: bool = False
    updated_at: datetime | None = None


class SearchProviderUpdateDTO(BaseModel):
    api_key: str = ""
    base_url: str = ""
    is_enabled: bool = False
    params: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=10, ge=1, le=10)


class SearchProviderTestResponse(BaseModel):
    success: bool
    message: str = ""
    result_count: int = 0


class SearchProviderAvailabilityDTO(BaseModel):
    available: bool
    provider_name: str = ""
