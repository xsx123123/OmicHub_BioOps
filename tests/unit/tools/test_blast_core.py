import uuid
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from omichub.core.exceptions import NotFoundError, TaskExecutionError
from omichub.tools.blast.cache import build_result_cache_key
from omichub.tools.blast.core import (
    build_blast_command,
    build_docker_blast_command,
    convert_blast_archive,
    detect_sequence_type,
    ensure_fasta,
    infer_program,
    parse_blast_xml,
    parse_fasta,
)
from omichub.tools.blast.events import get_blast_event_channel
from omichub.tools.blast.schema import BlastDatabaseCreateRequest, BlastSubmitRequest
from omichub.tools.blast.service import (
    BlastService,
    _combine_upload_chunks,
    _copy_upload_chunk,
    _validate_upload_id,
)


@pytest.mark.parametrize(
    ("sequence", "expected"),
    [
        ("ATGCGTACGT", "nucl"),
        ("AUGCGUACGU", "nucl"),
        ("NNNNRYMKSW", "nucl"),
        ("MKWVTFISLLFLFSSAYSR", "prot"),
        ("ACDEFGHIKLMNPQRSTVWY", "prot"),
        ("ATG?CGT", "unknown"),
        ("ACD123", "unknown"),
        ("ATG", "unknown"),
    ],
)
def test_detect_sequence_type(sequence: str, expected: str) -> None:
    assert detect_sequence_type(sequence) == expected


@pytest.mark.parametrize(
    ("query_type", "db_type", "expected"),
    [
        ("nucl", "nucl", "blastn"),
        ("prot", "prot", "blastp"),
        ("nucl", "prot", "blastx"),
        ("prot", "nucl", "tblastn"),
    ],
)
def test_infer_program(query_type: str, db_type: str, expected: str) -> None:
    assert infer_program(query_type, db_type) == expected


def test_parse_and_ensure_fasta() -> None:
    fasta = ensure_fasta("ATGCGT", "query one")
    assert fasta == ">query one\nATGCGT"
    assert parse_fasta(fasta) == ("query", "ATGCGT")


def test_build_blast_command_includes_optional_parameters(tmp_path: Path) -> None:
    command = build_blast_command(
        "blastn",
        tmp_path / "query.fasta",
        "/db/reference",
        tmp_path / "result.xml",
        evalue=1e-10,
        max_target_seqs=25,
        word_size=11,
        gapopen=5,
        gapextend=2,
    )

    assert command[0] == "blastn"
    assert command[command.index("-outfmt") + 1] == "5"
    assert command[command.index("-word_size") + 1] == "11"
    assert command[command.index("-gapopen") + 1] == "5"
    assert command[command.index("-gapextend") + 1] == "2"


def test_build_docker_blast_command_supports_archive_output(tmp_path: Path) -> None:
    command = build_docker_blast_command(
        "blastn",
        tmp_path / "query.fasta",
        tmp_path / "db" / "reference",
        tmp_path / "result.asn",
        outfmt=11,
    )

    assert command[command.index("-outfmt") + 1] == "11"
    assert command[command.index("-out") + 1] == "/results/result.asn"


def test_convert_blast_archive_uses_requested_format(tmp_path: Path, monkeypatch) -> None:
    archive_path = tmp_path / "result.asn"
    output_path = tmp_path / "result.txt"
    captured = {}

    monkeypatch.setattr("omichub.tools.blast.core.shutil.which", lambda _: "/usr/bin/blast_formatter")

    def fake_run(command, timeout, cwd=None):
        captured["command"] = command
        captured["timeout"] = timeout
        return Mock(returncode=0)

    monkeypatch.setattr("omichub.tools.blast.core.run_command", fake_run)
    convert_blast_archive(archive_path, output_path, 0)

    assert captured["command"] == [
        "blast_formatter",
        "-archive",
        str(archive_path),
        "-out",
        str(output_path),
        "-outfmt",
        "0",
    ]
    assert captured["timeout"] == 300


def test_parse_blast_xml_extracts_hit_statistics(tmp_path: Path) -> None:
    xml_path = tmp_path / "result.xml"
    xml_path.write_text(
        """<?xml version="1.0"?>
<BlastOutput>
  <BlastOutput_iterations>
    <Iteration>
      <Iteration_query-ID>Query_1</Iteration_query-ID>
      <Iteration_query-def>example query</Iteration_query-def>
      <Iteration_query-len>12</Iteration_query-len>
      <Iteration_hits>
        <Hit>
          <Hit_id>subject-1</Hit_id>
          <Hit_def>Arabidopsis protein</Hit_def>
          <Hit_hsps>
            <Hsp>
              <Hsp_bit-score>42.5</Hsp_bit-score>
              <Hsp_score>95</Hsp_score>
              <Hsp_evalue>1e-20</Hsp_evalue>
              <Hsp_query-from>1</Hsp_query-from>
              <Hsp_query-to>12</Hsp_query-to>
              <Hsp_hit-from>4</Hsp_hit-from>
              <Hsp_hit-to>15</Hsp_hit-to>
              <Hsp_identity>10</Hsp_identity>
              <Hsp_gaps>1</Hsp_gaps>
              <Hsp_align-len>12</Hsp_align-len>
              <Hsp_qseq>ATGCGTACGTAA</Hsp_qseq>
              <Hsp_hseq>ATGCGTTCG-AA</Hsp_hseq>
              <Hsp_midline>|||||| || ||</Hsp_midline>
            </Hsp>
          </Hit_hsps>
        </Hit>
      </Iteration_hits>
    </Iteration>
  </BlastOutput_iterations>
</BlastOutput>
""",
        encoding="utf-8",
    )

    result = parse_blast_xml(xml_path)

    assert result["hit_count"] == 1
    assert result["query_id"] == "Query_1"
    assert result["query_len"] == 12
    assert result["top_hit_identity"] == pytest.approx(83.33)
    assert result["top_hit_evalue"] == pytest.approx(1e-20)
    hit = result["hits"][0]
    assert hit["subject_id"] == "Arabidopsis"
    assert hit["gap_opens"] == 1
    assert hit["mismatches"] == 2
    assert hit["hit_id"] == "Arabidopsis"
    assert hit["hit_def"] == "protein"
    assert hit["identity_percent"] == pytest.approx(83.33)
    assert hit["query_coverage"] == pytest.approx(100.0)
    assert hit["best_hsp"]["evalue"] == pytest.approx(1e-20)

    # 兼容旧版 DTO 列表仍可通过 hit_dtos 访问
    assert result["hit_dtos"][0].subject_id == "Arabidopsis"
    assert result["hit_dtos"][0].query_coverage == pytest.approx(100.0)


def test_parse_blast_xml_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(TaskExecutionError, match="结果文件不存在"):
        parse_blast_xml(tmp_path / "missing.xml")


def test_submit_request_enforces_parameter_bounds() -> None:
    with pytest.raises(ValueError):
        BlastSubmitRequest(db_id=str(uuid.uuid4()), evalue=0)
    with pytest.raises(ValueError):
        BlastSubmitRequest(db_id=str(uuid.uuid4()), max_target_seqs=101)
    with pytest.raises(ValueError):
        BlastSubmitRequest(db_id=str(uuid.uuid4()), word_size=1)


def test_database_request_rejects_unsafe_key() -> None:
    with pytest.raises(ValueError):
        BlastDatabaseCreateRequest(name="unsafe", db_key="../escape")


@pytest.mark.asyncio
async def test_get_task_scopes_query_to_current_user() -> None:
    result = Mock()
    result.scalar_one_or_none.return_value = None
    db = Mock()
    db.execute = AsyncMock(return_value=result)
    user_id = str(uuid.uuid4())

    with pytest.raises(NotFoundError):
        await BlastService().get_task(db, "task-id", user_id)

    statement = db.execute.await_args.args[0]
    assert "blast_tasks.user_id" in str(statement)


def test_result_cache_key_is_deterministic_and_versioned() -> None:
    params = {
        "db_id": str(uuid.uuid4()),
        "db_version": "v1:2026-07-15",
        "program": "blastn",
        "query_sequence": ">query\natgc atgc",
        "evalue": 1e-5,
        "max_target_seqs": 10,
        "word_size": 11,
        "gapopen": 5,
        "gapextend": 2,
    }
    first = build_result_cache_key(**params)
    second = build_result_cache_key(**{**params, "query_sequence": ">different-title\nATGCATGC"})
    changed_version = build_result_cache_key(**{**params, "db_version": "v2:2026-07-16"})

    assert first == second
    assert first.startswith("blast:result:")
    assert changed_version != first


def test_blast_event_channel_is_task_scoped() -> None:
    assert get_blast_event_channel("abc123") == "blast:task:abc123:events"


def test_database_request_validates_version_group() -> None:
    request = BlastDatabaseCreateRequest(
        name="Rice v2", db_key="rice_v2", version_group="rice_reference"
    )
    assert request.version_group == "rice_reference"
    with pytest.raises(ValueError):
        BlastDatabaseCreateRequest(name="Rice v2", db_key="rice_v2", version_group="../rice")


def test_chunk_upload_helpers_round_trip(tmp_path: Path) -> None:
    upload_dir = tmp_path / "upload"
    upload_dir.mkdir()
    first = upload_dir / "chunk-000000"
    second = upload_dir / "chunk-000001"
    assert _copy_upload_chunk(BytesIO(b">seq\nATGC"), first, 1024) == 9
    assert _copy_upload_chunk(BytesIO(b"ATGC\n"), second, 1024) == 5

    destination = upload_dir / "combined.fasta"
    assert _combine_upload_chunks(upload_dir, destination, 2) == 14
    assert destination.read_bytes() == b">seq\nATGCATGC\n"


def test_chunk_upload_rejects_oversized_chunk(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="上传分片超过"):
        _copy_upload_chunk(BytesIO(b"12345"), tmp_path / "chunk", 4)


def test_upload_id_validation_rejects_path_traversal() -> None:
    _validate_upload_id("a" * 32)
    with pytest.raises(Exception, match="无效的分片上传 ID"):
        _validate_upload_id("../escape")


@pytest.mark.asyncio
async def test_get_storage_stats_calculates_size_and_counts(tmp_path: Path, monkeypatch) -> None:
    """存储统计应正确汇总任务计数与结果目录大小。"""
    settings = Mock()
    settings.storage_path = str(tmp_path)
    settings.blast_results_dir = "blast/results"

    monkeypatch.setattr(
        "omichub.tools.blast.service.get_settings", lambda: settings
    )

    result_dir = tmp_path / "blast" / "results" / "user-1" / "task-1"
    result_dir.mkdir(parents=True)
    (result_dir / "result.xml").write_bytes(b"a" * (1024 * 1024))
    (result_dir / "result.txt").write_bytes(b"b" * (512 * 1024))

    db = Mock()
    db.scalar = AsyncMock(side_effect=[10, 7, 2])

    stats = await BlastService().get_storage_stats(db)

    assert stats["total_tasks"] == 10
    assert stats["completed_tasks"] == 7
    assert stats["cleaned_tasks"] == 2
    assert stats["storage_mb"] == pytest.approx(1.5, rel=1e-6)
    assert "blast/results" in stats["result_dir"]


@pytest.mark.asyncio
async def test_get_storage_stats_returns_zero_when_directory_missing(monkeypatch) -> None:
    """结果目录不存在时，存储统计应返回零值而非报错。"""
    settings = Mock()
    settings.storage_path = "/nonexistent/path"
    settings.blast_results_dir = "blast/results"

    monkeypatch.setattr(
        "omichub.tools.blast.service.get_settings", lambda: settings
    )

    db = Mock()
    db.scalar = AsyncMock(side_effect=[0, 0, 0])

    stats = await BlastService().get_storage_stats(db)

    assert stats["storage_mb"] == 0.0
    assert stats["total_tasks"] == 0
