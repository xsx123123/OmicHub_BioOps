from pathlib import Path
from types import SimpleNamespace

import pytest

from cygnusx.application.services.chat.runtime_support import ChatRuntimeSupport
from cygnusx.application.services.chat_service import ChatService


@pytest.mark.asyncio
async def test_read_attachment_text_extracts_local_pdf(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF fake")
    # 方法体内部按 ChatRuntimeSupport 显式引用解析，补丁必须打在定义类上
    monkeypatch.setattr(
        ChatRuntimeSupport,
        "_resolve_attachment_path",
        staticmethod(lambda _url: str(pdf_path)),
    )
    async def fake_extract_pdf_text(source: str) -> str:
        return f"parsed:{Path(source).name}"

    monkeypatch.setattr(
        ChatRuntimeSupport,
        "_extract_pdf_text",
        staticmethod(fake_extract_pdf_text),
    )

    text = await ChatService._read_attachment_text(
        {
            "name": "paper.pdf",
            "mime_type": "application/pdf",
            "url": "/api/v1/files/chat-upload/user/paper.pdf",
        }
    )

    assert text == "parsed:paper.pdf"


@pytest.mark.asyncio
async def test_extract_pdf_text_delegates_to_pdf_processor(monkeypatch, tmp_path: Path) -> None:
    """验证 _extract_pdf_text 已迁移至 PDFProcessor。"""
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF fake")

    async def fake_process(self, file_path: str):
        return SimpleNamespace(
            content=f"processed:{Path(file_path).name}",
            metadata=SimpleNamespace(total_pages=2),
        )

    monkeypatch.setattr(
        "cygnusx.application.services.pdf_processor.PDFProcessor.process",
        fake_process,
    )

    text = await ChatService._extract_pdf_text(str(pdf_path))

    assert text == "processed:paper.pdf"


def _make_docx_bytes(paragraphs: list[str]) -> bytes:
    """构造最小可解析的 docx（OOXML zip），正文为若干段落。"""
    import io
    import zipfile

    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><w:document><w:body>{body}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_extract_docx_text_reads_paragraphs_and_entities(tmp_path: Path) -> None:
    from cygnusx.application.services.chat.runtime_support import extract_docx_text

    raw = _make_docx_bytes([">sp1", "ATGCGT", "A&amp;B 混合"])
    docx_path = tmp_path / "MDH2序列.docx"
    docx_path.write_bytes(raw)

    assert extract_docx_text(str(docx_path)) == ">sp1\nATGCGT\nA&B 混合"
    # bytes 形态（远程附件场景）同样可解析
    assert extract_docx_text(raw) == ">sp1\nATGCGT\nA&B 混合"
    # 非 zip 内容返回空串而不是抛异常
    assert extract_docx_text(b"not a zip") == ""


@pytest.mark.asyncio
async def test_read_attachment_text_extracts_local_docx(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docx_path = tmp_path / "MDH2序列.docx"
    docx_path.write_bytes(_make_docx_bytes([">MDH2_human", "MABC..."]))
    monkeypatch.setattr(
        ChatRuntimeSupport,
        "_resolve_attachment_path",
        staticmethod(lambda _url: str(docx_path)),
    )

    text = await ChatService._read_attachment_text(
        {
            "name": "MDH2序列.docx",
            "mime_type": (
                "application/vnd.openxmlformats-officedocument"
                ".wordprocessingml.document"
            ),
            "url": "/api/v1/files/chat-upload/user/MDH2序列.docx",
        }
    )

    assert text == ">MDH2_human\nMABC..."
