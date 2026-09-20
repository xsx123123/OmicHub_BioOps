"""MCP DTO"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from cygnusx.application.schemas.base import CygnusXBaseSchema


class MCPToolDTO(CygnusXBaseSchema):
    """MCP 工具描述"""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = {}


class MCPServerDTO(CygnusXBaseSchema):
    """MCP Server"""

    id: UUID
    name: str
    description: str = ""
    transport: str = "builtin"
    command: str = ""
    args: list[str] = []
    url: str = ""
    env: dict[str, str] = {}
    registry: str = "default"
    working_dir: str = ""
    version: str = ""
    current_version: str = "1.0.0"  # 当前生效版本号（版本管理真实指针）
    pool: str = "production"  # production / experimental / deprecated
    review_status: str = "approved"  # draft / pending / approved / rejected
    expires_at: datetime | None = None  # 实验池 TTL（NULL=永久）
    status: str = "offline"
    is_enabled: bool = True
    timeout: int = 30
    auto_restart: bool = True
    is_preset: bool = False
    tool_count: int = 0
    tools: list[MCPToolDTO] = []
    created_at: datetime | None = None


class CreateMCPServerDTO(CygnusXBaseSchema):
    """注册外部 MCP Server"""

    name: str
    description: str = ""
    transport: str = "stdio"  # stdio | sse | streamable_http
    command: str = ""
    args: list[str] = []
    url: str = ""
    env: dict[str, str] = {}
    registry: str = "default"
    working_dir: str = ""
    timeout: int = 30
    auto_restart: bool = True


class UpdateMCPServerDTO(CygnusXBaseSchema):
    """更新 MCP Server"""

    name: str | None = None
    description: str | None = None
    transport: str | None = None
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    env: dict[str, str] | None = None
    registry: str | None = None
    working_dir: str | None = None
    version: str | None = None
    timeout: int | None = None
    auto_restart: bool | None = None
    is_enabled: bool | None = None


class MCPServerVersionDTO(CygnusXBaseSchema):
    """MCP Server 版本历史条目"""

    id: UUID
    version: str
    is_major: bool = False
    source: str = "builder"  # builder / admin / rollback / publish
    changelog: str = ""
    created_by: UUID | None = None
    created_at: datetime | None = None
    has_config_snapshot: bool = False


class RollbackMCPServerDTO(CygnusXBaseSchema):
    """回滚 MCP Server 到指定版本"""

    version: str


class MCPLogEntryDTO(CygnusXBaseSchema):
    """MCP 日志条目"""

    timestamp: datetime
    level: str
    message: str
    source: str = "internal"


class InvokeToolDTO(CygnusXBaseSchema):
    """工具调用请求"""

    tool_name: str
    arguments: dict[str, Any] = {}
