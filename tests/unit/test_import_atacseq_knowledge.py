from pathlib import Path

from scripts.import_atacseq_knowledge import (
    ATACSEQ_DIR,
    KNOWLEDGE_BASE_ID,
    attachment_inventory,
    discover_markdown_files,
    document_id,
    rewrite_links,
)


def test_atacseq_source_lives_under_shared_knowledge_root() -> None:
    assert ATACSEQ_DIR.parts[-3:] == ("docs", "knowledge", "atac-seq")
    assert KNOWLEDGE_BASE_ID == "atacseq"


def test_atacseq_primary_document_ids_are_stable() -> None:
    assert document_id(Path("ATAC-seq.md")) == "atacseq-overview"
    assert document_id(Path("Chromatin Accessibility.md")) == "atacseq-chromatin-accessibility"
    assert document_id(Path("README.md")) == "atacseq-resource-catalog"


def test_atacseq_import_discovers_all_markdown_and_attachments() -> None:
    assert {path.name for path in discover_markdown_files()} == {
        "ATAC-seq.md",
        "Chromatin Accessibility.md",
        "README.md",
    }
    assert len(attachment_inventory()) == 36


def test_atacseq_import_rewrites_relative_attachments(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    source_dir = docs_root / "knowledge" / "atac-seq"
    source_dir.mkdir(parents=True)
    source_file = source_dir / "ATAC-seq.md"
    attachment = source_dir / "paper with spaces.pdf"
    attachment.write_bytes(b"pdf")
    content = '[paper](<paper with spaces.pdf> "reference") [remote](https://example.com)'

    rewritten, count, missing = rewrite_links(content, source_file, docs_root)

    assert "/docs-static/knowledge/atac-seq/paper%20with%20spaces.pdf" in rewritten
    assert "https://example.com" in rewritten
    assert count == 1
    assert missing == 0


def test_every_atacseq_attachment_is_linked_from_markdown() -> None:
    rewritten_targets: set[str] = set()
    for markdown_file in discover_markdown_files():
        rewritten, _, missing = rewrite_links(
            markdown_file.read_text(encoding="utf-8"), markdown_file
        )
        assert missing == 0
        for attachment in attachment_inventory():
            relative_url = "/docs-static/" + "/".join(
                part.replace(" ", "%20")
                for part in attachment.relative_to(ATACSEQ_DIR.parents[1]).parts
            )
            if relative_url in rewritten:
                rewritten_targets.add(relative_url)

    assert len(rewritten_targets) == len(attachment_inventory())
