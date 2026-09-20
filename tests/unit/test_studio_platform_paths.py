"""Studio 平台只读挂载路径放行与软链工具单元测试（P1 数据不搬家，宿主侧）"""

import os
from pathlib import Path

import pytest

from cygnusx.infrastructure.config.storage_config import StorageConfig
from cygnusx.infrastructure.storage.backend import LocalStorageBackend
from cygnusx.infrastructure.storage.path_factory import StoragePathFactory
from cygnusx.infrastructure.studio.paths import (
    PLATFORM_CONTAINER_MOUNT,
    PathEscapeError,
    resolve_workspace_path,
    resolve_workspace_read_path,
)
from cygnusx.infrastructure.studio.workspace import (
    disk_read_file,
    link_platform_file,
    list_input_links,
    platform_user_rel,
)

# ===== resolve_workspace_read_path：读路径放行 =====


@pytest.mark.unit
def test_read_path_inside_workspace_not_via_platform(tmp_path: Path):
    """工作区内普通路径照常放行，via_platform=False"""
    resolved = resolve_workspace_read_path("output/plot.png", root=tmp_path)
    assert resolved.path == tmp_path / "output" / "plot.png"
    assert resolved.via_platform is False


@pytest.mark.unit
def test_read_path_platform_symlink_allowed_and_translated(tmp_path: Path):
    """input/ 下指向 /data/platform 的软链：读放行并翻译到宿主用户数据目录"""
    workspace = tmp_path / "ws"
    storage_user = tmp_path / "storage" / "users" / "u1"
    (storage_user / "raw").mkdir(parents=True)
    (storage_user / "raw" / "x.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (workspace / "input").mkdir(parents=True)
    (workspace / "input" / "x.csv").symlink_to(f"{PLATFORM_CONTAINER_MOUNT}/raw/x.csv")

    resolved = resolve_workspace_read_path(
        "input/x.csv", root=workspace, platform_host_root=storage_user
    )
    assert resolved.via_platform is True
    assert resolved.path == storage_user / "raw" / "x.csv"


@pytest.mark.unit
def test_read_path_platform_symlink_identity_without_host_root(tmp_path: Path):
    """容器内语义（不传 platform_host_root）：返回 /data/platform 原路径"""
    workspace = tmp_path / "ws"
    (workspace / "input").mkdir(parents=True)
    (workspace / "input" / "x.csv").symlink_to(f"{PLATFORM_CONTAINER_MOUNT}/raw/x.csv")

    resolved = resolve_workspace_read_path("input/x.csv", root=workspace)
    assert resolved.via_platform is True
    assert resolved.path == Path(f"{PLATFORM_CONTAINER_MOUNT}/raw/x.csv")


@pytest.mark.unit
def test_read_path_direct_platform_absolute_rejected(tmp_path: Path):
    """直接拼 /data/platform 绝对路径被拒绝（只允许经工作区内软链跳转）"""
    with pytest.raises(PathEscapeError):
        resolve_workspace_read_path(f"{PLATFORM_CONTAINER_MOUNT}/users/other/x.csv", root=tmp_path)


@pytest.mark.unit
def test_read_path_platform_root_itself_rejected(tmp_path: Path):
    """词法路径在工作区外时，即使指向平台挂载也拒绝"""
    with pytest.raises(PathEscapeError):
        resolve_workspace_read_path(f"{PLATFORM_CONTAINER_MOUNT}", root=tmp_path)


@pytest.mark.unit
def test_read_path_non_platform_escape_still_rejected(tmp_path: Path):
    """软链跳到 /etc 等非平台挂载位置依然拒绝"""
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir(exist_ok=True)
    try:
        (tmp_path / "evil").symlink_to(outside)
        with pytest.raises(PathEscapeError):
            resolve_workspace_read_path("evil/secret.txt", root=tmp_path)
    finally:
        (tmp_path / "evil").unlink(missing_ok=True)
        outside.rmdir()


@pytest.mark.unit
def test_write_guard_still_rejects_platform_symlink(tmp_path: Path):
    """写路径守卫（resolve_workspace_path）对平台软链一律拒绝，不受读放行影响"""
    workspace = tmp_path / "ws"
    (workspace / "input").mkdir(parents=True)
    (workspace / "input" / "x.csv").symlink_to(f"{PLATFORM_CONTAINER_MOUNT}/raw/x.csv")
    with pytest.raises(PathEscapeError):
        resolve_workspace_path("input/x.csv", root=workspace)


@pytest.mark.unit
async def test_disk_read_file_through_platform_symlink(tmp_path: Path):
    """宿主磁盘回退：经平台软链翻译读取用户数据文件"""
    workspace = tmp_path / "ws"
    storage_root = tmp_path / "storage"
    storage_user = storage_root / "users" / "u1"
    (storage_user / "raw").mkdir(parents=True)
    (storage_user / "raw" / "x.csv").write_text("l1\nl2\nl3\n", encoding="utf-8")
    (workspace / "input").mkdir(parents=True)
    (workspace / "input" / "x.csv").symlink_to(f"{PLATFORM_CONTAINER_MOUNT}/raw/x.csv")

    factory = StoragePathFactory(
        StorageConfig(data_root=str(storage_root), users_subdir="users")
    )
    backend = LocalStorageBackend(factory)
    data = await disk_read_file(
        workspace,
        "input/x.csv",
        platform_host_root=storage_user,
        backend=backend,
        factory=factory,
    )
    assert data["total_lines"] == 3
    assert data["content"] == "l1\nl2\nl3"


# ===== platform_user_rel / link_platform_file / list_input_links =====


@pytest.mark.unit
def test_platform_user_rel_strips_user_prefix():
    assert platform_user_rel("users/u1/raw/a.csv", "u1") == "raw/a.csv"
    assert platform_user_rel("users/u1/results/t1/r.html", "u1") == "results/t1/r.html"


@pytest.mark.unit
def test_platform_user_rel_rejects_other_user_and_traversal():
    """其他用户目录 / .. / 绝对路径一律拒绝（多租户隔离）"""
    with pytest.raises(PathEscapeError):
        platform_user_rel("users/u2/raw/a.csv", "u1")
    with pytest.raises(PathEscapeError):
        platform_user_rel("users/u1/../u2/a.csv", "u1")
    with pytest.raises(PathEscapeError):
        platform_user_rel("/etc/passwd", "u1")


@pytest.mark.unit
def test_link_platform_file_creates_container_path_symlink(tmp_path: Path):
    """软链目标为容器内 /data/platform 路径；宿主侧悬空属预期（lexists 可见）"""
    link_name = link_platform_file(tmp_path, "raw/a.csv", "a.csv")
    assert link_name == "a.csv"
    link = tmp_path / "input" / "a.csv"
    assert os.path.lexists(link)
    assert os.readlink(link) == f"{PLATFORM_CONTAINER_MOUNT}/raw/a.csv"


@pytest.mark.unit
def test_link_platform_file_dedupes_on_collision(tmp_path: Path):
    """重名自动加 " (2)" 后缀（注意宿主侧软链悬空，exists 会漏判，必须用 lexists）"""
    first = link_platform_file(tmp_path, "raw/a.csv", "a.csv")
    second = link_platform_file(tmp_path, "raw/a.csv", "a.csv")
    third = link_platform_file(tmp_path, "raw/a.csv", "a.csv")
    assert first == "a.csv"
    assert second == "a (2).csv"
    assert third == "a (3).csv"


@pytest.mark.unit
def test_link_platform_file_sanitizes_display_name(tmp_path: Path):
    """显示名取 basename，防路径注入"""
    link_name = link_platform_file(tmp_path, "raw/a.csv", "../evil.csv")
    assert link_name == "evil.csv"
    assert os.path.lexists(tmp_path / "input" / "evil.csv")


@pytest.mark.unit
def test_list_input_links_includes_dangling(tmp_path: Path):
    link_platform_file(tmp_path, "raw/a.csv", "a.csv")
    link_platform_file(tmp_path, "raw/b.csv", "b.csv")
    assert list_input_links(tmp_path) == ["a.csv", "b.csv"]
    assert list_input_links(tmp_path / "nonexistent") == []
