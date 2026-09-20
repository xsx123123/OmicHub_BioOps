"""cloud 模式临时 POSIX scratch 卷管理。

阶段 4.1 目标：在 cloud 模式下，Studio / Terminal 等需要 POSIX 的沙盒不再直接
bind-mount 用户工作区，而是：

1. 按输入 file_id 清单从对象存储物化到临时 scratch 卷；
2. 容器挂载 scratch 卷内的 ``workspace`` / ``platform`` 目录；
3. 执行结束后扫描 ``workspace/output/``，回传到对象存储并注册到 ``file_records``；
4. 回收 scratch 卷。

本模块封装上述流程，业务代码只与 ``ScratchVolumeManager`` 交互，避免在
Studio/Terminal 中散落对象存储与本地 POSIX 的转换逻辑。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.domain.file.value_objects import FileSource
from cygnusx.infrastructure.config.storage_config import get_user_chat_upload_dir
from cygnusx.infrastructure.database.models.file import FileRecordModel
from cygnusx.infrastructure.storage import get_path_factory, get_storage_backend
from cygnusx.infrastructure.storage.backend import StorageBackend
from cygnusx.infrastructure.storage.file_registry import FileRegistry
from cygnusx.infrastructure.storage.path_factory import StoragePathFactory

_UPLOAD_ID_RE = re.compile(r"^[a-fA-F0-9]{16,128}$")
_SANDBOX_UID = 10001
_SANDBOX_GID = 10001


class PathEscapeError(ValueError):
    """路径逃逸平台数据区"""


def _platform_user_rel(storage_rel: str, user_id: str) -> str:
    """把 ``users/{uid}/...`` 折算为平台挂载内相对路径（与 studio.paths 同源规则）。"""
    rel = Path(storage_rel)
    if rel.is_absolute() or ".." in rel.parts:
        raise PathEscapeError(f"非法平台存储路径: {storage_rel}")
    prefix = Path("users") / user_id
    parts = rel.parts
    if len(parts) <= len(prefix.parts) or parts[: len(prefix.parts)] != prefix.parts:
        raise PathEscapeError(f"平台路径不属于当前用户: {storage_rel}")
    return Path(*parts[len(prefix.parts) :]).as_posix()


@dataclass
class ScratchVolume:
    """一次会话的 scratch 卷路径集合。"""

    root: Path
    workspace: Path
    platform: Path
    input: Path
    output: Path


class ScratchVolumeManager:
    """cloud 模式沙盒临时卷：物化输入、回收输出、清理卷。"""

    def __init__(
        self,
        session_id: str,
        user_id: str | UUID,
        db_session: AsyncSession,
        *,
        path_factory: StoragePathFactory | None = None,
        backend: StorageBackend | None = None,
        file_registry: FileRegistry | None = None,
    ):
        self.session_id = session_id
        self.user_id = UUID(str(user_id))
        self._session = db_session
        self._pf = path_factory or get_path_factory()
        self._backend = backend or get_storage_backend()
        self._registry = file_registry or FileRegistry(
            db_session, self._pf, self._backend
        )

        # scratch 卷统一放在 system/scratch/{session_id}/，便于统一清理与审计
        self._root = self._pf.data_root / "system" / "scratch" / session_id
        if not self._pf.is_within_root(self._root):
            raise ValueError(f"非法 scratch 路径: {self._root}")

        self.volume = ScratchVolume(
            root=self._root,
            workspace=self._root / "workspace",
            platform=self._root / "platform",
            input=self._root / "workspace" / "input",
            output=self._root / "workspace" / "output",
        )

    async def allocate(self) -> ScratchVolume:
        """创建 scratch 卷目录结构并返回路径集合。"""
        for sub in (
            self.volume.workspace,
            self.volume.input,
            self.volume.platform,
            self.volume.output,
            self.volume.workspace / "scripts",
            self.volume.workspace / "ref",
            self.volume.workspace / ".logs",
        ):
            sub.mkdir(parents=True, exist_ok=True)
        mount_dirs = (
            self.volume.workspace,
            self.volume.platform,
            self.volume.input,
            self.volume.output,
            self.volume.workspace / "scripts",
            self.volume.workspace / "ref",
            self.volume.workspace / ".logs",
        )
        try:
            # 容器内统一以 uid/gid 10001 运行；嵌套目录也必须同步授权。
            for path in mount_dirs:
                os.chown(path, _SANDBOX_UID, _SANDBOX_GID)
                path.chmod(0o770)
        except (PermissionError, OSError):
            for path in mount_dirs:
                with contextlib.suppress(OSError):
                    path.chmod(0o777)
        logger.info(
            "[ScratchVolume] 已分配 scratch: session=%s path=%s",
            self.session_id[:8],
            self._root,
        )
        return self.volume

    async def materialize_inputs(self, refs: list[str]) -> list[str]:
        """把 file_id / upload_id 清单对应的对象存储文件物化到 scratch/platform。

        返回容器内可读路径列表（如 ``/workspace/input/<name>``）。
        """
        resolved: list[str] = []
        seen: set[str] = set()
        for raw_ref in refs:
            ref = str(raw_ref or "").strip()
            if not ref or ref in seen:
                continue
            seen.add(ref)
            try:
                sandbox_path = await self._materialize_single(ref)
                if sandbox_path:
                    resolved.append(sandbox_path)
            except Exception as exc:  # noqa: BLE001 - 单个文件失败不阻断其余
                logger.warning(
                    "[ScratchVolume] 物化输入失败 ref=%s: %s", ref, exc
                )
        return resolved

    async def _materialize_single(self, ref: str) -> str | None:
        """解析单个引用并物化；返回沙盒内可读路径。"""
        if ref.startswith("upload://"):
            storage_rel, original_name = await self._resolve_upload_ref(ref)
        elif ref.startswith("file://"):
            storage_rel, original_name = await self._resolve_file_ref(ref)
        else:
            # 兼容裸 UUID，也按 file:// 处理
            try:
                uuid.UUID(ref)
                storage_rel, original_name = await self._resolve_file_ref(
                    f"file://{ref}"
                )
            except ValueError:
                logger.warning("[ScratchVolume] 不支持的引用格式: %s", ref)
                return None

        if not storage_rel:
            return None

        # 从对象存储读取完整内容（大文件也适用，S3 后端会流式返回）
        content = await self._backend.read(storage_rel)

        # 在 scratch/platform 下镜像持久层相对路径
        platform_local = self.volume.platform / storage_rel
        platform_local.parent.mkdir(parents=True, exist_ok=True)
        platform_local.write_bytes(content)

        # 在 workspace/input/ 下创建指向 /data/platform/<用户相对路径> 的软链
        try:
            mount_rel = _platform_user_rel(storage_rel, str(self.user_id))
        except PathEscapeError as exc:
            logger.warning("[ScratchVolume] 路径越权 %s: %s", storage_rel, exc)
            return None

        link_name = Path(original_name).name
        link_path = self._unique_link(self.volume.input, link_name)
        link_path.symlink_to(f"/data/platform/{mount_rel}")
        return f"/workspace/input/{link_path.name}"

    async def _resolve_upload_ref(self, ref: str) -> tuple[str, str]:
        upload_id = ref.removeprefix("upload://").strip()
        if not _UPLOAD_ID_RE.fullmatch(upload_id):
            raise ValueError(f"非法 upload_id: {upload_id}")
        upload_dir = get_user_chat_upload_dir(str(self.user_id))
        upload_rel_dir = self._pf.relative_to_root(upload_dir)
        entries = await self._backend.list(upload_rel_dir, recursive=False)
        candidates = [
            e for e in entries if e["type"] == "file" and e["name"].startswith(upload_id)
        ]
        if not candidates:
            raise FileNotFoundError(f"聊天上传文件不存在: {upload_id}")
        chosen = sorted(
            candidates, key=lambda e: (len(Path(e["name"]).suffix), e["name"])
        )[0]
        storage_rel = f"{upload_rel_dir}/{chosen['name']}".strip("/")
        return storage_rel, chosen["name"]

    async def _resolve_file_ref(self, ref: str) -> tuple[str, str]:
        file_id = ref.removeprefix("file://").strip()
        try:
            file_uuid = uuid.UUID(file_id)
        except ValueError as exc:
            raise ValueError(f"非法 file_id: {file_id}") from exc

        result = await self._session.execute(
            select(FileRecordModel).where(
                FileRecordModel.id == file_uuid,
                FileRecordModel.user_id == self.user_id,
                FileRecordModel.status == "active",
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise FileNotFoundError(f"文件不存在或无权访问: {file_id}")
        return record.storage_path, record.original_name

    @staticmethod
    def _unique_link(directory: Path, name: str) -> Path:
        candidate = directory / name
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
        stem, suffix = os.path.splitext(name)
        n = 1
        while True:
            candidate = directory / f"{stem} ({n}){suffix}"
            if not candidate.exists() and not candidate.is_symlink():
                return candidate
            n += 1

    async def materialize_workspace_inputs(self, persistent_workspace: Path) -> None:
        """把持久工作区 ``input/`` 下已存在的平台软链对应文件物化到 scratch。

        用于 cloud 模式启动沙盒前：宿主编排的软链保留在持久工作区，执行前按软链目标
        把真实数据从对象存储拉到 scratch/platform，并在 scratch/input 重建软链。
        """
        persistent_input = persistent_workspace / "input"
        if not persistent_input.is_dir():
            return
        for entry in persistent_input.iterdir():
            if not entry.is_symlink():
                continue
            target = os.readlink(entry)
            prefix = "/data/platform/"
            if not target.startswith(prefix):
                continue
            mount_rel = target[len(prefix) :].strip("/")
            storage_rel = f"users/{self.user_id}/{mount_rel}"
            await self._materialize_by_storage_rel(storage_rel, entry.name)

    async def _materialize_by_storage_rel(self, storage_rel: str, link_name: str) -> None:
        """按 storage_rel 查询记录并物化；在 scratch/input 下创建软链。"""
        result = await self._session.execute(
            select(FileRecordModel).where(
                FileRecordModel.user_id == self.user_id,
                FileRecordModel.storage_path == storage_rel,
                FileRecordModel.status == "active",
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            logger.warning("[ScratchVolume] 未找到记录: %s", storage_rel)
            return

        content = await self._backend.read(storage_rel)
        platform_local = self.volume.platform / storage_rel
        platform_local.parent.mkdir(parents=True, exist_ok=True)
        platform_local.write_bytes(content)

        try:
            mount_rel = _platform_user_rel(storage_rel, str(self.user_id))
        except PathEscapeError as exc:
            logger.warning("[ScratchVolume] 路径越权 %s: %s", storage_rel, exc)
            return

        link_path = self._unique_link(self.volume.input, link_name)
        link_path.symlink_to(f"/data/platform/{mount_rel}")

    async def register_outputs(
        self,
        *,
        source: FileSource = FileSource.STUDIO,
        task_id: UUID | None = None,
    ) -> list[FileRecordModel]:
        """扫描 ``workspace/output/``，把产物回传对象存储并注册到 ``file_records``。"""
        output_dir = self.volume.output
        if not output_dir.is_dir():
            return []

        records: list[FileRecordModel] = []
        session_short = self.session_id[:8]
        base_dest = (
            self._pf.user_root(str(self.user_id))
            / "workspace"
            / "studio-output"
            / session_short
        )

        for root, _dirs, files in os.walk(output_dir):
            for file_name in files:
                local_path = Path(root) / file_name
                rel = local_path.relative_to(output_dir).as_posix()
                dest_path = base_dest / rel
                dest_rel = self._pf.relative_to_root(dest_path)

                content = local_path.read_bytes()
                await self._backend.write(dest_rel, content)

                directory = dest_path.parent.relative_to(
                    self._pf.user_root(str(self.user_id))
                ).as_posix()
                record = await self._registry.register(
                    self.user_id,
                    dest_path,
                    source=source,
                    task_id=task_id,
                    directory=directory,
                )
                records.append(record)

        if records:
            await self._session.commit()
            logger.info(
                "[ScratchVolume] 已注册 %d 个产物: session=%s",
                len(records),
                self.session_id[:8],
            )
        return records

    async def cleanup(self) -> None:
        """删除 scratch 卷，释放本地磁盘。"""
        if self._root.exists():
            await asyncio.to_thread(shutil.rmtree, self._root, ignore_errors=True)
            logger.info(
                "[ScratchVolume] 已回收 scratch: session=%s",
                self.session_id[:8],
            )

    def volumes_for_container(self) -> dict[str, dict[str, str]]:
        """返回 Docker 容器挂载参数：workspace -> /workspace, platform -> /data/platform。"""
        return {
            str(self.volume.workspace): {"bind": "/workspace", "mode": "rw"},
            str(self.volume.platform): {"bind": "/data/platform", "mode": "ro"},
        }
