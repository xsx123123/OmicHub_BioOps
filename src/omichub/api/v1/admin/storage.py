"""存储空间监控 —— 管理员视角（全局磁盘容量 + 按用户 Top N 占用）。

data_root 由 data/OmicHub.yaml 的 storage 段驱动，见 storage_service。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from omichub.api.deps import DbSession
from omichub.application.schemas.storage import StorageUsage
from omichub.application.services.storage_service import StorageService
from omichub.middleware.rbac import AdminRequired

router = APIRouter()


def get_storage_service(db: DbSession) -> StorageService:
    """获取存储监控服务实例"""
    return StorageService(db)


StorageServiceDep = Annotated[StorageService, Depends(get_storage_service)]


@router.get("/usage", summary="存储空间监控")
async def storage_usage(
    _admin: AdminRequired,
    service: StorageServiceDep,
    top_n: Annotated[int, Query(ge=1, le=50, description="返回占用最多的前 N 个用户")] = 5,
) -> StorageUsage:
    """全局磁盘容量（总/已用/剩余）+ 按用户细分占用 Top N。

    后端遍历 {data_root}/users/ 下所有用户目录统计磁盘占用；
    生信数据量大，采用 `du` 批量统计 + Redis 缓存（5 min）避免接口超时。
    """
    return await service.get_usage(top_n)
