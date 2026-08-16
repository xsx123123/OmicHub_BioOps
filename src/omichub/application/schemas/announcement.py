"""首页条幅通知 DTO"""

from datetime import datetime
from uuid import UUID

from omichub.application.schemas.base import OmicsHubBaseSchema


class AnnouncementCreate(OmicsHubBaseSchema):
    """创建通知请求"""

    title: str
    description: str
    type: str = "info"
    icon: str | None = None
    link: str | None = None
    button_text: str | None = None
    start_time: datetime
    end_time: datetime | None = None
    dismiss_behavior: str = "none"
    priority: int = 0
    is_enabled: bool = True


class AnnouncementUpdate(OmicsHubBaseSchema):
    """更新通知请求（全字段可选，仅传需更新的字段）"""

    title: str | None = None
    description: str | None = None
    type: str | None = None
    icon: str | None = None
    link: str | None = None
    button_text: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    dismiss_behavior: str | None = None
    priority: int | None = None
    is_enabled: bool | None = None


class AnnouncementResponse(OmicsHubBaseSchema):
    """通知响应"""

    id: UUID
    title: str
    description: str
    type: str
    icon: str | None = None
    link: str | None = None
    button_text: str | None = None
    start_time: datetime
    end_time: datetime | None = None
    dismiss_behavior: str
    priority: int
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
