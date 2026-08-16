"""聊天轻量沙盒产物收集与下载测试。"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from omichub.api.v1.chat import download_chat_sandbox_artifact
from omichub.application.services import chat_sandbox_tools
from omichub.core.exceptions import ValidationError
from omichub.domain.file.value_objects import FileSource
from omichub.infrastructure.config.storage_config import StorageConfig
from omichub.infrastructure.storage.backend import LocalStorageBackend
from omichub.infrastructure.storage.file_registry import FileRegistry
from omichub.infrastructure.storage.path_factory import StoragePathFactory


def _tmp_path_factory(tmp_path: Path):
    """返回以 tmp_path 为 data_root 的 StoragePathFactory，供测试隔离使用。"""
    return lambda: StoragePathFactory(
        StorageConfig(data_root=str(tmp_path), users_subdir="users")
    )


def _tmp_storage_backend(tmp_path: Path):
    """返回以 tmp_path 为 data_root 的 LocalStorageBackend，供测试隔离使用。"""
    return lambda: LocalStorageBackend(_tmp_path_factory(tmp_path)())

_USER_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
def _reset_module_state() -> None:
    # 模块级状态（交付目录重置归属 / 已收集产物签名）在用例间隔离
    chat_sandbox_tools._artifact_dir_owner.clear()
    chat_sandbox_tools._collected_artifacts.clear()


def test_reset_cmd_creates_common_subdirs() -> None:
    # reset 后必须同时建好 figures/results 常用子目录，
    # 否则用户代码 savefig("/tmp/chat_output/figures/xxx.png") 会 FileNotFoundError
    cmd = chat_sandbox_tools._ARTIFACT_DIR_RESET_CMD
    assert "mkdir -p" in cmd
    for subdir in (
        "/tmp/chat_output/figures",
        "/tmp/chat_output/results",
        "/workspace/output/figures",
        "/workspace/output/results",
    ):
        assert subdir in cmd


class _FakeDB:
    async def commit(self) -> None:
        pass


class _FakeDBCtx:
    async def __aenter__(self) -> _FakeDB:
        return _FakeDB()

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _patch_execute_deps(
    monkeypatch: pytest.MonkeyPatch,
    session: SimpleNamespace,
    calls: list[tuple[str, str]],
) -> None:
    """把 execute_chat_sandbox 的运行时依赖替换为假实现，记录 execute_code 调用。"""

    class FakeService:
        def __init__(self, db: object) -> None:
            pass

        async def create_session(self, user_id: UUID, language: str) -> SimpleNamespace:
            return session

        async def execute_code(
            self,
            user_id: UUID,
            session_id: object,
            code: str,
            timeout_sec: int = 0,
            language: str = "python",
        ):
            calls.append((code, language))
            yield {"type": "done"}

    monkeypatch.setattr(
        "omichub.application.services.sandbox_service.SandboxService", FakeService
    )
    monkeypatch.setattr(
        "omichub.infrastructure.database.session.get_session_factory",
        lambda: _FakeDBCtx,
    )
    monkeypatch.setattr(
        chat_sandbox_tools, "_collect_artifacts", AsyncMock(return_value=[])
    )


def _run_execute() -> None:
    asyncio.run(
        chat_sandbox_tools.execute_chat_sandbox(
            {"language": "python", "code": "print(1)"}, _USER_ID
        )
    )


def test_execute_skips_reset_when_container_reused_by_same_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    session = SimpleNamespace(id="sandbox-1", container_id="container-1")
    _patch_execute_deps(monkeypatch, session, calls)

    _run_execute()
    _run_execute()

    resets = [c for c, lang in calls if c == chat_sandbox_tools._ARTIFACT_DIR_RESET_CMD]
    assert len(resets) == 1


def test_execute_resets_again_for_other_session_or_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    # 第一次：sandbox-1 占用 container-1，触发 reset
    _patch_execute_deps(
        monkeypatch, SimpleNamespace(id="sandbox-1", container_id="container-1"), calls
    )
    _run_execute()

    # 同一容器被其他会话占用：session.id 不同，必须再次 reset
    _patch_execute_deps(
        monkeypatch, SimpleNamespace(id="sandbox-2", container_id="container-1"), calls
    )
    _run_execute()

    # 同一会话但换容器（原容器被回收/换池）：同样要 reset
    _patch_execute_deps(
        monkeypatch, SimpleNamespace(id="sandbox-2", container_id="container-2"), calls
    )
    _run_execute()

    resets = [c for c, lang in calls if c == chat_sandbox_tools._ARTIFACT_DIR_RESET_CMD]
    assert len(resets) == 3


def test_collect_artifacts_dedupes_unchanged_files_within_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unchanged = {"path": "figures/a.png", "size": 100, "mtime": 1.0}
    first_round = [
        [dict(unchanged), {"path": "results/table.xlsx", "size": 10, "mtime": 1.0}],
        [],
    ]
    second_round = [
        # a.png 未变、table.xlsx 内容变化（size/mtime 不同）、新增 b.png
        [dict(unchanged), {"path": "results/table.xlsx", "size": 20, "mtime": 2.0}],
        [{"path": "figures/b.png", "size": 50, "mtime": 2.0}],
    ]
    pool = SimpleNamespace(
        copy_dir_out=AsyncMock(
            side_effect=[*first_round, *second_round]
        )
    )
    monkeypatch.setattr(
        "omichub.core.config.get_settings",
        lambda: SimpleNamespace(storage_path=str(tmp_path)),
    )
    monkeypatch.setattr(
        chat_sandbox_tools, "get_path_factory", _tmp_path_factory(tmp_path)
    )
    monkeypatch.setattr("omichub.infrastructure.sandbox.get_sandbox_pool", lambda: pool)

    first = asyncio.run(
        chat_sandbox_tools._collect_artifacts("container-1", "user-1", "sandbox-1")
    )
    assert [item["path"] for item in first] == [
        "figures/a.png",
        "results/table.xlsx",
    ]

    # 同一会话第二次收集：未变化的 a.png 不再出现在清单里，
    # 内容变化的 table.xlsx 与新增的 b.png 保留
    second = asyncio.run(
        chat_sandbox_tools._collect_artifacts("container-1", "user-1", "sandbox-1")
    )
    assert [item["path"] for item in second] == [
        "results/table.xlsx",
        "figures/b.png",
    ]


def test_collect_artifacts_persists_files_and_builds_download_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = SimpleNamespace(
        copy_dir_out=AsyncMock(
            side_effect=[
                [
                    {
                        "path": "carcinogenic pathways.xlsx",
                        "size": 128,
                        "mtime": 1.0,
                    }
                ],
                [
                    {
                        "path": "figures/barplot.png",
                        "size": 256,
                        "mtime": 2.0,
                    }
                ],
            ]
        )
    )
    monkeypatch.setattr(
        "omichub.core.config.get_settings",
        lambda: SimpleNamespace(storage_path=str(tmp_path)),
    )
    monkeypatch.setattr(
        chat_sandbox_tools, "get_path_factory", _tmp_path_factory(tmp_path)
    )
    monkeypatch.setattr("omichub.infrastructure.sandbox.get_sandbox_pool", lambda: pool)

    artifacts = asyncio.run(
        chat_sandbox_tools._collect_artifacts("container-1", "user-1", "sandbox-1")
    )

    host_dest = (
        tmp_path / "users" / "user-1" / "workspace" / "chat-output" / "sandbox-1" / "output"
    )
    # /tmp/chat_output 与 /workspace/output 两个约定目录并行收集
    assert [call.args for call in pool.copy_dir_out.await_args_list] == [
        ("container-1", "/tmp/chat_output", host_dest),
        ("container-1", "/workspace/output", host_dest),
    ]
    assert artifacts == [
        {
            "path": "carcinogenic pathways.xlsx",
            "size": 128,
            "mtime": 1.0,
            "url": (
                "/api/v1/chat/sandbox-sessions/sandbox-1/artifacts/download"
                "?path=carcinogenic%20pathways.xlsx"
            ),
            "file_id": None,
        },
        {
            "path": "figures/barplot.png",
            "size": 256,
            "mtime": 2.0,
            "url": (
                "/api/v1/chat/sandbox-sessions/sandbox-1/artifacts/download"
                "?path=figures/barplot.png"
            ),
            "file_id": None,
        },
    ]


def test_download_chat_sandbox_artifact_resolves_current_user_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = (
        tmp_path
        / "users"
        / "user-1"
        / "workspace"
        / "chat-output"
        / "sandbox-1"
        / "output"
        / "result.xlsx"
    )
    target.parent.mkdir(parents=True)
    target.write_bytes(b"xlsx")
    monkeypatch.setattr(
        "omichub.core.config.get_settings",
        lambda: SimpleNamespace(storage_path=str(tmp_path)),
    )
    monkeypatch.setattr(
        "omichub.infrastructure.storage.get_path_factory", _tmp_path_factory(tmp_path)
    )
    monkeypatch.setattr(
        "omichub.infrastructure.storage.get_storage_backend",
        _tmp_storage_backend(tmp_path),
    )

    response = asyncio.run(
        download_chat_sandbox_artifact("sandbox-1", "user-1", "result.xlsx")
    )

    assert Path(response.path) == target
    assert response.filename == "result.xlsx"


def test_download_chat_sandbox_artifact_blocks_path_traversal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "omichub.core.config.get_settings",
        lambda: SimpleNamespace(storage_path=str(tmp_path)),
    )
    monkeypatch.setattr(
        "omichub.infrastructure.storage.get_path_factory", _tmp_path_factory(tmp_path)
    )
    monkeypatch.setattr(
        "omichub.infrastructure.storage.get_storage_backend",
        _tmp_storage_backend(tmp_path),
    )

    with pytest.raises(ValidationError, match="产物路径无效"):
        asyncio.run(
            download_chat_sandbox_artifact("sandbox-1", "user-1", "../../secret.txt")
        )


@pytest.mark.unit
async def test_collect_artifacts_registers_files_with_file_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """产物落盘后应注册到 file_records 并返回 file_id。"""
    session_id = "sandbox-reg"
    host_dest = (
        tmp_path
        / "users"
        / _USER_ID
        / "workspace"
        / "chat-output"
        / session_id
        / "output"
    )
    host_dest.mkdir(parents=True, exist_ok=True)
    (host_dest / "result.xlsx").write_bytes(b"xlsx")

    monkeypatch.setattr(
        chat_sandbox_tools, "get_path_factory", _tmp_path_factory(tmp_path)
    )
    monkeypatch.setattr(
        chat_sandbox_tools, "get_storage_backend", _tmp_storage_backend(tmp_path)
    )
    pool = SimpleNamespace(
        copy_dir_out=AsyncMock(
            return_value=[{"path": "result.xlsx", "size": 10, "mtime": 1.0}]
        )
    )
    monkeypatch.setattr("omichub.infrastructure.sandbox.get_sandbox_pool", lambda: pool)

    fake_file_id = UUID("22222222-2222-2222-2222-222222222222")
    calls: list[tuple[object, ...], dict[str, object]] = []

    async def fake_register(*args: object, **kwargs: object) -> SimpleNamespace:
        calls.append((args, kwargs))
        return SimpleNamespace(id=fake_file_id)

    monkeypatch.setattr(FileRegistry, "register", fake_register)

    artifacts = await chat_sandbox_tools._collect_artifacts(
        "container-1", _USER_ID, session_id, db=SimpleNamespace()
    )

    assert len(artifacts) == 1
    assert artifacts[0]["file_id"] == str(fake_file_id)
    assert len(calls) == 1
    _args, kwargs = calls[0]
    assert kwargs.get("source") == FileSource.CHAT_SANDBOX
    assert str(kwargs.get("directory")) == f"workspace/chat-output/{session_id}/output"
