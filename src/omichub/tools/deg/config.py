"""DEG 差异表达分析工具外置 YAML 配置加载器。

配置文件路径由 settings.deg_config_yaml 决定（默认 tool_configs/deg/deg_config.yaml）。

热重载策略（与 enrichments/jbrowse 一致）：
- DegConfigManager 单例缓存解析后的 DegConfig，按文件 mtime 判定是否重解析；
- 文件不存在 / 解析失败 / 字段缺失时回退内置默认配置，绝不抛异常；
- 改文件后由加载器 mtime 自动热重载，无需重启。

引擎口径与容器契约见 tool_configs/deg/README.md。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from omichub.core.config import get_settings

DegMethod = Literal["auto", "deseq2", "edger"]


class DegMetaConfig(BaseModel):
    """工具元信息（仅展示/诊断用）。"""

    model_config = ConfigDict(extra="ignore")

    name: str = "DEG"
    version: str = "1.0"
    description: str = ""


class DegInputLimits(BaseModel):
    """上传输入限制，防止误传巨型矩阵拖垮计算 Worker。"""

    model_config = ConfigDict(extra="ignore")

    max_counts_file_size_mb: int = Field(default=200, gt=0)
    max_metadata_file_size_mb: int = Field(default=5, gt=0)
    max_pairs_file_size_mb: int = Field(default=5, gt=0)
    max_annotation_file_size_mb: int = Field(default=50, gt=0)
    min_samples: int = Field(default=2, ge=2)
    max_samples: int = Field(default=500, gt=0)
    max_contrasts: int = Field(default=50, gt=0)
    max_genes: int = Field(default=100_000, gt=0)


class DegExecutionConfig(BaseModel):
    """容器执行参数（Worker 侧）。"""

    model_config = ConfigDict(extra="ignore")

    use_docker: bool = True
    docker_image: str = "omichub-r-deg:v1"
    queue: str = "analysis"
    timeout: int = Field(default=7200, gt=0)
    cpus: float = Field(default=4.0, gt=0)
    memory: str = "8g"


class DegDefaultsConfig(BaseModel):
    """分析默认参数（前端表单默认值来源）。"""

    model_config = ConfigDict(extra="ignore")

    method: DegMethod = "auto"
    lfc: float = Field(default=1.0, ge=0)
    pval: float = Field(default=0.05, gt=0, le=1)
    bcv: float = Field(default=0.4, gt=0)
    min_replicates: int = Field(default=2, ge=1)


class DegResultsConfig(BaseModel):
    """结果目录与保留策略。"""

    model_config = ConfigDict(extra="ignore")

    results_subdir: str = "deg"
    retention_days: int = Field(default=30, ge=1)


class DegConfig(BaseModel):
    """根配置模型。"""

    model_config = ConfigDict(extra="ignore")

    meta: DegMetaConfig = Field(default_factory=DegMetaConfig)
    input_limits: DegInputLimits = Field(default_factory=DegInputLimits)
    execution: DegExecutionConfig = Field(default_factory=DegExecutionConfig)
    defaults: DegDefaultsConfig = Field(default_factory=DegDefaultsConfig)
    results: DegResultsConfig = Field(default_factory=DegResultsConfig)


class DegConfigManager:
    """配置管理器，支持 mtime 热重载。"""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config_path = (
            str(config_path) if config_path else get_settings().deg_config_yaml
        )
        self._config: DegConfig | None = None
        self._mtime: float = 0.0

    def _load_yaml(self) -> dict[str, Any]:
        """读盘；文件不存在 / 解析失败时返回空 dict（由默认值兜底）。"""
        path = Path(self.config_path)
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def get_config(self) -> DegConfig:
        """获取配置，自动检测文件变更并热重载；文件缺失返回默认配置。"""
        path = Path(self.config_path)
        if not path.exists():
            self._config = DegConfig()
            return self._config

        try:
            current_mtime = path.stat().st_mtime
        except OSError:
            return self._config or DegConfig()

        if self._config is None or current_mtime > self._mtime:
            raw = self._load_yaml()
            try:
                self._config = DegConfig(**raw)
            except Exception:
                # 字段不合法时回退默认，避免拖垮整个 API
                self._config = DegConfig()
            self._mtime = current_mtime

        return self._config

    def reload(self) -> DegConfig:
        """强制重载配置。"""
        self._config = None
        return self.get_config()


# 全局单例
config_manager = DegConfigManager()


def get_deg_config() -> DegConfig:
    """FastAPI 依赖用快捷函数。"""
    return config_manager.get_config()
