"""用户域 ORM 模型"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cygnusx.infrastructure.database.base import Base, TimestampMixin


class UserModel(Base, TimestampMixin):
    """用户表"""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="user")  # admin / user
    status: Mapped[str] = mapped_column(String(20), default="active")
    # JWT 版本号：改密/角色变更/状态禁用时递增，使旧 token 失效
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True
    )
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 昵称：展示用别名，空则前端降级为 username。不参与登录/鉴权
    nickname: Mapped[str | None] = mapped_column(String(120), nullable=True)
    preferences: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # ===== 存储配额（按用户隔离）=====
    # 默认 500 GiB；管理员可经 PUT /admin/users/{id}/quota 动态调配
    storage_quota: Mapped[int] = mapped_column(BigInteger, default=500 * 1024 * 1024 * 1024)
    used_storage: Mapped[int] = mapped_column(BigInteger, default=0)
    # ===== 管理员备注 =====
    # 供管理员记录辅助信息（如"客户要求延期""测试账号"），不对外暴露给用户
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # ===== 所属课题组 =====
    # 用户归属的研究组/实验室，用于资产看板分组与检索；可空
    lab_group: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    # ===== TOTP 二次验证（2FA）=====
    # totp_secret 加密落盘（Fernet，复用 ai_provider_key_encryption_key）；未配置密钥时明文。
    # is_2fa_enabled 仅在用户绑定验证器并成功校验一次后置 true。
    totp_secret: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    is_2fa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # ===== 模块权限管控 =====
    # 被禁用的模块 key 列表（数据源为 data/MODULE_LOCKED.yaml 注册表）；
    # 空列表 = 全部模块可用。管理员角色接口层强制全开，本字段对其不生效
    disabled_modules: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="'[]'")


class WorkspaceModel(Base, TimestampMixin):
    """工作空间表"""

    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(200))
    storage_quota: Mapped[int] = mapped_column(default=10 * 1024 * 1024 * 1024)
    used_storage: Mapped[int] = mapped_column(default=0)
