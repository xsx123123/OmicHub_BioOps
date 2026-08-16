"""Controlled Session workspace reference safety and manifest tests."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from omichub.application.services import workspace_references
from omichub.application.services.workspace_references import (
    _build_directory_manifest,
    parse_workspace_resource_ref,
)
from omichub.core.exceptions import BusinessError


@pytest.mark.unit
def test_parse_workspace_resource_ref_only_accepts_controlled_schemes() -> None:
    directory = parse_workspace_resource_ref("directory://00000000-0000-0000-0000-000000000001")
    file_ref = parse_workspace_resource_ref("file://00000000-0000-0000-0000-000000000002")
    upload = parse_workspace_resource_ref("upload://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")

    assert directory.kind == "directory"
    assert directory.resource_ref == "directory://00000000-0000-0000-0000-000000000001"
    assert file_ref.kind == "file"
    assert upload.kind == "upload"

    for invalid in ("@project/raw", "directory://../secret", "/data/platform", "file://not-a-uuid"):
        with pytest.raises(BusinessError):
            parse_workspace_resource_ref(invalid)


@pytest.mark.unit
def test_directory_manifest_enforces_limits_and_skips_symlinks(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "raw-data"
    source.mkdir()
    (source / "a.txt").write_text("a", encoding="utf-8")
    (source / "b.txt").write_text("bb", encoding="utf-8")
    (source / "nested").mkdir()
    (source / "nested" / "c.txt").write_text("ccc", encoding="utf-8")
    (source / "escape").symlink_to(tmp_path / "outside")
    monkeypatch.setattr(
        workspace_references,
        "get_settings",
        lambda: SimpleNamespace(
            workspace_directory_max_files=2,
            workspace_directory_max_total_bytes=1024,
            workspace_directory_manifest_page_size=2,
            workspace_directory_scan_timeout_seconds=5.0,
        ),
    )

    manifest = _build_directory_manifest(
        source,
        resource_ref="directory://00000000-0000-0000-0000-000000000001",
        sandbox_path="/workspace/input/raw-data/",
        recursive=True,
    )

    assert manifest.status == "file_limit"
    assert manifest.truncated is True
    assert manifest.next_cursor is not None
    assert manifest.file_count == 2
    assert all("escape" not in str(entry["path"]) for entry in manifest.entries)
    assert manifest.summary()["sandbox_path"] == "/workspace/input/raw-data/"

@pytest.mark.unit
@pytest.mark.asyncio
async def test_workspace_list_returns_a_bounded_page(monkeypatch) -> None:
    from omichub.application.services import studio_tools

    async def list_files(*_args, **_kwargs):
        return {
            "path": "input/raw-data",
            "entries": [{"name": f"file-{index}.txt", "type": "file"} for index in range(5)],
        }

    monkeypatch.setattr(studio_tools.studio_sandbox_manager, "list_files", list_files)
    result = await studio_tools._workspace_list(
        {"path": "input/raw-data", "offset": 2, "limit": 2}, "session-1", None, "user-1"
    )

    payload = result["result"]["llm_payload"]
    assert [item["name"] for item in payload["entries"]] == ["file-2.txt", "file-3.txt"]
    assert payload["total"] == 5
    assert payload["next_offset"] == 4

@pytest.mark.unit
def test_overdrive_context_includes_frozen_directory_manifest() -> None:
    from omichub.infrastructure.celery_app.tasks.overdrive import _overdrive_workspace_context

    run = SimpleNamespace(
        session_id="session-1",
        run_id="overdrive:run-1",
        plan={
            "workspace_resources": [
                {
                    "resource_ref": "directory://00000000-0000-0000-0000-000000000001",
                    "resource_type": "directory",
                    "permission": "read",
                    "sandbox_path": "/workspace/input/raw-data/",
                    "manifest_summary": {"file_count": 12, "total_size_bytes": 4096},
                }
            ]
        },
        artifact_index=[],
    )

    context = _overdrive_workspace_context(run, {"task_id": "independent-qc", "depends_on": []})

    assert "directory://00000000-0000-0000-0000-000000000001" in context
    assert "/workspace/input/raw-data/" in context
    assert "12 个文件" in context
