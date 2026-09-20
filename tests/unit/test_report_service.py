"""报告服务单元测试。"""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from cygnusx.application.services import report_service as report_service_module
from cygnusx.application.services.report_service import ReportService
from cygnusx.domain.file.value_objects import FileSource
from cygnusx.infrastructure.config.storage_config import StorageConfig
from cygnusx.infrastructure.storage import LocalStorageBackend
from cygnusx.infrastructure.storage.file_registry import FileRegistry
from cygnusx.infrastructure.storage.path_factory import StoragePathFactory


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


_USER_ID = UUID("22222222-2222-2222-2222-222222222222")
_TASK_ID = UUID("11111111-1111-1111-1111-111111111111")


def _build_report_service(tmp_path: Path, monkeypatch) -> ReportService:
    class _FakeRepo:
        async def get_by_task_id(self, task_id: UUID):
            return None

        async def create(self, report):
            return report

    class _FakeSession:
        def add(self, obj: object) -> None:
            pass

        async def flush(self) -> None:
            pass

        async def refresh(self, obj: object) -> None:
            pass

    monkeypatch.setattr(
        report_service_module, "get_path_factory", _tmp_path_factory(tmp_path)
    )

    async def fake_register(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(id=UUID("55555555-5555-5555-5555-555555555555"))

    monkeypatch.setattr(FileRegistry, "register", fake_register)

    class _FakeFlowService:
        def get_flow(self, flow_id: str):
            return SimpleNamespace(meta=SimpleNamespace(name="RNA", version="1", icon="📄"))

    path_factory = _tmp_path_factory(tmp_path)()
    service = ReportService(_FakeSession(), backend=LocalStorageBackend(path_factory=path_factory))
    service._factory = path_factory
    service._repo = _FakeRepo()
    service._flow_service = _FakeFlowService()
    return service


def _make_work_dir(tmp_path: Path) -> Path:
    work_dir = (
        tmp_path / "users" / str(_USER_ID) / "projects" / "p" / "runs" / "rna-1" / "work"
    )
    (work_dir / "Analysis_Report").mkdir(parents=True)
    return work_dir


async def _create(service: ReportService, work_dir: Path):
    return await service.create_report_from_task(
        task_id=str(_TASK_ID),
        user_id=str(_USER_ID),
        flow_id="rna",
        work_dir=str(work_dir),
        sample_count=2,
        duration=60,
    )


@pytest.mark.unit
async def test_create_report_prefers_valid_result_manifest(tmp_path: Path, monkeypatch):
    """ARDP：result_manifest.json 声明齐全且 md5 匹配 → completed，主文件取 report.entry。"""
    work_dir = _make_work_dir(tmp_path)
    html_path = work_dir / "Analysis_Report" / "index.html"
    html_path.write_text("<html>report</html>")
    deg = work_dir / "05_DEG" / "deg.csv"
    deg.parent.mkdir(parents=True)
    deg.write_text("gene,log2fc\nA,1.0\n")
    manifest = {
        "manifest_version": "1.0",
        "run": {"status": "completed"},
        "report": {"format": "html", "entry": "Analysis_Report/index.html"},
        "files": [
            {
                "name": "DEG 结果",
                "path": "05_DEG/deg.csv",
                "type": "csv",
                "md5": hashlib.md5(deg.read_bytes()).hexdigest(),
            }
        ],
    }
    (work_dir / "result_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    service = _build_report_service(tmp_path, monkeypatch)

    report = await _create(service, work_dir)

    assert report.status == "completed"
    assert report.completed_at is not None


@pytest.mark.unit
async def test_create_report_manifest_md5_mismatch_fails(tmp_path: Path, monkeypatch):
    """manifest 声明的 md5 与实际不一致 → failed，描述携带校验失败原因。"""
    work_dir = _make_work_dir(tmp_path)
    (work_dir / "Analysis_Report" / "index.html").write_text("<html>report</html>")
    deg = work_dir / "deg.csv"
    deg.write_text("gene,log2fc\nA,1.0\n")
    manifest = {
        "manifest_version": "1.0",
        "run": {"status": "completed"},
        "report": {"format": "html", "entry": "Analysis_Report/index.html"},
        "files": [{"name": "DEG", "path": "deg.csv", "type": "csv", "md5": "0" * 32}],
    }
    (work_dir / "result_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    service = _build_report_service(tmp_path, monkeypatch)

    report = await _create(service, work_dir)

    assert report.status == "failed"
    assert "产物校验失败" in report.description
    assert "md5" in report.description


@pytest.mark.unit
async def test_create_report_manifest_missing_declared_file_fails(tmp_path: Path, monkeypatch):
    work_dir = _make_work_dir(tmp_path)
    (work_dir / "Analysis_Report" / "index.html").write_text("<html>report</html>")
    manifest = {
        "manifest_version": "1.0",
        "run": {"status": "completed"},
        "files": [{"name": "DEG", "path": "not_exists.csv", "type": "csv"}],
    }
    (work_dir / "result_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    service = _build_report_service(tmp_path, monkeypatch)

    report = await _create(service, work_dir)

    assert report.status == "failed"
    assert "不存在" in report.description


@pytest.mark.unit
async def test_create_report_broken_manifest_falls_back_to_legacy(tmp_path: Path, monkeypatch):
    """manifest 解析失败 → 回退旧约定：index.html 存在且非空即 completed。"""
    work_dir = _make_work_dir(tmp_path)
    (work_dir / "Analysis_Report" / "index.html").write_text("<html>report</html>")
    (work_dir / "result_manifest.json").write_text("{not-json", encoding="utf-8")
    service = _build_report_service(tmp_path, monkeypatch)

    report = await _create(service, work_dir)

    assert report.status == "completed"


@pytest.mark.unit
async def test_create_report_empty_index_html_is_not_completed(tmp_path: Path, monkeypatch):
    """无 manifest 时旧约定收紧：index.html 存在但大小为零 → failed。"""
    work_dir = _make_work_dir(tmp_path)
    (work_dir / "Analysis_Report" / "index.html").write_text("")
    service = _build_report_service(tmp_path, monkeypatch)

    report = await _create(service, work_dir)

    assert report.status == "failed"
    assert report.completed_at is None
