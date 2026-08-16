"""deployment_mode 驱动差异项集中声明。

阶段 4.4 目标：把 ``deployment_mode=local|cloud`` 影响的业务行为差异
（沙盒挂载方式、大文件 URL 生成、产物回收策略等）集中在这里声明，
禁止在业务代码中散落 ``if deployment_mode == ...`` 判断。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from omichub.core.config import get_settings
from omichub.infrastructure.config.storage_config import get_storage_config


@dataclass(frozen=True)
class DeploymentConfig:
    """部署模式配置：所有因 local/cloud 产生的差异项。"""

    mode: Literal["local", "cloud"]
    storage_type: Literal["local", "s3"]

    # 沙盒执行层挂载策略
    sandbox_mount_strategy: Literal["bind_mount", "scratch_volume"]
    """local 模式直接 bind-mount 用户工作区；cloud 模式使用临时 POSIX scratch 卷。"""

    scratch_volume_enabled: bool
    """cloud 模式下为 Studio/Terminal 容器分配临时 scratch 卷。"""

    # 文件传输策略
    presigned_url_enabled: bool
    """cloud + S3 模式下大文件上传/下载走预签名 URL，不经过应用服务器。"""

    # 产物回收策略
    product_recycle_policy: Literal["keep", "archive", "delete"]
    """local 模式保留产物便于本地反复查看；cloud 模式按生命周期归档或删除。"""

    # 数据物化策略
    data_materialization_enabled: bool
    """cloud 模式下沙盒执行前按 file_id 清单把输入从对象存储物化到 scratch。"""

    # 默认大文件直传阈值（字节），供前端/CLI 参考
    presigned_upload_threshold_bytes: int

    @property
    def is_cloud(self) -> bool:
        return self.mode == "cloud"

    @property
    def is_local(self) -> bool:
        return self.mode == "local"


@lru_cache
def get_deployment_config() -> DeploymentConfig:
    """根据当前 Settings + StorageConfig 返回部署模式配置单例。"""
    settings = get_settings()
    storage_cfg = get_storage_config()
    mode = settings.deployment_mode
    storage_type = storage_cfg.storage_type

    if mode == "cloud":
        return DeploymentConfig(
            mode="cloud",
            storage_type=storage_type,  # type: ignore[arg-type]
            sandbox_mount_strategy="scratch_volume",
            scratch_volume_enabled=True,
            presigned_url_enabled=storage_type == "s3",
            product_recycle_policy="archive",
            data_materialization_enabled=True,
            presigned_upload_threshold_bytes=100 * 1024 * 1024,
        )

    # local 默认形态
    return DeploymentConfig(
        mode="local",
        storage_type=storage_type,  # type: ignore[arg-type]
        sandbox_mount_strategy="bind_mount",
        scratch_volume_enabled=False,
        presigned_url_enabled=False,
        product_recycle_policy="keep",
        data_materialization_enabled=False,
        presigned_upload_threshold_bytes=100 * 1024 * 1024,
    )


def reset_deployment_config_cache() -> None:
    """测试用：清除部署模式配置单例缓存。"""
    get_deployment_config.cache_clear()
