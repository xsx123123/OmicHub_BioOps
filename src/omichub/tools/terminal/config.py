"""云端沙盒终端外置 YAML 配置加载器。

配置文件路径由 settings.terminal_config_yaml 决定（默认 tool_configs/terminal/terminal_config.yaml，
集中配置于 tool_configs/<工具名>/ 目录，容器内经 tool_configs/ 挂载 :ro 可读；与 jbrowse / enrichment 同模式）。

热重载策略：
- TerminalConfigManager 单例缓存解析后的 TerminalConfig，按文件 mtime 判定是否需要重新解析；
- 文件不存在 / 解析失败 / 字段缺失时回退到内置默认配置，绝不抛异常；
- 改文件后由加载器 mtime 自动热重载，无需重启。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from omichub.core.config import get_settings


class TerminalImageResource(BaseModel):
    """镜像默认资源限制"""

    model_config = ConfigDict(extra="ignore")

    memory_mb: int = 512
    cpu_cores: float = 1.0
    pid_limit: int | None = None


class TerminalImageEnv(BaseModel):
    """镜像环境变量"""

    model_config = ConfigDict(extra="ignore")

    name: str
    value: str


class TerminalImage(BaseModel):
    """单个沙盒终端镜像定义"""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="镜像唯一标识")
    name: str = Field(..., description="显示名称")
    description: str = Field(..., description="描述")
    image: str = Field(..., description="Docker 镜像名")
    tags: list[str] = Field(default_factory=list)
    icon: str = Field(default="🔧", description="前端显示图标")
    resources: TerminalImageResource = Field(default_factory=TerminalImageResource)
    env: list[TerminalImageEnv] = Field(default_factory=list)
    enabled: bool = True

    def full_image_name(self, registry_prefix: str = "") -> str:
        """返回带可选仓库前缀的完整镜像名。"""
        if registry_prefix and not self.image.startswith(registry_prefix):
            return f"{registry_prefix}/{self.image}"
        return self.image


class TerminalImagesConfig(BaseModel):
    """镜像配置根模型"""

    model_config = ConfigDict(extra="ignore")

    version: str = "1.0"
    registry_prefix: str = ""
    default_image: str = "base"
    images: list[TerminalImage] = Field(default_factory=list)

    def get_image(self, image_id: str | None) -> TerminalImage | None:
        """根据 ID 获取启用的镜像配置；未传 ID 返回默认镜像。"""
        if image_id is None:
            return self.get_default_image()
        for img in self.images:
            if img.id == image_id and img.enabled:
                return img
        return None

    def get_enabled_images(self) -> list[TerminalImage]:
        """获取所有启用的镜像。"""
        return [img for img in self.images if img.enabled]

    def get_default_image(self) -> TerminalImage | None:
        """获取默认镜像；若默认镜像未启用或不存在，返回第一个启用的镜像。"""
        default = self.get_image(self.default_image)
        if default is not None:
            return default
        enabled = self.get_enabled_images()
        return enabled[0] if enabled else None


class ImageConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = "omichub/sandbox-terminal"
    tag: str = "latest"
    pull_policy: str = "IfNotPresent"

    @property
    def full_name(self) -> str:
        return f"{self.name}:{self.tag}"


class ResourceConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    memory_mb: int = 512
    cpu_cores: float = 1.0
    pid_limit: int = 100
    tmpfs_size_mb: int = 100


class LifecycleConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    idle_timeout: int = 1800
    disconnect_timeout: int = 300
    max_session_duration: int = 7200
    max_sessions_per_user: int = 2


class SecurityConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    read_only_root: bool = True
    cap_drop_all: bool = True
    no_new_privileges: bool = True


class NetworkConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = "omichub-sandbox-net"
    mode: str = "bridge"


class StorageConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    workspace_base: str = "/data/omichub/users"


class PortRangeConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    base: int = 20000
    max: int = 30000


class TerminalConfig(BaseModel):
    """根配置模型"""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    image: ImageConfig = Field(default_factory=ImageConfig)
    default_resources: ResourceConfig = Field(default_factory=ResourceConfig)
    max_resources: ResourceConfig = Field(
        default_factory=lambda: ResourceConfig(
            memory_mb=4096,
            cpu_cores=4.0,
            pid_limit=500,
            tmpfs_size_mb=500,
        )
    )
    lifecycle: LifecycleConfig = Field(default_factory=LifecycleConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    port_range: PortRangeConfig = Field(default_factory=PortRangeConfig)


class TerminalConfigManager:
    """配置管理器，支持 mtime 热重载。"""

    def __init__(
        self, config_path: str | Path | None = None, images_config_path: str | Path | None = None
    ) -> None:
        self.config_path = str(config_path) if config_path else get_settings().terminal_config_yaml
        self.images_config_path = (
            str(images_config_path)
            if images_config_path
            else get_settings().terminal_images_config_yaml
        )
        self._config: TerminalConfig | None = None
        self._images_config: TerminalImagesConfig | None = None
        self._mtime: float = 0.0
        self._images_mtime: float = 0.0

    def _load_yaml(self) -> dict[str, Any]:
        path = Path(self.config_path)
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _load_images_yaml(self) -> dict[str, Any]:
        path = Path(self.images_config_path)
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def get_config(self) -> TerminalConfig:
        """获取运行时配置，自动检测文件变更并热重载；文件缺失返回默认配置。"""
        path = Path(self.config_path)
        if not path.exists():
            self._config = TerminalConfig()
            return self._config

        try:
            current_mtime = path.stat().st_mtime
        except OSError:
            return self._config or TerminalConfig()

        if self._config is None or current_mtime > self._mtime:
            raw = self._load_yaml()
            try:
                self._config = TerminalConfig(**raw)
            except Exception:
                self._config = TerminalConfig()
            self._mtime = current_mtime

        return self._config

    def get_images_config(self) -> TerminalImagesConfig:
        """获取镜像配置，自动检测文件变更并热重载；文件缺失返回仅含默认基础镜像的配置。"""
        path = Path(self.images_config_path)

        if not path.exists():
            if self._images_config is None:
                self._images_config = self._default_images_config()
            return self._images_config

        try:
            current_mtime = path.stat().st_mtime
        except OSError:
            return self._images_config or self._default_images_config()

        if self._images_config is None or current_mtime > self._images_mtime:
            raw = self._load_images_yaml()
            try:
                self._images_config = TerminalImagesConfig(**raw)
            except Exception:
                self._images_config = self._default_images_config()
            self._images_mtime = current_mtime

        return self._images_config

    @staticmethod
    def _default_images_config() -> TerminalImagesConfig:
        """YAML 缺失时的兜底镜像配置，与当前默认行为保持一致。"""
        return TerminalImagesConfig(
            images=[
                TerminalImage(
                    id="base",
                    name="基础生信",
                    description="预装常用生信工具",
                    image="omichub/sandbox-terminal:latest",
                    enabled=True,
                ),
            ],
        )

    def reload(self) -> TerminalConfig:
        """强制重载运行时配置。"""
        self._config = None
        return self.get_config()

    def reload_images(self) -> TerminalImagesConfig:
        """强制重载镜像配置。"""
        self._images_config = None
        return self.get_images_config()


# 全局单例
config_manager = TerminalConfigManager()


def get_terminal_config() -> TerminalConfig:
    """FastAPI 依赖用快捷函数。"""
    return config_manager.get_config()


def get_terminal_images_config() -> TerminalImagesConfig:
    """FastAPI 依赖用快捷函数。"""
    return config_manager.get_images_config()
