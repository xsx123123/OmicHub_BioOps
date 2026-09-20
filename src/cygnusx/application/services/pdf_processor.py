"""OmiHub 统一 PDF 处理器。

主路径: pdf-inspector (结构化 Markdown)
降级路径: pypdf (纯文本，复刻现有行为)

使用方式::

    from cygnusx.application.services.pdf_processor import (
        PDFProcessor,
        CHAT_ATTACHMENT_CONFIG,
        KNOWLEDGE_BASE_CONFIG,
        WORKSPACE_MCP_CONFIG,
    )

    processor = PDFProcessor(config=CHAT_ATTACHMENT_CONFIG)
    result = await processor.process("/path/to/file.pdf")
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time

import anyio

from cygnusx.application.services.pdf_models import (
    CHAT_ATTACHMENT_CONFIG,
    PDFMetadata,
    PDFPage,
    PDFProcessResult,
    PDFSource,
    PDFType,
)
from cygnusx.infrastructure.pdf.exceptions import PDFInspectorError
from cygnusx.infrastructure.pdf.inspector_adapter import PDFInspectorAdapter
from cygnusx.infrastructure.pdf.pypdf_adapter import PyPDFAdapter

logger = logging.getLogger(__name__)


# ── 质量门控 ──────────────────────────────────────────────


class QualityGate:
    """PDF 解析质量门控。"""

    def __init__(self, config: dict) -> None:
        self.threshold = config.get("confidence_threshold", 0.7)
        self.max_file_size_mb = config.get("max_file_size_mb", 100)

    def pre_check(self, file_path: str) -> tuple[bool, str | None]:
        """前置检查。

        Returns:
            (passed: bool, reason: str|None)
        """
        if not os.path.exists(file_path):
            return False, "file_not_found"

        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if size_mb > self.max_file_size_mb:
            logger.warning(
                "PDF file size %.2f MB exceeds limit %d MB: %s",
                size_mb,
                self.max_file_size_mb,
                file_path,
            )
            return False, "file_size_exceeded"

        return True, None

    def check_inspector_result(self, result: dict) -> tuple[bool, str | None]:
        """检查 pdf-inspector 输出质量。

        Returns:
            (passed: bool, reason: str|None)
        """
        markdown = result.get("markdown", "")
        if not markdown or len(markdown.strip()) == 0:
            logger.warning("pdf-inspector returned empty output")
            return False, "empty_output"

        confidence = result.get("metadata", {}).get("confidence", 1.0)
        if confidence < self.threshold:
            logger.warning(
                "pdf-inspector confidence %.2f below threshold %.2f",
                confidence,
                self.threshold,
            )
            return False, "low_confidence"

        if result.get("metadata", {}).get("has_encoding_issues", False):
            logger.warning("pdf-inspector detected encoding issues")
            return False, "encoding_issues"

        total_pages = result.get("metadata", {}).get("total_pages", 1)
        ocr_pages = len(result.get("metadata", {}).get("pages_needing_ocr", []))
        if total_pages > 0 and ocr_pages / total_pages > 0.5:
            logger.warning(
                "pdf-inspector: %d/%d pages need OCR (ratio > 50%%)",
                ocr_pages,
                total_pages,
            )
            return False, "high_ocr_ratio"

        return True, None


# ── 输出标准化层 ──────────────────────────────────────────


class PDFOutputNormalizer:
    """将解析结果转换为场景需要的输出格式。"""

    def __init__(self, config: dict) -> None:
        self.config = config
        self.max_chars = config.get("max_chars", 50_000)
        self.output_format = config.get("output_format", "plaintext")
        self.page_marker = config.get("page_marker", "[第 {n} 页]")

    def normalize(
        self, result: dict, source: PDFSource
    ) -> PDFProcessResult:
        """标准化解析结果。"""
        pages = [
            PDFPage(
                page_number=p["page_number"],
                markdown=p.get("markdown", ""),
                text=p.get("text", ""),
                needs_ocr=p.get("needs_ocr", False),
                confidence=p.get("confidence", 1.0),
            )
            for p in result.get("pages", [])
        ]

        metadata = PDFMetadata(
            pdf_type=PDFType(
                result.get("metadata", {}).get("pdf_type", "unknown")
            ),
            total_pages=result.get("metadata", {}).get("total_pages", 0),
            confidence=result.get("metadata", {}).get("confidence", 1.0),
            has_encoding_issues=result.get("metadata", {}).get(
                "has_encoding_issues", False
            ),
            pages_needing_ocr=result.get("metadata", {}).get(
                "pages_needing_ocr", []
            ),
        )

        # 按场景格式化（先得到未截断内容）
        plaintext, _ = self._to_plaintext(result)
        if self.output_format == "plaintext":
            content = plaintext
        elif self.output_format == "markdown":
            content = result.get("markdown", "")
        elif self.output_format == "json":
            # JSON 先使用纯文本内容；序列化前再截断，保证合法 JSON
            content = plaintext
        else:
            content = result.get("markdown", "")

        # 字符截断（JSON 在序列化前截断内容）
        truncated = False
        if len(content) > self.max_chars:
            content = content[: self.max_chars]
            truncated = True

        # 截断后追加提示标记（纯文本/Markdown/JSON 内容均保留标记便于阅读）
        if truncated and self.output_format in ("plaintext", "markdown", "json"):
            last_page_number = self._last_page_number_in_content(content)
            marker = f"[已截断，仅覆盖前 {last_page_number} 页]"
            content = content + "\n\n" + marker

        # JSON 序列化放在截断之后，确保输出合法
        if self.output_format == "json":
            content = self._to_json(result, metadata, content)

        metadata.truncated = truncated

        return PDFProcessResult(
            success=True,
            content=content,
            pages=pages,
            metadata=metadata,
            source=source,
            raw_markdown=result.get("markdown"),
        )

    def _to_plaintext(self, result: dict) -> tuple[str, int]:
        """转换为带分页标记的纯文本（兼容现有格式）。

        Returns:
            (content, last_page_number)
        """
        parts: list[str] = []
        last_page_number = 0
        for page in result.get("pages", []):
            text = page.get("text", "").strip()
            if text:
                marker = self.page_marker.format(n=page["page_number"])
                parts.append(f"{marker}\n{text}")
                last_page_number = page["page_number"]
        return "\n\n".join(parts), last_page_number

    def _to_json(
        self, result: dict, metadata: PDFMetadata, plaintext: str
    ) -> str:
        """转换为 JSON 字符串（MCP 场景）。"""
        payload = {
            "content": plaintext,
            "pages": [
                {
                    "page_number": p["page_number"],
                    "text": p.get("text", ""),
                }
                for p in result.get("pages", [])
            ],
            "metadata": {
                "pdf_type": metadata.pdf_type.value,
                "total_pages": metadata.total_pages,
                "confidence": metadata.confidence,
            },
        }
        return json.dumps(payload, ensure_ascii=False)

    def _last_page_number_in_content(self, content: str) -> int:
        """从截断后的内容中解析最后包含的页码。"""
        import re

        # 匹配 [第 N 页] 或 [Page N]
        matches = re.findall(r"\[(?:第|Page)\s*(\d+)\s*页?\]", content)
        if matches:
            return int(matches[-1])
        return 0


# ── 统一处理器 ────────────────────────────────────────────


class PDFProcessor:
    """OmiHub 统一 PDF 处理器。

    主路径: pdf-inspector (结构化 Markdown)
    降级路径: pypdf (纯文本，复刻现有行为)

    灰度控制（环境变量）::

        PDF_INSPECTOR_ENABLED=true      # 启用 pdf-inspector 主路径
        PDF_INSPECTOR_ROLLOUT=100       # 100% 流量走主路径
    """

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or CHAT_ATTACHMENT_CONFIG
        self.gate = QualityGate(self.config)
        self.normalizer = PDFOutputNormalizer(self.config)

        self._inspector: PDFInspectorAdapter | None = None
        self._legacy: PyPDFAdapter | None = None

        # 灰度控制
        self.inspector_enabled = (
            os.getenv("PDF_INSPECTOR_ENABLED", "false").lower() == "true"
        )
        self.rollout_percent = int(
            os.getenv("PDF_INSPECTOR_ROLLOUT", "0")
        )

    @property
    def inspector(self) -> PDFInspectorAdapter:
        if self._inspector is None:
            self._inspector = PDFInspectorAdapter(self.config)
        return self._inspector

    @property
    def legacy(self) -> PyPDFAdapter:
        if self._legacy is None:
            self._legacy = PyPDFAdapter(self.config)
        return self._legacy

    def _should_try_inspector(self, file_path: str) -> bool:
        """基于灰度策略决定是否尝试 pdf-inspector。"""
        if not self.inspector_enabled:
            return False
        if self.rollout_percent >= 100:
            return True
        if self.rollout_percent <= 0:
            return False
        # 基于文件哈希的确定性分流（同一文件始终走同一路径）
        hash_val = int(
            hashlib.md5(file_path.encode()).hexdigest(), 16
        )
        return (hash_val % 100) < self.rollout_percent

    def process_sync(self, file_path: str) -> PDFProcessResult:
        """同步处理入口。"""
        start_time = time.time()

        # ① 前置检查
        passed, reason = self.gate.pre_check(file_path)
        if not passed:
            logger.warning("PDF pre-check failed: %s", reason)
            return self._fallback_sync(file_path, reason)

        # ② 尝试主路径
        if self._should_try_inspector(file_path):
            try:
                inspector_result = self.inspector.extract(file_path)

                # ③ 质量门控
                passed, reason = self.gate.check_inspector_result(
                    inspector_result
                )
                if passed:
                    result = self.normalizer.normalize(
                        inspector_result, PDFSource.INSPECTOR
                    )
                    result.metadata.processing_time_ms = (
                        time.time() - start_time
                    ) * 1000
                    logger.info(
                        "PDF processed via pdf-inspector: %s "
                        "(pages=%d, confidence=%.2f, time=%.0fms)",
                        file_path,
                        result.metadata.total_pages,
                        result.metadata.confidence,
                        result.metadata.processing_time_ms,
                    )
                    return result
                else:
                    logger.warning(
                        "PDF inspector quality gate failed: %s", reason
                    )
                    return self._fallback_sync(file_path, reason)

            except PDFInspectorError as exc:
                logger.warning("PDF inspector failed: %s", exc)
                return self._fallback_sync(
                    file_path, f"inspector_exception: {exc}"
                )

        # 灰度未命中，直接降级
        return self._fallback_sync(file_path, "rollout_skip")

    async def process(self, file_path: str) -> PDFProcessResult:
        """异步处理入口（包装同步方法到线程池）。"""
        return await anyio.to_thread.run_sync(
            self.process_sync, file_path
        )

    def _fallback_sync(
        self, file_path: str, reason: str
    ) -> PDFProcessResult:
        """降级到 pypdf 现有处理流程。"""
        logger.info("PDF fallback to pypdf: %s (reason=%s)", file_path, reason)
        try:
            legacy_result = self.legacy.extract(file_path)
            result = self.normalizer.normalize(
                legacy_result, PDFSource.LEGACY
            )
            result.fallback_reason = reason
            return result
        except Exception as exc:
            logger.error("PDF legacy fallback also failed: %s", exc)
            return PDFProcessResult(
                success=False,
                content="",
                pages=[],
                metadata=PDFMetadata(
                    pdf_type=PDFType.UNKNOWN,
                    total_pages=0,
                    confidence=0.0,
                    has_encoding_issues=False,
                ),
                source=PDFSource.LEGACY,
                fallback_reason=f"legacy_also_failed: {reason} -> {exc}",
            )
