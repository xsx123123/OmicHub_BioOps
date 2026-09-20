"""MCP 域实体 - 聚合根"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from cygnusx.domain.mcp.value_objects import (
    ReviewStatus,
    ServerPool,
    ServerStatus,
    Transport,
)


class MCPToolRegistry(BaseModel):
    """MCP 工具注册"""

    tool_name: str
    description: str = ""
    input_schema: dict[str, Any] = {}
    server_id: UUID
    # MCP 注解（readOnlyHint/destructiveHint 等）；builtin 预设从代码声明同步，
    # 外部 server 无声明时为空——safe_only（只读会诊）链路据此放行只读 MCP 工具。
    annotations: dict[str, Any] = {}


class MCPServer(BaseModel):
    """MCP Server 聚合根"""

    id: UUID
    name: str
    description: str = ""
    transport: Transport = Transport.STDIO
    command: str = ""  # stdio 模式的启动命令
    args: list[str] = []  # stdio 模式参数
    url: str = ""  # SSE 模式的 URL
    env: dict[str, str] = {}
    registry: str = "default"  # 包管理源
    working_dir: str = ""  # 工作目录
    version: str = ""  # 版本号
    status: ServerStatus = ServerStatus.OFFLINE
    is_enabled: bool = True  # 管理启用开关
    tools: list[MCPToolRegistry] = []
    timeout: int = 30  # 超时秒数
    auto_restart: bool = True
    is_preset: bool = False
    # --- MCP Builder 扩展字段 ---
    pool: ServerPool = ServerPool.PRODUCTION  # 正式池 / 实验池（AI 生成）
    expires_at: datetime | None = None  # 实验 MCP 过期时间（NULL=永久）
    created_by: UUID | None = None  # 创建者（实验 MCP 的所属用户）
    current_version: str = "1.0.0"  # 当前生效版本号
    generation_meta: dict[str, Any] = {}  # 生成元数据 {build_id, model, safety_report}
    review_status: ReviewStatus = ReviewStatus.APPROVED  # 审核状态
    is_template: bool = False  # 是否作为模板供其他用户复用
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def is_available(self) -> bool:
        return self.is_enabled and self.status == ServerStatus.ONLINE

    def is_expired(self, now: datetime | None = None) -> bool:
        """实验 MCP 是否已过 TTL（production 池永不过期）"""
        if self.expires_at is None:
            return False
        now = now or datetime.now()
        ref = self.expires_at.replace(tzinfo=None) if self.expires_at.tzinfo else self.expires_at
        now_ref = now.replace(tzinfo=None) if now.tzinfo else now
        return ref <= now_ref
