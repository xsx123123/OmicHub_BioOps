"""项目域 ORM 模型 —— 用户分析项目。

一个 Project 是用户视角的"分析项目"聚合根，下挂多个 Run（每次执行产生一个 Run）。
物理落盘：``{data_root}/users/{user_id}/projects/{slug}/runs/{run-slug}/``。

注意：Project 记录的是「用户可见的项目」，与 ``user_directories`` 中 path="projects/{slug}"
的目录记录是同一实体的两种投影（DB 元数据 vs 目录树节点）。创建 Project 时同步创建
对应的 Directory 记录，删除 Project 时同步删除。
"""

import uuid

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from omichub.infrastructure.database.base import Base, TimestampMixin


class ProjectModel(Base, TimestampMixin):
    """用户分析项目。"""

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("user_id", "slug", name="uq_projects_user_slug"),
        Index("ix_projects_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # 显示名（可含中文/空格），如 "COP1-HY5 示例分析"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # 目录 slug（URL/路径安全），如 "COP1-HY5_Example"；由 project_slug() 生成
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    # 可选描述
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
