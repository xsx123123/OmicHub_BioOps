from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from omichub.application.services.file_service import (
    FileService,
    _append_dedupe_suffix,
    canonical_original_name,
)
from omichub.core.exceptions import ValidationError
from omichub.domain.file.entities import DataFile, Directory
from omichub.domain.file.value_objects import FileType
from omichub.infrastructure.config.storage_config import StorageConfig
from omichub.infrastructure.mcp.presets import (
    PLATFORM_HANDLERS,
    PLATFORM_PRESET_TOOLS,
    WORKSPACE_FILES_SYSTEM_PROMPT_SUFFIX,
    _list_workspace_files,
)
from omichub.infrastructure.storage.backend import LocalStorageBackend
from omichub.infrastructure.storage.path_factory import StoragePathFactory


def _attach_test_factory(service: FileService, tmp_path: Path) -> None:
    """给 object.__new__ 构造的 FileService 注入以 tmp_path 为根的 PathFactory 与后端。"""
    service._factory = StoragePathFactory(
        StorageConfig(data_root=str(tmp_path), users_subdir="users")
    )
    service._backend = LocalStorageBackend(service._factory)


def test_platform_sandbox_tool_declares_native_r_execution() -> None:
    tool = next(item for item in PLATFORM_PRESET_TOOLS if item["name"] == "platform_sandbox_execute")
    properties = tool["inputSchema"]["properties"]

    assert properties["language"]["enum"] == ["python", "r", "bash"]
    assert "ggtree" in tool["description"]


def test_canonical_original_name_strips_service_dedupe_suffix() -> None:
    assert canonical_original_name("sample_1a2b3c4d.fastq.gz") == "sample.fastq.gz"
    assert canonical_original_name("sample.fastq_1a2b3c4d.gz") == "sample.fastq.gz"


def test_canonical_original_name_keeps_common_lane_numbers() -> None:
    assert canonical_original_name("sample_001.fastq.gz") == "sample_001.fastq.gz"


def test_append_dedupe_suffix_preserves_compound_suffix() -> None:
    result = _append_dedupe_suffix(Path("/tmp/sample.fastq.gz"), "1a2b3c4d")

    assert result.name == "sample_1a2b3c4d.fastq.gz"


def test_derive_directory_matches_upload_and_download_layouts() -> None:
    assert FileService._derive_directory(Path("raw/projectA/sample.fastq.gz")) == "projectA"
    assert FileService._derive_directory(Path("raw_data/PRJNA1/SRR1.fastq.gz")) == "raw_data/PRJNA1"
    assert FileService._derive_directory(Path("sample.fastq.gz")) == ""


@pytest.mark.parametrize("path", ["../other-user", "raw/../../other-user", "/etc", "C:/Users/x"])
def test_validate_workspace_path_rejects_escape(path: str) -> None:
    with pytest.raises(PermissionError, match="路径越权"):
        FileService.validate_workspace_path(path)


def test_validate_workspace_path_normalizes_relative_path() -> None:
    assert FileService.validate_workspace_path("./raw_data/project-a/") == "raw_data/project-a"


@pytest.mark.parametrize("directory", ["../escape", "raw/../../escape", "a/../b"])
def test_normalize_directory_rejects_dotdot(directory: str) -> None:
    service = object.__new__(FileService)
    with pytest.raises(ValidationError, match="禁止包含"):
        service._normalize_directory(directory)


def test_normalize_directory_normalizes_valid_path() -> None:
    service = object.__new__(FileService)
    assert service._normalize_directory("./raw_data/./project-a/") == "raw_data/project-a"
    assert service._normalize_directory("inbox/") == "inbox"


@pytest.mark.asyncio
async def test_ensure_default_directories_repairs_records_and_disk(tmp_path: Path) -> None:
    user_id = uuid4()
    existing = Directory(
        id=uuid4(),
        user_id=user_id,
        path="raw_data",
        name="raw_data",
        is_system=True,
    )
    service = object.__new__(FileService)
    service._dirs = SimpleNamespace()
    service._session = SimpleNamespace(commit_calls=0)
    service._storage_root = tmp_path
    service._factory = StoragePathFactory(
        StorageConfig(data_root=str(tmp_path), users_subdir="users")
    )
    service._backend = LocalStorageBackend(service._factory)

    class FakeDirectoryService:
        def __init__(self, svc: FileService) -> None:
            self._svc = svc

        async def ensure_default_directories(self, user_id: UUID) -> None:
            existing = await self._svc._dirs.list_by_user(user_id)
            existing_paths = {d.path for d in existing}
            created_any = False
            for name in ("inbox", "projects", "raw_data", "workspace", "downloads", "temp"):
                if name not in existing_paths:
                    await self._svc._dirs.save(
                        Directory(
                            id=uuid4(),
                            user_id=user_id,
                            path=name,
                            name=name,
                            parent_path=None,
                            is_system=True,
                        )
                    )
                    created_any = True
                await self._svc._ensure_user_system_subdir(user_id, name)
            if created_any:
                await self._svc._session.commit()

    service._FileService__dir_svc = FakeDirectoryService(service)

    records = [existing]

    async def list_by_user(_user_id: UUID):
        assert _user_id == user_id
        return list(records)

    saved: list[Directory] = []

    async def save(directory: Directory):
        saved.append(directory)
        records.append(directory)
        return directory

    async def commit():
        service._session.commit_calls += 1

    service._dirs.list_by_user = list_by_user
    service._dirs.save = save
    service._session.commit = commit

    await service.ensure_default_directories(user_id)

    assert {item.path for item in saved} == {"inbox", "projects", "workspace", "downloads", "temp"}
    assert {
        path.name for path in (tmp_path / "users" / str(user_id)).iterdir()
    } == {"inbox", "projects", "raw_data", "workspace", "downloads", "temp"}
    assert service._session.commit_calls == 1

    await service.ensure_default_directories(user_id)
    assert service._session.commit_calls == 1


@pytest.mark.asyncio
async def test_list_workspace_files_filters_pattern_and_returns_metadata() -> None:
    now = datetime.now(UTC)
    user_id = uuid4()
    service = object.__new__(FileService)
    service._files = SimpleNamespace()
    service._dirs = SimpleNamespace()

    async def list_by_user(_user_id: UUID, **kwargs):
        assert _user_id == user_id
        assert kwargs["status"] == "active"
        return [
                DataFile(
                    id=uuid4(),
                    user_id=user_id,
                    path=f"users/{user_id}/raw_data/counts.csv",
                    original_name="counts.csv",
                    size=123,
                    file_type=FileType.OTHER,
                    directory="raw_data",
                    created_at=now,
                    updated_at=now,
                ),
                DataFile(
                    id=uuid4(),
                    user_id=user_id,
                    path=f"users/{user_id}/raw_data/notes.txt",
                    original_name="notes.txt",
                    size=12,
                    directory="raw_data",
                    created_at=now,
                    updated_at=now,
                ),
            ]

    async def list_directories(_user_id: UUID):
        assert _user_id == user_id
        return []

    service._files.list_by_user = list_by_user
    service._dirs.list_by_user = list_directories

    result = await service.list_workspace_files(user_id, path="raw_data", pattern="*.csv")

    assert result["total"] == 1
    assert result["items"][0]["name"] == "counts.csv"
    assert result["items"][0]["file_id"]
    assert result["items"][0]["modified_at"] == now.isoformat()


@pytest.mark.asyncio
async def test_list_workspace_files_recursive_returns_nested_files() -> None:
    now = datetime.now(UTC)
    user_id = uuid4()
    service = object.__new__(FileService)
    service._files = SimpleNamespace()
    service._dirs = SimpleNamespace()

    async def list_by_user(_user_id: UUID, **kwargs):
        assert _user_id == user_id
        assert kwargs["status"] == "active"
        return [
            DataFile(
                id=uuid4(),
                user_id=user_id,
                path=f"users/{user_id}/raw_data/project/counts.csv",
                original_name="counts.csv",
                size=123,
                file_type=FileType.OTHER,
                directory="raw_data/project",
                created_at=now,
                updated_at=now,
            )
        ]

    async def list_directories(_user_id: UUID):
        return []

    service._files.list_by_user = list_by_user
    service._dirs.list_by_user = list_directories

    result = await service.list_workspace_files(user_id, recursive=True)

    assert result["recursive"] is True
    assert result["total"] == 1
    assert result["items"][0]["relative_path"] == "raw_data/project/counts.csv"


@pytest.mark.asyncio
async def test_search_files_is_user_scoped_and_excludes_ignored_directories(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    user_id = uuid4()
    service = object.__new__(FileService)
    _attach_test_factory(service, tmp_path)
    service._files = SimpleNamespace()
    service._dirs = SimpleNamespace()

    async def list_by_user(requested_user_id: UUID, **kwargs):
        assert requested_user_id == user_id
        assert kwargs["status"] == "active"
        return [
            DataFile(
                id=uuid4(),
                user_id=user_id,
                path=f"users/{user_id}/raw/expression.csv",
                original_name="expression.csv",
                size=100,
                file_type=FileType.OTHER,
                created_at=now,
                updated_at=now,
            ),
            DataFile(
                id=uuid4(),
                user_id=user_id,
                path=f"users/{user_id}/node_modules/expression-cache.csv",
                original_name="expression-cache.csv",
                size=50,
                file_type=FileType.OTHER,
                created_at=now,
                updated_at=now,
            ),
        ]

    async def list_directories(_user_id: UUID):
        return []

    service._files.list_by_user = list_by_user
    service._dirs.list_by_user = list_directories

    result = await service.search_files(user_id, query="expression", limit=50)

    assert result.total == 1
    assert result.items[0].original_name == "expression.csv"
    assert result.items[0].path == "raw/expression.csv"


@pytest.mark.asyncio
async def test_search_files_supports_nested_paths_with_spaces(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    user_id = uuid4()
    service = object.__new__(FileService)
    _attach_test_factory(service, tmp_path)
    service._files = SimpleNamespace()
    service._dirs = SimpleNamespace()

    async def list_by_user(requested_user_id: UUID, **kwargs):
        assert requested_user_id == user_id
        return [
            DataFile(
                id=uuid4(),
                user_id=user_id,
                path=f"users/{user_id}/docs/26.7.25/image copy 4.png",
                original_name="image copy 4.png",
                size=100,
                file_type=FileType.IMAGE,
                directory="docs/26.7.25",
                created_at=now,
                updated_at=now,
            ),
        ]

    async def list_directories(_user_id: UUID):
        return []

    service._files.list_by_user = list_by_user
    service._dirs.list_by_user = list_directories

    result = await service.search_files(
        user_id, query="docs/26.7.25/image copy 4.png", limit=50
    )

    assert result.total == 1
    assert result.items[0].path == "docs/26.7.25/image copy 4.png"


@pytest.mark.asyncio
async def test_search_files_returns_matching_directories(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    user_id = uuid4()
    service = object.__new__(FileService)
    _attach_test_factory(service, tmp_path)
    service._files = SimpleNamespace()
    service._dirs = SimpleNamespace()

    async def list_files(_user_id: UUID, **_kwargs):
        return []

    async def list_directories(_user_id: UUID):
        return [
            SimpleNamespace(
                id=uuid4(),
                path="enrichmrnet",
                name="enrichmrnet",
                parent_path=None,
                is_system=False,
                created_at=now,
                updated_at=now,
            ),
        ]

    service._files.list_by_user = list_files
    service._dirs.list_by_user = list_directories

    result = await service.search_files(user_id, query="enri", limit=50)

    assert result.total == 1
    assert result.directories[0].path == "enrichmrnet"


def test_workspace_file_tools_are_registered_with_expected_contract() -> None:
    tools = {tool["name"]: tool for tool in PLATFORM_PRESET_TOOLS}

    assert {"list_workspace_files", "search_workspace_files"} <= tools.keys()
    assert tools["list_workspace_files"]["inputSchema"]["properties"].keys() == {
        "path",
        "pattern",
        "recursive",
    }
    assert tools["search_workspace_files"]["inputSchema"]["required"] == ["query"]
    assert "list_workspace_files" in PLATFORM_HANDLERS
    assert "search_workspace_files" in PLATFORM_HANDLERS


def test_workspace_system_prompt_forbids_no_tool_fallback() -> None:
    assert "必须调用 `list_workspace_files`" in WORKSPACE_FILES_SYSTEM_PROMPT_SUFFIX
    assert "recursive=true" in WORKSPACE_FILES_SYSTEM_PROMPT_SUFFIX
    assert "必须先调用 `search_workspace_files`" in WORKSPACE_FILES_SYSTEM_PROMPT_SUFFIX
    assert "禁止声称没有浏览文件的工具" in WORKSPACE_FILES_SYSTEM_PROMPT_SUFFIX


def test_workspace_system_prompt_requires_a_parseable_tree_for_ggtree() -> None:
    assert "`.iqtree` 是 IQ-TREE 的文本运行报告" in WORKSPACE_FILES_SYSTEM_PROMPT_SUFFIX
    assert "`.treefile` 或 `.contree`" in WORKSPACE_FILES_SYSTEM_PROMPT_SUFFIX
    assert "`ape::read.tree()`" in WORKSPACE_FILES_SYSTEM_PROMPT_SUFFIX


@pytest.mark.asyncio
async def test_workspace_list_tool_rejects_traversal_before_accessing_storage() -> None:
    with pytest.raises(PermissionError, match="路径越权"):
        await _list_workspace_files(
            {"path": "../other-user"},
            user_id=str(uuid4()),
            context=SimpleNamespace(db=object()),
        )


@pytest.mark.asyncio
async def test_preview_by_path_returns_lines_and_rejects_traversal(tmp_path: Path) -> None:
    user_id = uuid4()
    service = object.__new__(FileService)
    _attach_test_factory(service, tmp_path)

    user_dir = tmp_path / "users" / str(user_id)
    (user_dir / "raw_data").mkdir(parents=True)
    (user_dir / "raw_data" / "counts.csv").write_text("a,b,c\n1,2,3\n4,5,6\n", encoding="utf-8")

    result = await service.preview_by_path(user_id, "raw_data/counts.csv", max_lines=2)
    assert result["path"] == "raw_data/counts.csv"
    assert result["lines"] == ["a,b,c", "1,2,3"]
    assert result["truncated"] is True
    assert result["total_size"] == 18

    with pytest.raises(PermissionError, match="路径越权"):
        await service.preview_by_path(user_id, "../other-user/secret.txt")
