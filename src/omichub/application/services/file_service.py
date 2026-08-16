"""文件应用服务 — DB 文件记录 + 分块上传 + 配额控制

落盘规范（统一由 StoragePathFactory 生成）：
  原始上传：{data_root}/users/{user_id}/inbox/{filename}
  分析输出：{data_root}/users/{user_id}/projects/{project}/runs/{analysis-time}/output/...
  下载产物：{data_root}/users/{user_id}/downloads/{filename}
  分片临时：{data_root}/system/.tmp/{upload_id}/{index}
"""

from __future__ import annotations

import fnmatch
import re
import uuid
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.schemas.file import (
    DataFileDTO,
    DirectoryCreateRequest,
    DirectoryDTO,
    DirectorySearchDTO,
    FileListResponse,
    FilePickerItemDTO,
    QuotaResponse,
    SampleCreateRequest,
    SampleDTO,
    SampleListResponse,
    SyncResponse,
    UploadChunkResponse,
    UploadInitRequest,
    UploadInitResponse,
    UploadMergeResponse,
)
from omichub.core.exceptions import (
    AuthorizationError,
    NotFoundError,
    ValidationError,
)
from omichub.domain.file.entities import DataFile, Directory, Sample
from omichub.domain.file.value_objects import FileSource, FileType, OwnerScope
from omichub.domain.team.value_objects import TeamRole
from omichub.infrastructure.database.repositories import (
    DirectoryRepositoryImpl,
    FileRepositoryImpl,
    SampleRepositoryImpl,
)
from omichub.infrastructure.database.repositories.user_repository import (
    SqlAlchemyUserRepository,
)
from omichub.infrastructure.storage import get_storage_backend
from omichub.infrastructure.storage.backend import StorageBackend
from omichub.infrastructure.storage.path_factory import get_path_factory

# 默认分片大小（客户端未传时兜底）
DEFAULT_CHUNK_SIZE = 5 * 1024 * 1024  # 5 MiB

# sync_user_files 跳过的系统内部目录（这些目录下的文件由各自服务登记，
# 不应作为普通 file_records 出现在"数据管理"视图里，否则会污染目录树）。
# 匹配规则：相对用户根的第一段目录名命中即跳过。
_SYNC_SKIP_USER_TOP_DIRS: frozenset[str] = frozenset(
    {
        "tasks",        # 任务产物（各工具/流程自行登记）
        "projects",     # 项目运行结果（由 pipeline/studio 服务登记）
        "temp",         # 临时文件
        "results",      # 旧版任务结果（legacy）
        "raw",          # 旧版上传目录（legacy，迁移后应清空）
    }
)
# workspace/ 下需要跳过的子目录（workspace/ 根允许登记，但 chat-uploads/ 由聊天服务登记）
_SYNC_SKIP_WORKSPACE_SUBDIRS: frozenset[str] = frozenset(
    {
        "chat-uploads",
        "sandbox",
    }
)

# 系统默认目录：用户首次访问时懒初始化，锁定不可删除/重命名
SYSTEM_DIRECTORIES: tuple[str, ...] = (
    "inbox",
    "projects",
    "raw_data",
    "workspace",
    "downloads",
    "temp",
)

_DEDUPE_SUFFIX_RE = re.compile(r"^(?P<stem>.+)_[0-9a-f]{8}$", re.IGNORECASE)
_LEGACY_GZIP_DEDUPE_RE = re.compile(
    r"^(?P<stem>.+\.(?:fastq|fq|vcf|gff|gtf|fa|fasta|fna))_[0-9a-f]{8}(?P<suffix>\.gz)$",
    re.IGNORECASE,
)
_COMPOUND_GZIP_SUFFIX_PARENTS = {
    ".fastq",
    ".fq",
    ".vcf",
    ".gff",
    ".gtf",
    ".fa",
    ".fasta",
    ".fna",
    ".tar",
}


def _detect_file_type(filename: str) -> FileType:
    """根据扩展名猜测文件类型"""
    name_lower = filename.lower()
    if name_lower.endswith((".fastq", ".fastq.gz", ".fq", ".fq.gz")):
        return FileType.FASTQ
    if name_lower.endswith(".bam") or name_lower.endswith(".cram"):
        return FileType.BAM
    if name_lower.endswith(".vcf") or name_lower.endswith(".vcf.gz"):
        return FileType.VCF
    if name_lower.endswith((".csv", ".tsv", ".txt")) and "count" in name_lower:
        return FileType.COUNT_MATRIX
    if name_lower.endswith(".h5ad"):
        return FileType.H5AD
    if name_lower.endswith(".rds") or name_lower.endswith(".rdata"):
        return FileType.RDS
    if name_lower.endswith((".meta", "_metadata.csv", "_metadata.tsv", "_meta.txt")):
        return FileType.META
    if name_lower.endswith((".pdf", ".html", ".md", ".docx")):
        return FileType.REPORT
    if name_lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg")):
        return FileType.IMAGE
    return FileType.OTHER


def _split_display_suffix(filename: str) -> tuple[str, str]:
    """拆分文件名 stem/suffix，保留常见双后缀如 .fastq.gz。"""
    suffixes = Path(filename).suffixes
    if (
        len(suffixes) >= 2
        and suffixes[-1].lower() == ".gz"
        and suffixes[-2].lower() in _COMPOUND_GZIP_SUFFIX_PARENTS
    ):
        suffix = "".join(suffixes[-2:])
    elif suffixes:
        suffix = suffixes[-1]
    else:
        suffix = ""

    stem = filename[: -len(suffix)] if suffix else filename
    return stem, suffix


def _append_dedupe_suffix(path: Path, token: str) -> Path:
    """生成去重后的物理文件名，同时尽量保留复合扩展名。"""
    stem, suffix = _split_display_suffix(path.name)
    return path.with_name(f"{stem}_{token}{suffix}")


def canonical_original_name(filename: str) -> str:
    """把系统生成的短 UUID 去重后缀从展示名里剥掉。

    只处理本服务生成的 8 位十六进制后缀，避免误伤常见测序 lane 编号
    （如 _001）或用户自带数字。
    """
    name = Path(filename).name

    legacy_match = _LEGACY_GZIP_DEDUPE_RE.match(name)
    if legacy_match:
        return f"{legacy_match.group('stem')}{legacy_match.group('suffix')}"

    stem, suffix = _split_display_suffix(name)
    match = _DEDUPE_SUFFIX_RE.match(stem)
    if match:
        return f"{match.group('stem')}{suffix}"
    return name


async def ensure_directory_chain(session: AsyncSession, user_id: UUID, path: str) -> None:
    """确保 path 及其各级父目录在 user_directories 中存在（幂等）。

    path 形如 ``raw_data/PRJNA1259417``。逐段创建缺失的 Directory 记录；系统默认目录段
    （inbox/projects/raw_data/workspace/temp）标记 is_system=True，其余为用户数据目录。
    供文件同步与下载产物登记共用。
    """
    repo = DirectoryRepositoryImpl(session)
    parts = [p for p in path.split("/") if p and p not in ("", ".", "..")]
    parent: str | None = None
    cumulative: list[str] = []
    for p in parts:
        cumulative.append(p)
        cur_path = "/".join(cumulative)
        if await repo.get_by_path(user_id, cur_path) is not None:
            parent = cur_path
            continue
        await repo.save(
            Directory(
                id=uuid.uuid4(),
                user_id=user_id,
                path=cur_path,
                name=p,
                parent_path=parent,
                # 仅顶层系统默认目录标 is_system；同名嵌套子目录（如 downloads/raw_data）不算
                is_system=(p in SYSTEM_DIRECTORIES and parent is None),
            )
        )
        parent = cur_path


class FileService:
    """文件应用服务 — 配额校验、分块上传、断点续传、生命周期路径"""

    def __init__(
        self,
        session: AsyncSession,
        backend: StorageBackend | None = None,
    ):
        self._session = session
        self._files = FileRepositoryImpl(session)
        self._samples = SampleRepositoryImpl(session)
        self._dirs = DirectoryRepositoryImpl(session)
        self._users = SqlAlchemyUserRepository(session)
        # 统一路径工厂：所有磁盘路径由此生成，禁止在本类中再硬编码拼接
        self._factory = get_path_factory()
        # 向后兼容：等价于 path_factory.data_root；允许外部/monkeypatch 覆盖
        self._storage_root = self._factory.data_root
        # 可插拔存储后端；local 模式行为与改造前一致
        self._backend = backend or get_storage_backend()

    # ------------------------------------------------------------------
    # 权限判定（阶段 3.2：个人/团队空间统一收口）
    # ------------------------------------------------------------------
    async def _team_role(self, team_id: UUID | None, user_id: UUID) -> TeamRole | None:
        """查询用户在指定团队中的角色；非团队文件返回 None。"""
        if team_id is None:
            return None
        return await self._files.get_team_role(team_id, user_id)

    def _is_personal_owner(self, file: DataFile, user_id: UUID) -> bool:
        return file.owner_scope == OwnerScope.PERSONAL.value and file.user_id == user_id

    async def _require_read_access(self, file: DataFile, actor_user_id: UUID) -> None:
        """读权限：个人 owner，或团队成员（任意角色）均可读。"""
        if self._is_personal_owner(file, actor_user_id):
            return
        if file.owner_scope == OwnerScope.TEAM.value:
            role = await self._team_role(file.team_id, actor_user_id)
            if role is not None:
                return
        raise AuthorizationError("无权访问该文件")

    async def _require_write_access(self, file: DataFile, actor_user_id: UUID) -> None:
        """写权限：个人 owner，或团队 writer/owner。"""
        if self._is_personal_owner(file, actor_user_id):
            return
        if file.owner_scope == OwnerScope.TEAM.value:
            role = await self._team_role(file.team_id, actor_user_id)
            if role in (TeamRole.WRITER, TeamRole.OWNER):
                return
        raise AuthorizationError("无权修改该文件")

    async def _require_delete_access(self, file: DataFile, actor_user_id: UUID) -> None:
        """删除权限：个人 owner；团队 owner 可删除任意文件，writer 仅可删除自己上传的文件。"""
        if self._is_personal_owner(file, actor_user_id):
            return
        if file.owner_scope == OwnerScope.TEAM.value:
            role = await self._team_role(file.team_id, actor_user_id)
            if role == TeamRole.OWNER:
                return
            if role == TeamRole.WRITER and file.user_id == actor_user_id:
                return
        raise AuthorizationError("无权删除该文件")

    # ------------------------------------------------------------------
    # 路径工具（统一委托给 StoragePathFactory）
    # ------------------------------------------------------------------
    def user_root(self, user_id: UUID) -> Path:
        """用户存储根目录：``{data_root}/users/{user_id}/``。"""
        return self._factory.user_root(str(user_id))

    @staticmethod
    def validate_workspace_path(path: str | None) -> str:
        """校验并规范工作区相对路径，显式拒绝绝对路径与 ``..``。"""
        raw = (path or "").strip().replace("\\", "/")
        if not raw or raw == ".":
            return ""
        if raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
            raise PermissionError("路径越权：仅允许当前用户工作区内的相对路径")
        parts = raw.split("/")
        if ".." in parts:
            raise PermissionError("路径越权：禁止使用 .. 访问工作区外目录")
        return "/".join(part for part in parts if part not in ("", "."))

    @staticmethod
    def _workspace_relative_path(storage_path: str, user_id: UUID) -> str:
        prefix = Path("users") / str(user_id)
        path = Path(storage_path)
        try:
            return path.relative_to(prefix).as_posix()
        except ValueError:
            return path.name

    def _resolve_abs(self, storage_path: str) -> Path:
        """storage_path 为相对 data_root 的路径；拼成绝对路径并做路径遍历校验。

        拒绝绝对路径输入，解析后必须仍位于 data_root 内，否则视为越权。
        """
        if not storage_path:
            raise NotFoundError("文件路径不能为空")
        if Path(storage_path).is_absolute():
            raise AuthorizationError("非法文件路径：禁止绝对路径")
        abs_path = (self._factory.data_root / storage_path).resolve()
        if not self._factory.is_within_root(abs_path):
            raise AuthorizationError("非法文件路径：路径越权")
        return abs_path

    def _normalize_directory(self, directory: str | None) -> str:
        """规整目录路径：去首尾斜杠；显式拒绝 .. 路径穿越。"""
        if not directory:
            return ""
        d = directory.strip().strip("/")
        if ".." in d.split("/"):
            raise ValidationError("目录路径禁止包含 ..")
        parts = [p for p in d.split("/") if p and p != "."]
        return "/".join(parts)

    async def _inbox_subdir(self, user_id: UUID, directory: str) -> Path:
        """用户 inbox/ 下的指定子目录（自动创建）。

        ``directory`` 是相对 inbox 的路径；空串表示 inbox 根。兼容历史调用方
        传入 ``"inbox"`` 或 ``"inbox/xxx"`` 前缀的情况。
        """
        normalized_directory = self._normalize_directory(directory)
        if normalized_directory == "inbox":
            normalized_directory = ""
        elif normalized_directory.startswith("inbox/"):
            normalized_directory = normalized_directory.removeprefix("inbox/")
        base = self._factory.inbox_dir(str(user_id))
        target = base / normalized_directory if normalized_directory else base
        await self._backend.ensure_dir(self._factory.relative_to_root(target))
        return target

    # 向后兼容：外部若还有 ``_raw_subdir`` / ``user_raw_dir`` 调用，转发到新方法
    async def _raw_subdir(self, user_id: UUID, directory: str) -> Path:
        return await self._inbox_subdir(user_id, directory)

    async def user_raw_dir(self, user_id: UUID) -> Path:
        """用户上传入口 inbox/（历史方法名保留，仅做转发）。"""
        d = self._factory.inbox_dir(str(user_id))
        await self._backend.ensure_dir(self._factory.relative_to_root(d))
        return d

    # ------------------------------------------------------------------
    # 列表 / 配额
    # ------------------------------------------------------------------
    async def list_files(
        self, user_id: UUID, directory: str | None = None, source: str | None = None
    ) -> FileListResponse:
        items = await self._files.list_visible(user_id, status="active", directory=directory)
        if source:
            items = [f for f in items if getattr(f, "source", None) == source]
        dtos = [
            DataFileDTO(
                id=f.id,
                original_name=f.original_name,
                size=f.size,
                file_type=f.file_type,
                status=f.status,
                checksum=f.checksum,
                directory=f.directory,
                path=self._workspace_relative_path(f.path, user_id),
                source=f.source or "upload",
                owner_scope=f.owner_scope or "personal",
                team_id=f.team_id,
                created_at=f.created_at,
                modified_at=f.updated_at,
            )
            for f in items
        ]
        return FileListResponse(items=dtos, total=len(dtos))

    async def get_file_tree(self, user_id: UUID) -> dict:
        """聚合视图：按来源分组返回用户个人 + 团队空间所有活跃文件。"""
        items = await self._files.list_visible(user_id, status="active")
        tree: dict[str, list] = {}
        for f in items:
            src = getattr(f, "source", None) or "upload"
            tree.setdefault(src, []).append(
                {
                    "id": str(f.id),
                    "name": f.original_name,
                    "size": f.size,
                    "file_type": f.file_type.value if hasattr(f.file_type, "value") else str(f.file_type),
                    "directory": f.directory,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                }
            )
        return {"user_id": str(user_id), "groups": tree, "total": len(items)}

    async def list_workspace_files(
        self,
        user_id: UUID,
        path: str | None = None,
        pattern: str | None = None,
        recursive: bool = False,
    ) -> dict[str, object]:
        """列出工作区目录的子项，支持按需递归返回所有文件。"""
        directory = self.validate_workspace_path(path)
        normalized_pattern = (pattern or "").strip()
        prefix_parts = tuple(Path(directory).parts) if directory else ()
        indexed_files = await self._files.list_by_user(user_id, status="active")
        indexed_directories = await self._dirs.list_by_user(user_id)

        folders: dict[str, dict[str, object]] = {}
        files: list[dict[str, object]] = []
        for file in indexed_files:
            relative_path = self._workspace_relative_path(file.path, user_id)
            relative_parts = tuple(Path(relative_path).parts)
            if relative_parts[: len(prefix_parts)] != prefix_parts:
                continue
            remainder = relative_parts[len(prefix_parts) :]
            if not remainder:
                continue
            if len(remainder) > 1 and not recursive:
                folder_name = remainder[0]
                folder_path = "/".join((*prefix_parts, folder_name))
                existing = folders.get(folder_path)
                if existing is None or str(existing["modified_at"]) < file.updated_at.isoformat():
                    folders[folder_path] = {
                        "file_id": None,
                        "name": folder_name,
                        "type": "folder",
                        "size": None,
                        "relative_path": folder_path,
                        "modified_at": file.updated_at.isoformat(),
                    }
                continue
            files.append(
                {
                    "file_id": str(file.id),
                    "name": file.original_name,
                    "type": "file",
                    "file_type": file.file_type.value
                    if hasattr(file.file_type, "value")
                    else str(file.file_type),
                    "size": file.size,
                    "relative_path": relative_path,
                    "modified_at": file.updated_at.isoformat(),
                }
            )

        for child in indexed_directories:
            if recursive:
                continue
            child_parts = tuple(Path(child.path).parts)
            if child_parts[: len(prefix_parts)] != prefix_parts:
                continue
            remainder = child_parts[len(prefix_parts) :]
            if len(remainder) != 1:
                continue
            folders.setdefault(
                child.path,
                {
                    "file_id": None,
                    "name": child.name,
                    "type": "folder",
                    "size": None,
                    "relative_path": child.path,
                    "modified_at": child.updated_at.isoformat(),
                },
            )

        items = [*folders.values(), *files]
        if normalized_pattern:
            items = [
                item
                for item in items
                if fnmatch.fnmatchcase(str(item["name"]).casefold(), normalized_pattern.casefold())
            ]

        items.sort(key=lambda item: (item["type"] != "folder", str(item["name"]).casefold()))
        return {
            "path": directory,
            "pattern": normalized_pattern or None,
            "recursive": recursive,
            "items": items,
            "total": len(items),
        }

    async def search_files(
        self, user_id: UUID, query: str = "", limit: int = 50
    ) -> FileListResponse:
        """在当前用户根目录的已索引文件中递归搜索。"""
        root = self.user_root(user_id)
        root_info = await self._backend.stat(self._factory.relative_to_root(root))
        if root_info is not None and not root_info.get("is_dir"):
            raise PermissionError("用户工作区根目录不可访问")

        normalized_query = query.replace("\\", "/").strip("/").casefold()
        items = await self._files.list_by_user(user_id, status="active")
        directories = await self._dirs.list_by_user(user_id)
        excluded_parts = {".git", "node_modules", "__pycache__"}
        matches = []
        for file in items:
            relative_path = self._workspace_relative_path(file.path, user_id)
            parts = set(Path(relative_path).parts)
            if parts & excluded_parts:
                continue
            if normalized_query and normalized_query not in relative_path.casefold():
                continue
            matches.append(
                DataFileDTO(
                    id=file.id,
                    original_name=file.original_name,
                    size=file.size,
                    file_type=file.file_type,
                    status=file.status,
                    checksum=file.checksum,
                    directory=file.directory,
                    path=relative_path,
                    source=file.source or "upload",
                    owner_scope=file.owner_scope or "personal",
                    team_id=file.team_id,
                    created_at=file.created_at,
                    modified_at=file.updated_at,
                )
            )
            if len(matches) >= limit:
                break
        directory_matches = [
            DirectorySearchDTO(
                id=directory.id,
                path=directory.path,
                name=directory.name,
                parent_path=directory.parent_path,
                is_system=directory.is_system,
            )
            for directory in directories
            if not normalized_query or normalized_query in directory.path.casefold()
        ][:limit]
        return FileListResponse(
            items=matches,
            directories=directory_matches,
            total=len(matches) + len(directory_matches),
        )

    async def preview_by_path(
        self,
        user_id: UUID,
        path: str,
        max_lines: int = 50,
        max_bytes: int = 200 * 1024,
    ) -> dict[str, Any]:
        """预览用户工作区内的文本文件内容（按行截断）。

        文件大小超过 ``max_bytes * 2`` 时仅返回元数据与提示，不读取内容；
        二进制或不可解码文件按 ``errors='replace'`` 兜底返回，避免直接抛错。
        """
        normalized = self.validate_workspace_path(path)
        if not normalized:
            raise ValidationError("文件路径不能为空")
        rel = f"users/{user_id}/{normalized}"
        info = await self._backend.stat(rel)
        if info is None:
            raise NotFoundError("文件不存在")
        if info.get("is_dir"):
            raise ValidationError("路径是目录，无法预览")
        total_size = info.get("size", 0) or 0
        if total_size > max_bytes * 2:
            return {
                "path": path,
                "truncated": True,
                "total_size": total_size,
                "lines": [],
                "message": f"文件过大 ({total_size} bytes)，仅返回前 {max_lines} 行",
            }
        content = await self._backend.read(rel, limit=max_bytes * 2)
        text = content.decode("utf-8", errors="replace")
        lines = text.splitlines()
        truncated = len(lines) > max_lines
        return {
            "path": path,
            "truncated": truncated,
            "total_size": total_size,
            "lines": lines[:max_lines],
        }

    async def read_file_text(
        self, user_id: UUID, file_id: UUID, max_bytes: int
    ) -> str:
        """按 file_id 读取用户/团队文件文本内容，超出上限或解码失败时抛 ValidationError。"""
        file = await self._files.get_visible(user_id, file_id)
        if file is None:
            raise NotFoundError("文件不存在")
        await self._require_read_access(file, user_id)
        info = await self._backend.stat(file.path)
        if info is None:
            raise NotFoundError("文件已被移除")
        size = info.get("size", 0) or 0
        if size > max_bytes:
            raise ValidationError(
                f"文件超过 {max_bytes} 字节，无法直接作为文本输入"
            )
        content = await self._backend.read(file.path, limit=max_bytes)
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError("文件不是 UTF-8 文本，无法直接作为文本输入") from exc

    async def get_quota(self, user_id: UUID) -> QuotaResponse:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        total = user.storage_quota
        used = user.used_storage
        percent = round(used / total * 100, 2) if total > 0 else 100.0
        return QuotaResponse(used=used, total=total, percent=percent)

    # ------------------------------------------------------------------
    # 预签名 URL（cloud / S3 模式大文件直传）
    # ------------------------------------------------------------------
    async def create_presigned_download(
        self, user_id: UUID, file_id: UUID, expires: int = 3600
    ) -> str:
        """为已有文件生成临时下载 URL；本地模式抛出 BusinessError。"""
        file = await self._files.get_visible(user_id, file_id)
        if file is None:
            raise NotFoundError("文件不存在")
        await self._require_read_access(file, user_id)
        return self._backend.presigned_get_url(file.path, expires=expires)

    async def create_presigned_upload(
        self,
        user_id: UUID,
        original_name: str,
        directory: str,
        size: int,
        file_type: str = "other",
        expires: int = 3600,
    ) -> tuple[str, uuid.UUID, str]:
        """预创建文件记录并生成直传 URL；本地模式抛出 BusinessError。"""
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        if size > 0 and user.used_storage + size > user.storage_quota:
            raise ValidationError("存储配额不足")

        directory = self._normalize_directory(directory)
        target_dir = await self._inbox_subdir(user_id, directory)
        file_id = uuid.uuid4()
        safe_name = Path(original_name).name
        dest = target_dir / f"{file_id.hex[:8]}_{safe_name}"
        rel_path = self._factory.relative_to_root(dest)

        detected = _detect_file_type(safe_name)
        record = DataFile(
            id=file_id,
            user_id=user_id,
            path=rel_path,
            original_name=safe_name,
            size=size,
            checksum="",
            file_type=detected,
            status="uploading",
            directory=directory,
            source=FileSource.UPLOAD.value,
            owner_scope=OwnerScope.PERSONAL.value,
        )
        await self._files.save(record)
        upload_url = self._backend.presigned_put_url(rel_path, expires=expires)
        return upload_url, file_id, rel_path

    async def complete_presigned_upload(
        self, user_id: UUID, file_id: UUID, checksum: str = ""
    ) -> DataFileDTO:
        """客户端直传完成后确认文件元数据并激活记录。"""
        file = await self._files.get_by_id(user_id, file_id)
        if file is None:
            raise NotFoundError("文件不存在")
        if file.status != "uploading":
            raise ValidationError("文件不处于待上传状态")

        info = await self._backend.stat(file.path)
        if info is None:
            raise ValidationError("未检测到已上传文件")
        actual_size = info.get("size", file.size)

        file.size = actual_size
        file.status = "active"
        file.checksum = checksum
        saved = await self._files.save(file)

        user = await self._users.get_by_id(user_id)
        if user is not None:
            delta = min(saved.size, user.storage_quota - user.used_storage)
            if delta > 0:
                await self._users.add_used_storage(user_id, delta)
        await self._session.commit()

        return DataFileDTO(
            id=saved.id,
            original_name=saved.original_name,
            size=saved.size,
            file_type=saved.file_type,
            status=saved.status,
            checksum=saved.checksum,
            directory=saved.directory,
            path=self._workspace_relative_path(saved.path, user_id),
            source=saved.source or "upload",
            owner_scope=saved.owner_scope or "personal",
            team_id=saved.team_id,
            created_at=saved.created_at,
            modified_at=saved.updated_at,
        )

    # ------------------------------------------------------------------
    # 分块上传（委托给 UploadService）
    # ------------------------------------------------------------------
    @property
    def _upload_svc(self):
        """懒加载上传服务，避免循环导入。"""
        if not hasattr(self, "__upload_svc"):
            from omichub.application.services.upload_service import UploadService

            object.__setattr__(self, "_FileService__upload_svc", UploadService(self._session))
        return self.__upload_svc

    async def init_upload(self, user_id: UUID, req: UploadInitRequest) -> UploadInitResponse:
        return await self._upload_svc.init_upload(user_id, req)

    async def save_chunk(
        self, user_id: UUID, upload_id: UUID, index: int, chunk_bytes: bytes, md5: str
    ) -> UploadChunkResponse:
        return await self._upload_svc.save_chunk(user_id, upload_id, index, chunk_bytes, md5)

    async def merge_upload(self, user_id: UUID, upload_id: UUID) -> UploadMergeResponse:
        return await self._upload_svc.merge_upload(user_id, upload_id)

    async def cancel_upload(self, user_id: UUID, upload_id: UUID) -> bool:
        return await self._upload_svc.cancel_upload(user_id, upload_id)

    # ------------------------------------------------------------------
    # 下载 / 删除
    # ------------------------------------------------------------------
    async def get_file_path(self, user_id: UUID, file_id: UUID) -> Path:
        """获取文件绝对路径（下载用，强制归属/团队权限校验）"""
        file = await self._files.get_visible(user_id, file_id)
        if file is None:
            raise NotFoundError("文件不存在")
        await self._require_read_access(file, user_id)
        if not await self._backend.exists(file.path):
            raise NotFoundError("文件已被移除")
        return await self._backend.get_local_path(file.path)

    async def delete_file(self, user_id: UUID, file_id: UUID) -> bool:
        file = await self._files.get_visible(user_id, file_id)
        if file is None:
            raise NotFoundError("文件不存在")
        await self._require_delete_access(file, user_id)
        # 删盘 + 删记录
        if await self._backend.exists(file.path):
            await self._backend.delete(file.path)
        await self._files.delete_visible(user_id, file_id)
        # 扣减配额：按文件实际归属用户扣减（团队文件也先归属上传者）
        user = await self._users.get_by_id(file.user_id)
        if user is not None:
            delta = -min(file.size, user.used_storage)
            if delta != 0:
                await self._users.add_used_storage(file.user_id, delta)
        await self._session.commit()
        return True

    async def move_file(self, user_id: UUID, file_id: UUID, directory: str) -> DataFileDTO:
        """移动文件到指定目录（改 storage_path + directory 字段 + 物理移动）。

        团队空间文件仅做逻辑目录移动，保持物理路径在团队存储空间内。
        """
        file = await self._files.get_visible(user_id, file_id)
        if file is None:
            raise NotFoundError("文件不存在")
        await self._require_write_access(file, user_id)
        directory = self._normalize_directory(directory)

        if file.owner_scope == OwnerScope.TEAM.value:
            # 团队文件：仅更新 directory 字段，不跨用户空间移动物理文件
            file.directory = directory
            saved = await self._files.save(file)
            await self._session.commit()
            return DataFileDTO(
                id=saved.id,
                original_name=saved.original_name,
                size=saved.size,
                file_type=saved.file_type,
                status=saved.status,
                checksum=saved.checksum,
                directory=saved.directory,
                path=self._workspace_relative_path(saved.path, user_id),
                source=saved.source or "upload",
                owner_scope=saved.owner_scope or "personal",
                team_id=saved.team_id,
                created_at=saved.created_at,
                modified_at=saved.updated_at,
            )

        old_exists = await self._backend.exists(file.path)
        if old_exists:
            old_abs = await self._backend.get_local_path(file.path)
        else:
            # 保持历史行为：即使源文件已不存在，也允许更新记录指向新目录
            old_abs = self._resolve_abs(file.path)
        new_subdir = await self._inbox_subdir(user_id, directory)
        new_abs = new_subdir / old_abs.name
        new_rel = self._factory.relative_to_root(new_abs)
        if await self._backend.exists(new_rel) and new_abs != old_abs:
            # 目标已存在同名：追加短 uuid
            new_abs = _append_dedupe_suffix(new_abs, uuid.uuid4().hex[:8])
        if old_exists and new_abs != old_abs:
            await self._backend.move(
                self._factory.relative_to_root(old_abs),
                self._factory.relative_to_root(new_abs),
            )
        file.directory = directory
        file.path = self._factory.relative_to_root(new_abs)
        saved = await self._files.save(file)
        await self._session.commit()
        return DataFileDTO(
            id=saved.id,
            original_name=saved.original_name,
            size=saved.size,
            file_type=saved.file_type,
            status=saved.status,
            checksum=saved.checksum,
            directory=saved.directory,
            path=self._workspace_relative_path(saved.path, user_id),
            source=saved.source or "upload",
            owner_scope=saved.owner_scope or "personal",
            team_id=saved.team_id,
            created_at=saved.created_at,
            modified_at=saved.updated_at,
        )

    async def _ensure_user_system_subdir(self, user_id: UUID, name: str) -> Path:
        """确保用户顶层系统子目录（inbox/projects/raw_data/workspace/downloads/temp）存在。"""
        mapping = {
            "inbox": self._factory.inbox_dir(str(user_id)),
            "projects": self._factory.projects_dir(str(user_id)),
            "raw_data": self._factory.user_root(str(user_id)) / "raw_data",
            "workspace": self._factory.workspace_dir(str(user_id)),
            "downloads": self._factory.downloads_dir(str(user_id)),
            "temp": self._factory.user_root(str(user_id)) / "temp",
        }
        d = mapping.get(name)
        if d is None:
            d = self._factory.user_root(str(user_id)) / name
        await self._backend.ensure_dir(self._factory.relative_to_root(d))
        return d

    # ------------------------------------------------------------------
    # 用户目录 CRUD（委托给 DirectoryService）
    # ------------------------------------------------------------------
    @property
    def _dir_svc(self):
        """懒加载目录服务，避免循环导入。"""
        if not hasattr(self, "_FileService__dir_svc"):
            from omichub.application.services.directory_service import DirectoryService

            object.__setattr__(self, "_FileService__dir_svc", DirectoryService(self._session))
        return self._FileService__dir_svc

    async def ensure_default_directories(self, user_id: UUID) -> None:
        return await self._dir_svc.ensure_default_directories(user_id)

    async def list_directories(self, user_id: UUID) -> list[DirectoryDTO]:
        return await self._dir_svc.list_directories(user_id)

    async def create_directory(self, user_id: UUID, req: DirectoryCreateRequest) -> DirectoryDTO:
        return await self._dir_svc.create_directory(user_id, req)

    async def delete_directory(self, user_id: UUID, path: str) -> bool:
        return await self._dir_svc.delete_directory(user_id, path)

    async def list_files_for_picker(
        self, user_id: UUID, directory: str | None = None, file_type: str | None = None
    ) -> list[FilePickerItemDTO]:
        """供分析文件选择器：返回用户可见文件 + 绝对路径（含团队空间）"""
        items = await self._files.list_visible(user_id, status="active", directory=directory)
        result: list[FilePickerItemDTO] = []
        for f in items:
            if file_type is not None and f.file_type.value != file_type:
                continue
            abs_path = await self._backend.get_local_path(f.path)
            result.append(
                FilePickerItemDTO(
                    id=f.id,
                    original_name=f.original_name,
                    size=f.size,
                    file_type=f.file_type,
                    directory=f.directory,
                    abs_path=str(abs_path),
                )
            )
        return result

    # ------------------------------------------------------------------
    # 文件同步（磁盘 ↔ file_records）
    # ------------------------------------------------------------------
    async def sync_user_files(self, user_id: UUID) -> SyncResponse:
        """对账用户目录与 file_records，并重算配额。

        用于：手动放入的文件、旧任务未登记的产物，以及用户从磁盘直接删除文件后的
        页面自愈。幂等：同 storage_path 已存在则跳过；active 记录的物理文件不存在则
        删除记录；历史去重后缀显示名会在同步时修正。
        """
        from sqlalchemy import select

        from omichub.infrastructure.database.models.file import FileRecordModel

        user_root = self.user_root(user_id)
        user_root_rel = self._factory.relative_to_root(user_root)

        res = await self._session.execute(
            select(FileRecordModel).where(
                FileRecordModel.user_id == user_id,
                FileRecordModel.status == "active",
            )
        )
        existing_paths: set[str] = set()
        removed = 0
        removed_size = 0
        renamed = 0

        for model in res.scalars().all():
            if not await self._backend.exists(model.storage_path):
                await self._files.delete(user_id, model.id)
                removed += 1
                removed_size += model.size or 0
                continue

            existing_paths.add(model.storage_path)
            physical_name = Path(model.storage_path).name
            if model.original_name == physical_name:
                clean_name = canonical_original_name(physical_name)
                if clean_name != model.original_name:
                    model.original_name = clean_name
                    model.file_type = _detect_file_type(clean_name).value
                    renamed += 1

        added = 0
        added_size = 0
        entries = await self._backend.list(user_root_rel, recursive=True)

        # 先登记目录，再登记文件
        for entry in entries:
            if entry["type"] != "dir":
                continue
            rel_user_parts = Path(entry["path"]).relative_to(Path(user_root_rel)).parts
            if self._should_skip_sync_path(rel_user_parts):
                continue
            relative_directory = "/".join(rel_user_parts)
            if relative_directory:
                await ensure_directory_chain(self._session, user_id, relative_directory)

        for entry in entries:
            if entry["type"] != "file":
                continue
            rel_user_parts = Path(entry["path"]).relative_to(Path(user_root_rel)).parts
            # 跳过隐藏目录/文件（.tmp 上传分片、.qoder 等 IDE 元数据）
            if any(part.startswith(".") for part in rel_user_parts):
                continue
            # 跳过系统内部目录下的文件（tasks/projects/... 由各自服务登记）
            if self._should_skip_sync_path(rel_user_parts):
                continue
            rel = entry["path"]
            if rel in existing_paths:
                continue
            rel_user = Path(*rel_user_parts) if rel_user_parts else None
            directory = self._derive_directory(rel_user)
            if directory:
                await ensure_directory_chain(self._session, user_id, directory)
            size = entry["size"] or 0
            original_name = canonical_original_name(entry["name"])
            record = DataFile(
                id=uuid.uuid4(),
                user_id=user_id,
                path=rel,
                original_name=original_name,
                size=size,
                checksum="",
                file_type=_detect_file_type(original_name),
                status="active",
                directory=directory,
            )
            await self._files.save(record)
            existing_paths.add(rel)
            added += 1
            added_size += size

        # 重算配额，修正历史漂移（下载/手动放入/手工删除未计入的部分）
        await self._users.recompute_used_storage(user_id)
        await self._session.commit()
        return SyncResponse(
            added=added,
            added_size=added_size,
            removed=removed,
            removed_size=removed_size,
            renamed=renamed,
        )

    @staticmethod
    def _derive_directory(rel_user: Path | None) -> str:
        """从「相对用户根的路径」推导 logical directory。

        - ``inbox/myproj/x.fq`` → ``myproj``（上传布局，剥离 inbox/ 前缀）
        - ``inbox/x.fq`` → ``""``（直接落在 inbox 根，归入用户根目录视图）
        - ``raw/myproj/x.fq`` → ``myproj``（兼容 legacy 上传布局，剥离 raw/）
        - ``raw_data/PRJNA1259417/x.fq`` → ``raw_data/PRJNA1259417``（下载布局，保留）
        - ``downloads/x.fq`` → ``downloads``（下载产物）
        - 直接在用户根下的文件 → ``""``
        """
        if rel_user is None:
            return ""
        parts = list(rel_user.parts)[:-1]  # 去掉文件名
        if not parts:
            return ""
        # 剥离上传暂存目录前缀（inbox 是当前，raw 是 legacy）
        if parts and parts[0] in ("inbox", "raw"):
            parts = parts[1:]
        parts = [p for p in parts if p and p not in (".", "..")]
        return "/".join(parts)

    @staticmethod
    def _should_skip_sync_path(parts: tuple[str, ...]) -> bool:
        """判断该路径是否属于系统内部目录，sync 时应跳过（不登记为普通文件记录）。

        - 顶层命中 _SYNC_SKIP_USER_TOP_DIRS（tasks/projects/temp/results/raw）→ 跳过
        - workspace/{chat-uploads,sandbox,...} → 跳过；workspace/ 根下的文件允许登记
        - 隐藏目录（以 . 开头）→ 跳过
        """
        if not parts:
            return False
        top = parts[0]
        return (
            top.startswith(".")
            or top in _SYNC_SKIP_USER_TOP_DIRS
            or (top == "workspace" and len(parts) >= 2 and parts[1] in _SYNC_SKIP_WORKSPACE_SUBDIRS)
        )

    # ------------------------------------------------------------------
    # 样本（供流程引擎读取文件路径）
    # ------------------------------------------------------------------
    async def list_samples(self, user_id: UUID) -> SampleListResponse:
        items = await self._samples.list_by_user(user_id)
        dtos = [
            SampleDTO(
                id=s.id,
                name=s.name,
                species=s.species,
                tissue=s.tissue,
                description=s.description,
                metadata=s.metadata,
                file_ids=s.file_ids,
                created_at=s.created_at,
            )
            for s in items
        ]
        return SampleListResponse(items=dtos, total=len(dtos))

    async def create_sample(self, user_id: UUID, req: SampleCreateRequest) -> SampleDTO:
        # 校验 file_ids 归属
        for fid in req.file_ids:
            if await self._files.get_by_id(user_id, fid) is None:
                raise NotFoundError(f"文件不存在或无权访问：{fid}")
        sample = Sample(
            id=uuid.uuid4(),
            user_id=user_id,
            name=req.name,
            species=req.species,
            tissue=req.tissue,
            description=req.description,
            metadata=req.metadata,
            file_ids=list(req.file_ids),
        )
        saved = await self._samples.save(sample)
        await self._session.commit()
        return SampleDTO(
            id=saved.id,
            name=saved.name,
            species=saved.species,
            tissue=saved.tissue,
            description=saved.description,
            metadata=saved.metadata,
            file_ids=saved.file_ids,
            created_at=saved.created_at,
        )

    async def get_sample_file_paths(self, user_id: UUID, sample_id: UUID) -> list[str]:
        """供下游 Nextflow/Snakemake 读取样本文件绝对路径"""
        sample = await self._samples.get_by_id(user_id, sample_id)
        if sample is None:
            raise NotFoundError("样本不存在")
        paths: list[str] = []
        for fid in sample.file_ids:
            file = await self._files.get_by_id(user_id, fid)
            if file is not None:
                abs_path = await self._backend.get_local_path(file.path)
                paths.append(str(abs_path))
        return paths
