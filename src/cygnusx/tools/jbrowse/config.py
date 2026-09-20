"""JBrowse 2 外置 YAML 配置加载器 —— 参考基因组 / 预设轨道 / 扫描与上传策略。

配置文件路径由 settings.jbrowse_config_yaml 决定（默认 tool_configs/jbrowse/jbrowse_config.yaml，
集中配置于 tool_configs/<工具名>/ 目录，容器内经 tool_configs/ 挂载 :ro 可读；与 enrichment 同模式）。

热重载策略：
- ConfigManager 单例缓存解析后的 JBrowseConfig，按文件 mtime 判定是否需要重新解析；
- 文件不存在 / 解析失败 / 字段缺失时回退到内置默认空配置，绝不抛异常（浏览器降级为
  "无可用基因组"，前端给出空状态，不影响平台其它功能）；
- 管理员可调 POST /api/v1/jbrowse/config/reload 强制清缓存立即生效。

data_root（用于把绝对路径换算成 /tracks/ 下的相对 URI）取自 storage_config，
与 CygnusX.yaml 的 storage 段保持单一数据源，避免在此重复声明。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from cygnusx.core.config import get_settings
from cygnusx.infrastructure.config.storage_config import get_storage_config


class AssemblyDataFileConfig(BaseModel):
    """数据库模块数据文件配置（FASTA/GFF/GO/KEGG）。"""

    model_config = ConfigDict(extra="ignore")

    path: str
    index_path: str | None = None
    db_path: str | None = None
    format: str | None = None
    build_required: bool = False
    build_tool: str | None = None
    build_status: str = "ready"
    size: str | None = None


class AssemblyConfig(BaseModel):
    """参考基因组/数据库版本配置"""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="唯一标识符")
    name: str = Field(..., description="显示名称")
    species: str | None = None
    common_name: str | None = None
    taxonomy_id: str | None = None
    version_id: str | None = None
    version_name: str | None = None
    assembly_name: str | None = None
    category: str | None = None
    icon: str | None = None
    is_default: bool = False
    status: str = "active"
    release_date: str | None = None
    stats: dict[str, Any] = Field(default_factory=dict)
    data_files: dict[str, AssemblyDataFileConfig] = Field(default_factory=dict)
    description: str | None = None
    fasta: str = Field(..., description="FASTA 文件绝对路径")
    fai: str = Field(..., description="FASTA 索引文件路径")
    aliases: list[str] = Field(
        default_factory=list, description="基因组别名（assembly name alternatives）"
    )


class TrackConfig(BaseModel):
    """预设轨道配置"""

    model_config = ConfigDict(extra="ignore")

    name: str
    file: str
    index: str | None = None
    type: str = Field(..., description="轨道类型: bam/cram/bw/vcf.gz/bed.gz/gff3.gz")
    color: str | None = "#1565C0"
    height: int | None = 100


class AutoScanConfig(BaseModel):
    """自动扫描配置"""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    scan_paths: list[str] = Field(default_factory=lambda: ["/data/cygnusx/users/{user_id}/bam/"])
    extensions: list[str] = Field(
        default_factory=lambda: [".bam", ".bw", ".bigwig", ".vcf.gz", ".bed.gz"]
    )
    interval: int = 5  # 分钟
    auto_index: bool = True


class UploadConfig(BaseModel):
    """上传配置"""

    model_config = ConfigDict(extra="ignore")

    upload_dir: str = "/data/cygnusx/users/{user_id}/uploads/"
    max_file_size: int = 10  # GB
    allowed_types: list[str] = Field(default_factory=lambda: [".bam", ".bw", ".vcf.gz", ".fasta"])
    auto_index_after_upload: bool = True
    index_timeout: int = 3600  # 秒


class DefaultsConfig(BaseModel):
    """默认配置"""

    model_config = ConfigDict(extra="ignore")

    default_assembly: str = "rice_nipponbare"
    default_region: str = "Chr1:1000000-2000000"
    track_height: int = 100
    show_labels: bool = True


class JBrowseConfig(BaseModel):
    """根配置模型"""

    model_config = ConfigDict(extra="ignore")

    assemblies: list[AssemblyConfig] = Field(default_factory=list)
    preset_tracks: dict[str, list[TrackConfig]] = Field(default_factory=dict)
    auto_scan: AutoScanConfig = Field(default_factory=AutoScanConfig)
    upload: UploadConfig = Field(default_factory=UploadConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)


class ConfigManager:
    """配置管理器，支持 mtime 热重载"""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config_path = str(config_path) if config_path else get_settings().jbrowse_config_yaml
        self._config: JBrowseConfig | None = None
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

    def get_config(self) -> JBrowseConfig:
        """获取配置，自动检测文件变更并热重载；文件缺失返回默认空配置。"""
        path = Path(self.config_path)
        if not path.exists():
            self._config = JBrowseConfig()
            return self._config

        try:
            current_mtime = path.stat().st_mtime
        except OSError:
            return self._config or JBrowseConfig()

        if self._config is None or current_mtime > self._mtime:
            raw = self._load_yaml()
            try:
                self._config = JBrowseConfig(**raw)
            except Exception:
                # 字段不合法时回退默认，避免拖垮整个 API
                self._config = JBrowseConfig()
            self._mtime = current_mtime

        return self._config

    def reload(self) -> JBrowseConfig:
        """强制重载配置（管理员接口调用）。"""
        self._config = None
        return self.get_config()

    def get_assembly(self, assembly_id: str) -> AssemblyConfig | None:
        """根据 ID 获取参考基因组配置。"""
        for asm in self.get_config().assemblies:
            if asm.id == assembly_id:
                return asm
        return None

    def get_preset_tracks(self, assembly_id: str) -> list[TrackConfig]:
        """获取指定参考基因组的预设轨道。"""
        return self.get_config().preset_tracks.get(assembly_id, [])

    def get_user_scan_paths(self, user_id: str) -> list[Path]:
        """获取用户扫描路径（替换 {user_id} 模板变量）。"""
        paths: list[Path] = []
        for template in self.get_config().auto_scan.scan_paths:
            paths.append(Path(template.replace("{user_id}", str(user_id))))
        return paths

    def get_user_upload_dir(self, user_id: str) -> Path:
        """获取用户上传目录（自动创建）。"""
        dir_str = self.get_config().upload.upload_dir.replace("{user_id}", str(user_id))
        path = Path(dir_str)
        path.mkdir(parents=True, exist_ok=True)
        return path


# 全局单例
config_manager = ConfigManager()


@lru_cache
def _data_root() -> Path:
    """数据根目录（用于把绝对路径换算成 /tracks/ 相对 URI）。"""
    return Path(get_storage_config().data_root)


def to_tracks_uri(abs_path: str) -> str:
    """把 /data/cygnusx/ref/rice/x.fasta 换算成 /tracks/ref/rice/x.fasta。

    供 JBrowse 2 通过 nginx /tracks/ 路径流式读取。路径不在 data_root 下时，
    退化为只保留文件名，避免泄漏目录结构。
    """
    try:
        rel = Path(abs_path).relative_to(_data_root())
        return "/tracks/" + rel.as_posix()
    except ValueError:
        return "/tracks/" + Path(abs_path).name


def get_jbrowse_config() -> JBrowseConfig:
    """FastAPI 依赖用快捷函数。"""
    return config_manager.get_config()
