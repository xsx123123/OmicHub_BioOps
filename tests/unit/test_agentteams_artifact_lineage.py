"""产物血缘（F1）测试：version 行写入/递增、依赖 DAG 查询、缺 source_refs 拒绝语义、checksum 篡改检测。"""

from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from cygnusx.application.services.agent_consultation_service import AgentConsultationService
from cygnusx.application.services.agentteams_artifact_lineage_service import (
    AgentTeamsArtifactLineageService,
    normalize_source_refs,
)
from cygnusx.application.services.agentteams_service import AgentTeamsService
from cygnusx.infrastructure.database.models.chat import (
    CaseArtifactDependencyModel,
    CaseArtifactVersionModel,
)


class _Result:
    """模拟 AsyncSession.execute 返回值的最小表面。"""

    def __init__(self, *, scalar=None, one_or_none=None, scalars=(), rows=()) -> None:
        self._scalar = scalar
        self._one_or_none = one_or_none
        self._scalars = scalars
        self._rows = rows

    def scalar(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._one_or_none

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))

    def all(self):
        return list(self._rows)


def _db_with_results(results: list[_Result]):
    db = SimpleNamespace()
    db.execute = AsyncMock(side_effect=results)
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def test_normalize_source_refs_accepts_strings_and_dicts() -> None:
    refs = normalize_source_refs(
        [
            "projects/p1/input.fastq",
            {"artifact_id": "s3://bucket/case/a.bam", "relation": "derived_from"},
            {"artifact_id": "x", "relation": "bogus"},
            {"artifact_id": " "},
            42,
        ]
    )
    assert refs == [
        {"artifact_id": "projects/p1/input.fastq", "relation": "input_to"},
        {"artifact_id": "s3://bucket/case/a.bam", "relation": "derived_from"},
        {"artifact_id": "x", "relation": "input_to"},
    ]
    assert normalize_source_refs(None) == []
    assert normalize_source_refs("not-a-list") == []


def test_register_version_increments_version_no_per_artifact() -> None:
    asyncio.run(_test_register_version_increments())


async def _test_register_version_increments() -> None:
    db = _db_with_results([_Result(scalar=None), _Result(scalar=1)])
    service = AgentTeamsArtifactLineageService(db)

    first = await service.register_version(
        case_id="case-1",
        artifact_id="exec-01/report.md",
        checksum_sha256="a" * 64,
        size_bytes=10,
        content_type="text/markdown",
        storage_uri="s3://agentteams/cases/case-1/exec-01/report.md",
        producing_event_id="event-1",
        work_item_id="exec-01",
        environment_snapshot={"agent_id": "agent-viz"},
    )
    second = await service.register_version(
        case_id="case-1",
        artifact_id="exec-01/report.md",
        checksum_sha256="b" * 64,
        size_bytes=12,
        content_type="text/markdown",
        storage_uri="s3://agentteams/cases/case-1/exec-01/report.md",
    )

    assert first.version_no == 1
    assert first.producing_event_id == "event-1"
    assert second.version_no == 2
    assert db.add.call_count == 2


def test_register_dependencies_dedupes_existing_edges() -> None:
    asyncio.run(_test_register_dependencies_dedupes())


async def _test_register_dependencies_dedupes() -> None:
    db = _db_with_results([_Result(one_or_none=None), _Result(one_or_none=uuid4())])
    service = AgentTeamsArtifactLineageService(db)

    edges = await service.register_dependencies(
        case_id="case-1",
        downstream_artifact_id="exec-02/plot.svg",
        source_refs=[
            {"artifact_id": "exec-01/report.md", "relation": "input_to"},
            {"artifact_id": "exec-01/counts.tsv", "relation": "input_to"},
        ],
    )

    assert len(edges) == 1
    assert edges[0].upstream_artifact_id == "exec-01/report.md"
    assert edges[0].relation == "input_to"


def test_case_lineage_expands_upstream_one_level() -> None:
    asyncio.run(_test_case_lineage())


async def _test_case_lineage() -> None:
    version = CaseArtifactVersionModel(
        case_id="case-1",
        artifact_id="exec-02/plot.svg",
        version_no=1,
        checksum_sha256="c" * 64,
        size_bytes=5,
        content_type="image/svg+xml",
        storage_uri="users/u1/workspace/agentteams/case-1/exec-02/plot.svg",
        producing_event_id="event-9",
        work_item_id="exec-02",
        environment_snapshot={},
    )
    edge = CaseArtifactDependencyModel(
        case_id="case-1",
        downstream_artifact_id="exec-02/plot.svg",
        upstream_artifact_id="exec-01/counts.tsv",
        relation="input_to",
    )
    db = _db_with_results([_Result(scalars=[version]), _Result(scalars=[edge])])
    lineage = await AgentTeamsArtifactLineageService(db).case_lineage("case-1")

    assert lineage["versions"][0]["version_id"] == str(version.id)
    assert lineage["versions"][0]["upstream"] == [
        {"artifact_id": "exec-01/counts.tsv", "relation": "input_to"}
    ]
    assert lineage["dependencies"][0]["downstream_artifact_id"] == "exec-02/plot.svg"


def test_affected_by_walks_dag_downstream_closure() -> None:
    asyncio.run(_test_affected_by())


async def _test_affected_by() -> None:
    rows = [
        ("exec-02/plot.svg", "exec-01/counts.tsv"),
        ("exec-03/report.pdf", "exec-02/plot.svg"),
        ("exec-02/other.svg", "exec-01/counts.tsv"),
    ]
    db = _db_with_results([_Result(rows=rows), _Result(rows=[])])
    service = AgentTeamsArtifactLineageService(db)

    affected = await service.affected_by("case-1", "exec-01/counts.tsv")
    assert affected == ["exec-02/other.svg", "exec-02/plot.svg", "exec-03/report.pdf"]
    assert await service.affected_by("case-1", "exec-03/report.pdf") == []


def test_verify_checksum_detects_tampering() -> None:
    row = CaseArtifactVersionModel(
        case_id="case-1",
        artifact_id="exec-01/report.md",
        version_no=1,
        checksum_sha256=hashlib.sha256(b"original").hexdigest(),
        size_bytes=8,
        content_type="text/markdown",
        storage_uri="p",
        environment_snapshot={},
    )
    assert AgentTeamsArtifactLineageService.verify_checksum(row, b"original") is True
    assert AgentTeamsArtifactLineageService.verify_checksum(row, b"tampered") is False


def test_workspace_registration_writes_version_row_and_dependency() -> None:
    asyncio.run(_test_workspace_registration())


async def _test_workspace_registration() -> None:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        workdir = tmp_path / "workdir"
        workdir.mkdir()
        (workdir / "plot.svg").write_text("<svg/>", encoding="utf-8")
        storage_root = tmp_path / "storage"

        class Factory:
            def user_root(self, user_id: str):
                return storage_root / "users" / user_id

            def relative_to_root(self, path):
                return path.relative_to(storage_root).as_posix()

        class Repository:
            def __init__(self, _db) -> None:
                pass

            async def save(self, file):
                return file

        added: list[object] = []
        db = SimpleNamespace(
            execute=AsyncMock(side_effect=[_Result(scalar=None), _Result(one_or_none=None)]),
            add=MagicMock(side_effect=added.append),
            flush=AsyncMock(),
        )

        import cygnusx.application.services.agent_consultation_service as module

        original_factory = module.get_path_factory
        original_repo = module.FileRepositoryImpl
        module.get_path_factory = lambda: Factory()
        module.FileRepositoryImpl = Repository
        try:
            service = AgentConsultationService(db)
            artifacts, errors = await service._register_workspace_artifacts(
                str(uuid4()),
                "case-1",
                "exec-01",
                workdir,
                causation_event_id="event-42",
                source_refs=[{"artifact_id": "projects/p1/counts.tsv", "relation": "input_to"}],
                execution_summary="plot from counts",
                agent_id="agent-viz",
                capability="workspace_execution",
            )
        finally:
            module.get_path_factory = original_factory
            module.FileRepositoryImpl = original_repo

        assert errors == []
        assert len(artifacts) == 1
        versions = [row for row in added if isinstance(row, CaseArtifactVersionModel)]
        deps = [row for row in added if isinstance(row, CaseArtifactDependencyModel)]
        assert len(versions) == 1
        version = versions[0]
        assert version.artifact_id == "exec-01/plot.svg"
        assert version.version_no == 1
        assert version.producing_event_id == "event-42"
        assert version.checksum_sha256 == hashlib.sha256(b"<svg/>").hexdigest()
        assert version.environment_snapshot["agent_id"] == "agent-viz"
        assert version.environment_snapshot["execution_summary"] == "plot from counts"
        assert artifacts[0]["version_id"] == str(version.id)
        assert len(deps) == 1
        assert deps[0].upstream_artifact_id == "projects/p1/counts.tsv"


def test_lineage_report_lines_render_versions_and_upstream() -> None:
    lineage = {
        "versions": [
            {
                "version_id": "v-1",
                "artifact_id": "exec-01/plot.svg",
                "version_no": 2,
                "checksum_sha256": "d" * 64,
                "producing_event_id": "event-1",
                "upstream": [{"artifact_id": "exec-00/counts.tsv", "relation": "input_to"}],
            }
        ],
        "dependencies": [],
    }
    lines = AgentTeamsService._lineage_report_lines(lineage, "")
    text = "\n".join(lines)
    assert "## 血缘清单" in text
    assert "version_id: `v-1`" in text
    assert "v2" in text
    assert "exec-00/counts.tsv" in text

    empty = AgentTeamsService._lineage_report_lines({"versions": []}, "")
    assert any("无平台登记" in line for line in empty)
    degraded = AgentTeamsService._lineage_report_lines({"versions": []}, "血缘清单不可用：DBError")
    assert degraded == ["## 血缘清单", "血缘清单不可用：DBError"]


def test_verify_case_checksums_compares_latest_versions() -> None:
    asyncio.run(_test_verify_case_checksums())


async def _test_verify_case_checksums() -> None:
    def row(artifact_id: str, version_no: int, checksum: str) -> CaseArtifactVersionModel:
        return CaseArtifactVersionModel(
            case_id="case-1",
            artifact_id=artifact_id,
            version_no=version_no,
            checksum_sha256=checksum,
            size_bytes=1,
            content_type="",
            storage_uri=f"uri:{artifact_id}",
            environment_snapshot={},
        )

    # DB 按 (artifact_id, version_no desc) 返回：每个产物最新版本在前
    rows = [
        row("exec-01/a.md", 2, hashlib.sha256(b"good").hexdigest()),
        row("exec-01/a.md", 1, hashlib.sha256(b"old").hexdigest()),
        row("exec-02/b.md", 1, hashlib.sha256(b"registered").hexdigest()),
        row("exec-03/c.md", 1, hashlib.sha256(b"gone").hexdigest()),
    ]
    db = _db_with_results([_Result(scalars=rows)])
    service = AgentTeamsArtifactLineageService(db)
    contents = {
        "uri:exec-01/a.md": b"good",
        "uri:exec-02/b.md": b"tampered",
        "uri:exec-03/c.md": None,
    }

    async def resolver(uri: str):
        return contents[uri]

    results = await service.verify_case_checksums("case-1", resolver)
    by_artifact = {item["artifact_id"]: item for item in results}

    assert set(by_artifact) == {"exec-01/a.md", "exec-02/b.md", "exec-03/c.md"}
    # 只比对每个产物的最新版本（v2），且与登记值一致
    assert by_artifact["exec-01/a.md"]["version_no"] == 2
    assert by_artifact["exec-01/a.md"]["status"] == "verified"
    # 内容被篡改 → mismatch（不静默吞）
    assert by_artifact["exec-02/b.md"]["status"] == "mismatch"
    assert "篡改" in by_artifact["exec-02/b.md"]["reason"]
    # 内容无法解析 → unverified 而非静默跳过
    assert by_artifact["exec-03/c.md"]["status"] == "unverified"


def test_checksum_report_line_summarizes_statuses() -> None:
    items = [
        {"artifact_id": "a", "status": "verified"},
        {"artifact_id": "b", "status": "mismatch"},
        {"artifact_id": "c", "status": "unverified"},
    ]
    line = AgentTeamsService._checksum_report_line(items)
    assert "1 一致" in line
    assert "1 不一致" in line
    assert "1 未比对" in line
    assert "`b`" in line
    assert "未做 checksum 比对" in AgentTeamsService._checksum_report_line([])
