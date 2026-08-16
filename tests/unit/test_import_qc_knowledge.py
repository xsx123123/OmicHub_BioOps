from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from rich.console import Console
from scripts import import_qc_knowledge
from scripts.import_qc_knowledge import (
    KNOWLEDGE_BASE_ID,
    QC_DIR,
    attachment_inventory,
    discover_markdown_files,
    document_id,
    render_summary,
    rewrite_links,
    searchable_asset_inventory,
    validate_sources,
)

from omichub.application.services.knowledge_asset_service import KnowledgeAssetService


def test_qc_source_lives_under_shared_knowledge_root() -> None:
    assert QC_DIR.parts[-3:] == ("docs", "knowledge", "qc")
    assert KNOWLEDGE_BASE_ID == "qc"


def test_qc_cli_logging_disables_sqlalchemy_echo(monkeypatch) -> None:
    engine = SimpleNamespace(echo=True)
    monkeypatch.setattr(import_qc_knowledge, "get_engine", lambda: engine)

    import_qc_knowledge.configure_cli_logging()

    assert engine.echo is False


def test_qc_summary_uses_readable_rich_table(monkeypatch) -> None:
    output = StringIO()
    monkeypatch.setattr(
        import_qc_knowledge,
        "console",
        Console(file=output, force_terminal=False, width=160),
    )

    render_summary(
        dry_run=False,
        markdown=63,
        added=2,
        updated=3,
        unchanged=58,
        attachments=240,
        searchable_assets=218,
        rewritten=90,
        missing=0,
    )

    rendered = output.getvalue()
    assert "QC 知识库同步完成" in rendered
    assert "可索引" in rendered
    assert "218" in rendered


def test_qc_primary_document_ids_are_stable() -> None:
    assert document_id(Path("README.md")) == "qc-resource-catalog"
    assert document_id(Path("Raw data QC.md")) == "qc-raw-data"
    assert document_id(Path("Quality control & preprocessing.md")) == "qc-preprocessing"
    assert document_id(Path("FastQC.md")) == "qc-fastqc"
    assert document_id(Path("fastp.md")) == "qc-fastp"
    assert document_id(Path("multiqc.md")) == "qc-multiqc"


def test_qc_import_discovers_markdown_and_attachments() -> None:
    markdown_files = discover_markdown_files()

    assert len(markdown_files) >= 63
    assert QC_DIR / "README.md" in markdown_files
    assert len(attachment_inventory()) > len(searchable_asset_inventory())
    assert len(searchable_asset_inventory()) >= 218


def test_qc_import_rewrites_relative_attachments(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    source_dir = docs_root / "knowledge" / "qc"
    source_dir.mkdir(parents=True)
    source_file = source_dir / "FastQC.md"
    attachment = source_dir / "report with spaces.pdf"
    attachment.write_bytes(b"pdf")
    content = '[report](<report with spaces.pdf> "reference") [remote](https://example.com)'

    rewritten, count, missing = rewrite_links(content, source_file, docs_root)

    assert "/docs-static/knowledge/qc/report%20with%20spaces.pdf" in rewritten
    assert "https://example.com" in rewritten
    assert count == 1
    assert missing == 0


def test_qc_import_does_not_rewrite_markdown_examples_in_code_fences(
    tmp_path: Path,
) -> None:
    docs_root = tmp_path / "docs"
    source_dir = docs_root / "knowledge" / "qc"
    source_dir.mkdir(parents=True)
    source_file = source_dir / "Markdown.md"
    content = "```markdown\n![Caption](elephant.png)\n```"

    rewritten, count, missing = rewrite_links(content, source_file, docs_root)

    assert rewritten == content
    assert count == 0
    assert missing == 0


def test_every_qc_pdf_and_image_is_attached_to_markdown() -> None:
    service = KnowledgeAssetService()
    covered: set[Path] = set()
    for markdown_file in discover_markdown_files():
        content = markdown_file.read_text(encoding="utf-8")
        covered.update(
            path
            for path, _label in service._referenced_assets(
                content,
                markdown_file.resolve(),
                include_unreferenced_assets=True,
            )
        )

    assert set(searchable_asset_inventory()) <= covered


def test_qc_source_validation_has_complete_asset_coverage() -> None:
    markdown_count, asset_count, missing_links, uncovered_assets = validate_sources()

    assert markdown_count >= 63
    assert asset_count >= 218
    assert missing_links == 0
    assert uncovered_assets == 0


def test_web_image_installs_chinese_ocr_runtime() -> None:
    dockerfile = (QC_DIR.parents[2] / "deploy" / "docker" / "Dockerfile").read_text(
        encoding="utf-8"
    )

    assert "tesseract-ocr" in dockerfile
    assert "tesseract-ocr-chi-sim" in dockerfile
