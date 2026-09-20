"""pypdf 降级路径适配器。

复刻现有三处实现的行为，确保降级时输出与旧代码完全一致。
"""

from __future__ import annotations

import logging

import pypdf

from .exceptions import PDFLegacyError

logger = logging.getLogger(__name__)


class PyPDFAdapter:
    """pypdf 降级路径适配器。"""

    def __init__(self, config: dict) -> None:
        self.config = config
        self.page_marker = config.get("page_marker", "[第 {n} 页]")

    def extract(self, file_path: str) -> dict:
        """使用 pypdf 提取 PDF 内容。

        复刻现有三处实现的核心逻辑：
        - 逐页 extract_text()
        - 空页跳过
        - 带分页标记拼接

        使用 ``pypdf.PdfReader`` 属性访问而非 ``from pypdf import PdfReader``，
        便于测试时通过 monkeypatch 替换 ``pypdf.PdfReader``。
        """
        try:
            reader = pypdf.PdfReader(file_path)
            texts: list[str] = []
            pages_data: list[dict] = []

            for i, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                stripped = text.strip()
                if stripped:
                    marker = self.page_marker.format(n=i)
                    texts.append(f"{marker}\n{stripped}")
                    pages_data.append(
                        {
                            "page_number": i,
                            "markdown": stripped,
                            "text": stripped,
                            "needs_ocr": False,
                            "confidence": 1.0,
                        }
                    )

            full_text = "\n\n".join(texts)

            return {
                "success": True,
                "markdown": full_text,
                "pages": pages_data,
                "metadata": {
                    "pdf_type": "unknown",
                    "confidence": 1.0,
                    "has_encoding_issues": False,
                    "pages_needing_ocr": [],
                    "total_pages": len(reader.pages),
                },
            }

        except Exception as exc:
            raise PDFLegacyError(f"pypdf failed: {exc}") from exc
