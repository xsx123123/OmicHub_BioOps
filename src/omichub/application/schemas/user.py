"""用户管理相关DTO模型"""

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from omichub.application.schemas.base import OmicsHubBaseSchema, PaginationParams
from omichub.domain.user.value_objects import Role, UserStatus


class UserResponse(OmicsHubBaseSchema):
    """用户响应（脱敏，不包含密码）"""

    id: UUID = Field(description="用户 UUID")
    username: str = Field(description="用户名")
    email: str = Field(description="邮箱")
    role: str = Field(description="角色")
    status: UserStatus = Field(description="账户状态")
    avatar_url: str | None = Field(default=None, description="头像 URL")
    nickname: str | None = Field(
        default=None, max_length=120, description="昵称（展示用，空则降级为用户名）"
    )
    preferences: dict = Field(default_factory=dict, description="用户偏好")
    storage_quota: int = Field(default=0, description="存储配额（字节）")
    used_storage: int = Field(default=0, description="已用存储（字节）")
    last_login_at: datetime | None = Field(default=None, description="最后登录时间")
    disabled_modules: list[str] = Field(
        default_factory=list, description="被禁用的模块 key 列表（空 = 全部模块可用）"
    )
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class UserUpdateRequest(OmicsHubBaseSchema):
    """用户更新请求"""

    username: str | None = Field(
        default=None,
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_]+$",
    )
    email: str | None = Field(
        default=None,
        max_length=255,
        pattern=r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$",
    )
    avatar_url: str | None = Field(default=None, max_length=500)
    nickname: str | None = Field(
        default=None, max_length=120, description="昵称（展示用，空则降级为用户名）"
    )
    preferences: dict | None = Field(default=None, description="用户偏好设置")
    status: UserStatus | None = Field(default=None, description="账户状态")

    @field_validator("preferences")
    @classmethod
    def validate_preferences(cls, v: dict | None) -> dict | None:
        if v is not None and not isinstance(v, dict):
            raise ValueError("Preferences must be a JSON object")
        return v


class UserModulesUpdateRequest(OmicsHubBaseSchema):
    """模块权限更新请求（管理端按用户配置被禁模块）"""

    disabled_modules: list[str] = Field(
        default_factory=list,
        description="被禁用的模块 key 列表（须为注册表中 lockable=true 的模块）",
    )


class UserListItem(OmicsHubBaseSchema):
    """用户列表项（精简字段，减少传输量）"""

    id: UUID
    username: str
    email: str
    role: str
    status: UserStatus
    created_at: datetime
    updated_at: datetime


class UserListParams(PaginationParams):
    """用户列表查询参数"""

    q: str | None = Field(default=None, description="搜索关键词")
    role: Role | None = Field(default=None)
    status: UserStatus | None = Field(default=None)


class ChangePasswordRequest(OmicsHubBaseSchema):
    """修改密码请求"""

    old_password: str = Field(min_length=8, max_length=128, description="当前密码")
    new_password: str = Field(
        min_length=8,
        max_length=128,
        description="新密码（至少8位，包含字母和数字）",
    )

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        if not any(c.isalpha() for c in v) or not any(c.isdigit() for c in v):
            raise ValueError("密码必须包含字母和数字")
        return v
