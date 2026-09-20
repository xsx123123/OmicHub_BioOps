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

from cygnusx.core.config import get_settings

_STORAGE_PLACEHOLDER = "{storage_path}"


class StudioSessionConfig(BaseModel):
    """会话生命周期配置"""

    model_config = ConfigDict(extra="ignore")

    idle_ttl_minutes: int = 30
    # 工作区删除线已迁往 retention.active_days；本字段仅保留为后续休眠功能的
    # 候选线（purge 不再用它做删除依据），配置项保留以兼容已有 studio.yaml。
    workspace_retention_days: int = 7
    prewarm_on_create: bool = True


class StudioRetentionConfig(BaseModel):
    """Studio 数据保留配置（purge 删除线与豁免窗口）。"""

    model_config = ConfigDict(extra="ignore")

    # 最近 active_days 天内有消息/执行记录的会话豁免 purge；
    # 超过该窗口且无豁免的会话工作区可被清理。
    active_days: int = Field(default=14, ge=1)
    # 超过 dormant_days 天未活动且无豁免的 studio 会话工作区会被
    # 休眠打包（tar.gz 归档），释放工作区配额。
    dormant_days: int = Field(default=90, ge=1)


class StudioQuotaConfig(BaseModel):
    """Studio 存储配额占位配置（本期仅配置化，不强制配额）。"""

    model_config = ConfigDict(extra="ignore")

    workspace_gb: int = Field(default=500, ge=0)
    archive_gb: int = Field(default=50, ge=0)


class StudioArchiveConfig(BaseModel):
    """Studio 归档配置占位（本期仅 local 生效，s3 为占位不实现）。"""

    model_config = ConfigDict(extra="ignore")

    backend: str = "local"
    retention_days: int = Field(default=180, ge=1)

    @field_validator("backend")
    @classmethod
    def validate_backend(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"local", "s3"}:
            raise ValueError("archive.backend 必须为 local 或 s3")
        # 注意：s3 仅为配置占位，本期不实现，运行期按 local 行为处理。
        return normalized


class StudioNetworkConfig(BaseModel):
    """沙盒网络配置（none 或经独立代理的 whitelist）。"""

    model_config = ConfigDict(extra="ignore")

    mode: str = "none"
    # whitelist 模式下作为每会话 internal 网络的名称前缀。
    docker_network: str = "cygnusx-studio-egress"
    proxy_container: str = "cygnusx-studio-egress-proxy"
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
    pids_limit: int = Field(default=512, ge=64, le=65_536)
    read_only_rootfs: bool = True
    tmpfs_size: str = "512m"
    container_user: str = "10001:10001"
    # default=使用 daemon 内置默认 profile（不下发 seccomp security_opt）；
    # unconfined=显式禁用；其余值按字面 JSON profile 内容透传。
    seccomp_profile: str = "default"
    # 只读根文件系统下需要可写 tmpfs 的容器内缓存目录（micromamba 进程锁等），
    # 挂载属主取 container_user；留空则不挂载。
    agent_cache_dir: str = "/home/mambauser/.cache"
    workspace_quota_bytes: int = Field(default=10 * 1024**3, ge=0)
    workspace_quota_check_interval_seconds: int = Field(default=30, ge=5, le=3600)
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


class StudioLoopControlConfig(BaseModel):
    """单条用户消息内 Agent 工具循环的熔断阈值。"""

    model_config = ConfigDict(extra="ignore")

    max_tool_calls_per_turn: int = Field(default=40, ge=1, le=500)
    max_consecutive_failures: int = Field(default=3, ge=1, le=20)
    auto_downgrade_to_supervised: bool = True


class StudioMicroCompactionConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    threshold_chars: int = Field(default=4000, ge=500, le=100_000)


class StudioAgentConfig(BaseModel):
    """Studio Agent 运行期防护配置。"""

    model_config = ConfigDict(extra="ignore")

    permission_modes: list[str] = Field(
        default_factory=lambda: ["supervised", "plan", "auto"]
    )
    micro_compaction: StudioMicroCompactionConfig = Field(
        default_factory=StudioMicroCompactionConfig
    )
    loop_control: StudioLoopControlConfig = Field(default_factory=StudioLoopControlConfig)

class StudioMountsConfig(BaseModel):
    """宿主挂载配置，{storage_path} 占位符在加载时解析"""

    model_config = ConfigDict(extra="ignore")

    workspace: str = f"{_STORAGE_PLACEHOLDER}/studio"


class StudioImageDef(BaseModel):
    """单个镜像定义"""

    model_config = ConfigDict(extra="ignore")

    dockerfile: str = ""
    image: str = ""
    runtime_profile: str | None = None
    needs_r: bool = False
    capabilities: list[str] = Field(default_factory=lambda: ["code"])

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, values: list[str]) -> list[str]:
        allowed = {"code", "browser", "document"}
        normalized = list(dict.fromkeys(str(value).strip().lower() for value in values))
        if not normalized or any(value not in allowed for value in normalized):
            raise ValueError("镜像 capabilities 只能包含 code/browser/document，且不能为空")
        if "code" not in normalized:
            normalized.insert(0, "code")
        return normalized


class StudioConfig(BaseModel):
    """Studio 配置根模型（对应 studio.yaml 的 studio 段）"""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    default_image: str = "cygnusx-analysis:core-v0.0.2dev"
    session: StudioSessionConfig = Field(default_factory=StudioSessionConfig)
    retention: StudioRetentionConfig = Field(default_factory=StudioRetentionConfig)
    quota: StudioQuotaConfig = Field(default_factory=StudioQuotaConfig)
    archive: StudioArchiveConfig = Field(default_factory=StudioArchiveConfig)
    sandbox: StudioSandboxConfig = Field(default_factory=StudioSandboxConfig)
    ui: StudioUiConfig = Field(default_factory=StudioUiConfig)
    agent: StudioAgentConfig = Field(default_factory=StudioAgentConfig)
    mounts: StudioMountsConfig = Field(default_factory=StudioMountsConfig)
    images: dict[str, StudioImageDef] = Field(default_factory=dict)

    def image_for_capabilities(self, capabilities: list[str]) -> str | None:
        """返回覆盖请求能力的已配置镜像，优先能力集合最小的镜像。"""
        requested = set(capabilities)
        candidates = [
            definition
            for definition in self.images.values()
            if definition.image and requested.issubset(set(definition.capabilities))
        ]
        if not candidates:
            return None
        selected = min(candidates, key=lambda definition: len(definition.capabilities))
        return selected.image

    def capabilities_for_image(self, image: str) -> list[str]:
        """返回已配置镜像的能力；未登记镜像按普通代码镜像处理。"""
        for definition in self.images.values():
            if definition.image == image:
                return list(definition.capabilities)
        return ["code"]

    @property
    def workspace_root(self) -> Path:
        """工作区根目录（{storage_path} 已解析为绝对路径）"""
        raw = self.mounts.workspace
        resolved = raw.replace(_STORAGE_PLACEHOLDER, get_settings().storage_path)
        path = Path(resolved)
        if not path.is_absolute():
            path = Path(get_settings().storage_path) / path
        return path

    @property
    def archive_root(self) -> Path:
        """归档包顶级目录（与 studio/ 平级、平台独占，不挂入任何容器）。"""
        return Path(get_settings().storage_path) / "studio-archive"


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
