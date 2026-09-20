"""系统发育树工具外置 YAML 配置加载器。

配置文件：
- tool_configs/phylogenetic-tree/config.yaml   工具能力/资源/输出/支持的方法矩阵
- tool_configs/phylogenetic-tree/defaults.yaml 默认参数预设

热重载策略：
- 按文件 mtime 判定是否重新解析；
- 文件不存在/解析失败时回退到内置默认配置，不阻塞 API。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cygnusx.core.config import get_settings

logger = logging.getLogger(__name__)


class ToolMeta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = "phylogenetic-tree"
    version: str = "1.0.0"
    description: str = "多序列比对与系统发育树构建工具"


class FeatureFlags(BaseModel):
    model_config = ConfigDict(extra="ignore")

    multiple_sequence_alignment: bool = True
    tree_building: bool = True
    bootstrap_analysis: bool = True
    model_selection: bool = True
    format_conversion: bool = True


class InputLimits(BaseModel):
    model_config = ConfigDict(extra="ignore")

    max_file_size_mb: int = 50
    max_sequences: int = 5000
    max_sequence_length: int = 50000


class ToolBinary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    binary: str = ""
    version: str = ""


class OutputFormat(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str
    ext: str
    mime: str


class CeleryExecution(BaseModel):
    model_config = ConfigDict(extra="ignore")

    queue: str = "phylo_tree"
    time_limit_seconds: int = Field(default=7200, ge=60)
    soft_time_limit_seconds: int = Field(default=3600, ge=30)


class ResourceExecution(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default_threads: int = Field(default=4, ge=1)
    max_threads: int = Field(default=16, ge=1)
    max_memory_mb: int = Field(default=32768, ge=256)


class ExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    celery: CeleryExecution = Field(default_factory=CeleryExecution)
    resources: ResourceExecution = Field(default_factory=ResourceExecution)


class OutputConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default_formats: list[str] = Field(default_factory=lambda: ["newick", "statistics"])
    available_formats: list[OutputFormat] = Field(default_factory=list)


class MethodOption(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str
    label: str
    description: str = ""
    supports_bootstrap: bool | None = None


class SupportedMethods(BaseModel):
    model_config = ConfigDict(extra="ignore")

    alignment_tools: list[MethodOption] = Field(
        default_factory=lambda: [
            MethodOption(key="mafft", label="MAFFT", description="通用首选，快速准确"),
            MethodOption(key="clustalo", label="Clustal Omega", description="适合大规模序列"),
            MethodOption(key="muscle5", label="MUSCLE5", description="高精度比对"),
            MethodOption(key="prealigned", label="已比对（跳过）", description="输入已经完成多序列比对"),
        ]
    )
    tree_methods: list[MethodOption] = Field(
        default_factory=lambda: [
            MethodOption(key="nj", label="Neighbor-Joining", supports_bootstrap=True),
            MethodOption(key="upgma", label="UPGMA", supports_bootstrap=False),
            MethodOption(key="fasttree", label="FastTree", supports_bootstrap=True),
            MethodOption(key="iqtree", label="IQ-TREE", supports_bootstrap=True),
            MethodOption(key="mrbayes", label="MrBayes", supports_bootstrap=False),
        ]
    )
    substitution_models: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "dna": ["JC69", "K2P", "HKY", "GTR", "GTR+I", "GTR+G", "GTR+I+G", "auto"],
            "protein": ["LG", "WAG", "JTT", "auto"],
        }
    )
    bootstrap_types: list[MethodOption] = Field(
        default_factory=lambda: [
            MethodOption(key="standard", label="标准 Bootstrap"),
            MethodOption(key="ultrafast", label="UFBoot (IQ-TREE)"),
        ]
    )


class PhyloPreset(BaseModel):
    model_config = ConfigDict(extra="allow")

    alignment_tool: str = "mafft"
    alignment_mode: str = "auto"
    tree_method: str = "iqtree"
    substitution_model: str = "auto"
    bootstrap_enabled: bool = True
    bootstrap_type: str = "ultrafast"
    bootstrap_replicates: int = Field(default=1000, ge=10, le=10000)


class PhyloConfig(BaseModel):
    """系统发育树工具完整配置。"""

    model_config = ConfigDict(extra="ignore")

    meta: ToolMeta = Field(default_factory=ToolMeta)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    input_limits: InputLimits = Field(default_factory=InputLimits)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    tools: dict[str, ToolBinary] = Field(default_factory=dict)
    output: OutputConfig = Field(default_factory=OutputConfig)
    supported_methods: SupportedMethods = Field(default_factory=SupportedMethods)

    def binary_path(self, tool_name: str) -> str | None:
        """返回工具二进制名（优先配置中的 binary，否则回退工具名本身）。"""
        cfg = self.tools.get(tool_name)
        return cfg.binary if cfg else tool_name


class PhyloDefaults(BaseModel):
    """默认参数预设。"""

    model_config = ConfigDict(extra="ignore")

    defaults: dict[str, PhyloPreset] = Field(default_factory=dict)


class PhyloConfigManager:
    """配置管理器，支持 mtime 热重载。"""

    def __init__(
        self,
        config_path: str | Path | None = None,
        defaults_path: str | Path | None = None,
    ) -> None:
        settings = get_settings()
        self.config_path = (
            str(config_path) if config_path else settings.phylogenetic_tree_config_yaml
        )
        self.defaults_path = (
            str(defaults_path) if defaults_path else settings.phylogenetic_tree_defaults_yaml
        )
        self._config: PhyloConfig | None = None
        self._defaults: PhyloDefaults | None = None
        self._config_mtime: float = 0.0
        self._defaults_mtime: float = 0.0
        self._config_error: str | None = None
        self._defaults_error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._config_error or self._defaults_error

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}

    def _maybe_reload(self) -> None:
        config_path = Path(self.config_path)
        defaults_path = Path(self.defaults_path)

        try:
            config_mtime = config_path.stat().st_mtime if config_path.exists() else 0.0
        except OSError:
            config_mtime = 0.0
        try:
            defaults_mtime = defaults_path.stat().st_mtime if defaults_path.exists() else 0.0
        except OSError:
            defaults_mtime = 0.0

        if self._config is None or config_mtime != self._config_mtime:
            try:
                raw = self._load_yaml(config_path)
                self._config = PhyloConfig(**raw)
                self._config_error = None
            except (OSError, yaml.YAMLError, ValidationError) as exc:
                self._config_error = f"config.yaml 加载失败: {exc}"
                logger.warning(self._config_error)
                self._config = PhyloConfig()
            self._config_mtime = config_mtime

        if self._defaults is None or defaults_mtime != self._defaults_mtime:
            try:
                raw = self._load_yaml(defaults_path)
                self._defaults = PhyloDefaults(**raw)
                self._defaults_error = None
            except (OSError, yaml.YAMLError, ValidationError) as exc:
                self._defaults_error = f"defaults.yaml 加载失败: {exc}"
                logger.warning(self._defaults_error)
                self._defaults = PhyloDefaults()
            self._defaults_mtime = defaults_mtime

    def get_config(self) -> PhyloConfig:
        self._maybe_reload()
        return self._config or PhyloConfig()

    def get_defaults(self) -> PhyloDefaults:
        self._maybe_reload()
        return self._defaults or PhyloDefaults()


# 全局单例
config_manager = PhyloConfigManager()
