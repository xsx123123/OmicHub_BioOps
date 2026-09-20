"""PDFProcessor 单元测试。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cygnusx.application.services.pdf_models import (
    CHAT_ATTACHMENT_CONFIG,
    KNOWLEDGE_BASE_CONFIG,
    WORKSPACE_MCP_CONFIG,
    PDFSource,
    PDFType,
)
from cygnusx.application.services.pdf_processor import PDFProcessor


@pytest.fixture
def sample_pdf() -> Path:
    """创建一个简单的测试 PDF（使用 pypdf 生成）。"""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        with open(tmp.name, "wb") as f:
            writer.write(f)
        return Path(tmp.name)


class TestPDFProcessor:
    """PDFProcessor 测试。"""

    @pytest.mark.asyncio
    async def test_chat_attachment_config(self, sample_pdf: Path) -> None:
        """聊天附件场景：降级路径应正常工作。"""
        processor = PDFProcessor(config=CHAT_ATTACHMENT_CONFIG)
        result = await processor.process(str(sample_pdf))

        assert result.success is True
        assert result.source == PDFSource.LEGACY  # Phase 1 走降级
        assert result.fallback_reason is not None  # 因为 inspector 占位
        assert result.metadata.total_pages >= 0

    @pytest.mark.asyncio
    async def test_knowledge_base_config(self, sample_pdf: Path) -> None:
        """知识库场景：降级路径应正常工作。"""
        processor = PDFProcessor(config=KNOWLEDGE_BASE_CONFIG)
        result = await processor.process(str(sample_pdf))

        assert result.success is True
        assert result.source == PDFSource.LEGACY
        assert result.metadata.pdf_type == PDFType.UNKNOWN  # pypdf 无法分类

    @pytest.mark.asyncio
    async def test_workspace_mcp_config(self, sample_pdf: Path) -> None:
        """MCP 工作区场景：应返回 JSON 格式内容。"""
        processor = PDFProcessor(config=WORKSPACE_MCP_CONFIG)
        result = await processor.process(str(sample_pdf))

        assert result.success is True
        assert result.source == PDFSource.LEGACY
        # JSON 格式验证
        import json

        parsed = json.loads(result.content)
        assert "content" in parsed
        assert "pages" in parsed
        assert "metadata" in parsed

    @pytest.mark.asyncio
    async def test_file_size_limit(self, sample_pdf: Path, monkeypatch) -> None:
        """文件大小超限应触发降级。"""
        config = {**CHAT_ATTACHMENT_CONFIG, "max_file_size_mb": 0}
        processor = PDFProcessor(config=config)
        result = await processor.process(str(sample_pdf))

        assert result.source == PDFSource.LEGACY
        assert "file_size_exceeded" in (result.fallback_reason or "")

    @pytest.mark.asyncio
    async def test_nonexistent_file(self) -> None:
        """不存在的文件应优雅失败。"""
        processor = PDFProcessor(config=CHAT_ATTACHMENT_CONFIG)
        result = await processor.process("/nonexistent/file.pdf")

        assert result.success is False
        assert "file_not_found" in (result.fallback_reason or "")

    @pytest.mark.asyncio
    async def test_truncate(self, tmp_path: Path, monkeypatch) -> None:
        """字符截断应正确标记。"""

        pdf_path = tmp_path / "long.pdf"
        pdf_path.write_bytes(b"%PDF fake")

        class FakePage:
            def extract_text(self) -> str:
                return "x" * 100

        class FakeReader:
            def __init__(self, _path: str) -> None:
                self.pages = [FakePage(), FakePage()]

        monkeypatch.setattr("pypdf.PdfReader", FakeReader)

        config = {**CHAT_ATTACHMENT_CONFIG, "max_chars": 10}
        processor = PDFProcessor(config=config)
        result = await processor.process(str(pdf_path))

        assert result.metadata.truncated is True
        assert "[第 2 页]" in result.content or "[已截断" in result.content
