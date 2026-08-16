"""团队域值对象"""

from enum import Enum


class TeamRole(str, Enum):
    """团队成员在团队空间中的权限角色"""

    OWNER = "owner"
    WRITER = "writer"
    READER = "reader"
