"""MCP Builder DTO"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from cygnusx.application.schemas.base import CygnusXBaseSchema


class SubmitBuildRequest(CygnusXBaseSchema):
    """提交 MCP 构建（code 缺省时由 LLM 生成）"""

    requirement: str
    code: str | None = None
    mcp_name: str | None = None
    runtime: str = "python"
    model_name: str | None = None
    session_id: str | None = None  # 提供则在沙箱内即时启动验证
    ttl_hours: int | None = None  # 缺省用平台配置
    parent_build_id: UUID | None = None  # 迭代来源
    change_type: str | None = None  # feature | fix | breaking | refactor


class GenerateCodeRequest(CygnusXBaseSchema):
    """仅生成代码（不落库注册）"""

    requirement: str
    model_name: str | None = None


class MCPBuildDTO(CygnusXBaseSchema):
    """MCP 构建记录"""

    id: UUID
    user_id: UUID
    requirement: str
    plan_summary: str = ""
    generated_code: str = ""
    runtime: str = "python"
    safety_report: dict[str, Any] | None = None
    mcp_server_id: UUID | None = None
    version: str = "1.0.0"
    parent_build_id: UUID | None = None
    status: str = "planning"
    test_cases: list[dict[str, Any]] = []
    test_passed: bool | None = None
    build_doc: str = ""
    architecture_doc: str = ""
    model_used: str = ""
    tokens_consumed: int | None = None
    generation_time_ms: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ReviewRequest(CygnusXBaseSchema):
    """审核决定"""

    decision: str  # approved | rejected | request_changes
    comment: str = ""


class SandboxTestRequest(CygnusXBaseSchema):
    """沙箱内测试构建"""

    session_id: str
    test_arguments: dict[str, dict[str, Any]] = {}  # {tool_name: args}


class ToolInvokeRequest(CygnusXBaseSchema):
    """调用实验 MCP 工具"""

    tool: str
    arguments: dict[str, Any] = {}
    session_id: str


class RenewRequest(CygnusXBaseSchema):
    """续期实验 MCP"""

    hours: int | None = None


class ExperimentalServerDTO(CygnusXBaseSchema):
    """实验 MCP Server（含 Builder 扩展字段）"""

    id: UUID
    name: str
    description: str = ""
    status: str = "offline"
    is_enabled: bool = True
    pool: str = "experimental"
    expires_at: datetime | None = None
    created_by: UUID | None = None
    current_version: str = "1.0.0"
    review_status: str = "approved"
    is_template: bool = False
    tool_count: int = 0
    tools: list[dict[str, Any]] = []
    created_at: datetime | None = None


class VersionDTO(CygnusXBaseSchema):
    """MCP 版本快照"""

    id: UUID
    mcp_server_id: UUID
    build_id: UUID | None = None
    version: str
    version_tag: str = ""
    is_major: bool = False
    changelog: str = ""
    created_by: UUID | None = None
    created_at: datetime | None = None
