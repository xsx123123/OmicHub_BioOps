"""可观测性数据留存（C6）— 清理超期轮转归档

日志与 span 都按大小轮转成 ``<name>.log.N`` / ``.zip`` 归档。本模块按冷数据保留天数
删除超期归档，控制磁盘占用。活动文件（无后缀编号的当前文件）永不删除，保证在线排查
始终有最新数据；热数据窗口（hot_days）内的归档同样保留。
"""

from __future__ import annotations

import time
from pathlib import Path

from loguru import logger

from cygnusx.core.config import get_settings
from cygnusx.core.logging import _resolve_log_dir
from cygnusx.core.span_store import SPAN_LOG_NAME

_JSON_LOG_NAME = "cygnusx.json.log"


def _archive_globs() -> list[str]:
    """需纳入留存清理的归档文件 glob（活动文件本身不在内）。"""
    return [
        f"{_JSON_LOG_NAME}.*",
        f"{SPAN_LOG_NAME}.*",
    ]


def prune_observability_archives(log_dir: Path | None = None) -> dict:
    """删除超过冷数据保留天数的日志/span 归档，返回清理统计。"""
    settings = get_settings()
    if not settings.log_retention_enabled:
        return {"enabled": False, "deleted": 0, "freed_bytes": 0}

    directory = log_dir or _resolve_log_dir()
    cutoff = time.time() - settings.log_retention_cold_days * 86400

    deleted = 0
    freed = 0
    for pattern in _archive_globs():
        for path in directory.glob(pattern):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
                if stat.st_mtime >= cutoff:
                    continue  # 仍在冷数据窗口内，保留
                size = stat.st_size
                path.unlink()
                deleted += 1
                freed += size
            except OSError as exc:
                logger.warning(f"留存清理：删除 {path.name} 失败: {exc}")

    if deleted:
        logger.info(
            f"留存清理完成：删除 {deleted} 个超期归档，释放 {freed / 1024 / 1024:.2f} MB"
            f"（冷数据阈值 {settings.log_retention_cold_days} 天）"
        )
    return {
        "enabled": True,
        "cold_days": settings.log_retention_cold_days,
        "deleted": deleted,
        "freed_bytes": freed,
    }
