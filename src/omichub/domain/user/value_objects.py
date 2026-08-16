"""用户域值对象"""

from enum import Enum


class Role(str, Enum):
    """用户角色"""

    ADMIN = "admin"
    USER = "user"


class UserStatus(str, Enum):
    """用户状态"""

    ACTIVE = "active"
    INACTIVE = "inactive"
    LOCKED = "locked"
    PENDING = "pending"
