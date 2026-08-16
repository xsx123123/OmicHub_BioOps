from pathlib import Path

from scripts.import_rnaseq_knowledge import DOCUMENT_ID, SOURCE_FILE, rewrite_links


def test_rnaseq_document_id_is_stable() -> None:
    assert DOCUMENT_ID == "rnaseq-overview"


def test_rnaseq_source_lives_under_shared_knowledge_root() -> None:
    assert SOURCE_FILE.parts[-4:] == ("docs", "knowledge", "rna-seq", "RNA-seq.md")


def test_rnaseq_import_rewrites_existing_relative_attachments(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    source_dir = docs_root / "knowledge" / "rna-seq"
    source_dir.mkdir(parents=True)
    source_file = source_dir / "RNA-seq.md"
    attachment = source_dir / "paper.pdf"
    attachment.write_bytes(b"pdf")
    content = (
        '[paper](<paper.pdf> "reference") '
        '[legacy](<file/paper.pdf> "legacy") '
        'and [remote](https://example.com)'
    )

    from scripts import import_rnaseq_knowledge as importer

    original_docs_root = importer.DOCS_ROOT
    importer.DOCS_ROOT = docs_root
    try:
        rewritten, count, missing = rewrite_links(content, source_file)
    finally:
        importer.DOCS_ROOT = original_docs_root

    assert "/docs-static/knowledge/rna-seq/paper.pdf" in rewritten
    assert "https://example.com" in rewritten
    assert count == 2
    assert missing == 0
