"""参考基因组模块 YAML 配置加载器 —— 物种 → 版本两级注册表。

配置文件路径由 settings.reference_genomes_yaml 决定（默认 refdata/reference_genomes.yaml，
容器内解析为 /app/refdata/reference_genomes.yaml，本地为仓库内同名文件；可用环境变量
REFERENCE_GENOMES_YAML 覆盖）。

热重载策略（对齐 tools/jbrowse/config.py）：
- ConfigManager 单例缓存解析后的 ReferenceGenomesConfig，按文件 mtime 判定是否需要重新解析；
- 文件不存在 / 解析失败 / 字段缺失时回退到内置默认空配置，绝不抛异常（前端降级为
  空列表，不影响平台其它功能）；
- 管理员可调 POST /api/v1/reference-genomes/reload 强制清缓存立即生效。

注册表 schema（设计文档 §4.1）：

    species:
      - id: arabidopsis
        common_name: 拟南芥
        ...
        versions:
          - id: tair10
            data_dir: /data/cygnusx/cygnusx_data/reference/TAIR10
            files:
              gff3: { path: TAIR10_GFF3_genes.gff }
            gene_index: gene_index.db   # 相对 data_dir 的构建产物
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from cygnusx.core.config import get_settings


class FileEntryConfig(BaseModel):
    """files 段单项：原始数据文件声明。

    path 相对 data_dir 解析（以 / 开头则视为绝对路径）；
    format 告诉 indexer 用哪个解析器（gff3/gaf/obo/kegg_list/...）。
    """

    model_config = ConfigDict(extra="ignore")

    path: str
    format: str | None = None
    type: str | None = None  # 如 fasta 的 genomic 标记


class VersionStatsConfig(BaseModel):
    """版本组装统计（展示用；真实基因数以 gene_index 的 meta 表为准）。"""

    model_config = ConfigDict(extra="ignore")

    chromosomes: int = 0
    total_genes: int = 0
    protein_coding: int = 0
    genome_size: str = ""
    n50: str = ""


class IdMappingConfig(BaseModel):
    """版本间基因 ID 映射声明（TSV 两列：source_id<TAB>target_id）。"""

    model_config = ConfigDict(extra="ignore")

    to: str
    path: str


class VersionConfig(BaseModel):
    """一个参考基因组版本（如 tair10）。"""

    model_config = ConfigDict(extra="ignore")

    id: str
    version_name: str = ""
    assembly_name: str | None = None
    is_default: bool = False
    status: str = "active"
    release_date: str | None = None
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    data_dir: str = ""
    stats: VersionStatsConfig = Field(default_factory=VersionStatsConfig)
    files: dict[str, FileEntryConfig] = Field(default_factory=dict)
    gene_index: str = "gene_index.db"
    id_mapping: list[IdMappingConfig] = Field(default_factory=list)


class SpeciesConfig(BaseModel):
    """一个物种（含一个或多个版本）。"""

    model_config = ConfigDict(extra="ignore")

    id: str
    common_name: str = ""
    latin_name: str = ""
    taxonomy_id: str = ""
    icon: str = ""
    category: str = "plant"
    gradient: str = ""
    description: str = ""
    versions: list[VersionConfig] = Field(default_factory=list)


class ReferenceGenomesConfig(BaseModel):
    """根配置模型。"""

    model_config = ConfigDict(extra="ignore")

    species: list[SpeciesConfig] = Field(default_factory=list)


class ConfigManager:
    """配置管理器，支持 mtime 热重载。"""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config_path = str(config_path) if config_path else get_settings().reference_genomes_yaml
        self._config: ReferenceGenomesConfig | None = None
        self._mtime: float = 0.0

    def _load_yaml(self) -> dict[str, Any]:
        """读盘；文件不存在 / 解析失败时返回空 dict（由降级逻辑兜底）。"""
        path = Path(self.config_path)
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def get_config(self) -> ReferenceGenomesConfig:
        """获取配置，自动检测文件变更并热重载；文件缺失返回默认空配置。"""
        path = Path(self.config_path)
        if not path.exists():
            self._config = ReferenceGenomesConfig()
            return self._config

        try:
            current_mtime = path.stat().st_mtime
        except OSError:
            return self._config or ReferenceGenomesConfig()

        if self._config is None or current_mtime > self._mtime:
            raw = self._load_yaml()
            try:
                self._config = ReferenceGenomesConfig(**raw)
            except Exception:
                # 字段不合法时回退默认，避免拖垮整个 API
                self._config = ReferenceGenomesConfig()
            self._mtime = current_mtime

        return self._config

    def reload(self) -> ReferenceGenomesConfig:
        """强制重载配置（管理员接口调用）。"""
        self._config = None
        return self.get_config()

    # ---------- 便捷查询 ----------

    def get_species(self, species_id: str) -> SpeciesConfig | None:
        for sp in self.get_config().species:
            if sp.id == species_id:
                return sp
        return None

    def get_version(self, version_id: str) -> tuple[SpeciesConfig, VersionConfig] | None:
        """按版本 id 反查 (物种, 版本)。"""
        for sp in self.get_config().species:
            for ver in sp.versions:
                if ver.id == version_id:
                    return sp, ver
        return None

    def all_versions(self) -> list[tuple[SpeciesConfig, VersionConfig]]:
        return [(sp, ver) for sp in self.get_config().species for ver in sp.versions]


# 全局单例
config_manager = ConfigManager()


def resolve_file_path(version: VersionConfig, key: str) -> Path | None:
    """解析 files[key] 的绝对路径；未声明返回 None。

    相对路径基于 version.data_dir；data_dir 缺失时相对路径无法解析，返回 None。
    """
    entry = version.files.get(key)
    if entry is None or not entry.path:
        return None
    p = Path(entry.path)
    if p.is_absolute():
        return p
    if not version.data_dir:
        return None
    return Path(version.data_dir) / p


def gene_index_path(version: VersionConfig) -> Path | None:
    """gene_index.db 绝对路径（相对 data_dir 解析）。"""
    if not version.gene_index:
        return None
    p = Path(version.gene_index)
    if p.is_absolute():
        return p
    if not version.data_dir:
        return None
    return Path(version.data_dir) / p


def get_reference_genomes_config() -> ReferenceGenomesConfig:
    """FastAPI 依赖用快捷函数。"""
    return config_manager.get_config()
