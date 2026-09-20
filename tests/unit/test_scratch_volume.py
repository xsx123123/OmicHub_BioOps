"""ScratchVolumeManager 单元测试（cloud 模式临时 POSIX scratch 卷）"""

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from cygnusx.domain.file.value_objects import FileSource
from cygnusx.infrastructure.config.storage_config import StorageConfig
from cygnusx.infrastructure.storage.backend import LocalStorageBackend
from cygnusx.infrastructure.storage.path_factory import StoragePathFactory
from cygnusx.infrastructure.storage.scratch_volume import ScratchVolumeManager


def _manager(tmp_path: Path, user_id: UUID | None = None):
    user_id = user_id or uuid4()
    session_id = uuid4().hex
    pf = StoragePathFactory(StorageConfig(data_root=str(tmp_path), users_subdir="users"))
    backend = LocalStorageBackend(pf)
    mgr = object.__new__(ScratchVolumeManager)
    mgr.session_id = session_id
    mgr.user_id = user_id
    mgr._session = SimpleNamespace()
    mgr._pf = pf
    mgr._backend = backend
    mgr._root = pf.data_root / "system" / "scratch" / session_id
    mgr.volume = SimpleNamespace(
        root=mgr._root,
        workspace=mgr._root / "workspace",
        platform=mgr._root / "platform",
        input=mgr._root / "workspace" / "input",
        output=mgr._root / "workspace" / "output",
    )
    return mgr, user_id, session_id


@pytest.mark.asyncio
async def test_allocate_creates_scratch_layout(tmp_path: Path) -> None:
    mgr, _, _ = _manager(tmp_path)
    volume = await mgr.allocate()

    assert volume.workspace.is_dir()
    assert volume.input.is_dir()
    assert volume.output.is_dir()
    assert volume.platform.is_dir()
    assert (volume.workspace / "scripts").is_dir()


@pytest.mark.asyncio
async def test_materialize_inputs_creates_platform_mirror_and_input_link(tmp_path: Path) -> None:
    user_id = uuid4()
    mgr, _, _ = _manager(tmp_path, user_id)
    await mgr.allocate()

    # 在持久层写入一个用户文件
    persistent_rel = f"users/{user_id}/inbox/sample.fastq"
    persistent_path = tmp_path / persistent_rel
    persistent_path.parent.mkdir(parents=True, exist_ok=True)
    persistent_path.write_bytes(b"ACGT")

    file_id = uuid4()
    record = SimpleNamespace(
        id=file_id,
        user_id=user_id,
        storage_path=persistent_rel,
        original_name="sample.fastq",
        status="active",
    )

    async def _execute(stmt):
        class _Result:
            def scalar_one_or_none(self):
                return record
        return _Result()

    mgr._session.execute = _execute

    paths = await mgr.materialize_inputs([f"file://{file_id}"])

    assert len(paths) == 1
    assert paths[0].startswith("/workspace/input/")
    assert (mgr.volume.platform / persistent_rel).read_bytes() == b"ACGT"
    assert (mgr.volume.input / "sample.fastq").is_symlink()


@pytest.mark.asyncio
async def test_register_outputs_uploads_and_registers(tmp_path: Path) -> None:
    user_id = uuid4()
    mgr, _, session_id = _manager(tmp_path, user_id)
    await mgr.allocate()

    # 在 scratch output 下写入产物
    output_file = mgr.volume.output / "results" / "counts.csv"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("gene,count\nA,1")

    registered: list[SimpleNamespace] = []

    class FakeRegistry:
        async def register(self, uid, path, *, source, task_id=None, directory=""):
            registered.append(
                SimpleNamespace(
                    user_id=uid,
                    path=str(path),
                    source=source,
                    directory=directory,
                )
            )
            return SimpleNamespace(id=uuid4())

    mgr._registry = FakeRegistry()

    async def _commit():
        return None

    mgr._session.commit = _commit

    records = await mgr.register_outputs(source=FileSource.STUDIO)

    assert len(records) == 1
    assert len(registered) == 1
    assert "studio-output" in registered[0].path
    assert registered[0].source == FileSource.STUDIO
    # 产物应已写入持久存储
    dest_rel = f"users/{user_id}/workspace/studio-output/{session_id[:8]}/results/counts.csv"
    assert (tmp_path / dest_rel).read_text() == "gene,count\nA,1"


@pytest.mark.asyncio
async def test_cleanup_removes_scratch(tmp_path: Path) -> None:
    mgr, _, _ = _manager(tmp_path)
    await mgr.allocate()
    assert mgr._root.exists()

    await mgr.cleanup()

    assert not mgr._root.exists()


def test_volumes_for_container_returns_expected_bind_mounts(tmp_path: Path) -> None:
    mgr, _, _ = _manager(tmp_path)
    volumes = mgr.volumes_for_container()

    assert volumes[str(mgr.volume.workspace)] == {"bind": "/workspace", "mode": "rw"}
    assert volumes[str(mgr.volume.platform)] == {"bind": "/data/platform", "mode": "ro"}
