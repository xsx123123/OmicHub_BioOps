"""分析任务 Celery 任务单元测试。"""

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from omichub.domain.file.value_objects import FileSource
from omichub.infrastructure.celery_app.tasks.analysis import _register_pipeline_outputs
from omichub.infrastructure.storage.file_registry import FileRegistry


@pytest.mark.unit
async def test_register_pipeline_outputs_scans_output_dir(tmp_path: Path, monkeypatch):
    """任务成功后应扫描 output 目录并注册到 file_records（source=PIPELINE）。"""
    run_dir = tmp_path / "users" / "user-1" / "projects" / "p" / "runs" / "rna-20260101-120000"
    work_dir = run_dir / "work"
    output_dir = run_dir / "output"
    output_dir.mkdir(parents=True)
    (output_dir / "result.csv").write_text("a,b\n1,2")
    plot_dir = output_dir / "figures"
    plot_dir.mkdir(parents=True)
    (plot_dir / "plot.png").write_bytes(b"png")

    task = SimpleNamespace(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        user_id=UUID("22222222-2222-2222-2222-222222222222"),
        work_dir=str(work_dir),
    )

    registered_paths: list[Path] = []

    async def fake_register_directory(
        self, user_id, directory, *, source, task_id, recursive, **kwargs
    ):
        registered_paths.append(Path(directory))
        assert user_id == task.user_id
        assert source == FileSource.PIPELINE
        assert task_id == task.id
        assert recursive is True
        return [SimpleNamespace(id=UUID(int=i)) for i in range(2)]

    monkeypatch.setattr(FileRegistry, "register_directory", fake_register_directory)

    count = await _register_pipeline_outputs(SimpleNamespace(), task)

    assert count == 2
    assert registered_paths == [output_dir]
