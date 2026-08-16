"""Knowledge-base PDF/image asset extraction contracts."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from omichub.application.services.knowledge_asset_service import KnowledgeAssetService


def test_asset_enrichment_indexes_referenced_and_sibling_assets(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "rna-seq" / "RNA-seq.md"
    source.parent.mkdir()
    image_path = source.parent / "figure.png"
    Image.new("RGB", (32, 16), "white").save(image_path)
    orphan_path = source.parent / "orphan.png"
    Image.new("RGB", (8, 8), "black").save(orphan_path)
    pdf_path = source.parent / "paper.pdf"
    pdf_path.write_bytes(b"placeholder")
    source.write_text("# RNA-seq\n\n![表达矩阵](figure.png)\n\n[论文](paper.pdf)", encoding="utf-8")

    class FakePage:
        def __init__(self, number: int) -> None:
            self.number = number

        def extract_text(self) -> str:
            return f"PDF evidence page {self.number}"

    class FakeReader:
        def __init__(self, _path: str) -> None:
            self.pages = [FakePage(1), FakePage(2)]

    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=FakeReader))

    enriched, report = KnowledgeAssetService().enrich_markdown(
        source.read_text(encoding="utf-8"), source_path=source
    )

    assert report.discovered == 3
    assert report.indexed == 3
    assert "附件PDF：paper.pdf" in enriched
    assert "PDF evidence page 1" in enriched
    assert "附件图片：figure.png" in enriched
    assert "图像说明：表达矩阵" in enriched
    assert "附件图片：orphan.png" in enriched


def test_asset_resolver_supports_static_docs_urls_and_rejects_escape(tmp_path: Path) -> None:
    source = tmp_path / "repo" / "docs" / "knowledge" / "rna-seq" / "RNA-seq.md"
    source.parent.mkdir(parents=True)
    asset = source.parent / "paper.pdf"
    asset.write_bytes(b"pdf")
    shared_asset = source.parent.parent / "shared.png"
    Image.new("RGB", (4, 4), "white").save(shared_asset)
    outside = tmp_path / "repo" / "secret.pdf"
    outside.write_bytes(b"secret")

    assert (
        KnowledgeAssetService._resolve_local_asset(
            "/docs-static/knowledge/rna-seq/paper.pdf", source
        )
        == asset.resolve()
    )
    assert (
        KnowledgeAssetService._resolve_local_asset("../shared.png", source)
        == shared_asset.resolve()
    )
    assert KnowledgeAssetService._resolve_local_asset("../../secret.pdf", source) is None


def test_asset_enrichment_extracts_docx_and_pptx(tmp_path: Path) -> None:
    source = tmp_path / "cloud" / "Cloud.md"
    source.parent.mkdir()
    docx = source.parent / "runbook.docx"
    pptx = source.parent / "architecture.pptx"
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="urn:w"><w:body><w:p><w:r><w:t>备份与恢复</w:t></w:r></w:p></w:body></w:document>',
        )
    with zipfile.ZipFile(pptx, "w") as archive:
        archive.writestr(
            "ppt/slides/slide1.xml",
            '<p:sld xmlns:p="urn:p" xmlns:a="urn:a"><a:t>NAS 缓存架构</a:t></p:sld>',
        )
    source.write_text("[运行手册](runbook.docx)\n[架构](architecture.pptx)", encoding="utf-8")

    enriched, report = KnowledgeAssetService().enrich_markdown(
        source.read_text(encoding="utf-8"), source_path=source
    )

    assert report.indexed == 2
    assert "附件DOCX：runbook.docx" in enriched
    assert "备份与恢复" in enriched
    assert "附件PPTX：architecture.pptx" in enriched
    assert "NAS 缓存架构" in enriched
