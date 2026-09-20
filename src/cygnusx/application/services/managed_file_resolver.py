"""受控文件解析器。

解析 upload:// / file:// / directory:// / sample_sheet_ref:// 引用，
校验用户归属、拒绝危险路径，对大文件仅返回元数据。
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from cygnusx.application.schemas.tool_invocation import ToolInvocationContext
from cygnusx.domain.file.repositories import IFileRepository
from cygnusx.infrastructure.config.storage_config import get_user_chat_upload_dir
from cygnusx.infrastructure.database.repositories.file_repository import (
    FileRepositoryImpl,
)


class FileResolutionError(Exception):
    """文件解析失败"""

    def __init__(self, message: str, code: str = "FILE_RESOLUTION_ERROR"):
        super().__init__(message)
        self.code = code
        self.message = message


class FileMetadata(BaseModel):
    """解析后的文件元数据。"""

    ref: str
    resolved_type: Literal["upload", "file", "sample_sheet_ref", "directory"]
    file_id: str
    file_name: str
    file_size: int
    mime_type: str | None = None
    internal_path: str
    content: str | None = None
    metadata: dict[str, Any] = {}
    is_valid_for_analysis: bool = True
    validation_message: str | None = None


class ManagedFileResolver:
    """受控文件引用解析器。"""

    FORBIDDEN_PATTERNS = [
        re.compile(r"\.\."),  # 父目录引用
        re.compile(r"^/"),  # 绝对路径
        re.compile(r"^file://[^/]"),  # 非受控 file:// 格式
        re.compile(r"^/proc"),
        re.compile(r"^/sys"),
        re.compile(r"^/dev"),
    ]

    MAX_UPLOAD_CONTENT_SIZE = 5 * 1024 * 1024  # 5MB

    def __init__(self, file_repo: IFileRepository | None = None):
        self._file_repo = file_repo

    async def resolve(
        self,
        context: ToolInvocationContext,
        ref: str,
        require_content: bool = False,
    ) -> FileMetadata:
        """解析文件引用。

        Args:
            context: 工具调用上下文，含 user_id / db。
            ref: 文件引用字符串，如 upload://abc, file://uuid, directory://path。
            require_content: 是否必须读取内容（仅对 upload:// 小文本生效）。
        """
        self._validate_ref_format(ref)

        if ref.startswith("upload://"):
            return await self._resolve_upload(context, ref, require_content)
        if ref.startswith("file://"):
            return await self._resolve_file(context, ref)
        if ref.startswith("directory://"):
            return await self._resolve_directory(context, ref)
        if ref.startswith("sample_sheet_ref://"):
            return await self._resolve_sample_sheet_ref(context, ref, require_content)

        raise FileResolutionError(f"不支持的文件引用格式: {ref}", "UNSUPPORTED_REF")

    def _validate_ref_format(self, ref: str) -> None:
        """拒绝包含危险模式的引用。"""
        for pattern in self.FORBIDDEN_PATTERNS:
            if pattern.search(ref):
                raise FileResolutionError(f"文件引用包含非法模式: {ref}", "FORBIDDEN_PATTERN")

    async def _resolve_upload(
        self, context: ToolInvocationContext, ref: str, require_content: bool
    ) -> FileMetadata:
        """解析聊天上传文件引用。"""
        file_id = ref[len("upload://") :].strip()
        if not file_id:
            raise FileResolutionError("upload:// 引用缺少 file_id", "MISSING_FILE_ID")

        upload_dir = get_user_chat_upload_dir(context.user_id)
        candidates = list(upload_dir.glob(f"{file_id}*"))
        if not candidates:
            raise FileResolutionError(f"上传文件不存在: {file_id}", "FILE_NOT_FOUND")

        candidates.sort(key=lambda p: (len(p.suffix), p.name))
        target = candidates[0]

        try:
            target.resolve().relative_to(upload_dir.resolve())
        except ValueError as e:
            raise FileResolutionError(f"上传文件路径越权: {file_id}", "PATH_TRAVERSAL") from e

        content: str | None = None
        if require_content:
            size = target.stat().st_size
            if size > self.MAX_UPLOAD_CONTENT_SIZE:
                raise FileResolutionError(
                    f"上传文件 {file_id} 超过 {self.MAX_UPLOAD_CONTENT_SIZE} 字节",
                    "FILE_TOO_LARGE",
                )
            try:
                content = await asyncio.to_thread(target.read_text, encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                raise FileResolutionError(f"读取上传文件失败: {e}", "READ_ERROR") from e

        return FileMetadata(
            ref=ref,
            resolved_type="upload",
            file_id=file_id,
            file_name=target.name,
            file_size=target.stat().st_size,
            internal_path=str(target),
            content=content,
        )

    async def _resolve_file(
        self, context: ToolInvocationContext, ref: str
    ) -> FileMetadata:
        """解析文件中心归档文件引用。"""
        file_id = ref[len("file://") :].strip()
        try:
            file_uuid = UUID(file_id)
        except ValueError as e:
            raise FileResolutionError(f"file:// 引用不是有效 UUID: {file_id}", "INVALID_UUID") from e

        repo = self._file_repo or FileRepositoryImpl(context.db)
        data_file = await repo.get_by_id(UUID(context.user_id), file_uuid)
        if data_file is None:
            raise FileResolutionError(f"文件不存在或无权限: {file_id}", "FILE_NOT_FOUND")

        return FileMetadata(
            ref=ref,
            resolved_type="file",
            file_id=file_id,
            file_name=data_file.original_name,
            file_size=data_file.size,
            mime_type=data_file.file_type.value if data_file.file_type else None,
            internal_path=data_file.path,
            content=None,
        )

    async def _resolve_directory(
        self, context: ToolInvocationContext, ref: str
    ) -> FileMetadata:
        """解析受控目录引用（目前仅校验路径安全并返回元数据）。"""
        dir_path = ref[len("directory://") :].strip()
        if not dir_path:
            raise FileResolutionError("directory:// 引用缺少路径", "MISSING_PATH")

        if ".." in dir_path or Path(dir_path).is_absolute():
            raise FileResolutionError(f"目录路径非法: {dir_path}", "FORBIDDEN_PATTERN")

        return FileMetadata(
            ref=ref,
            resolved_type="directory",
            file_id=dir_path,
            file_name=Path(dir_path).name,
            file_size=0,
            internal_path=dir_path,
            content=None,
        )

    async def _resolve_sample_sheet_ref(
        self, context: ToolInvocationContext, ref: str, require_content: bool
    ) -> FileMetadata:
        """解析预保存样本表引用（目前委托为 upload:// 或 file://）。"""
        inner_ref = ref[len("sample_sheet_ref://") :].strip()
        if not inner_ref:
            raise FileResolutionError("sample_sheet_ref:// 引用为空", "MISSING_REF")

        # 第一阶段：支持 upload:// 或 file:// 前缀的引用
        if inner_ref.startswith("upload://") or inner_ref.startswith("file://"):
            return await self.resolve(context, inner_ref, require_content=True)

        raise FileResolutionError(
            f"sample_sheet_ref:// 目前仅支持嵌套 upload:// 或 file:// 引用: {ref}",
            "UNSUPPORTED_REF",
        )
