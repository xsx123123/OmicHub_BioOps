"""可插拔存储后端抽象。

阶段 1 目标：把文件实体的读写从直接 pathlib 调用收敛到 StorageBackend，
使 ``storage.type=local|s3`` 与 ``deployment_mode=local|cloud`` 成为真正的后端选择器。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from omichub.core.exceptions import AuthorizationError, BusinessError, NotFoundError
from omichub.infrastructure.config.storage_config import get_storage_config
from omichub.infrastructure.storage.path_factory import StoragePathFactory, get_path_factory

logger = logging.getLogger(__name__)


_cache: StorageBackend | None = None


def get_storage_backend() -> StorageBackend:
    """根据配置返回 StorageBackend 单例。"""
    global _cache
    if _cache is None:
        storage_type = get_storage_config().storage_type
        if storage_type == "s3":
            from omichub.infrastructure.storage.s3_backend import S3CompatibleStorageBackend

            _cache = S3CompatibleStorageBackend()
        else:
            if storage_type != "local":
                logger.warning("未知 storage.type=%s，回退到 local", storage_type)
            _cache = LocalStorageBackend()
    return _cache


def reset_storage_backend() -> None:
    """用于测试切换后端。"""
    global _cache
    _cache = None


class StorageBackend(ABC):
    """存储后端抽象接口。

    所有 ``path`` 参数均为相对 data_root 的路径（与 ``file_records.storage_path`` 同义）。
    """

    name: str = "abstract"

    @abstractmethod
    async def read(self, path: str, offset: int = 0, limit: int | None = None) -> bytes:
        """读取文件内容；``offset``/``limit`` 为字节级偏移与上限。"""

    @abstractmethod
    async def write(self, path: str, content: bytes) -> None:
        """写入文件；自动创建父目录（对象存储无目录概念，仅保证对象存在）。"""

    @abstractmethod
    async def delete(self, path: str) -> None:
        """删除文件；不存在时抛出 ``NotFoundError``。"""

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """路径是否存在且为文件。"""

    @abstractmethod
    async def stat(self, path: str) -> dict[str, Any] | None:
        """返回文件元数据：``size``、``mtime``、``is_dir``；不存在返回 None。"""

    @abstractmethod
    async def list(
        self, directory: str, recursive: bool = False
    ) -> list[dict[str, Any]]:
        """列出目录下的直接子项（``recursive=False``）或全部后代（``recursive=True``）。

        返回条目格式::

            {
                "name": str,
                "path": str,      # 相对 data_root 的完整路径
                "type": "file" | "dir",
                "size": int | None,
                "mtime": float | None,
            }
        """

    @abstractmethod
    async def get_local_path(self, path: str) -> Path:
        """返回本地 POSIX 路径；非本地后端抛出 ``BusinessError``。

        供仍必须依赖本地文件系统接口（如某些生信二进制）的场景兜底使用。
        """

    @abstractmethod
    async def move(self, src: str, dst: str) -> None:
        """移动/重命名文件；源文件不存在时抛出 ``NotFoundError``。"""

    @abstractmethod
    async def copy(self, src: str, dst: str) -> None:
        """复制文件；源文件不存在时抛出 ``NotFoundError``。"""

    @abstractmethod
    async def delete_tree(self, directory: str) -> None:
        """递归删除目录/前缀；不存在时静默返回。"""

    @abstractmethod
    async def is_symlink(self, path: str) -> bool:
        """路径是否为符号链接；对象存储永远返回 False。"""

    async def ensure_dir(self, directory: str) -> None:
        """确保目录存在；对象存储默认空实现。"""
        return None

    def presigned_get_url(self, path: str, expires: int = 3600) -> str:
        """生成临时下载 URL；不支持的后端抛出 BusinessError。"""
        raise BusinessError(f"存储后端 {self.name} 不支持预签名下载 URL")

    def presigned_put_url(self, path: str, expires: int = 3600) -> str:
        """生成临时上传 URL；不支持的后端抛出 BusinessError。"""
        raise BusinessError(f"存储后端 {self.name} 不支持预签名上传 URL")


class LocalStorageBackend(StorageBackend):
    """本地文件系统后端：行为与现状完全一致，仅把 pathlib 调用收进统一接口。"""

    name = "local"

    def __init__(self, path_factory: StoragePathFactory | None = None) -> None:
        self._pf = path_factory or get_path_factory()

    def _abs(self, path: str) -> Path:
        if Path(path).is_absolute():
            raise AuthorizationError("StorageBackend 不接受绝对路径")
        return self._pf.data_root / path

    async def read(self, path: str, offset: int = 0, limit: int | None = None) -> bytes:
        target = self._abs(path)
        if not target.is_file():
            raise NotFoundError(f"文件不存在: {path}")
        return await asyncio.to_thread(self._read_sync, target, offset, limit)

    @staticmethod
    def _read_sync(target: Path, offset: int, limit: int | None) -> bytes:
        with target.open("rb") as f:
            if offset:
                f.seek(offset)
            return f.read(limit) if limit is not None else f.read()

    async def write(self, path: str, content: bytes) -> None:
        target = self._abs(path)
        await asyncio.to_thread(self._write_sync, target, content)

    @staticmethod
    def _write_sync(target: Path, content: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    async def delete(self, path: str) -> None:
        target = self._abs(path)
        if not target.is_file():
            raise NotFoundError(f"文件不存在: {path}")
        await asyncio.to_thread(target.unlink)

    async def exists(self, path: str) -> bool:
        return await asyncio.to_thread(self._abs(path).is_file)

    async def stat(self, path: str) -> dict[str, Any] | None:
        target = self._abs(path)
        info = await asyncio.to_thread(self._stat_sync, target)
        return info

    @staticmethod
    def _stat_sync(target: Path) -> dict[str, Any] | None:
        if target.is_file():
            st = target.stat()
            return {"size": st.st_size, "mtime": st.st_mtime, "is_dir": False}
        if target.is_dir():
            st = target.stat()
            return {"size": 0, "mtime": st.st_mtime, "is_dir": True}
        return None

    async def list(
        self, directory: str, recursive: bool = False
    ) -> list[dict[str, Any]]:
        target = self._abs(directory)
        if not target.is_dir():
            return []
        return await asyncio.to_thread(self._list_sync, target, directory, recursive)

    @staticmethod
    def _list_sync(target: Path, directory: str, recursive: bool) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        iterator = target.rglob("*") if recursive else target.iterdir()
        for p in iterator:
            rel = p.relative_to(target).as_posix()
            entry_path = f"{directory}/{rel}".strip("/") if directory else rel
            if p.is_dir():
                entries.append(
                    {
                        "name": p.name,
                        "path": entry_path,
                        "type": "dir",
                        "size": None,
                        "mtime": p.stat().st_mtime,
                    }
                )
            elif p.is_file():
                st = p.stat()
                entries.append(
                    {
                        "name": p.name,
                        "path": entry_path,
                        "type": "file",
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                    }
                )
        return entries

    async def get_local_path(self, path: str) -> Path:
        target = self._abs(path)
        if not target.is_file():
            raise NotFoundError(f"文件不存在: {path}")
        return target

    async def move(self, src: str, dst: str) -> None:
        src_path = self._abs(src)
        dst_path = self._abs(dst)
        if not src_path.is_file():
            raise NotFoundError(f"文件不存在: {src}")
        await asyncio.to_thread(self._move_sync, src_path, dst_path)

    @staticmethod
    def _move_sync(src_path: Path, dst_path: Path) -> None:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dst_path))

    async def copy(self, src: str, dst: str) -> None:
        src_path = self._abs(src)
        dst_path = self._abs(dst)
        if not src_path.is_file():
            raise NotFoundError(f"文件不存在: {src}")
        await asyncio.to_thread(self._copy_sync, src_path, dst_path)

    @staticmethod
    def _copy_sync(src_path: Path, dst_path: Path) -> None:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src_path), str(dst_path))

    async def delete_tree(self, directory: str) -> None:
        target = self._abs(directory)
        await asyncio.to_thread(self._delete_tree_sync, target)

    @staticmethod
    def _delete_tree_sync(target: Path) -> None:
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)

    async def is_symlink(self, path: str) -> bool:
        return await asyncio.to_thread(self._abs(path).is_symlink)

    async def ensure_dir(self, directory: str) -> None:
        await asyncio.to_thread(self._abs(directory).mkdir, parents=True, exist_ok=True)

