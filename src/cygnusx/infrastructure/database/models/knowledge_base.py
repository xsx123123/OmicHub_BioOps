"""知识库（Knowledge Base）资源表

将文档按"知识库"分组管理：实验室知识库、单细胞知识库等。
- show_in_lab: 是否在「实验室知识库」页面展示该库的文档
- ai_searchable: 是否允许 AI（knowledge_search 工具）检索该库
- is_enabled: 整体停用（不展示也不可检索）
"""

from __future__ import annotations

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from cygnusx.infrastructure.database.base import Base, TimestampMixin


class KnowledgeBaseModel(Base, TimestampMixin):
    """知识库资源主表"""

    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    show_in_lab: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    ai_searchable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
