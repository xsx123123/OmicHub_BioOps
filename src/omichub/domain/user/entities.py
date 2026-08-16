"""用户域实体 - 聚合根"""

import uuid
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from omichub.domain.user.value_objects import Role, UserStatus


class Workspace(BaseModel):
    """工作空间 - 用户数据隔离边界"""

    id: UUID = Field(default_factory=uuid.uuid4)
    owner_id: UUID
    name: str
    storage_quota: int = 1024 * 1024 * 1024 * 10  # 默认 10GB
    used_storage: int = 0


class User(BaseModel):
    """用户聚合根"""

    id: UUID = Field(default_factory=uuid.uuid4)
    username: str
    email: str
    hashed_password: str
    role: Role = Role.USER
    status: UserStatus = UserStatus.ACTIVE
    workspace_id: UUID | None = None
    avatar_url: str | None = None
    # 昵称：展示用别名，空则前端降级为 username
    nickname: str | None = None
    preferences: dict = Field(default_factory=dict)
    last_login_at: datetime | None = None
    # 存储配额（按用户隔离，默认 500 GiB）
    storage_quota: int = 500 * 1024 * 1024 * 1024
    used_storage: int = 0
    # 管理员备注（如"客户要求延期""测试账号"），不对外暴露给用户
    admin_note: str | None = None
    # 所属课题组（研究组/实验室，可空）
    lab_group: str | None = None
    # ===== TOTP 二次验证（2FA）=====
    # totp_secret 为加密后的密文（Fernet）；未配置加密密钥时为明文
    totp_secret: str | None = None
    is_2fa_enabled: bool = False
    # 模块权限管控：被禁用的模块 key 列表（空 = 全部可用）；管理员角色强制全开
    disabled_modules: list[str] = Field(default_factory=list)
    # JWT 版本号：改密/角色变更/状态禁用时递增，使旧 token 失效
    token_version: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE
