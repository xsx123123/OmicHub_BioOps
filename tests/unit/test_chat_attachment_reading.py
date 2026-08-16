from pathlib import Path
from types import SimpleNamespace

import pytest

from omichub.application.services.chat_service import ChatService


@pytest.mark.asyncio
async def test_read_attachment_text_extracts_local_pdf(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF fake")
    monkeypatch.setattr(ChatService, "_resolve_attachment_path", staticmethod(lambda _url: str(pdf_path)))
    monkeypatch.setattr(ChatService, "_extract_pdf_text", staticmethod(lambda source: f"parsed:{Path(source).name}"))

    text = await ChatService._read_attachment_text(
        {
            "name": "paper.pdf",
            "mime_type": "application/pdf",
            "url": "/api/v1/files/chat-upload/user/paper.pdf",
        }
    )

    assert text == "parsed:paper.pdf"


def test_extract_pdf_text_preserves_page_boundaries(monkeypatch) -> None:
    pages = [
        SimpleNamespace(extract_text=lambda: "第一页内容"),
        SimpleNamespace(extract_text=lambda: "第二页内容"),
    ]
    fake_pypdf = SimpleNamespace(PdfReader=lambda _source: SimpleNamespace(pages=pages))
    monkeypatch.setitem(__import__("sys").modules, "pypdf", fake_pypdf)

    text = ChatService._extract_pdf_text(b"pdf")

    assert text == "[第 1 页]\n第一页内容\n\n[第 2 页]\n第二页内容"
