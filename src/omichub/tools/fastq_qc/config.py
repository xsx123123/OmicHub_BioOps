"""FASTQ 极速质控的只读配置加载与参数快照契约。"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from omichub.core.config import get_settings


class ToolConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = "fastq_qc"
    display_name: str = "FASTQ 极速质控"
    version: str = "1.0.0"
    enabled: bool = True


class ImageConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    repository: str = "omichub/qc-worker"
    tag: str = "latest"
    pull_policy: str = "IfNotPresent"


class WorkerResourcesConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    concurrency: int = Field(default=1, ge=1)
    cpu_limit: int = Field(default=1, ge=1)
    mem_limit: str = "1G"


class FastpResourcesConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    threads: int = Field(default=1, ge=1)


class ResourcesConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    worker: WorkerResourcesConfig = Field(default_factory=WorkerResourcesConfig)
    fastp: FastpResourcesConfig = Field(default_factory=FastpResourcesConfig)


class QueueConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = "qc"
    task_soft_time_limit: int = Field(default=16200, ge=1)
    task_time_limit: int = Field(default=18000, ge=1)
    max_retries: int = Field(default=1, ge=0)


class FastpParameters(BaseModel):
    """受控映射到 fastp argv 的参数集合。"""

    model_config = ConfigDict(extra="forbid")

    qualified_quality_phred: int = Field(default=19, ge=0, le=93)
    unqualified_percent_limit: int = Field(default=40, ge=0, le=100)
    n_base_limit: int = Field(default=5, ge=0)
    length_required: int = Field(default=15, ge=0)
    trim_to_len: int = Field(default=0, ge=0)
    adapter_trim: bool = True
    detect_adapter_for_pe: bool = True
    correction: bool = False
    compression_level: int = Field(default=6, ge=1, le=9)


class FastpConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    bin: str = "fastp"
    timeout_per_sample: int = Field(default=14400, ge=1)
    defaults: FastpParameters = Field(default_factory=FastpParameters)
    overridable: list[str] = Field(default_factory=list)
    extra_args: list[str] = Field(default_factory=list)

    @field_validator("overridable")
    @classmethod
    def validate_overridable(cls, values: list[str]) -> list[str]:
        allowed_fields = set(FastpParameters.model_fields)
        unknown = set(values) - allowed_fields
        if unknown:
            raise ValueError(f"fastp.overridable contains unsupported fields: {sorted(unknown)}")
        return values


class MultiqcConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    min_version: str = "1.29"
    report_name: str = "multiqc_report.html"
    force: bool = True
    modules: list[str] = Field(default_factory=lambda: ["fastp"])
    require_parquet: bool = True
    extra_args: list[str] = Field(default_factory=list)
    timeout: int = Field(default=1800, ge=1)


class StorageConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    root: str = "/data/omichub/qc/tasks"
    subdirs: list[str] = Field(
        default_factory=lambda: ["input", "output", "reports", "multiqc", "logs"]
    )
    zip_lazy: bool = True


class ValidationConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    on_worker_start: list[str] = Field(default_factory=list)


class FastqQcConfig(BaseModel):
    """`tool_configs/fastq_qc/config.yaml` 的完整运行时模型。"""

    model_config = ConfigDict(extra="ignore")

    tool: ToolConfig = Field(default_factory=ToolConfig)
    image: ImageConfig = Field(default_factory=ImageConfig)
    resources: ResourcesConfig = Field(default_factory=ResourcesConfig)
    queue: QueueConfig = Field(default_factory=QueueConfig)
    fastp: FastpConfig = Field(default_factory=FastpConfig)
    multiqc: MultiqcConfig = Field(default_factory=MultiqcConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)


class FastqQcConfigManager:
    """基于 mtime 的配置加载器，失效时保留上一份有效配置。"""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config_path = str(config_path) if config_path else get_settings().fastq_qc_config_yaml
        self._config: FastqQcConfig | None = None
        self._mtime: float = 0.0

    def _load_yaml(self) -> dict[str, Any]:
        path = Path(self.config_path)
        if not path.exists():
            return {}
        try:
            with path.open(encoding="utf-8") as config_file:
                raw = yaml.safe_load(config_file) or {}
        except (OSError, yaml.YAMLError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def get_config(self) -> FastqQcConfig:
        path = Path(self.config_path)
        if not path.exists():
            return self._config or FastqQcConfig()
        try:
            current_mtime = path.stat().st_mtime
        except OSError:
            return self._config or FastqQcConfig()
        if self._config is None or current_mtime > self._mtime:
            try:
                self._config = FastqQcConfig.model_validate(self._load_yaml())
                self._mtime = current_mtime
            except Exception:
                return self._config or FastqQcConfig()
        return self._config

    def reload(self) -> FastqQcConfig:
        self._config = None
        self._mtime = 0.0
        return self.get_config()

    def merge_fastp_parameters(self, overrides: Mapping[str, Any] | None) -> FastpParameters:
        config = self.get_config()
        values = dict(overrides or {})
        unsupported = set(values) - set(config.fastp.overridable)
        if unsupported:
            raise ValueError(f"FASTQ QC parameters are not overridable: {sorted(unsupported)}")
        return config.fastp.defaults.model_copy(update=values)


@lru_cache
def get_fastq_qc_config_manager() -> FastqQcConfigManager:
    return FastqQcConfigManager()


def get_fastq_qc_config() -> FastqQcConfig:
    """FastAPI 依赖和 Worker 使用的配置访问入口。"""
    return get_fastq_qc_config_manager().get_config()
