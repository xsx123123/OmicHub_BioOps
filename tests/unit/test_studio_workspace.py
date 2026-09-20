"""Studio 工作区路径防护与磁盘回退单元测试（宿主侧，与 sandbox-agent 规则一致）"""

from pathlib import Path

import pytest

from cygnusx.core.exceptions import BusinessError, NotFoundError
from cygnusx.infrastructure.config.storage_config import StorageConfig
from cygnusx.infrastructure.storage.backend import LocalStorageBackend
from cygnusx.infrastructure.storage.path_factory import StoragePathFactory
from cygnusx.infrastructure.studio.paths import PathEscapeError, resolve_workspace_path
from cygnusx.infrastructure.studio.workspace import (
    disk_list_artifacts,
    disk_list_files,
    disk_read_file,
    link_platform_file,
    list_input_links,
    resolve_artifact_path,
)


def _tmp_backend_factory(tmp_path: Path):
    """返回以 tmp_path 为 data_root 的 (backend, factory)，供测试隔离使用。"""
    factory = StoragePathFactory(
        StorageConfig(data_root=str(tmp_path), users_subdir="users")
    )
    return LocalStorageBackend(factory), factory


# ===== 路径防护 =====


@pytest.mark.unit
def test_relative_path_resolves_inside_root(tmp_path: Path):
    resolved = resolve_workspace_path("output/plot.png", root=tmp_path)
    assert resolved == tmp_path / "output" / "plot.png"


@pytest.mark.unit
def test_dotdot_escape_rejected(tmp_path: Path):
    with pytest.raises(PathEscapeError):
        resolve_workspace_path("../etc/passwd", root=tmp_path)
    with pytest.raises(PathEscapeError):
        resolve_workspace_path("a/../../outside", root=tmp_path)


@pytest.mark.unit
def test_absolute_path_outside_root_rejected(tmp_path: Path):
    with pytest.raises(PathEscapeError):
        resolve_workspace_path("/etc/passwd", root=tmp_path)


@pytest.mark.unit
def test_symlink_escape_rejected(tmp_path: Path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir(exist_ok=True)
    try:
        link = tmp_path / "evil-link"
        link.symlink_to(outside)
        with pytest.raises(PathEscapeError):
            resolve_workspace_path("evil-link/secret.txt", root=tmp_path)
    finally:
        (tmp_path / "evil-link").unlink(missing_ok=True)
        outside.rmdir()


# ===== 磁盘目录列表 / 读文件 =====


@pytest.mark.unit
async def test_disk_list_files_shape(tmp_path: Path):
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "a.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    backend, factory = _tmp_backend_factory(tmp_path)
    listing = await disk_list_files(tmp_path, "output", backend=backend, factory=factory)
    assert listing["path"] == "output"
    assert listing["entries"][0]["name"] == "a.csv"
    assert listing["entries"][0]["type"] == "file"
    assert listing["entries"][0]["size"] == 8


@pytest.mark.unit
async def test_disk_list_files_missing_path(tmp_path: Path):
    backend, factory = _tmp_backend_factory(tmp_path)
    with pytest.raises(NotFoundError):
        await disk_list_files(tmp_path, "nope", backend=backend, factory=factory)


@pytest.mark.unit
async def test_disk_list_files_escape_rejected(tmp_path: Path):
    backend, factory = _tmp_backend_factory(tmp_path)
    with pytest.raises(PathEscapeError):
        await disk_list_files(tmp_path, "../other", backend=backend, factory=factory)


@pytest.mark.unit
async def test_disk_read_file_default_200_lines(tmp_path: Path):
    lines = [f"line-{i}" for i in range(250)]
    (tmp_path / "big.txt").write_text("\n".join(lines), encoding="utf-8")
    backend, factory = _tmp_backend_factory(tmp_path)
    data = await disk_read_file(tmp_path, "big.txt", backend=backend, factory=factory)
    assert data["total_lines"] == 250
    assert data["truncated"] is True
    assert len(data["content"].splitlines()) == 200

    page2 = await disk_read_file(
        tmp_path, "big.txt", offset=200, backend=backend, factory=factory
    )
    assert page2["truncated"] is False
    assert len(page2["content"].splitlines()) == 50


@pytest.mark.unit
async def test_disk_read_file_missing(tmp_path: Path):
    backend, factory = _tmp_backend_factory(tmp_path)
    with pytest.raises(NotFoundError):
        await disk_read_file(tmp_path, "ghost.txt", backend=backend, factory=factory)


@pytest.mark.unit
async def test_disk_read_file_limit_capped(tmp_path: Path):
    (tmp_path / "a.txt").write_text("1\n2\n3", encoding="utf-8")
    backend, factory = _tmp_backend_factory(tmp_path)
    data = await disk_read_file(
        tmp_path, "a.txt", limit=99999, backend=backend, factory=factory
    )
    assert data["total_lines"] == 3
    assert data["truncated"] is False


# ===== 产物扫描与下载路径 =====


@pytest.mark.unit
async def test_disk_list_artifacts_recursive(tmp_path: Path):
    out = tmp_path / "output"
    (out / "sub").mkdir(parents=True)
    (out / "a.png").write_bytes(b"png")
    (out / "sub" / "b.csv").write_text("x", encoding="utf-8")
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "raw.csv").write_text("y", encoding="utf-8")  # 非产物目录

    backend, factory = _tmp_backend_factory(tmp_path)
    artifacts = await disk_list_artifacts(tmp_path, backend=backend, factory=factory)
    paths = {a["path"] for a in artifacts}
    assert paths == {"output/a.png", "output/sub/b.csv"}
    assert all(a["size"] > 0 and a["mtime"] > 0 for a in artifacts)


@pytest.mark.unit
async def test_disk_list_artifacts_empty_when_no_output(tmp_path: Path):
    backend, factory = _tmp_backend_factory(tmp_path)
    assert await disk_list_artifacts(tmp_path, backend=backend, factory=factory) == []


@pytest.mark.unit
def test_resolve_artifact_path_confined_to_output(tmp_path: Path):
    (tmp_path / "output").mkdir()
    target = resolve_artifact_path(tmp_path, "output/plot.png")
    assert target == tmp_path / "output" / "plot.png"
    # 工作区内但非 output 目录 → 拒绝
    with pytest.raises(PathEscapeError):
        resolve_artifact_path(tmp_path, "input/raw.csv")
    # 逃逸工作区 → 拒绝
    with pytest.raises(PathEscapeError):
        resolve_artifact_path(tmp_path, "../outside.png")


@pytest.mark.unit
def test_business_error_importable():
    """磁盘回退使用的是既有异常约定（404/400）"""
    assert issubclass(NotFoundError, Exception)
    assert issubclass(BusinessError, Exception)


# ===== 平台数据软链（挂载进沙盒工作区） =====


@pytest.mark.unit
def test_link_platform_file_creates_input_symlink(tmp_path: Path):
    from cygnusx.infrastructure.studio.paths import PLATFORM_CONTAINER_MOUNT

    name = link_platform_file(tmp_path, "raw/a.csv")
    assert name == "a.csv"
    link = tmp_path / "input" / "a.csv"
    assert link.is_symlink()
    # 软链目标为容器内平台只读挂载路径（宿主侧悬空属预期）
    assert link.readlink() == Path(f"{PLATFORM_CONTAINER_MOUNT}/raw/a.csv")
    assert list_input_links(tmp_path) == ["a.csv"]


@pytest.mark.unit
def test_link_platform_file_idempotent_same_target(tmp_path: Path):
    """idempotent=True 时同一平台路径重复引入复用既有软链，不生成 name (2)/(3) 冗余链接。"""
    first = link_platform_file(tmp_path, "raw/a.csv", idempotent=True)
    second = link_platform_file(tmp_path, "raw/a.csv", idempotent=True)
    third = link_platform_file(tmp_path, "raw/a.csv", display_name="renamed.csv", idempotent=True)
    assert first == second == third == "a.csv"
    assert list_input_links(tmp_path) == ["a.csv"]


@pytest.mark.unit
def test_link_platform_file_distinct_targets_distinct_links(tmp_path: Path):
    """不同平台路径（即便同名）应各自建立软链。"""
    a = link_platform_file(tmp_path, "raw/a.csv")
    b = link_platform_file(tmp_path, "other/a.csv")
    assert a == "a.csv"
    assert b == "a (2).csv"
    assert set(list_input_links(tmp_path)) == {"a.csv", "a (2).csv"}


@pytest.mark.unit
def test_link_platform_file_non_idempotent_forces_duplicate(tmp_path: Path):
    a = link_platform_file(tmp_path, "raw/a.csv", idempotent=False)
    b = link_platform_file(tmp_path, "raw/a.csv", idempotent=False)
    assert a == "a.csv"
    assert b == "a (2).csv"
