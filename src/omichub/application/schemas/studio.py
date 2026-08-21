"""OmicStudio AI 分析工作台 Pydantic DTO"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from omichub.application.schemas.chat import ChatSessionDTO


class CreateStudioSessionRequest(BaseModel):
    """创建 Studio 会话请求"""

    agent_id: str = Field(..., description="绑定的 Agent ID")
    title: str | None = Field(None, description="会话标题，缺省为「与 <Agent名> 的工作台」")
    project_id: str | None = Field(None, max_length=64, description="项目边界标识")
    model_id: UUID | None = Field(None, description="模型配置 ID，缺省用 Agent 绑定模型")


class PromoteStudioSessionRequest(BaseModel):
    """普通会话升级为 Studio 工作台请求（保留历史消息）"""

    agent_id: str | None = Field(
        None, description="可选：将会话重绑定到该 Agent（路由场景缺省沿用会话绑定 Agent）"
    )


class CreateStudioSessionFromReportRequest(BaseModel):
    """从报告创建 Studio 会话请求（结果报告中心「在 AI 工作台中优化」，§7.2）"""

    report_id: UUID = Field(..., description="来源报告 ID")
    agent_id: str = Field(..., description="绑定的 Agent ID")


class RegisterStudioArtifactRequest(BaseModel):
    """产物登记请求（右栏「保存为新版本」，与 artifact_register 工具同服务路径）"""

    path: str = Field(..., description="产物路径（相对 /workspace，必须在 output/ 下）")
    title: str = Field(..., description="报告标题")
    type: str | None = Field(None, description="产物类型（html/pdf/png/csv 等），缺省按扩展名推断")
    description: str | None = Field(None, description="报告描述")


class RegisterStudioArtifactResponse(BaseModel):
    """产物登记响应"""

    report_id: UUID
    title: str
    version: int = Field(..., description="版本号（挂接版本树时为父版本+1）")
    parent_id: UUID | None = Field(None, description="父报告 ID（版本树）")
    file: dict[str, Any] = Field(default_factory=dict, description="登记的文件信息")


class ImportStudioDataFileRequest(BaseModel):
    """从数据管理或聊天上传记录引入文件请求。"""

    file_id: str = Field(..., description="file://{uuid} 数据管理文件或 upload://{hex} 聊天上传文件")
    name: str | None = Field(None, description="工作区内显示名，缺省用原文件名")


class StudioPathRequest(BaseModel):
    path: str = Field(..., min_length=1, description="相对 /workspace 的路径")


class RenameStudioFileRequest(BaseModel):
    path: str = Field(..., min_length=1)
    new_path: str = Field(..., min_length=1)


class SaveStudioFileRequest(BaseModel):
    """从工作区编辑器完整保存 UTF-8 文本文件。"""

    path: str = Field(..., min_length=1, description="相对 /workspace 的文件路径")
    content: str = Field(..., max_length=1_048_576, description="完整文件内容，最大 1 MiB")


class SaveStudioFileResponse(BaseModel):
    """工作区文件保存结果。"""

    path: str
    size: int = 0


class EditStudioFileRequest(BaseModel):
    """Studio 文件编辑请求（workspace_edit 拒绝时用 old/new 交换回滚）。"""

    path: str = Field(..., description="相对 /workspace 的文件路径")
    old_string: str = Field(..., description="必须唯一出现的原文本")
    new_string: str = Field(..., description="替换文本")


class EditStudioFileResponse(BaseModel):
    """文件编辑结果，diff 为统一 diff 文本。"""

    path: str
    diff: str = ""
    size: int = 0


class ImportStudioDataFileResponse(BaseModel):
    """引入结果：沙盒内路径 + 当前 input/ 清单（与 datahub_import 工具 payload 同构）"""

    sandbox_path: str = Field(..., description="沙盒内可读路径，如 /workspace/input/a.csv")
    name: str = Field(..., description="工作区内链接名（重名自动加序号）")
    size: int = Field(..., description="文件大小（字节）")
    file_type: str = Field(..., description="数据管理或聊天上传文件类型")
    input_files: list[str] = Field(
        default_factory=list, description="当前 /workspace/input/ 下全部已引入路径"
    )


class UpdateStudioUiRequest(BaseModel):
    """会话级代码工作室视图状态。"""

    view_mode: Literal["chat", "split", "code"] | None = None
    split_ratio: float | None = Field(None, ge=25, le=70)
    follow_ai: bool | None = None
    terminal_collapsed: bool | None = None


class UpdateStudioPermissionsRequest(BaseModel):
    """会话级权限模式（监督 / 计划 / 放权）。"""

    mode: Literal["supervised", "plan", "auto"] = Field(..., description="权限模式")


class StudioApprovalApproveRequest(BaseModel):
    """批准工具审批；modified_args 为用户编辑后的参数（编辑后批准）。"""

    modified_args: dict[str, Any] | None = Field(None, description="编辑后的工具参数")


class StudioApprovalRejectRequest(BaseModel):
    """退回工具审批；reason 回灌 LLM 让其修改后重试。"""

    reason: str | None = Field(None, description="退回理由")


class StudioShareStatusDTO(BaseModel):
    active: bool
    expires_at: datetime | None = None
    shared_at: datetime | None = None


class StudioSessionDetailDTO(BaseModel):
    """Studio 会话详情：会话本体 + 沙盒状态 + 工作区文件树 + 当前计划"""

    session: ChatSessionDTO
    sandbox_status: str = Field(..., description="running / stopped / absent / unavailable")
    workspace_id: str | None = None
    files: list[dict[str, Any]] = Field(default_factory=list, description="工作区根目录条目")
    plan: dict[str, Any] | None = Field(None, description="最新待办计划（sandbox_meta.plan）")
    capabilities: dict[str, Any] | None = Field(
        None, description="会话级 MCP/Skill 加载状态与最近审计记录（sandbox_meta.capabilities）"
    )
    ui: dict[str, Any] = Field(default_factory=dict, description="代码工作室视图与交互设置")
    permissions: dict[str, Any] = Field(
        default_factory=lambda: {"mode": "supervised"},
        description="会话级权限模式（sandbox_meta.permissions，默认 supervised）",
    )
    sandbox_metrics: dict[str, Any] = Field(default_factory=dict, description="容器 CPU/内存快照")
    share: StudioShareStatusDTO | None = Field(
        None, description="只读分享状态；原始令牌永不从详情接口返回"
    )


class CreateStudioShareRequest(BaseModel):
    """创建或轮换 Studio 会话只读分享链接。"""

    expires_hours: int = Field(
        168, ge=1, le=720, description="分享有效期小时数，默认 7 天，最长 30 天"
    )


class StudioShareResponse(BaseModel):
    token: str = Field(..., description="仅创建/轮换时返回一次的高熵分享令牌")
    share_path: str = Field(..., description="公开只读页面路径")
    expires_at: datetime


class SharedStudioMessageDTO(BaseModel):
    role: str
    content: str
    created_at: datetime


class SharedStudioSessionDTO(BaseModel):
    title: str
    agent_id: str | None = None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    messages: list[SharedStudioMessageDTO] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


class ExtractStudioSkillRequest(BaseModel):
    """管理员将工作区脚本提炼为可复用 Skill。"""

    path: str = Field(..., min_length=1, max_length=240, description="工作区内脚本路径")
    skill_id: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z0-9][a-z0-9_-]{0,49}$")
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field("", max_length=500)
    usage_instructions: str = Field("", max_length=4000)
    category: str = Field("studio", max_length=50)
    icon: str = Field("🧪", max_length=10)
    confirm_no_secrets: bool = Field(
        False, description="管理员已人工检查脚本，不包含 API Key、密码或用户隐私数据"
    )


class StudioRunRequest(BaseModel):
    """用户重跑代码卡片请求（对应 /studio/sessions/{id}/run）"""

    code: str = Field(..., description="要执行的完整代码")
    language: Literal["python", "r", "bash"] = "python"
    timeout: int | None = Field(None, description="超时秒数，缺省用沙盒默认（600s）")


class StudioInternalExecRequest(BaseModel):
    """Worker -> Web 的内部沙盒执行请求。"""

    user_id: str
    language: Literal["python", "r", "bash"]
    code: str
    timeout_sec: int = Field(ge=1, le=3600)
    image: str | None = None
