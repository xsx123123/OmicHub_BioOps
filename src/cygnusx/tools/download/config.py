"""统一下载器 YAML 配置加载器。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from cygnusx.core.config import get_settings


class DownloadFeaturesConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ebi: bool = False
    cloud_storage: bool = False
    direct_link: bool = False


class DownloadBinariesConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ebi: str = "/data/cygnusx/bin/EBIDownload"
    ebi_config: str = "/data/cygnusx/bin/EBIDownload.yaml"
    aria2c: str = "/usr/bin/aria2c"
    ossutil: str = "/data/cygnusx/bin/ossutil"
    tosutil: str = "/data/cygnusx/bin/tosutil"
    obsutil: str = "/data/cygnusx/bin/obsutil"


class Aria2Config(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default_threads: int = Field(default=4, ge=1, le=16)
    max_threads: int = Field(default=16, ge=1, le=64)
    max_concurrent_downloads: int = Field(default=4, ge=1, le=64)
    max_tries: int = Field(default=5, ge=1, le=20)
    retry_wait: int = Field(default=5, ge=0, le=300)
    connect_timeout: int = Field(default=30, ge=1, le=600)
    timeout: int = Field(default=60, ge=1, le=3600)
    file_allocation: str = "none"
    check_integrity: bool = True
    ftp_reuse_connection: bool = True


class DownloadValidationConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    max_links_per_task: int = Field(default=100, ge=1, le=1000)
    allowed_schemes: list[str] = Field(default_factory=lambda: ["http", "https", "ftp"])


class DownloadConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    features: DownloadFeaturesConfig = Field(default_factory=DownloadFeaturesConfig)
    binaries: DownloadBinariesConfig = Field(default_factory=DownloadBinariesConfig)
    aria2: Aria2Config = Field(default_factory=Aria2Config)
    validation: DownloadValidationConfig = Field(default_factory=DownloadValidationConfig)


class DownloadConfigManager:
    """按文件 mtime 缓存配置，解析失败时保留上一份有效配置。"""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config_path = str(config_path) if config_path else get_settings().download_config_yaml
        self._config: DownloadConfig | None = None
        self._mtime = 0.0

    def get_config(self) -> DownloadConfig:
        path = Path(self.config_path)
        if not path.exists():
            return self._config or DownloadConfig()
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return self._config or DownloadConfig()
        if self._config is None or mtime > self._mtime:
            try:
                with path.open(encoding="utf-8") as stream:
                    raw = yaml.safe_load(stream) or {}
                self._config = DownloadConfig.model_validate(raw)
                self._mtime = mtime
            except (OSError, yaml.YAMLError, ValueError):
                return self._config or DownloadConfig()
        return self._config

    def reload(self) -> DownloadConfig:
        self._config = None
        self._mtime = 0.0
        return self.get_config()


@lru_cache
def get_download_config_manager() -> DownloadConfigManager:
    return DownloadConfigManager()


def get_download_config() -> DownloadConfig:
    return get_download_config_manager().get_config()
