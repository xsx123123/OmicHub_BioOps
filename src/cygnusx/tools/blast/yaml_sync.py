"""BLAST 数据库 YAML 配置文件同步。

文件：tool_configs/blast/blast_db.yaml

设计原则：
- PostgreSQL 是运行时权威（支持构建状态、日志、任务关联）。
- YAML 是声明式/可人工编辑的副本，便于 Git 版本控制和跨环境迁移。
- Web 端创建/重建/删除会实时写回 YAML。
- 提供 /admin/databases/sync-from-yaml 接口，将 YAML 中新增或变更的条目导入数据库。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import ValidationError
from cygnusx.infrastructure.database.models.blast import BlastDatabaseModel


class BlastDbYamlEntry(BaseModel):
    """YAML 中单个数据库条目。"""

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


class BlastDbYamlDocument(BaseModel):
    """blast_db.yaml 顶层结构。"""

    model_config = ConfigDict(extra="ignore")

    databases: list[BlastDbYamlEntry] = []


class BlastDbYamlManager:
    """管理 blast_db.yaml 的读写与数据库同步。"""

    def __init__(self, yaml_path: str | Path | None = None) -> None:
        settings = get_settings()
        self.yaml_path = (
            Path(yaml_path)
            if yaml_path
            else Path(settings.blast_config_yaml).parent / "blast_db.yaml"
        )

    def _load_raw(self) -> dict[str, Any]:
        if not self.yaml_path.exists():
            return {}
        try:
            with self.yaml_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            raise ValidationError(f"blast_db.yaml 解析失败: {exc}") from exc
        return data if isinstance(data, dict) else {}

    def load(self) -> BlastDbYamlDocument:
        """读取 YAML。"""
        return BlastDbYamlDocument(**self._load_raw())

    def save(self, document: BlastDbYamlDocument) -> None:
        """写入 YAML。"""
        self.yaml_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "databases": [
                {
                    "db_key": entry.db_key,
                    "name": entry.name,
                    "db_type": entry.db_type,
                    "path": entry.path,
                    "description": entry.description,
                    "source_species": entry.source_species,
                    "source_version": entry.source_version,
                    "version_group": entry.version_group,
                    "is_active": entry.is_active,
                    "is_public": entry.is_public,
                }
                for entry in document.databases
            ]
        }
        with self.yaml_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                data,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )

    def _model_to_entry(self, model: BlastDatabaseModel) -> BlastDbYamlEntry:
        """将 ORM 模型转换为 YAML 条目。"""
        return BlastDbYamlEntry(
            db_key=model.db_key,
            name=model.name,
            db_type=model.db_type,
            path=str(model.file_path),
            description="",
            source_species=model.source_species,
            source_version=model.source_version,
            version_group=model.version_group,
            is_active=model.is_active,
            is_public=model.is_public,
        )

    def sync_from_models(self, models: list[BlastDatabaseModel]) -> None:
        """根据数据库模型列表重写 YAML。"""
        # 只同步非 deprecated 状态的记录
        active_models = [m for m in models if m.build_status != "deprecated"]
        document = BlastDbYamlDocument(databases=[self._model_to_entry(m) for m in active_models])
        self.save(document)

    def diff_against_models(
        self, models: list[BlastDatabaseModel]
    ) -> tuple[list[BlastDbYamlEntry], list[BlastDbYamlEntry]]:
        """比较 YAML 与数据库，返回 (yaml 中新增/变更的条目, yaml 中已删除的条目)。

        目前仅按 db_key 判断：YAML 中有但数据库中没有 -> 待新增。
        """
        db_keys = {m.db_key for m in models}
        document = self.load()
        to_add = [entry for entry in document.databases if entry.db_key not in db_keys]
        yaml_keys = {entry.db_key for entry in document.databases}
        to_remove = [
            m for m in models if m.db_key not in yaml_keys and m.build_status != "deprecated"
        ]
        return to_add, to_remove


# 全局单例
blast_db_yaml_manager = BlastDbYamlManager()
