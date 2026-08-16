"""Private MinIO object storage for AgentTeams case evidence."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from omichub.core.config import Settings, get_settings
from omichub.core.exceptions import BusinessError

logger = logging.getLogger(__name__)

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class ObjectMeta:
    key: str
    size_bytes: int
    etag: str | None = None
    last_modified: Any = None


class MinioStore:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: Any | None = None,
        probe: bool = True,
    ) -> None:
        self.settings = settings or get_settings()
        self.bucket = self.settings.minio_agentteams_bucket
        self._client = client
        if self._client is None and self.settings.minio_access_key and self.settings.minio_secret_key:
            try:
                from minio import Minio

                parsed = urlparse(self.settings.minio_endpoint)
                self._client = Minio(
                    parsed.netloc or parsed.path,
                    access_key=self.settings.minio_access_key,
                    secret_key=self.settings.minio_secret_key,
                    secure=parsed.scheme == "https",
                )
            except Exception as exc:
                logger.warning("MinIO client initialization failed: %s", exc)
        if probe and self._client is not None:
            try:
                self._client.bucket_exists(self.bucket)
            except Exception as exc:
                logger.warning("MinIO is unavailable; AgentTeams will use local fallback: %s", exc)

    @staticmethod
    def _validate_id(value: str, label: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError(f"invalid {label}")
        return value

    @classmethod
    def _object_name(cls, case_id: str, key: str) -> str:
        cls._validate_id(case_id, "case_id")
        path = PurePosixPath(str(key).replace("\\", "/"))
        if path.is_absolute() or len(path.parts) < 2 or ".." in path.parts:
            raise ValueError("key must be work_item_id/relative_path without traversal")
        cls._validate_id(path.parts[0], "work_item_id")
        if any(part in {"", "."} for part in path.parts[1:]):
            raise ValueError("invalid relative_path")
        return f"{case_id}/{path.as_posix()}"

    def _require_client(self) -> Any:
        if self._client is None:
            raise BusinessError("对象存储不可用")
        return self._client

    def put_case_object(
        self, case_id: str, key: str, local_path: str | Path, content_type: str | None = None
    ) -> str:
        object_name = self._object_name(case_id, key)
        try:
            self._require_client().fput_object(
                self.bucket, object_name, str(Path(local_path)), content_type=content_type
            )
        except BusinessError:
            raise
        except Exception as exc:
            raise BusinessError("对象存储不可用") from exc
        return f"s3://{self.bucket}/{object_name}"

    def presigned_get(self, case_id: str, key: str, expires: int | None = None) -> str:
        object_name = self._object_name(case_id, key)
        seconds = expires or self.settings.minio_presign_expire_seconds
        try:
            return self._require_client().presigned_get_object(
                self.bucket, object_name, expires=timedelta(seconds=seconds)
            )
        except BusinessError:
            raise
        except Exception as exc:
            raise BusinessError("对象存储不可用") from exc

    def fetch_case_object(self, case_id: str, key: str, dest_path: str | Path) -> Path:
        object_name = self._object_name(case_id, key)
        destination = Path(dest_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._require_client().fget_object(self.bucket, object_name, str(destination))
        except BusinessError:
            raise
        except Exception as exc:
            raise BusinessError("对象存储不可用") from exc
        return destination

    def read_case_object(self, case_id: str, key: str, *, max_bytes: int) -> bytes:
        object_name = self._object_name(case_id, key)
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        response = None
        try:
            response = self._require_client().get_object(self.bucket, object_name)
            payload = response.read(max_bytes + 1)
        except BusinessError:
            raise
        except Exception as exc:
            raise BusinessError("对象存储不可用") from exc
        finally:
            if response is not None:
                response.close()
                response.release_conn()
        if len(payload) > max_bytes:
            raise BusinessError("产物超过预览大小上限")
        return payload

    def list_case_objects(self, case_id: str, prefix: str = "") -> list[ObjectMeta]:
        self._validate_id(case_id, "case_id")
        normalized = PurePosixPath(prefix.replace("\\", "/")) if prefix else None
        if normalized and (normalized.is_absolute() or ".." in normalized.parts):
            raise ValueError("invalid prefix")
        object_prefix = f"{case_id}/{normalized.as_posix().strip('/')}/" if normalized else f"{case_id}/"
        try:
            objects = self._require_client().list_objects(
                self.bucket, prefix=object_prefix, recursive=True
            )
            return [
                ObjectMeta(
                    key=str(item.object_name)[len(f"{case_id}/") :],
                    size_bytes=int(item.size or 0),
                    etag=getattr(item, "etag", None),
                    last_modified=getattr(item, "last_modified", None),
                )
                for item in objects
            ]
        except BusinessError:
            raise
        except Exception as exc:
            raise BusinessError("对象存储不可用") from exc

    def delete_case_prefix(self, case_id: str, *, preserve_delivery: bool = False) -> None:
        objects = self.list_case_objects(case_id)
        try:
            client = self._require_client()
            for item in objects:
                if preserve_delivery and item.key.startswith("delivery/"):
                    continue
                client.remove_object(self.bucket, f"{case_id}/{item.key}")
        except BusinessError:
            raise
        except Exception as exc:
            raise BusinessError("对象存储不可用") from exc


__all__ = ["MinioStore", "ObjectMeta"]
