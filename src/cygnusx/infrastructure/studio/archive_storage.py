"""Studio 工作区归档包存储后端（WP1）。

平台侧归档存储与 ``studio/`` 工作区平级、独立顶级目录
``{storage_path}/studio-archive/{user_id}/``：
- 目录创建 mode 0700（服务进程可写、用户不可达），文件 0600；
- 任何容器挂载都不得包含该目录（现有容器只 bind-mount workspace_root
  与 users/{user_id}，本目录不进挂载表，禁止新增挂载）；
- 归档文件名对非 UUID / 含非法字符的 session_id 走 sha256 哈希分支
  （与 manager.container_name 同一防非法字符规则）。

backend=s3 本期仅为配置占位：工厂显式 raise NotImplementedError，
避免调用方误以为归档真的落到了对象存储。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from loguru import logger

from cygnusx.infrastructure.config.studio_loader import StudioConfig

# 环境快照四件套：存在性校验缺失时标 missing_env_snapshot（不阻断打包）
_ENV_SNAPSHOT_FILES = (
    "conda-explicit.txt",
    "environment.yml",
    "software-versions.txt",
    "pip-freeze.txt",
)
_HASH_CHUNK_SIZE = 1024 * 1024
_SAFE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,47}")


class ArchiveStorageError(Exception):
    """归档包存取失败（磁盘错误 / tar 结构非法 / 路径逃逸）。"""


@dataclass
class ArchiveManifestFile:
    """manifest.json 中单个文件的清单条目。"""

    path: str  # tar 内相对路径（workspace/ 前缀）
    size: int
    sha256: str


@dataclass
class ArchivePackage:
    """一次打包的产物：包文件 + manifest 及其哈希。"""

    path: Path
    size_bytes: int
    manifest: dict[str, Any]
    manifest_sha256: str


def safe_archive_stem(session_id: str) -> str:
    """归档文件名主干：UUID/安全字符 session_id 直用，其余走 sha256 哈希分支。

    与 manager.container_name 同一规则，保证 ``agentteams:xxx`` 这类含
    ``:`` 等非法字符的 session_id 不会污染文件名。
    """
    candidate = session_id.strip()
    if _SAFE_NAME_RE.fullmatch(candidate or ""):
        return candidate
    return hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:12]


def _hash_file(path: Path) -> str:
    """流式计算文件 sha256（分块读取，大文件不进内存）。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_HASH_CHUNK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def build_manifest(workspace_dir: Path, session_id: str) -> dict[str, Any]:
    """扫描工作区目录生成 manifest：逐文件 path/size/sha256（流式哈希）。

    同时校验环境快照四件套存在性，缺失时在 env_snapshot 标
    missing_env_snapshot（不阻断打包）。
    """
    files: list[ArchiveManifestFile] = []
    env_snapshot: dict[str, Any] = {"checked_files": list(_ENV_SNAPSHOT_FILES)}
    missing: list[str] = []
    for name in _ENV_SNAPSHOT_FILES:
        if not (workspace_dir / name).is_file():
            missing.append(name)
    if missing:
        env_snapshot["missing_env_snapshot"] = missing
    total_bytes = 0
    for path in sorted(workspace_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        rel = f"workspace/{path.relative_to(workspace_dir).as_posix()}"
        files.append(ArchiveManifestFile(path=rel, size=size, sha256=_hash_file(path)))
        total_bytes += size
    return {
        "schema_version": 1,
        "session_id": session_id,
        "packed_at": datetime.now(UTC).isoformat(),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "env_snapshot": env_snapshot,
        "files": [f.__dict__ for f in files],
    }


def _validate_member_name(name: str) -> str | None:
    """校验 tar 成员名：只允许 workspace/ 子树内且不越界。

    返回规范化的相对路径（不含 workspace/ 前缀）；非法返回 None。
    """
    pure = PurePosixPath(name)
    parts = [part for part in pure.parts if part not in {"", "."}]
    if not parts or parts[0] != "workspace":
        return None
    if any(part == ".." for part in parts):
        return None
    # 只允许常规文件 / 目录 / 软链，且软链不允许指向 workspace 之外
    return "/".join(parts[1:])


class ArchiveStorageBackend:
    """归档包存储后端接口。"""

    def package_path(self, user_id: str, session_id: str, created_at: datetime) -> Path:
        """归档包最终落盘路径。"""
        raise NotImplementedError

    def save_package(
        self, user_id: str, session_id: str, workspace_dir: Path, *, created_at: datetime
    ) -> ArchivePackage:
        """把 workspace_dir 整目录打成 tar.gz（含 manifest.json）并落盘。"""
        raise NotImplementedError

    def delete_package(self, package_path: Path) -> bool:
        """删除包文件；不存在视为成功，返回是否实际删除。"""
        raise NotImplementedError

    def exists(self, package_path: Path) -> bool:
        raise NotImplementedError


@dataclass
class LocalArchiveStorage(ArchiveStorageBackend):
    """本地磁盘归档存储：{storage_path}/studio-archive/{user_id}/，mode 0700。"""

    config: StudioConfig
    _root: Path = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_root", self.config.archive_root)

    # ------------------------------------------------------------------
    def _user_dir(self, user_id: str) -> Path:
        """用户归档目录（防路径逃逸：user_id 不允许含路径分隔）。"""
        safe_user = str(user_id)
        if not _SAFE_NAME_RE.fullmatch(safe_user) or "/" in safe_user or ".." in safe_user:
            safe_user = hashlib.sha256(safe_user.encode("utf-8")).hexdigest()[:16]
        directory = self._root / safe_user
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        return directory

    def package_path(self, user_id: str, session_id: str, created_at: datetime) -> Path:
        stem = safe_archive_stem(session_id)
        stamp = created_at.strftime("%Y%m%d%H%M%S")
        unique = uuid.uuid4().hex[:8]
        return self._user_dir(user_id) / f"ws-{stem}-{stamp}-{unique}.tar.gz"

    def exists(self, package_path: Path) -> bool:
        return package_path.is_file()

    def delete_package(self, package_path: Path) -> bool:
        try:
            return package_path.unlink() is None or not package_path.exists()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise ArchiveStorageError(f"归档包删除失败: {package_path}: {exc}") from exc

    # ------------------------------------------------------------------
    def save_package(
        self,
        user_id: str,
        session_id: str,
        workspace_dir: Path,
        *,
        created_at: datetime,
    ) -> ArchivePackage:
        if not workspace_dir.is_dir():
            raise ArchiveStorageError(f"工作区目录不存在: {workspace_dir}")
        manifest = build_manifest(workspace_dir, session_id)
        manifest_bytes = (
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        )
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()

        final_path = self.package_path(user_id, session_id, created_at)
        # 临时文件同窗目录构建，写完后 os.replace 原子改名，避免半成品包被读到
        tmp_path = final_path.with_suffix(final_path.suffix + f".tmp-{os.getpid()}")
        try:
            with tarfile.open(tmp_path, "w:gz") as tar:
                tar.add(workspace_dir, arcname="workspace", recursive=True)
                info = tarfile.TarInfo("manifest.json")
                info.size = len(manifest_bytes)
                info.mtime = int(created_at.timestamp())
                import io

                tar.addfile(info, io.BytesIO(manifest_bytes))
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, final_path)
        except OSError as exc:
            tmp_path.unlink(missing_ok=True)
            raise ArchiveStorageError(f"归档包写入失败: {exc}") from exc
        size_bytes = final_path.stat().st_size
        logger.info(
            "[Archive] 打包完成 session={} path={} size={} files={} manifest_sha256={}",
            session_id[:12],
            final_path,
            size_bytes,
            manifest["file_count"],
            manifest_sha256,
        )
        return ArchivePackage(
            path=final_path,
            size_bytes=size_bytes,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
        )

    # ------------------------------------------------------------------
    def iter_workspace_members(self, package_path: Path) -> Any:
        """打开 tar.gz 供解包迭代（调用方负责关闭）。"""
        return tarfile.open(package_path, "r:gz")

    @staticmethod
    def extract_workspace(package_path: Path, workspace_dir: Path) -> dict[str, Any]:
        """解 tar.gz 回 workspace_dir：只解 workspace/ 子树，拒绝路径逃逸成员。

        返回 {extracted_files, skipped_members, sha256_mismatch}；
        manifest 校验失败（sha256 不匹配）只记 warning 不阻断（磁盘位腐人工处理）。
        """
        manifest: dict[str, Any] = {}
        extracted = 0
        skipped: list[str] = []
        mismatched: list[str] = []
        with tarfile.open(package_path, "r:gz") as tar:
            members = tar.getmembers()
            for member in members:
                if member.name == "manifest.json":
                    handle = tar.extractfile(member)
                    if handle is not None:
                        try:
                            manifest = json.loads(handle.read().decode("utf-8"))
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            manifest = {}
                    continue
            expected = {
                item["path"]: item for item in manifest.get("files", []) if isinstance(item, dict)
            }
            for member in members:
                if not member.isfile():
                    continue
                rel = _validate_member_name(member.name)
                if rel is None:
                    skipped.append(member.name)
                    logger.warning("[Archive] 跳过非法 tar 成员: {}", member.name)
                    continue
                target = workspace_dir / rel
                # 双重防护：规范化后必须仍落在 workspace_dir 内
                resolved_parent = target.resolve().parent
                if not str(resolved_parent).startswith(str(workspace_dir.resolve())):
                    skipped.append(member.name)
                    logger.warning("[Archive] 拒绝逃逸 tar 成员: {}", member.name)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                source = tar.extractfile(member)
                if source is None:
                    continue
                with target.open("wb") as out:
                    shutil.copyfileobj(source, out, _HASH_CHUNK_SIZE)
                extracted += 1
                expected_entry = expected.get(member.name)
                if expected_entry is not None:
                    try:
                        actual_size = target.stat().st_size
                    except OSError:
                        actual_size = -1
                    if int(expected_entry.get("size", -1)) != actual_size:
                        mismatched.append(member.name)
                        logger.warning(
                            "[Archive] manifest 大小不匹配（继续恢复）: {} expected={} actual={}",
                            member.name,
                            expected_entry.get("size"),
                            actual_size,
                        )
                    elif _hash_file(target) != str(expected_entry.get("sha256", "")):
                        mismatched.append(member.name)
                        logger.warning(
                            "[Archive] manifest sha256 不匹配（继续恢复，人工核查位腐）: {}",
                            member.name,
                        )
        return {
            "extracted_files": extracted,
            "skipped_members": skipped,
            "sha256_mismatch": mismatched,
        }


def get_archive_storage(config: StudioConfig) -> ArchiveStorageBackend:
    """按 archive.backend 返回存储后端；非 local 本期显式未实现。"""
    backend = (config.archive.backend or "local").strip().lower()
    if backend == "local":
        return LocalArchiveStorage(config)
    raise NotImplementedError(
        f"archive.backend={backend} 本期未实现（仅 local 可用），归档请求被拒绝"
    )
