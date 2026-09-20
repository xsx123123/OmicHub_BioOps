"""存储空间监控 Schema —— 全局磁盘容量 + 按用户细分占用。

字段单位均为字节（int），百分比保留两位小数（float）。
"""

from __future__ import annotations

from pydantic import Field

from cygnusx.application.schemas.base import CygnusXBaseSchema


class StorageGlobalUsage(CygnusXBaseSchema):
    """全局磁盘容量（data_root 所在挂载盘）。"""

    total: int = Field(..., description="总容量（字节）")
    used: int = Field(..., description="已用空间（字节）")
    free: int = Field(..., description="剩余空间（字节）")
    used_percent: float = Field(..., description="已用百分比（0-100）")


class UserStorageUsage(CygnusXBaseSchema):
    """单个用户的空间占用。"""

    user_id: str = Field(..., description="用户 ID（即 users/ 下的目录名）")
    username: str = Field(..., description="用户名（查库映射；未映射成功时回退为目录名）")
    nickname: str | None = Field(
        default=None, description="昵称（查库映射；空则前端降级用 username）"
    )
    size: int = Field(..., description="占用磁盘空间（字节，按块大小统计）")
    percent: float = Field(..., description="占所有用户占用总和的百分比（0-100）")


class StorageUsage(CygnusXBaseSchema):
    """存储监控聚合响应。"""

    data_root: str = Field(..., description="本次统计的数据根目录")
    global_usage: StorageGlobalUsage = Field(..., description="全局磁盘容量")
    users: list[UserStorageUsage] = Field(
        default_factory=list, description="占用最多的前 N 个用户（降序）"
    )
    users_total: int = Field(0, description="扫描到的用户目录总数（含未进入 Top N 的）")
