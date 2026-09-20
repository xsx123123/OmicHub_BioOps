"""存储空间监控应用服务 —— 全局磁盘容量 + 按用户细分占用。

data_root 取自 data/CygnusX.yaml 的 storage 段（缺失回退 settings.storage_path，
详见 infrastructure/config/storage_config.py）。
用户目录约定：{data_root}/users/{user_id}/（与 FileService.user_raw_dir 等一致）。

性能策略（生信数据文件庞大且数量多，朴素 Python 递归会超时）：
- 全局容量用 shutil.disk_usage（底层 statvfs，毫秒级），返回 data_root 所在挂载盘的总量；
- 按用户目录大小用 `du -s --block-size=1` 一次性统计 users/ 下所有子目录
  （GNU coreutils 的 C 实现，远快于 Python os.walk 逐文件累加），
  du 不可用 / 超时 / 返回异常时回退到 os.walk 纯 Python 递归；
- 重计算放线程池（asyncio.to_thread）避免阻塞事件循环；
- 结果走 Redis 缓存（5 min，复用 stats_cache.cached_json），重复请求即时返回；
- 无权限读取的目录捕获 PermissionError / OSError 跳过，不影响整体可用。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.schemas.storage import (
    StorageUsage,
)
from cygnusx.infrastructure.cache.stats_cache import cached_json
from cygnusx.infrastructure.config.storage_config import get_storage_config
from cygnusx.infrastructure.database.models.user import UserModel
from cygnusx.infrastructure.storage import get_path_factory, get_storage_backend

# 与管理员全平台指标一致的缓存 TTL
_TTL = 300  # 5 分钟
# du 子进程超时：生信目录可能很大，给足时间；超时则回退纯 Python
_DU_TIMEOUT = 120


class StorageService:
    """存储空间监控服务"""

    def __init__(self, db: AsyncSession | None = None, backend=None) -> None:
        self._db = db
        cfg = get_storage_config()
        self._data_root = Path(cfg.data_root)
        self._users_dir = self._data_root / cfg.users_subdir
        self._factory = get_path_factory()
        self._backend = backend or get_storage_backend()

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------

    async def get_usage(self, top_n: int = 5) -> StorageUsage:
        """全局磁盘容量 + 按用户细分占用（Top N，降序）。

        结果缓存 5 分钟。Redis 不可用时每次实时计算（仍走线程池，不阻塞事件循环）。
        """
        cache_key = f"stats:admin:storage:v3:{top_n}"

        async def _compute() -> dict:
            return await self._compute_raw(top_n)

        data = await cached_json(cache_key, _TTL, _compute)
        return StorageUsage.model_validate(data)

    # ------------------------------------------------------------------
    # 计算
    # ------------------------------------------------------------------

    async def _compute_raw(self, top_n: int) -> dict:
        global_usage = await self._global_usage_raw()
        all_users = await self._user_usage_raw()
        top = all_users[: max(0, top_n)]
        return {
            "data_root": str(self._data_root),
            "global_usage": global_usage,
            "users": top,
            "users_total": len(all_users),
        }

    async def _global_usage_raw(self) -> dict:
        """全局磁盘容量（statvfs，毫秒级）。data_root 不存在时返回全 0。"""

        def _disk_usage() -> dict:
            try:
                usage = shutil.disk_usage(str(self._data_root))
                total, used, free = usage.total, usage.used, usage.free
            except (OSError, FileNotFoundError):
                # 路径不存在 / 无权限：返回 0，前端据此提示"不可读"
                total = used = free = 0
            percent = round(used / total * 100, 2) if total > 0 else 0.0
            return {
                "total": int(total),
                "used": int(used),
                "free": int(free),
                "used_percent": percent,
            }

        return await asyncio.to_thread(_disk_usage)

    async def _user_usage_raw(self) -> list[dict]:
        """遍历 users/ 下子目录，统计每个用户目录的磁盘占用（降序）。

        仅统计数据库中存在的用户目录，过滤孤儿/已删除用户残留目录。
        """
        users_rel = self._factory.relative_to_root(self._users_dir)
        try:
            entries = await self._backend.list(users_rel, recursive=False)
        except (PermissionError, OSError):
            return []
        child_dirs = [self._data_root / e["path"] for e in entries if e["type"] == "dir"]
        if not child_dirs:
            return []

        # 查询数据库中所有有效用户标识（UUID + username），过滤孤儿目录
        valid_names = await self._get_valid_user_names()
        if valid_names:
            child_dirs = [p for p in child_dirs if p.name in valid_names]
        if not child_dirs:
            return []

        # du 快路径：一次性统计所有子目录，C 优化
        sizes = await asyncio.to_thread(self._du_batch, child_dirs)

        # 子目录名 → user_id；批量查库映射 username + nickname（一次查询）
        name_to_display = await self._map_user_display(list(sizes.keys()))

        total_used = sum(sizes.values())
        result: list[dict] = []
        for name, size in sorted(sizes.items(), key=lambda x: x[1], reverse=True):
            percent = round(size / total_used * 100, 2) if total_used > 0 else 0.0
            display = name_to_display.get(name)
            result.append(
                {
                    "user_id": name,
                    "username": display["username"] if display else name,
                    "nickname": display["nickname"] if display else None,
                    "size": int(size),
                    "percent": percent,
                }
            )
        return result

    # ------------------------------------------------------------------
    # 目录大小统计
    # ------------------------------------------------------------------

    def _du_batch(self, dirs: list[Path]) -> dict[str, int]:
        """`du -s --block-size=1 dir1 dir2 ...` 一次性统计，返回 {目录名: 字节}。

        - 不加 -c，du 对每个参数输出一行 `<bytes>\t<path>`，无合计行；
        - 无权限的子目录 du 会把可读部分计入并在 stderr 告警，stdout 仍输出该目录行；
        - du 不可用 / 超时 / 无输出时回退到纯 Python os.walk。
        """
        try:
            proc = subprocess.run(
                ["du", "-s", "--block-size=1", *(str(d) for d in dirs)],
                capture_output=True,
                text=True,
                timeout=_DU_TIMEOUT,
                check=False,
            )
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            # du 不存在（非 Linux/Mac 或无 coreutils）→ 纯 Python 兜底
            return self._python_sizes(dirs)

        if proc.returncode != 0 and not proc.stdout:
            # du 完全失败（非 0 且无输出）→ 兜底
            return self._python_sizes(dirs)

        result: dict[str, int] = {}
        for line in proc.stdout.splitlines():
            # 形如 "12345\t/data/cygnusx/users/<uuid>"
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            try:
                size = int(parts[0])
            except ValueError:
                continue
            name = Path(parts[1].rstrip("/")).name
            result[name] = size

        # du 可能漏掉个别无法访问的目录，补 0 保证每个目录都有条目
        for d in dirs:
            result.setdefault(d.name, 0)
        return result

    def _python_sizes(self, dirs: list[Path]) -> dict[str, int]:
        """纯 Python 兜底：os.walk 逐文件累加 apparent size。

        仅在 du 不可用时使用；生信海量小文件场景较慢，但保证可用。
        无权限目录捕获 OSError 跳过。
        """
        result: dict[str, int] = {}
        for d in dirs:
            total = 0
            try:
                for root, _subdirs, files in os.walk(d):
                    for fname in files:
                        try:
                            total += os.path.getsize(os.path.join(root, fname))
                        except OSError:
                            continue
            except (PermissionError, OSError):
                pass
            result[d.name] = total
        return result

    # ------------------------------------------------------------------
    # user_id → username / nickname 批量映射
    # ------------------------------------------------------------------

    async def _get_valid_user_names(self) -> set[str]:
        """返回数据库中所有用户的 UUID 字符串和 username 集合。

        用于过滤 users/ 下的孤儿目录（已删除/不存在的用户残留）。
        DB 不可用时返回空 set，调用方据此跳过过滤（保留所有目录）。
        """
        if self._db is None:
            return set()
        try:
            rows = await self._db.execute(
                select(UserModel.id, UserModel.username)
            )
            names: set[str] = set()
            for r in rows.all():
                names.add(str(r[0]))
                names.add(r[1])
            return names
        except Exception:
            return set()

    async def _map_user_display(self, names: list[str]) -> dict[str, dict[str, str | None]]:
        """把 users/ 下目录名（user_id 或 username）批量映射为 {username, nickname}。

        同时支持 UUID 和 username 命名的目录。
        DB 不可用时返回空 dict，不影响统计结果。
        """
        if not names or self._db is None:
            return {}

        user_ids: list[UUID] = []
        plain_names: list[str] = []
        for name in names:
            try:
                user_ids.append(UUID(name))
            except ValueError:
                plain_names.append(name)

        result: dict[str, dict[str, str | None]] = {}
        try:
            if user_ids:
                rows = await self._db.execute(
                    select(UserModel.id, UserModel.username, UserModel.nickname).where(
                        UserModel.id.in_(user_ids)
                    )
                )
                for r in rows.all():
                    result[str(r[0])] = {"username": r[1], "nickname": r[2]}
            if plain_names:
                rows = await self._db.execute(
                    select(UserModel.id, UserModel.username, UserModel.nickname).where(
                        UserModel.username.in_(plain_names)
                    )
                )
                for r in rows.all():
                    result[r[1]] = {"username": r[1], "nickname": r[2]}
        except Exception:
            pass
        return result
