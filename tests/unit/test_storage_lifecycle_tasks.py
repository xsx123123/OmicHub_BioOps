"""存储生命周期任务 — 冷数据归档路径与覆盖保护测试。"""

from pathlib import Path

import pytest

from cygnusx.infrastructure.celery_app.tasks.storage import (
    _archive_destination,
    _archive_file,
)

_UID = "11111111-1111-1111-1111-111111111111"


@pytest.mark.unit
def test_archive_file_preserves_relative_directory_structure(tmp_path: Path) -> None:
    src = tmp_path / "users" / _UID / "workspace" / "proj-a" / "output" / "report.xlsx"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"v1")

    assert _archive_file(tmp_path, _UID, f"users/{_UID}/workspace/proj-a/output/report.xlsx")

    dst = tmp_path / "archive" / _UID / "workspace" / "proj-a" / "output" / "report.xlsx"
    assert dst.read_bytes() == b"v1"
    assert not src.exists()


@pytest.mark.unit
def test_archive_file_same_name_from_different_dirs_does_not_overwrite(
    tmp_path: Path,
) -> None:
    """回归：不同目录下的同名文件先后归档，不得互相覆盖。"""
    for proj, content in (("proj-a", b"A"), ("proj-b", b"B")):
        src = tmp_path / "users" / _UID / "workspace" / proj / "output" / "result.csv"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(content)
        assert _archive_file(
            tmp_path, _UID, f"users/{_UID}/workspace/{proj}/output/result.csv"
        )

    base = tmp_path / "archive" / _UID / "workspace"
    assert (base / "proj-a" / "output" / "result.csv").read_bytes() == b"A"
    assert (base / "proj-b" / "output" / "result.csv").read_bytes() == b"B"


@pytest.mark.unit
def test_archive_file_same_path_twice_gets_sequence_suffix(tmp_path: Path) -> None:
    """同一路径被重建后二次归档：旧归档保留，新文件追加序号。"""
    rel = f"users/{_UID}/workspace/proj-a/output/report.xlsx"
    for content in (b"v1", b"v2", b"v3"):
        src = tmp_path / rel
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(content)
        assert _archive_file(tmp_path, _UID, rel)

    base = tmp_path / "archive" / _UID / "workspace" / "proj-a" / "output"
    assert (base / "report.xlsx").read_bytes() == b"v1"
    assert (base / "report (2).xlsx").read_bytes() == b"v2"
    assert (base / "report (3).xlsx").read_bytes() == b"v3"


@pytest.mark.unit
def test_archive_file_keeps_non_user_paths_as_is(tmp_path: Path) -> None:
    src = tmp_path / "studio" / "sess-1" / "output" / "fig.png"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"png")

    assert _archive_file(tmp_path, _UID, "studio/sess-1/output/fig.png")
    assert (
        tmp_path / "archive" / _UID / "studio" / "sess-1" / "output" / "fig.png"
    ).read_bytes() == b"png"


@pytest.mark.unit
def test_archive_file_missing_source_is_noop(tmp_path: Path) -> None:
    assert not _archive_file(tmp_path, _UID, f"users/{_UID}/gone.txt")
    assert not (tmp_path / "archive").exists()


@pytest.mark.unit
def test_archive_destination_ignores_mismatched_user_prefix(tmp_path: Path) -> None:
    # storage_path 里的用户 id 与归档归属不一致时保留原路径，避免误 strip
    archive_dir = tmp_path / "archive" / _UID
    dst = _archive_destination(archive_dir, _UID, "users/other-user/workspace/a.txt")
    assert dst == archive_dir / "users" / "other-user" / "workspace" / "a.txt"
