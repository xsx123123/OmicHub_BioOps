"""报告服务单元测试。"""

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from omichub.application.services import report_service as report_service_module
from omichub.application.services.report_service import ReportService
from omichub.domain.file.value_objects import FileSource
from omichub.infrastructure.config.storage_config import StorageConfig
from omichub.infrastructure.storage import LocalStorageBackend
from omichub.infrastructure.storage.file_registry import FileRegistry
from omichub.infrastructure.storage.path_factory import StoragePathFactory


def _tmp_path_factory(tmp_path: Path):
    return lambda: StoragePathFactory(
        StorageConfig(data_root=str(tmp_path), users_subdir="users")
    )


@pytest.mark.unit
async def test_create_report_from_task_registers_html_in_file_records(
    tmp_path: Path, monkeypatch
):
    """create_report_from_task 生成报告时，HTML 文件应同步注册到 file_records（source=REPORT）。"""
    user_id = UUID("22222222-2222-2222-2222-222222222222")
    run_dir = tmp_path / "users" / str(user_id) / "projects" / "p" / "runs" / "rna-20260101-120000"
    work_dir = run_dir / "work"
    report_dir = work_dir / "Analysis_Report"
    report_dir.mkdir(parents=True)
    html_path = report_dir / "index.html"
    html_path.write_text("<html>report</html>")

    task_id = UUID("11111111-1111-1111-1111-111111111111")

    fake_report = SimpleNamespace(id=UUID("33333333-3333-3333-3333-333333333333"), files=[])
    fake_file = SimpleNamespace(
        id=UUID("44444444-4444-4444-4444-444444444444"),
        report_id=fake_report.id,
        name="index.html",
        type="html",
        size=html_path.stat().st_size,
        path=str(html_path),
        is_primary=True,
    )

    class _FakeRepo:
        async def get_by_task_id(self, task_id: UUID):
            return None

        async def create(self, report):
            return fake_report

        async def get_file_by_id(self, file_id: UUID):
            return fake_file

    class _FakeSession:
        def __init__(self):
            self.added: list[object] = []

        def add(self, obj: object) -> None:
            self.added.append(obj)

        async def flush(self) -> None:
            pass

        async def refresh(self, obj: object) -> None:
            pass

        async def commit(self) -> None:
            pass

    monkeypatch.setattr(
        report_service_module, "get_path_factory", _tmp_path_factory(tmp_path)
    )

    calls: list[tuple[object, ...], dict[str, object]] = []

    async def fake_register(*args: object, **kwargs: object) -> SimpleNamespace:
        calls.append((args, kwargs))
        return SimpleNamespace(id=UUID("55555555-5555-5555-5555-555555555555"))

    monkeypatch.setattr(FileRegistry, "register", fake_register)

    class _FakeFlowService:
        def get_flow(self, flow_id: str):
            return SimpleNamespace(
                meta=SimpleNamespace(name="RNA", version="1", icon="📄")
            )

        def get_flow_config(self, flow_id: str):
            return SimpleNamespace()

    path_factory = _tmp_path_factory(tmp_path)()
    session = _FakeSession()
    service = ReportService(session, backend=LocalStorageBackend(path_factory=path_factory))
    service._factory = path_factory
    service._repo = _FakeRepo()
    service._flow_service = _FakeFlowService()

    report = await service.create_report_from_task(
        task_id=str(task_id),
        user_id=str(user_id),
        flow_id="rna",
        work_dir=str(work_dir),
        sample_count=2,
        duration=60,
    )

    assert report is not None
    assert report.status == "completed"
    assert len(calls) == 1
    _args, kwargs = calls[0]
    assert kwargs.get("source") == FileSource.REPORT
    assert kwargs.get("task_id") == task_id
    assert str(kwargs.get("directory", "")).endswith("Analysis_Report")
