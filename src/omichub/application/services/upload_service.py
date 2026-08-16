"""分块上传服务 —— 从 FileService 抽出，单独承担断点续传生命周期。

职责：
- 上传会话的创建 / 分片接收 / 合并 / 取消
- 配额前置校验、秒传去重、合并时创建 FileRecord
- 临时分片目录的生命周期管理

合并完成后的「登记文件」逻辑放在本服务内，避免 FileService 承担上传细节。
"""

from __future__ import annotations

import contextlib
import hashlib
import uuid
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.schemas.file import (
    UploadChunkResponse,
    UploadInitRequest,
    UploadInitResponse,
    UploadMergeResponse,
)
from omichub.application.services.file_service import (
    _append_dedupe_suffix,
    _detect_file_type,
)
from omichub.core.exceptions import (
    NotFoundError,
    QuotaExceededError,
    ValidationError,
)
from omichub.domain.file.entities import DataFile, UploadSession
from omichub.infrastructure.database.repositories import (
    FileRepositoryImpl,
    UploadSessionRepositoryImpl,
)
from omichub.infrastructure.database.repositories.user_repository import (
    SqlAlchemyUserRepository,
)
from omichub.infrastructure.storage import get_path_factory, get_storage_backend

# 默认分片大小（客户端未传时兜底）
DEFAULT_CHUNK_SIZE = 5 * 1024 * 1024  # 5 MiB


def _normalize_directory(directory: str | None) -> str:
    if not directory:
        return ""
    d = directory.strip().strip("/")
    parts = [p for p in d.split("/") if p not in ("", ".", "..")]
    return "/".join(parts)


class UploadService:
    """分块上传：init / chunk / merge / cancel。"""

    def __init__(self, session: AsyncSession, backend=None):
        self._session = session
        self._sessions = UploadSessionRepositoryImpl(session)
        self._files = FileRepositoryImpl(session)
        self._users = SqlAlchemyUserRepository(session)
        self._factory = get_path_factory()
        self._backend = backend or get_storage_backend()

    # ------------------------------------------------------------------
    async def _inbox_subdir(self, user_id: UUID, directory: str) -> Path:
        """用户 inbox/ 下的指定子目录（自动创建）。"""
        normalized = _normalize_directory(directory)
        if normalized == "inbox":
            normalized = ""
        elif normalized.startswith("inbox/"):
            normalized = normalized.removeprefix("inbox/")
        base = self._factory.inbox_dir(str(user_id))
        target = base / normalized if normalized else base
        await self._backend.ensure_dir(self._factory.relative_to_root(target))
        return target

    # ------------------------------------------------------------------
    # init / chunk / merge / cancel
    # ------------------------------------------------------------------
    async def init_upload(
        self, user_id: UUID, req: UploadInitRequest
    ) -> UploadInitResponse:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("用户不存在")

        directory = _normalize_directory(req.directory) or "inbox"

        if user.used_storage + req.total_size > user.storage_quota:
            raise QuotaExceededError(
                f"存储空间不足：已用 {user.used_storage}，配额 {user.storage_quota}，"
                f"本次需 {req.total_size}"
            )

        # 秒传：同名同大小且已 completed 的会话 → 视为已传完
        completed = await self._sessions.find_completed(
            user_id, req.file_name, req.total_size
        )
        if completed is not None:
            return UploadInitResponse(
                upload_id=completed.id,
                completed=True,
                file_id=None,
                uploaded_chunks=list(range(completed.total_chunks)),
                chunk_size=completed.chunk_size,
            )

        await self._inbox_subdir(user_id, directory)

        session = UploadSession(
            id=uuid.uuid4(),
            user_id=user_id,
            file_name=req.file_name,
            total_size=req.total_size,
            chunk_size=req.chunk_size,
            total_chunks=req.total_chunks,
            uploaded_chunks=[],
            file_md5=req.file_md5,
            status="pending",
            directory=directory,
        )
        await self._sessions.save(session)
        await self._session.commit()
        return UploadInitResponse(
            upload_id=session.id,
            completed=False,
            uploaded_chunks=[],
            chunk_size=req.chunk_size,
        )

    async def save_chunk(
        self,
        user_id: UUID,
        upload_id: UUID,
        index: int,
        chunk_bytes: bytes,
        md5: str,
    ) -> UploadChunkResponse:
        session = await self._sessions.get_by_id(user_id, upload_id)
        if session is None:
            raise NotFoundError("上传会话不存在")
        if session.status in ("completed", "merging"):
            raise ValidationError("上传会话已结束")
        if index < 0 or index >= session.total_chunks:
            raise ValidationError(f"分片序号越界：{index}")

        actual_md5 = hashlib.md5(chunk_bytes).hexdigest()
        if actual_md5 != md5:
            raise ValidationError(f"分片 {index} 校验失败：MD5 不匹配")

        tmp_base = self._factory.tmp_dir(str(upload_id))
        chunk_path = tmp_base / str(index)
        await self._backend.write(
            self._factory.relative_to_root(chunk_path), chunk_bytes
        )

        session = await self._sessions.add_chunk(user_id, upload_id, {"index": index, "md5": md5})
        if session is None:
            raise NotFoundError("上传会话不存在")
        await self._session.commit()
        return UploadChunkResponse(
            upload_id=upload_id,
            index=index,
            accepted=True,
            uploaded=len(session.uploaded_chunks),
        )

    async def merge_upload(
        self, user_id: UUID, upload_id: UUID
    ) -> UploadMergeResponse:
        session = await self._sessions.get_by_id(user_id, upload_id)
        if session is None:
            raise NotFoundError("上传会话不存在")
        if session.status == "completed":
            raise ValidationError("上传会话已合并完成")
        if len(session.uploaded_chunks) != session.total_chunks:
            raise ValidationError(
                f"分片不齐全：已传 {len(session.uploaded_chunks)}/{session.total_chunks}"
            )

        await self._sessions.update_status(user_id, upload_id, "merging")
        await self._session.commit()

        tmp_dir = self._factory.tmp_dir(str(upload_id))
        directory = _normalize_directory(session.directory)
        inbox_subdir = await self._inbox_subdir(user_id, directory)
        final_path = inbox_subdir / session.file_name
        final_rel = self._factory.relative_to_root(final_path)
        if await self._backend.exists(final_rel):
            final_path = _append_dedupe_suffix(final_path, uuid.uuid4().hex[:8])
            final_rel = self._factory.relative_to_root(final_path)

        hasher = hashlib.md5()
        merged_bytes = bytearray()
        for chunk_meta in sorted(session.uploaded_chunks, key=lambda c: c["index"]):
            chunk_rel = self._factory.relative_to_root(
                tmp_dir / str(chunk_meta["index"])
            )
            if not await self._backend.exists(chunk_rel):
                raise ValidationError(f"分片文件丢失：{chunk_meta['index']}")
            data = await self._backend.read(chunk_rel)
            merged_bytes.extend(data)
            hasher.update(data)

        await self._backend.write(final_rel, bytes(merged_bytes))

        checksum = hasher.hexdigest()
        size = len(merged_bytes)

        file_record = DataFile(
            id=uuid.uuid4(),
            user_id=user_id,
            path=final_rel,
            original_name=session.file_name,
            size=size,
            checksum=checksum,
            file_type=_detect_file_type(session.file_name),
            status="active",
            directory=directory,
        )
        await self._files.save(file_record)

        new_used = await self._users.add_used_storage(user_id, size)

        await self._sessions.update_status(user_id, upload_id, "completed")
        await self._session.commit()

        # 清理分片与本地临时目录
        for chunk_meta in sorted(session.uploaded_chunks, key=lambda c: c["index"]):
            chunk_rel = self._factory.relative_to_root(
                tmp_dir / str(chunk_meta["index"])
            )
            with contextlib.suppress(NotFoundError):
                await self._backend.delete(chunk_rel)
        await self._backend.delete_tree(self._factory.relative_to_root(tmp_dir))
        # 兼容旧版 .tmp 位置
        legacy_tmp = self._factory.data_root / ".tmp" / str(upload_id)
        await self._backend.delete_tree(self._factory.relative_to_root(legacy_tmp))

        return UploadMergeResponse(
            file_id=file_record.id,
            original_name=file_record.original_name,
            size=size,
            checksum=checksum,
            used_storage=new_used,
        )

    async def cancel_upload(self, user_id: UUID, upload_id: UUID) -> bool:
        session = await self._sessions.get_by_id(user_id, upload_id)
        if session is None:
            raise NotFoundError("上传会话不存在")
        await self._sessions.delete(user_id, upload_id)
        await self._session.commit()

        tmp_dir = self._factory.tmp_dir(str(upload_id))
        tmp_dir_rel = self._factory.relative_to_root(tmp_dir)
        try:
            entries = await self._backend.list(tmp_dir_rel, recursive=True)
            for entry in entries:
                if entry["type"] == "file":
                    with contextlib.suppress(NotFoundError):
                        await self._backend.delete(entry["path"])
        except NotFoundError:
            pass
        await self._backend.delete_tree(tmp_dir_rel)
        legacy_tmp = self._factory.data_root / ".tmp" / str(upload_id)
        await self._backend.delete_tree(self._factory.relative_to_root(legacy_tmp))
        return True
