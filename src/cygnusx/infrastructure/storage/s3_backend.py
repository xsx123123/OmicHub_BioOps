"""S3 兼容对象存储后端。

复用项目已有的 MinIO SDK 连接配置；对象键与现有相对路径模型一一对应，
即 ``users/{uid}/...`` 直接作为对象键前缀。
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import BusinessError, NotFoundError
from cygnusx.infrastructure.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


class S3CompatibleStorageBackend(StorageBackend):
    """基于 minio SDK 的 S3 兼容后端。"""

    name = "s3"

    def __init__(self) -> None:
        self._settings = get_settings()
        self._bucket = self._settings.storage_s3_bucket or self._settings.minio_agentteams_bucket
        self._client = self._build_client()

    def _build_client(self) -> Any:
        access_key = self._settings.storage_s3_access_key or self._settings.minio_access_key
        secret_key = self._settings.storage_s3_secret_key or self._settings.minio_secret_key
        endpoint = self._settings.storage_s3_endpoint or self._settings.minio_endpoint
        if not access_key or not secret_key or not endpoint:
            logger.warning("S3 后端缺少连接凭证，降级为不可用状态")
            return None
        try:
            from minio import Minio

            parsed = urlparse(endpoint)
            return Minio(
                parsed.netloc or parsed.path,
                access_key=access_key,
                secret_key=secret_key,
                secure=parsed.scheme == "https",
                region=self._settings.storage_s3_region or None,
            )
        except Exception as exc:
            logger.warning("S3 客户端初始化失败: %s", exc)
            return None

    def _require_client(self) -> Any:
        if self._client is None:
            raise BusinessError("S3 对象存储不可用")
        return self._client

    async def read(self, path: str, offset: int = 0, limit: int | None = None) -> bytes:
        try:
            response = self._require_client().get_object(
                self._bucket, path, offset=offset, length=limit
            )
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except BusinessError:
            raise
        except Exception as exc:
            raise NotFoundError(f"S3 读取失败: {path}") from exc

    async def write(self, path: str, content: bytes) -> None:
        from io import BytesIO

        try:
            self._require_client().put_object(
                self._bucket, path, BytesIO(content), length=len(content)
            )
        except BusinessError:
            raise
        except Exception as exc:
            raise BusinessError(f"S3 写入失败: {path}") from exc

    async def delete(self, path: str) -> None:
        try:
            self._require_client().remove_object(self._bucket, path)
        except BusinessError:
            raise
        except Exception as exc:
            raise NotFoundError(f"S3 删除失败: {path}") from exc

    async def exists(self, path: str) -> bool:
        try:
            self._require_client().stat_object(self._bucket, path)
            return True
        except Exception:
            return False

    async def stat(self, path: str) -> dict[str, Any] | None:
        try:
            obj = self._require_client().stat_object(self._bucket, path)
            return {
                "size": obj.size,
                "mtime": obj.last_modified.timestamp() if obj.last_modified else None,
                "is_dir": False,
            }
        except Exception:
            return None

    async def list(
        self, directory: str, recursive: bool = False
    ) -> list[dict[str, Any]]:
        prefix = f"{directory.strip('/')}/" if directory else ""
        try:
            objects = self._require_client().list_objects(
                self._bucket, prefix=prefix, recursive=recursive
            )
        except BusinessError:
            raise
        except Exception as exc:
            raise BusinessError(f"S3 列表失败: {directory}") from exc

        entries: list[dict[str, Any]] = []
        seen_dirs: set[str] = set()
        for item in objects:
            key: str = item.object_name
            if not key or key == prefix:
                continue
            rel = key[len(prefix) :].strip("/")
            if recursive:
                entries.append(
                    {
                        "name": Path(rel).name,
                        "path": key,
                        "type": "file",
                        "size": int(item.size or 0),
                        "mtime": (
                            item.last_modified.timestamp() if item.last_modified else None
                        ),
                    }
                )
            else:
                first_part = rel.split("/", 1)[0]
                if first_part in seen_dirs:
                    continue
                seen_dirs.add(first_part)
                entries.append(
                    {
                        "name": first_part,
                        "path": f"{prefix}{first_part}".strip("/"),
                        "type": "dir",
                        "size": None,
                        "mtime": None,
                    }
                )
        return entries

    async def get_local_path(self, path: str) -> Path:
        raise BusinessError("S3 后端不支持本地 POSIX 路径；请使用 read/write 接口")

    async def move(self, src: str, dst: str) -> None:
        from minio.commonconfig import CopySource

        try:
            self._require_client().copy_object(
                self._bucket, dst, CopySource(self._bucket, src)
            )
            self._require_client().remove_object(self._bucket, src)
        except BusinessError:
            raise
        except Exception as exc:
            raise BusinessError(f"S3 移动失败: {src} -> {dst}") from exc

    async def copy(self, src: str, dst: str) -> None:
        from minio.commonconfig import CopySource

        try:
            self._require_client().copy_object(
                self._bucket, dst, CopySource(self._bucket, src)
            )
        except BusinessError:
            raise
        except Exception as exc:
            raise BusinessError(f"S3 复制失败: {src} -> {dst}") from exc

    async def delete_tree(self, directory: str) -> None:
        prefix = f"{directory.strip('/')}/" if directory else ""
        try:
            objects = self._require_client().list_objects(
                self._bucket, prefix=prefix, recursive=True
            )
            for item in objects:
                self._require_client().remove_object(self._bucket, item.object_name)
        except BusinessError:
            raise
        except Exception as exc:
            raise BusinessError(f"S3 删除前缀失败: {directory}") from exc

    async def is_symlink(self, path: str) -> bool:
        return False

    def presigned_get_url(self, path: str, expires: int = 3600) -> str:
        """生成临时下载 URL（cloud 模式大文件传输用）。"""
        try:
            return self._require_client().presigned_get_object(
                self._bucket, path, expires=timedelta(seconds=expires)
            )
        except BusinessError:
            raise
        except Exception as exc:
            raise BusinessError(f"S3 预签名 URL 生成失败: {path}") from exc

    def presigned_put_url(self, path: str, expires: int = 3600) -> str:
        """生成临时上传 URL。"""
        try:
            return self._require_client().presigned_put_object(
                self._bucket, path, expires=timedelta(seconds=expires)
            )
        except BusinessError:
            raise
        except Exception as exc:
            raise BusinessError(f"S3 预签名上传 URL 生成失败: {path}") from exc
