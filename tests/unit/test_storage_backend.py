from pathlib import Path

import pytest

from cygnusx.core.exceptions import NotFoundError
from cygnusx.infrastructure.config.storage_config import StorageConfig
from cygnusx.infrastructure.storage import (
    LocalStorageBackend,
    S3CompatibleStorageBackend,
    reset_storage_backend,
)
from cygnusx.infrastructure.storage.backend import (
    get_storage_backend as _backend_get_storage_backend,
)
from cygnusx.infrastructure.storage.path_factory import StoragePathFactory


def _make_factory(tmp_path: Path) -> StoragePathFactory:
    return StoragePathFactory(
        StorageConfig(data_root=str(tmp_path), users_subdir="users")
    )


@pytest.mark.asyncio
async def test_local_read_write_delete_exists(tmp_path: Path) -> None:
    backend = LocalStorageBackend(path_factory=_make_factory(tmp_path))
    rel_path = "users/u1/inbox/hello.txt"
    content = b"hello, cygnusx"

    assert await backend.exists(rel_path) is False

    await backend.write(rel_path, content)
    assert await backend.exists(rel_path) is True
    assert await backend.read(rel_path) == content

    await backend.delete(rel_path)
    assert await backend.exists(rel_path) is False

    with pytest.raises(NotFoundError):
        await backend.read(rel_path)
    with pytest.raises(NotFoundError):
        await backend.delete(rel_path)


@pytest.mark.asyncio
async def test_local_read_with_offset_and_limit(tmp_path: Path) -> None:
    backend = LocalStorageBackend(path_factory=_make_factory(tmp_path))
    rel_path = "users/u1/inbox/seq.txt"
    content = b"ABCDEFGHIJ"
    await backend.write(rel_path, content)

    assert await backend.read(rel_path, offset=2, limit=4) == b"CDEF"
    assert await backend.read(rel_path, offset=7) == b"HIJ"
    assert await backend.read(rel_path, limit=3) == b"ABC"


@pytest.mark.asyncio
async def test_local_stat(tmp_path: Path) -> None:
    backend = LocalStorageBackend(path_factory=_make_factory(tmp_path))
    rel_path = "users/u1/inbox/data.bin"
    await backend.write(rel_path, b"x" * 42)

    info = await backend.stat(rel_path)
    assert info is not None
    assert info["is_dir"] is False
    assert info["size"] == 42
    assert isinstance(info["mtime"], float)

    assert await backend.stat("users/u1/inbox") is not None
    assert (await backend.stat("users/u1/inbox"))["is_dir"] is True
    assert await backend.stat("not/exists.txt") is None


@pytest.mark.asyncio
async def test_local_list_recursive_and_non_recursive(tmp_path: Path) -> None:
    backend = LocalStorageBackend(path_factory=_make_factory(tmp_path))
    await backend.write("users/u1/inbox/a.txt", b"a")
    await backend.write("users/u1/inbox/sub/b.txt", b"b")

    flat = await backend.list("users/u1/inbox", recursive=False)
    flat_paths = {e["path"] for e in flat}
    assert "users/u1/inbox/a.txt" in flat_paths
    assert "users/u1/inbox/sub" in flat_paths
    assert "users/u1/inbox/sub/b.txt" not in flat_paths

    deep = await backend.list("users/u1/inbox", recursive=True)
    deep_paths = {e["path"] for e in deep}
    assert "users/u1/inbox/a.txt" in deep_paths
    assert "users/u1/inbox/sub" in deep_paths
    assert "users/u1/inbox/sub/b.txt" in deep_paths

    # 不存在的目录返回空列表
    assert await backend.list("users/u1/missing", recursive=True) == []


@pytest.mark.asyncio
async def test_local_get_local_path(tmp_path: Path) -> None:
    backend = LocalStorageBackend(path_factory=_make_factory(tmp_path))
    rel_path = "users/u1/inbox/local.txt"
    await backend.write(rel_path, b"local")

    local_path = await backend.get_local_path(rel_path)
    assert isinstance(local_path, Path)
    assert local_path == tmp_path / rel_path
    assert local_path.read_bytes() == b"local"

    with pytest.raises(NotFoundError):
        await backend.get_local_path("users/u1/inbox/nope.txt")


def test_get_storage_backend_returns_local_by_default(monkeypatch, tmp_path: Path) -> None:
    reset_storage_backend()
    factory = _make_factory(tmp_path)

    monkeypatch.setattr(
        "cygnusx.infrastructure.storage.backend.get_storage_config",
        lambda: StorageConfig(data_root=str(tmp_path), users_subdir="users", storage_type="local"),
    )
    monkeypatch.setattr(
        "cygnusx.infrastructure.storage.backend.get_path_factory",
        lambda: factory,
    )

    backend1 = _backend_get_storage_backend()
    backend2 = _backend_get_storage_backend()
    assert isinstance(backend1, LocalStorageBackend)
    assert backend1 is backend2

    reset_storage_backend()
    backend3 = _backend_get_storage_backend()
    assert backend3 is not backend1
    assert isinstance(backend3, LocalStorageBackend)


def test_get_storage_backend_switches_to_s3(monkeypatch, tmp_path: Path) -> None:
    reset_storage_backend()
    factory = _make_factory(tmp_path)

    monkeypatch.setattr(
        "cygnusx.infrastructure.storage.backend.get_storage_config",
        lambda: StorageConfig(data_root=str(tmp_path), users_subdir="users", storage_type="s3"),
    )
    monkeypatch.setattr(
        "cygnusx.infrastructure.storage.backend.get_path_factory",
        lambda: factory,
    )

    backend = _backend_get_storage_backend()
    assert isinstance(backend, S3CompatibleStorageBackend)

    reset_storage_backend()
