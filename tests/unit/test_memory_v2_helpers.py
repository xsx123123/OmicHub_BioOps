"""Focused tests for v2 memory helpers without database dependencies."""

import asyncio
from pathlib import Path

import pytest

from cygnusx.application.services import studio_context_service, studio_tools
from cygnusx.infrastructure.celery_app.tasks.memory import _extract_json_array


def test_fact_extraction_parser_accepts_only_json_arrays() -> None:
    response = {"choices": [{"message": {"content": '[{"content":"用户偏好 DESeq2"}]'}}]}

    assert _extract_json_array(response) == [{"content": "用户偏好 DESeq2"}]
    assert _extract_json_array({"choices": [{"message": {"content": "not json"}}]}) == []
    assert _extract_json_array({"choices": [{"message": {"content": "{}"}}]}) == []


def test_workspace_remember_writes_note_and_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        studio_tools.studio_sandbox_manager,
        "workspace_dir",
        lambda _session_id: tmp_path,
    )
    monkeypatch.setattr(
        studio_context_service.studio_sandbox_manager,
        "workspace_dir",
        lambda _session_id: tmp_path,
    )

    result = asyncio.run(
        studio_tools._workspace_remember(
            {"title": "RNA normalization", "summary": "Use DESeq2", "content": "Keep the VST workflow."},
            "session",
        )
    )

    assert result["success"] is True
    index = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "RNA normalization" in index
    note = next((tmp_path / ".memory").glob("*.md"))
    assert "Keep the VST workflow." in note.read_text(encoding="utf-8")
    assert studio_context_service.load_workspace_memory_index("session") == index


def test_workspace_remember_preserves_markup_and_avoids_same_day_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        studio_tools.studio_sandbox_manager,
        "workspace_dir",
        lambda _session_id: tmp_path,
    )

    first = asyncio.run(
        studio_tools._workspace_remember(
            {"title": "HTML", "summary": "Keep markup", "content": "<script>if (a < b) return;"},
            "session",
        )
    )
    second = asyncio.run(
        studio_tools._workspace_remember(
            {"title": "HTML", "summary": "Keep the second note", "content": "<b>second</b>"},
            "session",
        )
    )

    assert first["success"] is True
    assert second["success"] is True
    notes = sorted((tmp_path / ".memory").glob("*.md"))
    assert len(notes) == 2
    note_contents = [note.read_text(encoding="utf-8") for note in notes]
    assert any("<script>if (a < b) return;" in content for content in note_contents)
    assert any("<b>second</b>" in content for content in note_contents)
    assert len([line for line in (tmp_path / "MEMORY.md").read_text(encoding="utf-8").splitlines() if line.startswith("- [")]) == 2
