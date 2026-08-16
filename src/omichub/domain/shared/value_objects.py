"""共享值对象 - 跨域通用的值对象"""

from uuid import UUID, uuid4


class BaseEntity:
    """实体基类 - 提供唯一标识"""

    id: UUID
    created_at: str
    updated_at: str


class TimestampMixin:
    """时间戳混入"""

    pass


class IDMixin:
    """ID 混入"""

    pass


def generate_id() -> UUID:
    """生成 UUID"""
    return uuid4()
