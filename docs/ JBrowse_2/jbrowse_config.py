"""
src/backend/core/jbrowse_config.py
JBrowse 2 外置 YAML 配置加载器
支持热重载、配置验证、默认值填充
"""

import os
import yaml
from typing import List, Dict, Optional, Any
from pathlib import Path
from pydantic import BaseModel, Field, validator
from functools import lru_cache


class AssemblyConfig(BaseModel):
    """参考基因组配置"""
    id: str = Field(..., description="唯一标识符")
    name: str = Field(..., description="显示名称")
    species: Optional[str] = None
    description: Optional[str] = None
    fasta: str = Field(..., description="FASTA 文件绝对路径")
    fai: str = Field(..., description="FASTA 索引文件路径")
    aliases: Optional[Dict[str, str]] = Field(default={}, description="染色体别名")

    @validator('fasta', 'fai')
    def check_file_exists(cls, v):
        # 注意：容器内路径可能与宿主机不同，这里只做基本校验
        # 实际运行时再检查
        return v


class TrackConfig(BaseModel):
    """轨道配置"""
    name: str
    file: str
    index: Optional[str] = None
    type: str = Field(..., description="track 类型: bam, bigwig, vcf, gene, bed")
    color: Optional[str] = "#1565C0"
    height: Optional[int] = 100


class AutoScanConfig(BaseModel):
    """自动扫描配置"""
    enabled: bool = True
    scan_paths: List[str] = ["/data/omichub/users/{user_id}/bam/"]
    extensions: List[str] = [".bam", ".bw", ".bigwig", ".vcf.gz", ".bed.gz"]
    interval: int = 5  # 分钟
    auto_index: bool = True


class UploadConfig(BaseModel):
    """上传配置"""
    upload_dir: str = "/data/omichub/users/{user_id}/uploads/"
    max_file_size: int = 10  # GB
    allowed_types: List[str] = [".bam", ".bw", ".vcf.gz", ".fasta"]
    auto_index_after_upload: bool = True
    index_timeout: int = 3600  # 秒


class DefaultsConfig(BaseModel):
    """默认配置"""
    default_assembly: str = "rice_nipponbare"
    default_region: str = "Chr1:1000000-2000000"
    track_height: int = 100
    show_labels: bool = True


class JBrowseConfig(BaseModel):
    """根配置模型"""
    assemblies: List[AssemblyConfig] = []
    preset_tracks: Dict[str, List[TrackConfig]] = {}
    auto_scan: AutoScanConfig = AutoScanConfig()
    upload: UploadConfig = UploadConfig()
    defaults: DefaultsConfig = DefaultsConfig()


class ConfigManager:
    """配置管理器，支持热重载"""

    def __init__(self, config_path: str = None):
        self.config_path = config_path or os.getenv(
            "JBROWSE_CONFIG_PATH",
            "/data/omichub/config/jbrowse_config.yaml"
        )
        self._config: Optional[JBrowseConfig] = None
        self._mtime: float = 0

    def _load_yaml(self) -> dict:
        """加载 YAML 文件"""
        path = Path(self.config_path)
        if not path.exists():
            raise FileNotFoundError(f"JBrowse 配置文件不存在: {self.config_path}")

        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}

    def get_config(self) -> JBrowseConfig:
        """获取配置，自动检测文件变更并热重载"""
        path = Path(self.config_path)

        if not path.exists():
            # 返回默认空配置
            return JBrowseConfig()

        current_mtime = path.stat().st_mtime

        if self._config is None or current_mtime > self._mtime:
            raw = self._load_yaml()
            self._config = JBrowseConfig(**raw)
            self._mtime = current_mtime
            print(f"[JBrowse] 配置已加载: {self.config_path}")

        return self._config

    def reload(self) -> JBrowseConfig:
        """强制重载配置"""
        self._config = None
        return self.get_config()

    def get_assembly(self, assembly_id: str) -> Optional[AssemblyConfig]:
        """根据 ID 获取参考基因组配置"""
        config = self.get_config()
        for asm in config.assemblies:
            if asm.id == assembly_id:
                return asm
        return None

    def get_preset_tracks(self, assembly_id: str) -> List[TrackConfig]:
        """获取指定参考基因组的预设轨道"""
        config = self.get_config()
        return config.preset_tracks.get(assembly_id, [])

    def get_user_scan_paths(self, user_id: str) -> List[Path]:
        """获取用户扫描路径（替换模板变量）"""
        config = self.get_config()
        paths = []
        for template in config.auto_scan.scan_paths:
            path_str = template.replace("{user_id}", str(user_id))
            paths.append(Path(path_str))
        return paths

    def get_user_upload_dir(self, user_id: str) -> Path:
        """获取用户上传目录"""
        config = self.get_config()
        dir_str = config.upload.upload_dir.replace("{user_id}", str(user_id))
        path = Path(dir_str)
        path.mkdir(parents=True, exist_ok=True)
        return path


# 全局单例
config_manager = ConfigManager()


def get_jbrowse_config() -> JBrowseConfig:
    """FastAPI dependency 用快捷函数"""
    return config_manager.get_config()
