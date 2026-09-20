"""聊天轻量沙盒产物收集与下载测试。"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from cygnusx.api.v1.chat import download_chat_sandbox_artifact
from cygnusx.application.services import chat_sandbox_tools
from cygnusx.core.exceptions import ValidationError
from cygnusx.domain.file.value_objects import FileSource
from cygnusx.infrastructure.config.storage_config import StorageConfig
from cygnusx.infrastructure.storage.backend import LocalStorageBackend
from cygnusx.infrastructure.storage.file_registry import FileRegistry
from cygnusx.infrastructure.storage.path_factory import StoragePathFactory


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
    # 模块级状态（交付目录重置归属 / 已收集产物签名 / 已注入输入签名 /
    # 产物 sha256 实测缓存）在用例间隔离
    chat_sandbox_tools._artifact_dir_owner.clear()
    chat_sandbox_tools._collected_artifacts.clear()
    chat_sandbox_tools._injected_inputs.clear()
    chat_sandbox_tools._artifact_digests.clear()


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


def test_reset_cmd_tolerates_tmpfs_mount_points() -> None:
    # /workspace/output、/workspace/input 在只读 rootfs 基线下是 tmpfs 挂载点，
    # rm -rf 删不掉挂载点本身会返回非零；不能用 && 短路，否则 mkdir 不执行
    cmd = chat_sandbox_tools._ARTIFACT_DIR_RESET_CMD
    assert "&&" not in cmd
    assert "mkdir -p" in cmd


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
        "cygnusx.application.services.sandbox_service.SandboxService", FakeService
    )
    monkeypatch.setattr(
        "cygnusx.infrastructure.database.session.get_session_factory",
        lambda: _FakeDBCtx,
    )
    monkeypatch.setattr(
        chat_sandbox_tools, "_collect_artifacts", AsyncMock(return_value=([], [], []))
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
        "cygnusx.core.config.get_settings",
        lambda: SimpleNamespace(storage_path=str(tmp_path)),
    )
    monkeypatch.setattr(
        chat_sandbox_tools, "get_path_factory", _tmp_path_factory(tmp_path)
    )
    monkeypatch.setattr("cygnusx.infrastructure.sandbox.get_sandbox_pool", lambda: pool)

    first = asyncio.run(
        chat_sandbox_tools._collect_artifacts("container-1", "user-1", "sandbox-1")
    )
    assert [item["path"] for item in first[0]] == [
        "figures/a.png",
        "results/table.xlsx",
    ]

    # 同一会话第二次收集：未变化的 a.png 不再出现在清单里，
    # 内容变化的 table.xlsx 与新增的 b.png 保留
    second = asyncio.run(
        chat_sandbox_tools._collect_artifacts("container-1", "user-1", "sandbox-1")
    )
    assert [item["path"] for item in second[0]] == [
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
        "cygnusx.core.config.get_settings",
        lambda: SimpleNamespace(storage_path=str(tmp_path)),
    )
    monkeypatch.setattr(
        chat_sandbox_tools, "get_path_factory", _tmp_path_factory(tmp_path)
    )
    monkeypatch.setattr("cygnusx.infrastructure.sandbox.get_sandbox_pool", lambda: pool)

    artifacts = asyncio.run(
        chat_sandbox_tools._collect_artifacts("container-1", "user-1", "sandbox-1")
    )[0]

    host_dest = (
        tmp_path / "users" / "user-1" / "workspace" / "chat-output" / "sandbox-1" / "output"
    )
    # /tmp/chat_output 与 /workspace/output 两个约定目录并行收集
    assert [call.args for call in pool.copy_dir_out.await_args_list] == [
        ("container-1", "/tmp/chat_output", host_dest),
        ("container-1", "/workspace/output", host_dest),
    ]
    # 宿主磁盘上没有真实文件（copy_dir_out 被 mock），sha256 实测失败记 None
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
            "sha256": None,
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
            "sha256": None,
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
        "cygnusx.core.config.get_settings",
        lambda: SimpleNamespace(storage_path=str(tmp_path)),
    )
    monkeypatch.setattr(
        "cygnusx.infrastructure.storage.get_path_factory", _tmp_path_factory(tmp_path)
    )
    monkeypatch.setattr(
        "cygnusx.infrastructure.storage.get_storage_backend",
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
        "cygnusx.core.config.get_settings",
        lambda: SimpleNamespace(storage_path=str(tmp_path)),
    )
    monkeypatch.setattr(
        "cygnusx.infrastructure.storage.get_path_factory", _tmp_path_factory(tmp_path)
    )
    monkeypatch.setattr(
        "cygnusx.infrastructure.storage.get_storage_backend",
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
    monkeypatch.setattr("cygnusx.infrastructure.sandbox.get_sandbox_pool", lambda: pool)

    fake_file_id = UUID("22222222-2222-2222-2222-222222222222")
    calls: list[tuple[object, ...], dict[str, object]] = []

    async def fake_register(*args: object, **kwargs: object) -> SimpleNamespace:
        calls.append((args, kwargs))
        return SimpleNamespace(id=fake_file_id)

    monkeypatch.setattr(FileRegistry, "register", fake_register)

    artifacts = await chat_sandbox_tools._collect_artifacts(
        "container-1", _USER_ID, session_id, db=SimpleNamespace()
    )

    assert len(artifacts[0]) == 1
    assert artifacts[0][0]["file_id"] == str(fake_file_id)
    # 实测 sha256 写入新建 file_records 记录的 checksum 列
    import hashlib

    assert artifacts[0][0]["sha256"] == hashlib.sha256(b"xlsx").hexdigest()
    assert len(calls) == 1
    _args, kwargs = calls[0]
    assert kwargs.get("source") == FileSource.CHAT_SANDBOX
    assert kwargs.get("checksum") == hashlib.sha256(b"xlsx").hexdigest()
    assert str(kwargs.get("directory")) == f"workspace/chat-output/{session_id}/output"


# ===== 声明产物 sha256 实测对账（missing_artifacts） =====


def _patch_collect_deps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pool: Any) -> Path:
    """指向 tmp storage 的最小依赖替换，返回宿主产物目录。"""
    monkeypatch.setattr(
        chat_sandbox_tools, "get_path_factory", _tmp_path_factory(tmp_path)
    )
    monkeypatch.setattr(
        chat_sandbox_tools, "get_storage_backend", _tmp_storage_backend(tmp_path)
    )
    monkeypatch.setattr("cygnusx.infrastructure.sandbox.get_sandbox_pool", lambda: pool)
    return (
        tmp_path
        / "users"
        / "user-1"
        / "workspace"
        / "chat-output"
        / "sandbox-decl"
        / "output"
    )


def test_collect_artifacts_manifest_sha256_matches_measured(tmp_path, monkeypatch):
    """声明 2 个产物且都真实存在 → manifest 含 path/size/sha256 且与实测一致。"""
    host_dest = _patch_collect_deps(
        tmp_path,
        monkeypatch,
        SimpleNamespace(copy_dir_out=AsyncMock(return_value=[])),
    )
    host_dest.mkdir(parents=True, exist_ok=True)
    (host_dest / "results").mkdir()
    (host_dest / "results" / "summary.csv").write_bytes(b"a,b\n1,2\n")
    (host_dest / "figures").mkdir()
    (host_dest / "figures" / "plot.png").write_bytes(b"png-bytes")

    import hashlib

    pool = SimpleNamespace(
        copy_dir_out=AsyncMock(
            return_value=[
                {"path": "results/summary.csv", "size": 7, "mtime": 1.0},
                {"path": "figures/plot.png", "size": 9, "mtime": 1.0},
            ]
        )
    )
    monkeypatch.setattr("cygnusx.infrastructure.sandbox.get_sandbox_pool", lambda: pool)

    _fresh, manifest, missing = asyncio.run(
        chat_sandbox_tools._collect_artifacts(
            "container-1",
            "user-1",
            "sandbox-decl",
            declared=["results/summary.csv", "figures/*.png"],
        )
    )

    assert missing == []
    by_path = {e["path"]: e for e in manifest}
    assert by_path["results/summary.csv"]["sha256"] == hashlib.sha256(
        b"a,b\n1,2\n"
    ).hexdigest()
    assert by_path["results/summary.csv"]["size"] == 8
    assert by_path["figures/plot.png"]["sha256"] == hashlib.sha256(
        b"png-bytes"
    ).hexdigest()


def test_collect_artifacts_declared_missing_is_reported(tmp_path, monkeypatch):
    """声明 1 个产物但文件不存在 → missing_artifacts 含声明路径、流程不中断。"""
    host_dest = _patch_collect_deps(
        tmp_path,
        monkeypatch,
        SimpleNamespace(copy_dir_out=AsyncMock(return_value=[])),
    )
    host_dest.mkdir(parents=True, exist_ok=True)
    (host_dest / "exists.txt").write_bytes(b"here")

    pool = SimpleNamespace(
        copy_dir_out=AsyncMock(
            return_value=[{"path": "exists.txt", "size": 4, "mtime": 1.0}]
        )
    )
    monkeypatch.setattr("cygnusx.infrastructure.sandbox.get_sandbox_pool", lambda: pool)

    _fresh, manifest, missing = asyncio.run(
        chat_sandbox_tools._collect_artifacts(
            "container-1",
            "user-1",
            "sandbox-decl",
            declared=["exists.txt", "results/never_written.csv"],
        )
    )

    assert missing == ["results/never_written.csv"]
    # 登记/对账主流程未被缺失声明中断：存在的文件仍出 manifest
    assert [e["path"] for e in manifest] == ["exists.txt"]
    assert manifest[0]["sha256"]


def test_collect_artifacts_unreadable_file_recorded_with_error(tmp_path, monkeypatch):
    """sha256 实测失败的文件记入 manifest 标 error，不抛出阻断登记。"""
    host_dest = _patch_collect_deps(
        tmp_path,
        monkeypatch,
        SimpleNamespace(copy_dir_out=AsyncMock(return_value=[])),
    )
    host_dest.mkdir(parents=True, exist_ok=True)
    # 目录伪装成文件：stat 成功但 open 失败（IsADirectoryError 是 OSError 子类）
    (host_dest / "fake.txt").mkdir()

    pool = SimpleNamespace(
        copy_dir_out=AsyncMock(
            return_value=[{"path": "fake.txt", "size": 6, "mtime": 1.0}]
        )
    )
    monkeypatch.setattr("cygnusx.infrastructure.sandbox.get_sandbox_pool", lambda: pool)

    _fresh, manifest, missing = asyncio.run(
        chat_sandbox_tools._collect_artifacts(
            "container-1", "user-1", "sandbox-decl", declared=["fake.txt"]
        )
    )

    entry = manifest[0]
    assert entry["path"] == "fake.txt"
    assert entry["sha256"] is None and entry["error"]
    # 无 hash 的条目不能兑现声明 → 声明落空进 missing
    assert missing == ["fake.txt"]


# ===== 会话附件注入 /workspace/input/ =====


class _FakeScalars:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _FakeResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeSessionDB:
    """伪装 SQLAlchemy 会话：execute 返回预设的消息行。"""

    def __init__(self, messages: list[object]) -> None:
        self._messages = messages

    async def execute(self, _stmt: object) -> _FakeResult:
        return _FakeResult(self._messages)


def _user_message(attachments: list[dict[str, object]]) -> SimpleNamespace:
    return SimpleNamespace(role="user", metadata_json={"attachments": attachments})


def _patch_inject_deps(
    monkeypatch: pytest.MonkeyPatch,
    host_file: Path,
    pool: SimpleNamespace,
) -> None:
    """替换 _inject_session_files 的解析器与沙盒池；chat-uploads 扫描指向空目录。"""

    async def fake_resolve(user_id: str, file_id: str, db: object):
        return host_file, {"file_id": file_id.replace("upload://", "")}

    monkeypatch.setattr(
        "cygnusx.infrastructure.mcp.presets._resolve_workspace_file", fake_resolve
    )
    monkeypatch.setattr("cygnusx.infrastructure.sandbox.get_sandbox_pool", lambda: pool)
    monkeypatch.setattr(
        "cygnusx.infrastructure.config.storage_config.get_user_chat_upload_dir",
        lambda _uid: host_file.parent / "nonexistent-chat-uploads",
    )


@pytest.mark.unit
async def test_inject_session_files_copies_uploads_into_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host_file = tmp_path / "abc123.s12345678.docx"
    host_file.write_bytes(b"docx-bytes")
    pool = SimpleNamespace(copy_files_in=AsyncMock(return_value=["MDH2序列.docx"]))
    _patch_inject_deps(monkeypatch, host_file, pool)
    db = _FakeSessionDB(
        [
            _user_message(
                [{"file_id": "upload://abc123", "name": "MDH2序列.docx", "type": "file"}]
            )
        ]
    )

    metas = await chat_sandbox_tools._inject_session_files(
        db, _USER_ID, "12345678-chat-session", "container-1"
    )

    assert metas == [
        {"name": "MDH2序列.docx", "path": "/workspace/input/MDH2序列.docx", "size": 10}
    ]
    args = pool.copy_files_in.await_args
    assert args.args[0] == "container-1"
    assert args.args[1] == [(host_file, "MDH2序列.docx")]
    assert args.args[2] == "/workspace/input"


@pytest.mark.unit
async def test_inject_session_files_skips_unchanged_reinject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host_file = tmp_path / "abc123.s12345678.docx"
    host_file.write_bytes(b"docx-bytes")
    pool = SimpleNamespace(copy_files_in=AsyncMock(return_value=["MDH2序列.docx"]))
    _patch_inject_deps(monkeypatch, host_file, pool)
    db = _FakeSessionDB(
        [
            _user_message(
                [{"file_id": "upload://abc123", "name": "MDH2序列.docx", "type": "file"}]
            )
        ]
    )

    first = await chat_sandbox_tools._inject_session_files(
        db, _USER_ID, "12345678-chat-session", "container-1"
    )
    second = await chat_sandbox_tools._inject_session_files(
        db, _USER_ID, "12345678-chat-session", "container-1"
    )

    # 第二次注入：文件未变化则不再复制，但仍报告容器内已有路径
    assert pool.copy_files_in.await_count == 1
    assert second == first

    # 文件变化（size 改变）后再次注入：需要重新复制
    host_file.write_bytes(b"docx-bytes-v2-longer")
    await chat_sandbox_tools._inject_session_files(
        db, _USER_ID, "12345678-chat-session", "container-1"
    )
    assert pool.copy_files_in.await_count == 2


@pytest.mark.unit
async def test_inject_session_files_without_session_or_container_is_noop() -> None:
    assert await chat_sandbox_tools._inject_session_files(None, _USER_ID, None, "c1") == []
    assert await chat_sandbox_tools._inject_session_files(None, _USER_ID, "sess", None) == []


def test_reset_cmd_clears_and_recreates_input_dir() -> None:
    cmd = chat_sandbox_tools._ARTIFACT_DIR_RESET_CMD
    assert "rm -rf" in cmd and chat_sandbox_tools.CHAT_INPUT_CONTAINER_DIR in cmd
    assert "mkdir -p" in cmd
