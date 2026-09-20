"""BLAST 工具外置 YAML 配置加载器。

配置文件：
- tool_configs/blast/blast_config.yaml

热重载策略：
- 按文件 mtime 判定是否重新解析；
- 文件不存在/解析失败时回退到内置默认配置，不阻塞 API。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from cygnusx.core.config import get_settings


class InputLimits(BaseModel):
    model_config = ConfigDict(extra="ignore")

    max_query_file_size_mb: int = 20
    max_query_sequence_length: int = 50000
    max_target_seqs: int = 100
    max_database_file_size_mb: int = 10240
    database_upload_chunk_size_mb: int = 16


class ExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    use_docker: bool = False
    docker_image: str = "ncbi/blast:latest"
    num_threads: int = 4
    search_timeout: int = 3000
    build_timeout: int = 3600
    search_queue: str = "blast_search"
    build_queue: str = "blast_db_build"


class ProgramMapItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query_type: str
    db_type: str
    program: str


class BlastDatabaseConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    db_key: str
    name: str
    db_type: str
    path: str
    description: str = ""
    source_species: str | None = None
    source_version: str | None = None
    version_group: str | None = None
    is_active: bool = False
    is_public: bool = True


class BlastConfig(BaseModel):
    """BLAST 工具完整配置。"""

    model_config = ConfigDict(extra="ignore")

    meta: dict[str, Any] = Field(default_factory=dict)
    input_limits: InputLimits = Field(default_factory=InputLimits)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    program_map: list[ProgramMapItem] = Field(default_factory=list)
    defaults: dict[str, Any] = Field(default_factory=dict)
    databases: list[BlastDatabaseConfig] = Field(default_factory=list)

    def program_for(self, query_type: str, db_type: str) -> str | None:
        """根据查询序列类型和数据库类型推断 program。"""
        for item in self.program_map:
            if item.query_type == query_type and item.db_type == db_type:
                return item.program
        return None


class BlastConfigManager:
    """配置管理器，支持 mtime 热重载。"""

    def __init__(self, config_path: str | Path | None = None) -> None:
        settings = get_settings()
        self.config_path = str(config_path) if config_path else settings.blast_config_yaml
        self._config: BlastConfig | None = None
        self._config_mtime: float = 0.0

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _maybe_reload(self) -> None:
        config_path = Path(self.config_path)
        try:
            config_mtime = config_path.stat().st_mtime if config_path.exists() else 0.0
        except OSError:
            config_mtime = 0.0

        if self._config is None or config_mtime > self._config_mtime:
            raw = self._load_yaml(config_path)
            try:
                self._config = BlastConfig(**raw)
            except Exception:
                self._config = BlastConfig()
            self._config_mtime = config_mtime

    def get_config(self) -> BlastConfig:
        self._maybe_reload()
        return self._config or BlastConfig()


# 全局单例
config_manager = BlastConfigManager()
