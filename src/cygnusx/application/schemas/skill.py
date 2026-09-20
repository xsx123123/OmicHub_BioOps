"""Skill Pydantic DTO"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SkillDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    skill_id: str
    name: str
    description: str = ""
    prompt: str = ""
    tool_definition: dict[str, Any] | None = None
    icon: str = "\U0001f527"
    category: str = "general"
    is_active: bool = True
    is_builtin: bool = False
    version: str | None = None
    author: str | None = None
    source_type: str = "json"
    source_ref: str | None = None
    source_commit: str | None = None
    has_scripts: bool = False
    frontmatter: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class CreateSkillDTO(BaseModel):
    skill_id: str
    name: str
    description: str = ""
    prompt: str = ""
    tool_definition: dict[str, Any] | None = None
    icon: str = "\U0001f527"
    category: str = "general"
    is_active: bool = True


class UpdateSkillDTO(BaseModel):
    name: str | None = None
    description: str | None = None
    prompt: str | None = None
    tool_definition: dict[str, Any] | None = None
    icon: str | None = None
    category: str | None = None
    is_active: bool | None = None


# --- 版本控制 DTO ---


class SkillVersionDTO(BaseModel):
    """技能版本历史条目（列表用，不含正文 prompt）"""

    revision: int
    version: str | None = None
    name: str = ""
    source: str = "admin"
    changelog: str = ""
    created_by: UUID | None = None
    created_at: datetime


class SkillRollbackRequest(BaseModel):
    """回滚到指定 revision"""

    revision: int


class SkillVersionDetailDTO(SkillVersionDTO):
    """版本快照详情（含正文，供 diff 查看）"""

    description: str = ""
    prompt: str = ""
    icon: str = ""
    category: str = ""
    frontmatter: dict[str, Any] | None = None


class SkillReferenceDTO(BaseModel):
    """引用某技能的助手（删除保护二次确认用）"""

    agent_id: str
    name: str


# --- 导入层 DTO（Part A） ---


class SkillFileEntryDTO(BaseModel):
    path: str
    size: int
    kind: str  # skill_md | script | reference | asset | other
    content: str | None = None


class SkillImportPreviewDTO(BaseModel):
    """统一导入预览：四个入口解析后产出，确认后才入库"""

    skill_id: str
    name: str
    description: str = ""
    body: str = ""
    frontmatter: dict[str, Any] = {}
    icon: str = "\U0001f9e9"
    category: str = "general"
    version: str = ""
    author: str = ""
    source_type: str = "json"  # market | github | zip | markdown | json
    source_ref: str = ""
    source_commit: str = ""
    has_scripts: bool = False
    warnings: list[str] = []
    files: list[SkillFileEntryDTO] = []


class SkillImportConfirmDTO(BaseModel):
    """确认导入：回传预览内容（多 worker 无状态，不落服务端会话）"""

    preview: SkillImportPreviewDTO
    overwrite: bool = False  # skill_id 已存在时是否覆盖升级


class GithubImportRequest(BaseModel):
    url: str


class JsonImportRequest(BaseModel):
    text: str


class SkillMarketplaceItemDTO(BaseModel):
    """技能市场条目：内置源（随仓库发布）+ 阿里云官方源（同步自 GitHub）"""

    skill_id: str
    name: str
    description: str = ""
    icon: str = "\U0001f9e9"
    category: str = "general"
    version: str = ""
    author: str = ""
    has_scripts: bool = False
    installed: bool = False
    # 市场来源分组：builtin（平台内置）/ aliyun_official（阿里云官方）
    source: str = "builtin"
    official: bool = False  # 官方标识 badge（阿里云官方源为 True）


class AliyunMarketplaceStatusDTO(BaseModel):
    """阿里云官方技能源同步状态（空态展示与同步控制用）"""

    enabled: bool = True  # 总开关（ALIYUN_SKILLS_ENABLED）；关闭时市场隐藏官方源分组
    available: bool  # 本地缓存是否有可用条目
    count: int = 0  # 缓存中的技能条目数
    repo: str = ""  # 上游来源标识（AgentExplorer OpenAPI 或 GitHub owner/repo）
    branch: str = ""  # API 区域或 GitHub 分支
    commit: str = ""  # GitHub 缓存对应的上游 commit（短 sha）
    last_synced_at: datetime | None = None
    stale: bool = False  # 缓存是否过期（超过 TTL）
    error: str = ""  # 最近一次同步失败的错误信息


class SkillUpdateCheckDTO(BaseModel):
    has_update: bool
    current_version: str = ""
    current_commit: str = ""
    latest_commit: str = ""
    source_ref: str = ""
    message: str = ""


# --- 调用记录 DTO（Skill 调用可视化） ---


class SkillInvocationDTO(BaseModel):
    """单次技能调用记录（资源中心调用记录列表用）"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    skill_id: str
    skill_name: str = ""
    skill_version: str | None = None
    source: str = ""
    tool_name: str = "use_skill"
    status: str = "completed"  # completed | failed
    duration_ms: float | None = None
    summary: str = ""
    error: str = ""
    session_id: UUID | None = None
    message_id: UUID | None = None
    user_id: UUID | None = None
    created_at: datetime


class SkillInvocationStatDTO(BaseModel):
    """技能调用聚合统计（技能卡片"最近调用 · 累计 N 次"用）"""

    skill_id: str
    total: int = 0
    last_invoked_at: datetime | None = None
    last_status: str = ""
