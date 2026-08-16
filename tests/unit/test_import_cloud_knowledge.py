from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from rich.console import Console
from scripts import import_cloud_knowledge
from scripts.import_cloud_knowledge import (
    CLOUD_DIR,
    KNOWLEDGE_BASE_ID,
    discover_markdown_files,
    document_id,
    render_summary,
    searchable_asset_inventory,
    validate_sources,
)


def test_cloud_knowledge_sources_are_complete() -> None:
    markdown, assets, missing, uncovered = validate_sources()

    assert CLOUD_DIR.parts[-3:] == ("docs", "knowledge", "cloud")
    assert KNOWLEDGE_BASE_ID == "cloud"
    assert markdown >= 23
    assert assets >= 126
    assert missing == 0
    assert uncovered == 0


def test_cloud_document_ids_are_stable() -> None:
    assert document_id(Path("README.md")) == "cloud-resource-catalog"
    assert document_id(Path("Cloud.md")) == "cloud-overview"
    assert len(discover_markdown_files()) >= 23
    assert len(searchable_asset_inventory()) >= 126


def test_cloud_cli_logging_disables_sqlalchemy_echo(monkeypatch) -> None:
    engine = SimpleNamespace(echo=True)
    monkeypatch.setattr(import_cloud_knowledge, "get_engine", lambda: engine)

    import_cloud_knowledge.configure_cli_logging()

    assert engine.echo is False


def test_cloud_summary_uses_readable_rich_table(monkeypatch) -> None:
    output = StringIO()
    monkeypatch.setattr(
        import_cloud_knowledge,
        "console",
        Console(file=output, force_terminal=False, width=160),
    )

    render_summary(
        dry_run=True,
        markdown=23,
        added=1,
        updated=2,
        unchanged=20,
        searchable_assets=126,
        rewritten=40,
        missing=0,
    )

    rendered = output.getvalue()
    assert "Cloud 知识库预览" in rendered
    assert "可索引附件" in rendered
    assert "126" in rendered
