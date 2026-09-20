"""工作区归档（WP1）纯逻辑单测：tar 路径逃逸防护 / manifest 四件套校验 / 幂等追加。

不依赖 DB 与 Docker：只测 archive_storage 的纯函数与本地文件操作，
以及 workspace_archive_service 的 AGENTS.md 幂等追加。
"""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

from cygnusx.application.services.workspace_archive_service import (
    append_workspace_archive_entry,
)
from cygnusx.infrastructure.studio.archive_storage import (
    LocalArchiveStorage,
    build_manifest,
    safe_archive_stem,
)


def _make_config(tmp_path: Path):
    """构造一个指向临时目录的 StudioConfig（不经全局 settings）。"""
    from cygnusx.infrastructure.config.studio_loader import StudioConfig, StudioMountsConfig

    config = StudioConfig()
    config.mounts = StudioMountsConfig(workspace=str(tmp_path / "studio"))
    object.__setattr__(config, "archive_root", tmp_path / "studio-archive")  # property 不行，换方式
    return config


class _FakeConfig:
    """最小 config 替身：LocalArchiveStorage 只需要 archive_root。"""

    def __init__(self, root: Path) -> None:
        self.archive_root = root


def _storage(tmp_path: Path) -> LocalArchiveStorage:
    return LocalArchiveStorage(_FakeConfig(tmp_path / "studio-archive"))  # type: ignore[arg-type]


# ------------------------------------------------------------------
# 文件名哈希分支
# ------------------------------------------------------------------


def test_safe_archive_stem_uuid_passthrough() -> None:
    assert safe_archive_stem("f44a8386-b420-4154-bc3f-d4f3ca940492") == (
        "f44a8386-b420-4154-bc3f-d4f3ca940492"
    )


def test_safe_archive_stem_hash_branch_for_non_uuid() -> None:
    stem = safe_archive_stem("agentteams:case-42")
    assert stem != "agentteams:case-42"
    assert ":" not in stem and "/" not in stem and len(stem) == 12


# ------------------------------------------------------------------
# manifest 生成：逐文件 sha256 + 四件套校验
# ------------------------------------------------------------------


def test_build_manifest_hashes_and_env_snapshot(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    (workspace / "output").mkdir(parents=True)
    (workspace / "output" / "result.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (workspace / "environment.yml").write_text("name: test\n", encoding="utf-8")

    manifest = build_manifest(workspace, "sess-1")
    assert manifest["file_count"] == 2
    assert manifest["total_bytes"] > 0
    by_path = {f["path"]: f for f in manifest["files"]}
    entry = by_path["workspace/output/result.csv"]
    assert entry["size"] == len("a,b\n1,2\n")
    assert len(entry["sha256"]) == 64
    # 四件套只缺 3 件（environment.yml 存在）
    missing = manifest["env_snapshot"]["missing_env_snapshot"]
    assert "environment.yml" not in missing
    assert set(missing) == {"conda-explicit.txt", "software-versions.txt", "pip-freeze.txt"}


def test_build_manifest_all_env_files_present(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    for name in ("conda-explicit.txt", "environment.yml", "software-versions.txt", "pip-freeze.txt"):
        (workspace / name).write_text("x", encoding="utf-8")
    manifest = build_manifest(workspace, "sess-2")
    assert "missing_env_snapshot" not in manifest["env_snapshot"]


# ------------------------------------------------------------------
# tar 路径逃逸防护
# ------------------------------------------------------------------


def _build_evil_tar(path: Path) -> None:
    with tarfile.open(path, "w:gz") as tar:
        payload = b"pwned"
        for name in ("workspace/ok.txt", "../evil.txt", "workspace/../../etc/evil2.txt"):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        # 目录穿越型成员（纯目录）
        tar.addfile(tarfile.TarInfo("workspace/sub/../../.."))


def test_extract_rejects_path_traversal(tmp_path: Path) -> None:
    package = tmp_path / "evil.tar.gz"
    _build_evil_tar(package)
    target = tmp_path / "restore"
    target.mkdir()
    result = LocalArchiveStorage.extract_workspace(package, target)
    assert (target / "ok.txt").read_bytes() == b"pwned"
    assert "evil.txt" not in [p.name for p in target.rglob("*")]
    assert result["extracted_files"] == 1
    assert "../evil.txt" in result["skipped_members"]
    assert any("etc" in m for m in result["skipped_members"])


def test_extract_skips_non_workspace_members(tmp_path: Path) -> None:
    package = tmp_path / "pkg.tar.gz"
    with tarfile.open(package, "w:gz") as tar:
        payload = b"data"
        for name in ("manifest.json", "workspace/a.txt", "other-root.txt"):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    target = tmp_path / "restore"
    target.mkdir()
    result = LocalArchiveStorage.extract_workspace(package, target)
    assert result["extracted_files"] == 1
    assert (target / "a.txt").is_file()
    assert not (target / "other-root.txt").exists()
    assert not (target / "manifest.json").exists()


# ------------------------------------------------------------------
# 打包 → 解包 roundtrip + manifest 校验
# ------------------------------------------------------------------


def test_pack_unpack_roundtrip(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    workspace = tmp_path / "studio" / "sess-roundtrip"
    (workspace / "scripts").mkdir(parents=True)
    (workspace / "scripts" / "run.py").write_text("print('hi')\n", encoding="utf-8")
    (workspace / "software-versions.txt").write_text("python=3.12\n", encoding="utf-8")

    storage = _storage(tmp_path)
    created_at = datetime(2026, 9, 18, tzinfo=UTC)
    package = storage.save_package("user-1", "sess-roundtrip", workspace, created_at=created_at)
    assert package.path.is_file()
    assert package.size_bytes > 0
    assert len(package.manifest_sha256) == 64
    # 目录权限：0700（服务可写、用户不可达）
    assert (tmp_path / "studio-archive" / "user-1").stat().st_mode & 0o777 == 0o700
    # tar 内含 workspace/ 树 + manifest.json
    with tarfile.open(package.path, "r:gz") as tar:
        names = tar.getnames()
    assert "manifest.json" in names
    assert "workspace/scripts/run.py" in names

    target = tmp_path / "restore"
    target.mkdir()
    result = LocalArchiveStorage.extract_workspace(package.path, target)
    assert result["extracted_files"] == 2
    assert result["sha256_mismatch"] == []
    assert (target / "scripts" / "run.py").read_text(encoding="utf-8") == "print('hi')\n"


def test_save_package_missing_workspace(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from cygnusx.infrastructure.studio.archive_storage import ArchiveStorageError

    storage = _storage(tmp_path)
    with pytest.raises(ArchiveStorageError):
        storage.save_package(
            "user-1", "sess-x", tmp_path / "nope", created_at=datetime(2026, 9, 18, tzinfo=UTC)
        )


# ------------------------------------------------------------------
# 项目 AGENTS.md 幂等追加
# ------------------------------------------------------------------


def test_append_workspace_archive_entry_idempotent() -> None:
    content = "# Proj\n"
    line = "会话 s1 于 2026-09-18T00:00:00+00:00 归档，包路径 /pkg，manifest sha256 abc"
    updated, appended = append_workspace_archive_entry(
        content, marker="workspace-archive/pkg-1", timestamp="2026-09-18T00:00:00+00:00", line=line
    )
    assert appended is True
    assert "## 分析记录" in updated
    assert "workspace-archive/pkg-1" in updated

    again, appended2 = append_workspace_archive_entry(
        updated, marker="workspace-archive/pkg-1", timestamp="t2", line="dup"
    )
    assert appended2 is False
    assert again == updated


def test_manifest_json_valid_in_package(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    workspace = tmp_path / "studio" / "sess-json"
    workspace.mkdir(parents=True)
    (workspace / "conda-explicit.txt").write_text("pkg", encoding="utf-8")
    (workspace / "environment.yml").write_text("name: x", encoding="utf-8")
    (workspace / "software-versions.txt").write_text("py", encoding="utf-8")
    (workspace / "pip-freeze.txt").write_text("pip", encoding="utf-8")

    storage = _storage(tmp_path)
    package = storage.save_package(
        "user-1", "sess-json", workspace, created_at=datetime(2026, 9, 18, tzinfo=UTC)
    )
    with tarfile.open(package.path, "r:gz") as tar:
        handle = tar.extractfile("manifest.json")
        assert handle is not None
        manifest = json.loads(handle.read().decode("utf-8"))
    assert manifest["session_id"] == "sess-json"
    assert manifest["env_snapshot"]["checked_files"]  # 四件套已校验
    assert "missing_env_snapshot" not in manifest["env_snapshot"]
    # 落库 manifest_sha256 与包内 manifest 一致
    import hashlib

    canonical = (
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    )
    assert hashlib.sha256(canonical).hexdigest() == package.manifest_sha256
