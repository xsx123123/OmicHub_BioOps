"""FileService 预签名 URL 单元测试（cloud/S3 模式大文件直传）"""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from omichub.application.services.file_service import FileService
from omichub.core.exceptions import AuthorizationError, BusinessError, NotFoundError, ValidationError
from omichub.domain.file.entities import DataFile
from omichub.domain.file.value_objects import FileType, OwnerScope
from omichub.infrastructure.config.storage_config import StorageConfig
from omichub.infrastructure.storage.backend import LocalStorageBackend
from omichub.infrastructure.storage.path_factory import StoragePathFactory


class _FakeS3Backend:
    """只覆盖预签名链路所需的最小后端接口。"""

    name = "s3"

    async def ensure_dir(self, directory: str) -> None:
        return None

    async def stat(self, path: str) -> dict | None:
        return {"size": 1024, "mtime": datetime.now(UTC).timestamp(), "is_dir": False}

    def presigned_get_url(self, path: str, expires: int = 3600) -> str:
        return f"http://s3.example.com/download/{path}?expires={expires}"

    def presigned_put_url(self, path: str, expires: int = 3600) -> str:
        return f"http://s3.example.com/upload/{path}?expires={expires}"


def _service_with_backend(backend, tmp_path: str | None = None) -> FileService:
    service = object.__new__(FileService)
    service._files = SimpleNamespace()
    service._users = SimpleNamespace()
    service._dirs = SimpleNamespace()
    service._samples = SimpleNamespace()
    service._session = SimpleNamespace()

    async def _commit() -> None:
        return None

    service._session.commit = _commit
    if tmp_path is not None:
        service._factory = StoragePathFactory(
            StorageConfig(data_root=str(tmp_path), users_subdir="users")
        )
    service._backend = backend
    return service


@pytest.mark.asyncio
async def test_create_presigned_download_returns_s3_url(tmp_path) -> None:
    user_id = uuid4()
    file_id = uuid4()
    file = DataFile(
        id=file_id,
        user_id=user_id,
        path=f"users/{user_id}/inbox/report.pdf",
        original_name="report.pdf",
        size=2048,
        owner_scope=OwnerScope.PERSONAL.value,
    )
    service = _service_with_backend(_FakeS3Backend(), tmp_path)

    async def _get_visible(actor: UUID, fid: UUID):
        return file if fid == file_id else None

    service._files.get_visible = _get_visible

    url = await service.create_presigned_download(user_id, file_id, expires=7200)

    assert "download/users/" in url
    assert "expires=7200" in url


@pytest.mark.asyncio
async def test_create_presigned_download_rejects_other_user() -> None:
    owner = uuid4()
    actor = uuid4()
    file_id = uuid4()
    file = DataFile(
        id=file_id,
        user_id=owner,
        path=f"users/{owner}/inbox/report.pdf",
        original_name="report.pdf",
        size=2048,
        owner_scope=OwnerScope.PERSONAL.value,
    )
    service = _service_with_backend(_FakeS3Backend())

    async def _get_visible(actor_user_id: UUID, fid: UUID):
        return file if fid == file_id else None

    service._files.get_visible = _get_visible

    with pytest.raises(AuthorizationError):
        await service.create_presigned_download(actor, file_id)


@pytest.mark.asyncio
async def test_create_presigned_download_local_backend_raises(tmp_path) -> None:
    user_id = uuid4()
    file_id = uuid4()
    file = DataFile(
        id=file_id,
        user_id=user_id,
        path=f"users/{user_id}/inbox/report.pdf",
        original_name="report.pdf",
        size=2048,
        owner_scope=OwnerScope.PERSONAL.value,
    )
    service = _service_with_backend(LocalStorageBackend(), tmp_path)
    service._factory = StoragePathFactory(
        StorageConfig(data_root=str(tmp_path), users_subdir="users")
    )
    service._backend = LocalStorageBackend(service._factory)

    async def _get_visible(actor: UUID, fid: UUID):
        return file if fid == file_id else None

    service._files.get_visible = _get_visible

    with pytest.raises(BusinessError, match="不支持预签名"):
        await service.create_presigned_download(user_id, file_id)


@pytest.mark.asyncio
async def test_create_presigned_upload_returns_s3_url_and_creates_record(tmp_path) -> None:
    user_id = uuid4()
    saved: list[DataFile] = []

    service = _service_with_backend(_FakeS3Backend(), tmp_path)

    async def _get_user(uid: UUID):
        return SimpleNamespace(used_storage=0, storage_quota=10 * 1024 * 1024)

    async def _save(record: DataFile):
        saved.append(record)
        return record

    service._users.get_by_id = _get_user
    service._files.save = _save

    url, file_id, storage_path = await service.create_presigned_upload(
        user_id,
        original_name="sample.fastq.gz",
        directory="raw_data",
        size=1024,
        file_type="fastq",
        expires=1800,
    )

    assert "upload/users/" in url
    assert "expires=1800" in url
    assert isinstance(file_id, UUID)
    assert storage_path.startswith(f"users/{user_id}/inbox/raw_data/")
    assert len(saved) == 1
    record = saved[0]
    assert record.status == "uploading"
    assert record.source == "upload"
    assert record.owner_scope == OwnerScope.PERSONAL.value
    assert record.file_type == FileType.FASTQ


@pytest.mark.asyncio
async def test_create_presigned_upload_rejects_quota_exceeded(tmp_path) -> None:
    user_id = uuid4()
    service = _service_with_backend(_FakeS3Backend(), tmp_path)

    async def _get_user(uid: UUID):
        return SimpleNamespace(used_storage=9_900, storage_quota=10_000)

    service._users.get_by_id = _get_user

    with pytest.raises(ValidationError, match="配额不足"):
        await service.create_presigned_upload(
            user_id,
            original_name="big.bam",
            directory="",
            size=200,
        )


@pytest.mark.asyncio
async def test_create_presigned_upload_local_backend_raises(tmp_path) -> None:
    user_id = uuid4()
    service = _service_with_backend(LocalStorageBackend(), tmp_path)
    service._factory = StoragePathFactory(
        StorageConfig(data_root=str(tmp_path), users_subdir="users")
    )
    service._backend = LocalStorageBackend(service._factory)

    async def _get_user(uid: UUID):
        return SimpleNamespace(used_storage=0, storage_quota=10 * 1024 * 1024)

    async def _save(record: DataFile):
        return record

    service._users.get_by_id = _get_user
    service._files.save = _save

    with pytest.raises(BusinessError, match="不支持预签名"):
        await service.create_presigned_upload(
            user_id,
            original_name="sample.bam",
            directory="",
            size=1024,
        )


@pytest.mark.asyncio
async def test_complete_presigned_upload_activates_record(tmp_path) -> None:
    user_id = uuid4()
    file_id = uuid4()
    file = DataFile(
        id=file_id,
        user_id=user_id,
        path=f"users/{user_id}/inbox/raw_data/sample.fastq.gz",
        original_name="sample.fastq.gz",
        size=0,
        checksum="",
        status="uploading",
        directory="raw_data",
        file_type=FileType.FASTQ,
    )

    service = _service_with_backend(_FakeS3Backend(), tmp_path)

    async def _get_file(uid: UUID, fid: UUID):
        return file if fid == file_id else None

    async def _save(record: DataFile):
        return record

    async def _get_user(uid: UUID):
        return SimpleNamespace(used_storage=0, storage_quota=10 * 1024 * 1024)

    async def _add_used_storage(uid: UUID, delta: int):
        return 1024

    service._files.get_by_id = _get_file
    service._files.save = _save
    service._users.get_by_id = _get_user
    service._users.add_used_storage = _add_used_storage

    dto = await service.complete_presigned_upload(user_id, file_id, checksum="abc")

    assert dto.status == "active"
    assert dto.size == 1024
    assert dto.checksum == "abc"
    assert file.status == "active"


@pytest.mark.asyncio
async def test_complete_presigned_upload_rejects_missing_file() -> None:
    user_id = uuid4()
    file_id = uuid4()
    service = _service_with_backend(_FakeS3Backend())

    async def _get_file(uid: UUID, fid: UUID):
        return None

    service._files.get_by_id = _get_file

    with pytest.raises(NotFoundError):
        await service.complete_presigned_upload(user_id, file_id)


@pytest.mark.asyncio
async def test_complete_presigned_upload_rejects_non_uploading_status() -> None:
    user_id = uuid4()
    file_id = uuid4()
    file = DataFile(
        id=file_id,
        user_id=user_id,
        path=f"users/{user_id}/inbox/file.txt",
        original_name="file.txt",
        size=100,
        status="active",
    )
    service = _service_with_backend(_FakeS3Backend())

    async def _get_file(uid: UUID, fid: UUID):
        return file if fid == file_id else None

    service._files.get_by_id = _get_file

    with pytest.raises(ValidationError, match="不处于待上传状态"):
        await service.complete_presigned_upload(user_id, file_id)
