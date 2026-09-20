"""项目分析归档服务单元测试（AGENTS.md / run README / environment.json）。"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from cygnusx.application.services import project_archive_service
from cygnusx.application.services.project_archive_service import (
    ArchivedFile,
    ProjectInfo,
    append_analysis_entry,
    archive_overdrive_delivery,
    archive_run,
    archive_studio_run,
    collect_environment,
    md5_stream,
    render_environment_markdown,
    render_project_agents_md,
    sha256_stream,
)
from cygnusx.infrastructure.config.storage_config import StorageConfig
from cygnusx.infrastructure.storage import LocalStorageBackend
from cygnusx.infrastructure.storage.path_factory import StoragePathFactory


@pytest.fixture
def storage_env(tmp_path: Path):
    storage = tmp_path / "storage"
    factory = StoragePathFactory(StorageConfig(data_root=str(storage), users_subdir="users"))
    backend = LocalStorageBackend(path_factory=factory)
    return storage, factory, backend


def _fake_runtime_config(profile: Any) -> Any:
    return SimpleNamespace(profile_for_image=lambda image: ("analysis-core", profile))


# ===== collect_environment / render_environment_markdown =====


@pytest.mark.unit
def test_collect_environment_stable_fields_without_image():
    env = collect_environment(flow_id="studio", flow_name="OmicStudio")
    assert env["schema_version"] == 1
    assert env["captured_at"]
    assert env["platform"]["name"]
    assert "version" in env["platform"] and "git_sha" in env["platform"]
    assert env["python"]["version"]
    assert env["runtime"]["image"] == ""
    assert env["runtime"]["software"] == {}
    assert env["flow"] == {"id": "studio", "name": "OmicStudio", "version": ""}


@pytest.mark.unit
def test_collect_environment_resolves_registered_image(monkeypatch):
    profile = SimpleNamespace(
        languages={"python": "3.12"},
        software={"samtools": "1.21", "fastp": "0.24"},
        resources=SimpleNamespace(cpu=4, memory="8g", pids=512),
    )
    monkeypatch.setattr(
        project_archive_service, "get_runtime_images", lambda: _fake_runtime_config(profile)
    )
    env = collect_environment(image="cygnusx-runtime:analysis-core")
    runtime = env["runtime"]
    assert runtime["image"] == "cygnusx-runtime:analysis-core"
    assert runtime["profile"] == "analysis-core"
    assert runtime["software"] == {"samtools": "1.21", "fastp": "0.24"}
    assert runtime["resources"] == {"cpu": 4, "memory": "8g", "pids": 512}


@pytest.mark.unit
def test_collect_environment_registry_failure_degrades(monkeypatch):
    def _broken():
        raise RuntimeError("注册表缺失")

    monkeypatch.setattr(project_archive_service, "get_runtime_images", _broken)
    env = collect_environment(image="cygnusx-runtime:analysis-core")
    assert env["runtime"]["image"] == "cygnusx-runtime:analysis-core"
    assert env["runtime"]["software"] == {}


@pytest.mark.unit
def test_render_environment_markdown_sections():
    env = collect_environment(flow_id="overdrive", flow_name="超频协作", flow_version="v2")
    env["runtime"].update(
        {"image": "img:tag", "profile": "analysis-core", "software": {"samtools": "1.21"}}
    )
    content = "\n".join(render_environment_markdown(env))
    assert "## 软件与版本" in content
    assert "## 分析环境" in content
    assert "img:tag" in content
    assert "| samtools | 1.21 |" in content
    assert "流程版本: v2" in content
    assert "environment.json" in content


# ===== AGENTS.md =====


@pytest.mark.unit
def test_render_project_agents_md_initial_content():
    project = ProjectInfo(
        name="TP53 项目", description="示例", customer="客户A", created_at="2026-09-04T00:00:00"
    )
    content = render_project_agents_md(project)
    assert "# TP53 项目" in content
    assert "- 客户: 客户A" in content
    assert "- 创建时间: 2026-09-04T00:00:00" in content
    assert "## 分析记录" in content
    assert f"projects/{project.slug}/" in content


@pytest.mark.unit
def test_append_analysis_entry_idempotent_by_run_name():
    content = render_project_agents_md(ProjectInfo(name="P"))
    updated, appended = append_analysis_entry(
        content,
        run_name="studio-20260904-120000",
        timestamp="2026-09-04T12:00:00",
        analysis_type="OmicStudio 产物登记",
        status="completed",
        summary="登记 de.csv",
    )
    assert appended
    again, appended_again = append_analysis_entry(
        updated,
        run_name="studio-20260904-120000",
        timestamp="2026-09-04T12:00:01",
        analysis_type="OmicStudio 产物登记",
        status="completed",
        summary="登记 de.csv",
    )
    assert not appended_again
    assert again == updated
    assert again.count("runs/studio-20260904-120000") == 1


@pytest.mark.unit
def test_append_analysis_entry_adds_missing_heading():
    updated, appended = append_analysis_entry(
        "# 外部写入的项目说明\n",
        run_name="overdrive-20260904-120000",
        timestamp="2026-09-04T12:00:00",
        analysis_type="超频协作",
        status="completed",
        summary="多行\n摘要|含管道",
    )
    assert appended
    assert "## 分析记录" in updated
    assert "多行 摘要\\|含管道" in updated


# ===== archive_run（run 级文档） =====


@pytest.mark.unit
async def test_archive_run_writes_readme_environment_and_agents(storage_env):
    storage, factory, backend = storage_env
    uid = str(uuid.uuid4())
    run_dir = factory.create_project_run_dir(uid, "TP53 项目", "studio")
    artifact = run_dir / "output" / "de.csv"
    artifact.write_bytes(b"gene,log2fc\nA,1.2\n")
    expected_md5 = hashlib.md5(b"gene,log2fc\nA,1.2\n").hexdigest()
    expected_sha256 = hashlib.sha256(b"gene,log2fc\nA,1.2\n").hexdigest()

    project = ProjectInfo(name="TP53 项目", customer="客户A")
    env = collect_environment(flow_id="studio", flow_name="OmicStudio")
    environment = await archive_run(
        user_id=uid,
        project=project,
        run_dir=run_dir,
        analysis_type="OmicStudio 产物登记",
        status="completed",
        summary="登记 de.csv",
        environment=env,
        artifacts=[
            ArchivedFile(
                name="de.csv",
                relative_path="output/de.csv",
                size=artifact.stat().st_size,
                md5=md5_stream(artifact),
                sha256=sha256_stream(artifact),
            )
        ],
        factory=factory,
        backend=backend,
    )

    readme = (run_dir / "README.md").read_text(encoding="utf-8")
    assert "- 项目: TP53 项目" in readme
    assert "- 客户: 客户A" in readme
    assert "- 分析类型: OmicStudio 产物登记" in readme
    assert "## 最终结果" in readme and "output/de.csv" in readme and expected_md5 in readme
    # MD5 保留兼容 + 新增 sha256 列并存
    assert "| 文件 | 大小(bytes) | MD5 | SHA-256 |" in readme
    assert expected_sha256 in readme
    assert "## 代码与脚本" in readme
    assert "## 软件与版本" in readme and "## 分析环境" in readme

    snapshot = json.loads((run_dir / "environment.json").read_text(encoding="utf-8"))
    assert snapshot["schema_version"] == 1
    assert snapshot["flow"]["id"] == "studio"
    assert snapshot["run"]["directory"].endswith(f"runs/{run_dir.name}")
    assert snapshot["run"]["analysis_type"] == "OmicStudio 产物登记"
    assert snapshot["artifacts"][0]["md5"] == expected_md5
    assert snapshot["artifacts"][0]["sha256"] == expected_sha256
    assert environment["run"]["status"] == "completed"

    # 产物 manifest 旁落：逐文件 path/size/sha256 实测对账记录
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"] == [
        {"path": "output/de.csv", "size": artifact.stat().st_size, "sha256": expected_sha256}
    ]

    agents = (factory.project_dir(uid, project.slug) / "AGENTS.md").read_text(encoding="utf-8")
    assert "## 分析记录" in agents
    assert f"runs/{run_dir.name}" in agents

    # 幂等：同一 run 重复归档不产生重复条目
    await archive_run(
        user_id=uid,
        project=project,
        run_dir=run_dir,
        analysis_type="OmicStudio 产物登记",
        summary="登记 de.csv",
        factory=factory,
        backend=backend,
    )
    agents_again = (factory.project_dir(uid, project.slug) / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    assert agents_again.count(f"runs/{run_dir.name}") == 1


@pytest.mark.unit
async def test_archive_run_rejects_run_dir_outside_project(storage_env):
    _, factory, backend = storage_env
    uid = str(uuid.uuid4())
    outsider = factory.tasks_dir(uid) / "task-1"
    outsider.mkdir(parents=True)
    with pytest.raises(ValueError, match="项目目录"):
        await archive_run(
            user_id=uid,
            project=ProjectInfo(name="TP53 项目"),
            run_dir=outsider,
            analysis_type="OmicStudio 产物登记",
            factory=factory,
            backend=backend,
        )


@pytest.mark.unit
async def test_archive_run_scans_code_files(storage_env):
    _, factory, backend = storage_env
    uid = str(uuid.uuid4())
    run_dir = factory.create_project_run_dir(uid, "P", "overdrive")
    (run_dir / "work" / "analysis.py").write_text("print(1)\n", encoding="utf-8")
    await archive_run(
        user_id=uid,
        project=ProjectInfo(name="P"),
        run_dir=run_dir,
        analysis_type="超频协作",
        factory=factory,
        backend=backend,
    )
    readme = (run_dir / "README.md").read_text(encoding="utf-8")
    assert "work/analysis.py" in readme


# ===== archive_studio_run =====


@pytest.mark.unit
async def test_archive_studio_run_generates_documents(storage_env):
    _, factory, backend = storage_env
    uid = str(uuid.uuid4())
    run_dir = factory.create_project_run_dir(uid, "我的项目", "studio")
    (run_dir / "output" / "a.png").write_bytes(b"img")
    session = SimpleNamespace(title="我的项目", sandbox_meta={"image": ""})
    report = SimpleNamespace(title="图 v1", status="completed", description="")
    artifact = SimpleNamespace(name="a.png", size=3)

    await archive_studio_run(
        user_id=uid,
        session=session,
        run_dir=run_dir,
        report=report,
        artifact=artifact,
        factory=factory,
        backend=backend,
        db=None,
    )

    readme = (run_dir / "README.md").read_text(encoding="utf-8")
    assert "OmicStudio 产物登记" in readme
    assert "output/a.png" in readme
    # MD5 与 sha256 并存，且 sha256 为落盘文件实测值
    assert hashlib.md5(b"img").hexdigest() in readme
    assert hashlib.sha256(b"img").hexdigest() in readme
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"] == [
        {"path": "output/a.png", "size": 3, "sha256": hashlib.sha256(b"img").hexdigest()}
    ]
    agents = (factory.project_dir(uid, "我的项目") / "AGENTS.md").read_text(encoding="utf-8")
    assert "图 v1" in agents
    assert (run_dir / "environment.json").is_file()


# ===== archive_overdrive_delivery =====


class _FakeDb:
    def __init__(self, session: Any = None, project: Any = None) -> None:
        self._session = session
        self._project = project

    async def scalar(self, _stmt: Any) -> Any:
        return self._session

    async def get(self, _model: Any, _pk: Any) -> Any:
        return self._project


def _make_overdrive_run(user_id: str, session_id: str) -> Any:
    return SimpleNamespace(
        run_id="overdrive:test",
        session_id=session_id,
        user_id=user_id,
        status="COMPLETED",
        plan={
            "version": 2,
            "hash": "sha256:abcdef123456",
            "summary": {"title": "TP53 单细胞分析", "summary": "完成聚类与注释"},
        },
    )


@pytest.mark.unit
async def test_archive_overdrive_delivery_skips_without_project_id(storage_env):
    storage, factory, backend = storage_env
    uid = str(uuid.uuid4())
    session = SimpleNamespace(session_id="sess-1", title="T", project_id=None, sandbox_meta={})
    run = _make_overdrive_run(uid, "sess-1")

    result = await archive_overdrive_delivery(
        _FakeDb(session=session), run, delivery_paths=["output/overdrive/x/README.md"],
        factory=factory, backend=backend,
    )

    assert result is None
    assert not factory.projects_dir(uid).exists() or not any(
        factory.projects_dir(uid).iterdir()
    )


@pytest.mark.unit
async def test_archive_overdrive_delivery_copies_deliverables(storage_env):
    storage, factory, backend = storage_env
    uid = str(uuid.uuid4())
    project_id = str(uuid.uuid4())
    project = SimpleNamespace(
        user_id=uuid.UUID(uid),
        name="TP53 项目",
        slug="TP53_项目",
        description="desc",
        created_at=None,
        customer="客户A",
    )
    session = SimpleNamespace(
        session_id="sess-1",
        title="TP53 项目",
        project_id=project_id,
        sandbox_meta={"image": ""},
    )
    run = _make_overdrive_run(uid, "sess-1")
    await backend.write("output/overdrive/sess-1/overdrive:test/delivery/final-report.md", b"# report")
    await backend.write("output/overdrive/sess-1/overdrive:test/delivery/artifacts.zip", b"zip")
    await backend.write("output/overdrive/sess-1/overdrive:test/delivery/README.md", b"readme")

    run_dir = await archive_overdrive_delivery(
        _FakeDb(session=session, project=project),
        run,
        delivery_paths=[
            "output/overdrive/sess-1/overdrive:test/delivery/final-report.md",
            "output/overdrive/sess-1/overdrive:test/delivery/artifacts.zip",
            "output/overdrive/sess-1/overdrive:test/delivery/README.md",
        ],
        factory=factory,
        backend=backend,
    )

    assert run_dir is not None
    assert run_dir.parent.parent.name == "TP53_项目"
    assert (run_dir / "output" / "final-report.md").read_bytes() == b"# report"
    assert (run_dir / "output" / "artifacts.zip").read_bytes() == b"zip"
    readme = (run_dir / "README.md").read_text(encoding="utf-8")
    assert "- 项目: TP53 项目" in readme and "- 客户: 客户A" in readme
    assert "- 分析类型: 超频协作" in readme
    assert "- 流程版本: v2 (hash sha256:a)" in readme
    assert "final-report.md" in readme and "artifacts.zip" in readme
    snapshot = json.loads((run_dir / "environment.json").read_text(encoding="utf-8"))
    assert snapshot["flow"]["version"] == "v2 (hash sha256:a)"
    assert {a["name"] for a in snapshot["artifacts"]} == {
        "final-report.md",
        "artifacts.zip",
        "README.md",
    }
    agents = (factory.project_dir(uid, "TP53_项目") / "AGENTS.md").read_text(encoding="utf-8")
    assert "## 分析记录" in agents and f"runs/{run_dir.name}" in agents


@pytest.mark.unit
async def test_archive_overdrive_delivery_falls_back_when_project_record_missing(storage_env):
    _, factory, backend = storage_env
    uid = str(uuid.uuid4())
    session = SimpleNamespace(
        session_id="sess-1",
        title="兜底项目名",
        project_id="not-a-uuid",
        sandbox_meta={},
    )
    run = _make_overdrive_run(uid, "sess-1")
    await backend.write("output/overdrive/sess-1/overdrive:test/delivery/README.md", b"readme")

    run_dir = await archive_overdrive_delivery(
        _FakeDb(session=session, project=None),
        run,
        delivery_paths=["output/overdrive/sess-1/overdrive:test/delivery/README.md"],
        planning_only=True,
        factory=factory,
        backend=backend,
    )

    assert run_dir is not None
    readme = (run_dir / "README.md").read_text(encoding="utf-8")
    assert "- 项目: 兜底项目名" in readme
    assert "- 客户: 未填写" in readme
    assert "超频协作(方案规划)" in readme


@pytest.mark.unit
async def test_archive_overdrive_delivery_survives_missing_artifact(storage_env):
    _, factory, backend = storage_env
    uid = str(uuid.uuid4())
    session = SimpleNamespace(
        session_id="sess-1", title="T", project_id=str(uuid.uuid4()), sandbox_meta={}
    )
    run = _make_overdrive_run(uid, "sess-1")

    run_dir = await archive_overdrive_delivery(
        _FakeDb(session=session, project=None),
        run,
        delivery_paths=["output/overdrive/sess-1/overdrive:test/delivery/missing.md"],
        factory=factory,
        backend=backend,
    )

    assert run_dir is not None
    assert (run_dir / "README.md").is_file()
    snapshot = json.loads((run_dir / "environment.json").read_text(encoding="utf-8"))
    assert snapshot["artifacts"] == []
