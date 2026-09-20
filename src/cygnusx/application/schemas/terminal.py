"""终端 DTO"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from cygnusx.application.schemas.base import CygnusXBaseSchema


class TerminalResourceDTO(CygnusXBaseSchema):
    """终端资源配额"""

    memory_mb: int | None = None
    cpu_cores: float | None = None
    pid_limit: int | None = None


class TerminalImageResourceDTO(CygnusXBaseSchema):
    """镜像默认资源限制"""

    memory_mb: int = 512
    cpu_cores: float = 1.0
    pid_limit: int | None = None


class TerminalRuntimeResourceDTO(CygnusXBaseSchema):
    """终端运行时资源配置"""

    memory_mb: int
    cpu_cores: float
    pid_limit: int
    tmpfs_size_mb: int


class TerminalRuntimeConfigDTO(CygnusXBaseSchema):
    """终端运行时配置（返回前端用）"""

    enabled: bool
    default_resources: TerminalRuntimeResourceDTO
    max_resources: TerminalRuntimeResourceDTO


class TerminalImageEnvDTO(CygnusXBaseSchema):
    """镜像环境变量"""

    name: str
    value: str


class TerminalImageDTO(CygnusXBaseSchema):
    """单个沙盒终端镜像定义（返回前端用）"""

    id: str = Field(..., description="镜像唯一标识")
    name: str = Field(..., description="显示名称")
    description: str = Field(..., description="描述")
    image: str = Field(..., description="Docker 镜像名")
    tags: list[str] = Field(default_factory=list)
    icon: str = Field(default="🔧", description="前端显示图标")
    resources: TerminalImageResourceDTO = Field(default_factory=TerminalImageResourceDTO)
    env: list[TerminalImageEnvDTO] = Field(default_factory=list)
    enabled: bool = True


class TerminalImagesConfigDTO(CygnusXBaseSchema):
    """镜像配置根模型"""

    version: str = "1.0"
    registry_prefix: str | None = None
    default_image: str = "base"
    images: list[TerminalImageDTO] = Field(default_factory=list)

    def get_image(self, image_id: str) -> TerminalImageDTO | None:
        """根据 ID 获取启用的镜像配置"""
        for img in self.images:
            if img.id == image_id and img.enabled:
                return img
        return None

    def get_enabled_images(self) -> list[TerminalImageDTO]:
        """获取所有启用的镜像"""
        return [img for img in self.images if img.enabled]

    def get_default_image(self) -> TerminalImageDTO | None:
        """获取默认镜像"""
        return self.get_image(self.default_image)


class TerminalSessionDTO(CygnusXBaseSchema):
    """终端会话"""

    id: UUID
    user_id: UUID
    session_id: str
    status: str = "creating"
    host_port: int | None = None
    ws_url: str | None = None
    image_id: str | None = None
    image_name: str | None = None
    last_activity: datetime
    created_at: datetime
    expires_at: datetime | None = None
    resources: TerminalResourceDTO | None = None


class CreateTerminalDTO(CygnusXBaseSchema):
    """创建终端会话"""

    image_id: str | None = None
    image_tag: str = "latest"
    resources: TerminalResourceDTO | None = None


class AdminTerminalSessionDTO(CygnusXBaseSchema):
    """管理员视角的终端会话（含容器名、使用时长、实时占用）"""

    id: UUID
    user_id: UUID
    username: str | None = None
    nickname: str | None = None
    session_id: str
    status: str = "creating"
    container_id: str | None = None
    container_name: str | None = None
    host_port: int | None = None
    ws_url: str | None = None
    image_id: str | None = None
    image_name: str | None = None
    created_at: datetime
    last_activity: datetime
    expires_at: datetime | None = None
    usage_seconds: int
    resources: TerminalResourceDTO | None = None
    stats: dict | None = None
