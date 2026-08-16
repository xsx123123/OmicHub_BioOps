"""存储目录配置 —— 统一从 data/OmicHub.yaml 的 storage 段读取 data_root。

设计目标：避免在代码中硬编码数据路径。所有需要数据根目录的后端逻辑都应调用
`get_storage_config()`，而不是直接读 `settings.storage_path` 或写死字符串。

解析优先级（逐级降级，文件缺失/解析失败/字段为空时静默回退，绝不抛异常）：
  1) YAML storage.data_root          ← 本文件 storage 段
  2) settings.storage_path           ← .env 的 STORAGE_PATH（默认 /data/omichub）
  3) 内置兜底 /data/omichub

复用 settings.site_content_yaml 指向的同一份 OmicHub.yaml，与 SiteContentService
保持单一配置源，不引入额外的 yaml 文件。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from omichub.core.config import get_settings

# 内置兜底：YAML 与 env 都缺失时的最终默认值
_DEFAULT_DATA_ROOT = "/data/omichub"
_DEFAULT_USERS_SUBDIR = "users"
_DEFAULT_SHARED_SUBDIR = "shared"
_DEFAULT_SYSTEM_SUBDIR = "system"


@dataclass(frozen=True)
class LifecycleConfig:
    """文件生命周期管理配置"""

    upload_session_timeout_hours: int = 24
    work_retention_days: int = 30
    output_archive_days: int = 90
    archive_mode: str = "archive"


@dataclass(frozen=True)
class StorageConfig:
    """存储目录配置"""

    data_root: str
    users_subdir: str
    shared_subdir: str = _DEFAULT_SHARED_SUBDIR
    system_subdir: str = _DEFAULT_SYSTEM_SUBDIR
    # 存储后端类型：local | s3；默认与 Settings.storage_type 一致
    storage_type: str = "local"
    lifecycle: LifecycleConfig = LifecycleConfig()


def _load_yaml_dict(path: Path) -> dict[str, Any]:
    """读盘；文件不存在 / 解析失败 / 非字典时返回空 dict（由降级逻辑兜底）。"""
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def get_storage_config(yaml_path: str | Path | None = None) -> StorageConfig:
    """解析存储配置。

    YAML storage 段优先；data_root 缺失时回退到 settings.storage_path，
    再缺失回退到内置默认。users_subdir 缺失时回退到内置默认。
    """
    settings = get_settings()
    path = Path(yaml_path) if yaml_path else Path(settings.site_content_yaml)
    data = _load_yaml_dict(path)

    raw_storage = data.get("storage")
    storage: dict[str, Any] = raw_storage if isinstance(raw_storage, dict) else {}

    data_root = (
        str(storage.get("data_root") or "").strip()
        or str(settings.storage_path or "").strip()
        or _DEFAULT_DATA_ROOT
    )
    users_subdir = str(storage.get("users_subdir") or "").strip() or _DEFAULT_USERS_SUBDIR
    shared_subdir = str(storage.get("shared_subdir") or "").strip() or _DEFAULT_SHARED_SUBDIR
    system_subdir = str(storage.get("system_subdir") or "").strip() or _DEFAULT_SYSTEM_SUBDIR
    storage_type = (
        str(storage.get("type") or "").strip()
        or str(settings.storage_type or "").strip()
        or "local"
    )

    raw_lifecycle = storage.get("lifecycle")
    lc: dict[str, Any] = raw_lifecycle if isinstance(raw_lifecycle, dict) else {}
    lifecycle = LifecycleConfig(
        upload_session_timeout_hours=int(lc.get("upload_session_timeout_hours", 24)),
        work_retention_days=int(lc.get("work_retention_days", 30)),
        output_archive_days=int(lc.get("output_archive_days", 90)),
        archive_mode=str(lc.get("archive_mode", "archive")),
    )

    return StorageConfig(
        data_root=data_root,
        users_subdir=users_subdir,
        shared_subdir=shared_subdir,
        system_subdir=system_subdir,
        storage_type=storage_type,
        lifecycle=lifecycle,
    )


def get_user_chat_upload_dir(user_id: str) -> Path:
    """AI 助手聊天附件的落盘目录：{data_root}/{users_subdir}/{user_id}/workspace/chat-uploads。

    放在用户 workspace 下，便于后续工具/流程直接引用，也方便文件管理器统一浏览。
    本函数仅返回路径，不创建目录；目录由调用方经 StorageBackend 按需创建。
    """
    cfg = get_storage_config()
    return Path(cfg.data_root) / cfg.users_subdir / str(user_id) / "workspace" / "chat-uploads"
