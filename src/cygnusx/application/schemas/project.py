"""项目聚合视图（按项目浏览历史分析）的响应模型。

供 ``GET /api/v1/projects/{project_id}/overview`` 使用。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProjectMetaDTO(BaseModel):
    """项目元数据。``customer`` 由并行开发的项目字段提供，缺失时为 None。"""

    id: str
    name: str
    slug: str
    description: str = ""
    customer: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ProjectSessionItemDTO(BaseModel):
    """项目下的一条会话摘要（聊天会话或 agentteams 协作室房间）。"""

    id: str = Field(..., description="会话 ID（session_id）或房间 ID（room_id）")
    title: str
    agent_id: str | None = None
    status: str
    mode: str = "chat"
    message_count: int = 0
    last_message_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    room_id: str | None = Field(
        None, description="agentteams 条目的房间 ID（mode=agentteams 时有值），前端据此路由到协作室"
    )
    case_id: str | None = Field(None, description="agentteams 条目绑定的 Case ID（未立项为 None）")


class ProjectSessionListDTO(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ProjectSessionItemDTO] = Field(default_factory=list)


class ProjectRunItemDTO(BaseModel):
    """项目 runs 目录下的一个历史分析运行目录。"""

    name: str = Field(..., description="运行目录名（分析名-时间戳[-序号]）")
    timestamp: str | None = Field(None, description="运行时间（优先解析目录名中的时间戳）")
    has_agents_md: bool = False
    has_readme: bool = False
    has_environment: bool = Field(False, description="是否含 environment.json 环境快照")
    file_count: int = 0
    total_size_bytes: int = 0


class ProjectOverviewResponse(BaseModel):
    project: ProjectMetaDTO
    sessions: ProjectSessionListDTO
    runs: list[ProjectRunItemDTO] = Field(default_factory=list)
