"""Pydantic v2 基础Schema"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CygnusXBaseSchema(BaseModel):
    """所有 Schema 的基类"""

    model_config = ConfigDict(
        from_attributes=True,  # 支持从 ORM 对象自动转换
        populate_by_name=True,  # 允许通过字段名赋值
        str_strip_whitespace=True,  # 自动去除字符串首尾空格
        use_enum_values=True,  # 枚举序列化为值而非名称
    )


class TimestampMixin(BaseModel):
    """时间戳混入类"""

    created_at: datetime = Field(description="创建时间（UTC）")
    updated_at: datetime = Field(description="更新时间（UTC）")


class PaginationParams(CygnusXBaseSchema):
    """分页参数基类"""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)
    sort_by: str | None = Field(default="created_at")
    sort_order: str = Field(default="desc", pattern="^(asc|desc)$")
