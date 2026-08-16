"""OmicStudio AI 分析工作台外置 YAML 配置加载器。

配置文件路径由 settings.studio_config_yaml 决定（默认 data/ai/studio.yaml，
与 festival / terminal 等外置配置同模式）。

热重载策略（仿 tools/terminal/config.py）：
- StudioConfigManager 单例缓存解析后的 StudioConfig，按文件 mtime 判定是否需要重新解析；
- 文件不存在 / 解析失败 / 字段非法时回退到内置默认配置，绝不抛异常；
- mounts.workspace 中的 {storage_path} 占位符在加载时替换为 settings.storage_path。
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from omichub.core.config import get_settings

_STORAGE_PLACEHOLDER = "{storage_path}"


class StudioSessionConfig(BaseModel):
    """会话生命周期配置"""

    model_config = ConfigDict(extra="ignore")

    idle_ttl_minutes: int = 30
    workspace_retention_days: int = 7
    prewarm_on_create: bool = True


class StudioNetworkConfig(BaseModel):
    """沙盒网络配置（none 或经独立代理的 whitelist）。"""

    model_config = ConfigDict(extra="ignore")

    mode: str = "none"
    # whitelist 模式下作为每会话 internal 网络的名称前缀。
    docker_network: str = "omichub-studio-egress"
    proxy_container: str = "omichub-studio-egress-proxy"
    proxy_host: str = "studio-egress-proxy"
    proxy_port: int = Field(default=3128, ge=1, le=65535)
    allow: list[str] = Field(default_factory=list)

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"none", "whitelist"}:
            raise ValueError("mode 必须为 none 或 whitelist")
        return normalized

    @field_validator("docker_network", "proxy_container", "proxy_host")
    @classmethod
    def validate_docker_name(cls, value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,47}", normalized):
            raise ValueError("Docker 网络/容器/别名名称非法或过长")
        return normalized

    @field_validator("allow")
    @classmethod
    def validate_allow_domains(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw in values:
            domain = str(raw).strip().lower().rstrip(".")
            if domain.startswith("."):
                domain = domain[1:]
            if not domain or "*" in domain or "/" in domain or ":" in domain:
                raise ValueError(f"非法白名单域名: {raw}")
            try:
                ipaddress.ip_address(domain)
            except ValueError:
                pass
            else:
                raise ValueError("白名单不允许 IP 字面量")
            ascii_domain = domain.encode("idna").decode("ascii")
            if ascii_domain not in normalized:
                normalized.append(ascii_domain)
        return normalized


class StudioSandboxConfig(BaseModel):
    """单会话沙盒资源与执行配置"""

    model_config = ConfigDict(extra="ignore")

    cpu: float = 2.0
    memory: str = "4g"
    exec_timeout_seconds: int = 600
    network: StudioNetworkConfig = Field(default_factory=StudioNetworkConfig)


class StudioUiConfig(BaseModel):
    """代码工作室 UI 默认设置。"""

    model_config = ConfigDict(extra="ignore")

    default_view_mode: str = "chat"
    follow_ai_default: bool = True
    terminal_collapsed_default: bool = False
    terminal_collapse_below_px: int = 760
    hibernate_on_leave: bool = True

    @field_validator("default_view_mode")
    @classmethod
    def validate_default_view_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"chat", "split", "code"}:
            raise ValueError("default_view_mode 必须为 chat/split/code")
        return normalized


class StudioMountsConfig(BaseModel):
    """宿主挂载配置，{storage_path} 占位符在加载时解析"""

    model_config = ConfigDict(extra="ignore")

    workspace: str = f"{_STORAGE_PLACEHOLDER}/studio"


class StudioImageDef(BaseModel):
    """单个镜像定义"""

    model_config = ConfigDict(extra="ignore")

    dockerfile: str = ""
    needs_r: bool = False


class StudioConfig(BaseModel):
    """Studio 配置根模型（对应 studio.yaml 的 studio 段）"""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    default_image: str = "omichub-analysis:core-2026.07"
    session: StudioSessionConfig = Field(default_factory=StudioSessionConfig)
    sandbox: StudioSandboxConfig = Field(default_factory=StudioSandboxConfig)
    ui: StudioUiConfig = Field(default_factory=StudioUiConfig)
    mounts: StudioMountsConfig = Field(default_factory=StudioMountsConfig)
    images: dict[str, StudioImageDef] = Field(default_factory=dict)

    @property
    def workspace_root(self) -> Path:
        """工作区根目录（{storage_path} 已解析为绝对路径）"""
        raw = self.mounts.workspace
        resolved = raw.replace(_STORAGE_PLACEHOLDER, get_settings().storage_path)
        path = Path(resolved)
        if not path.is_absolute():
            path = Path(get_settings().storage_path) / path
        return path


class StudioConfigManager:
    """Studio 配置管理器，支持 mtime 热重载。"""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config_path = str(config_path) if config_path else get_settings().studio_config_yaml
        self._config: StudioConfig | None = None
        self._mtime: float = 0.0

    def _load_yaml(self) -> dict[str, Any]:
        """读盘并取 studio 段；文件缺失 / 解析失败 / 结构非法时返回空 dict。"""
        path = Path(self.config_path)
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError):
            return {}
        if not isinstance(data, dict):
            return {}
        studio = data.get("studio", {})
        return studio if isinstance(studio, dict) else {}

    def get_config(self) -> StudioConfig:
        """获取配置，自动检测文件变更并热重载；文件缺失返回默认配置。"""
        path = Path(self.config_path)
        if not path.exists():
            self._config = StudioConfig()
            return self._config

        try:
            current_mtime = path.stat().st_mtime
        except OSError:
            return self._config or StudioConfig()

        if self._config is None or current_mtime > self._mtime:
            raw = self._load_yaml()
            try:
                self._config = StudioConfig(**raw)
            except Exception:  # noqa: BLE001 - 配置非法时回退默认，绝不影响主流程
                self._config = StudioConfig()
            self._mtime = current_mtime

        return self._config

    def reload(self) -> StudioConfig:
        """强制重载配置。"""
        self._config = None
        return self.get_config()


# 全局单例
studio_config_manager = StudioConfigManager()


def get_studio_config() -> StudioConfig:
    """快捷函数：获取当前 Studio 配置（带 mtime 热重载）。"""
    return studio_config_manager.get_config()
