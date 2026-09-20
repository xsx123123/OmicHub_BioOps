"""PDF 处理数据模型与场景配置常量。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PDFType(StrEnum):
    """PDF 分类类型。"""

    TEXT_BASED = "TextBased"
    SCANNED = "Scanned"
    MIXED = "Mixed"
    IMAGE_ONLY = "ImageOnly"
    UNKNOWN = "unknown"


class PDFSource(StrEnum):
    """解析来源。"""

    INSPECTOR = "pdf-inspector"
    LEGACY = "pypdf"


class PDFOutputFormat(StrEnum):
    """输出格式类型。"""

    PLAINTEXT = "plaintext"
    MARKDOWN = "markdown"
    JSON = "json"


@dataclass
class PDFPage:
    """单页解析结果。"""

    page_number: int
    markdown: str
    text: str
    needs_ocr: bool = False
    confidence: float = 1.0


@dataclass
class PDFMetadata:
    """PDF 解析元数据。"""

    pdf_type: PDFType
    total_pages: int
    confidence: float
    has_encoding_issues: bool
    pages_needing_ocr: list[int] = field(default_factory=list)
    processing_time_ms: float | None = None
    truncated: bool = False


@dataclass
class PDFProcessResult:
    """PDF 处理统一返回结果。"""

    success: bool
    content: str
    pages: list[PDFPage]
    metadata: PDFMetadata
    source: PDFSource
    fallback_reason: str | None = None
    raw_markdown: str | None = None


# ── 场景化配置 ──────────────────────────────────────────

CHAT_ATTACHMENT_CONFIG: dict = {
    "max_chars": 50_000,
    "output_format": "plaintext",
    "page_marker": "[第 {n} 页]",
    "enable_ocr": False,
    "confidence_threshold": 0.7,
    "max_file_size_mb": 50,
    "include_metadata": False,
}

KNOWLEDGE_BASE_CONFIG: dict = {
    "max_chars": 40_000,
    "output_format": "markdown",
    "page_marker": "[第 {n} 页]",
    "enable_ocr": True,
    "confidence_threshold": 0.6,
    "max_file_size_mb": 100,
    "include_metadata": True,
}

WORKSPACE_MCP_CONFIG: dict = {
    "max_chars": 50_000,
    "output_format": "json",
    "page_marker": "[Page {n}]",
    "enable_ocr": False,
    "confidence_threshold": 0.7,
    "max_file_size_mb": 50,
    "include_metadata": True,
}
