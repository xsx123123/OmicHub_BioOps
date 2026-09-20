# OmiHub PDF 处理流程优化指南（Kimi Code 版）
> **目标**: 一步到位，将三处独立的 pypdf 实现替换为 `PDFProcessor` + `pdf-inspector` 主路径 / `pypdf` 降级路径  
> **范围**: `src/cygnusx`  
> **基于**: `pdf_inspection_report_2026-08-22.md`

---

## 1. 执行摘要

### 1.1 当前问题

| 问题 | 影响 | 解决方式 |
|------|------|---------|
| 三处独立 pypdf 实现 | 重复代码、维护困难、行为不一致 | 统一为 `PDFProcessor` |
| 无结构化输出 | 表格变乱码、多栏串行、阅读顺序错乱 | pdf-inspector 主路径 |
| 扫描件无 OCR 降级 | 扫描 PDF 返回空文本 | 质量门控 → 降级路径 |
| 分页标记不一致 | `[第 N 页]` vs `[Page N]` | `PDFOutputNormalizer` 统一 |
| 无文件大小检查 | 大文件可能导致内存问题 | 前置检查 + 配置限制 |

### 1.2 变更范围

- **新建**: 6 个文件（模型、处理器、适配器、异常、包 init）
- **修改**: 3 个现有文件（chat_service、knowledge_asset_service、mcp presets）
- **删除**: 0 个文件（保留 pypdf 作为降级路径）
- **依赖**: +1（`pdf-inspector`），保留 `pypdf`

---

## 2. 目标架构

```
用户上传 PDF
    ↓
┌─────────────────────────────────────────┐
│  ChatService / KnowledgeAssetService   │
│  / MCP workspace_read_file             │
└─────────────┬───────────────────────────┘
              │ 统一调用
              ▼
┌─────────────────────────────────────────┐
│         PDFProcessor.process()          │
│  ┌─────────────────────────────────┐    │
│  │  主路径: pdf-inspector          │    │
│  │  • detect_pdf() → 分类/置信度   │    │
│  │  • process_pdf() → Markdown   │    │
│  └─────────────────────────────────┘    │
│              ↓ 失败/质量不达标            │
│  ┌─────────────────────────────────┐    │
│  │  降级路径: pypdf (现有行为)      │    │
│  │  • PdfReader.extract_text()     │    │
│  └─────────────────────────────────┘    │
└─────────────┬───────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│      PDFOutputNormalizer                │
│  • 按场景格式化 (纯文本/Markdown/JSON)   │
│  • 统一分页标记                         │
│  • 字符截断                             │
│  • 元数据注入                           │
└─────────────┬───────────────────────────┘
              ↓
        下游消费 (LLM / RAG / Agent)
```

---

## 3. 新建文件（完整代码）

### 3.1 `src/cygnusx/application/services/pdf_models.py`

```python
"""PDF 处理数据模型与场景配置常量。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PDFType(str, Enum):
    """PDF 分类类型。"""

    TEXT_BASED = "TextBased"
    SCANNED = "Scanned"
    MIXED = "Mixed"
    IMAGE_ONLY = "ImageOnly"
    UNKNOWN = "unknown"


class PDFSource(str, Enum):
    """解析来源。"""

    INSPECTOR = "pdf-inspector"
    LEGACY = "pypdf"


class PDFOutputFormat(str, Enum):
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
    processing_time_ms: Optional[float] = None
    truncated: bool = False


@dataclass
class PDFProcessResult:
    """PDF 处理统一返回结果。"""

    success: bool
    content: str
    pages: list[PDFPage]
    metadata: PDFMetadata
    source: PDFSource
    fallback_reason: Optional[str] = None
    raw_markdown: Optional[str] = None


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
```

### 3.2 `src/cygnusx/infrastructure/pdf/exceptions.py`

```python
"""PDF 处理异常定义。"""


class PDFProcessingError(Exception):
    """PDF 处理基础异常。"""

    pass


class PDFInspectorError(PDFProcessingError):
    """pdf-inspector 主路径异常。"""

    pass


class PDFLegacyError(PDFProcessingError):
    """pypdf 降级路径异常。"""

    pass


class PDFQualityGateError(PDFProcessingError):
    """质量门控未通过。"""

    pass
```

### 3.3 `src/cygnusx/infrastructure/pdf/__init__.py`

```python
"""PDF 处理基础设施包。"""

from .exceptions import PDFProcessingError, PDFInspectorError, PDFLegacyError, PDFQualityGateError

__all__ = [
    "PDFProcessingError",
    "PDFInspectorError",
    "PDFLegacyError",
    "PDFQualityGateError",
]
```

### 3.4 `src/cygnusx/infrastructure/pdf/inspector_adapter.py`

```python
"""pdf-inspector 主路径适配器。

Phase 2 启用：取消注释所有被标记为 "Phase 2" 的代码块，
并确保 `pdf-inspector` 已安装且 Rust 编译环境就绪。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .exceptions import PDFInspectorError

logger = logging.getLogger(__name__)


class PDFInspectorAdapter:
    """pdf-inspector 主路径适配器。

    当前为 **占位实现**（Phase 1），内部直接返回空结果触发降级。
    待 pdf-inspector 安装并验证后，取消注释 Phase 2 代码即可激活。
    """

    def __init__(self, config: dict) -> None:
        self.config = config
        self._inspector: Optional[Any] = None

    # ── Phase 2: 激活 pdf-inspector 时取消注释 ─────────────
    # def _ensure_loaded(self) -> None:
    #     if self._inspector is not None:
    #         return
    #     try:
    #         import pdf_inspector
    #         self._inspector = pdf_inspector
    #     except ImportError as exc:
    #         raise PDFInspectorError(
    #             "pdf-inspector is not installed. "
    #             "Run: pip install pdf-inspector"
    #         ) from exc

    def extract(self, file_path: str) -> dict:
        """使用 pdf-inspector 提取 PDF 内容。

        Returns:
            {
                "success": True,
                "markdown": str,
                "pages": [
                    {
                        "page_number": int,
                        "markdown": str,
                        "text": str,
                        "needs_ocr": bool,
                    }
                ],
                "metadata": {
                    "pdf_type": str,
                    "confidence": float,
                    "has_encoding_issues": bool,
                    "pages_needing_ocr": list[int],
                    "total_pages": int,
                }
            }
        """
        # ── Phase 1: 占位 ────────────────────────────────────
        logger.info("pdf-inspector adapter is in placeholder mode (Phase 1)")
        raise PDFInspectorError("pdf-inspector not yet activated (Phase 1)")

        # ── Phase 2: 激活时取消注释以下代码 ──────────────────
        # self._ensure_loaded()
        #
        # try:
        #     detection = self._inspector.detect_pdf(file_path)
        #     result = self._inspector.process_pdf(
        #         file_path,
        #         options={
        #             "extract_markdown": True,
        #             "extract_metadata": True,
        #             "enable_ocr": self.config.get("enable_ocr", False),
        #         },
        #     )
        #
        #     return {
        #         "success": True,
        #         "markdown": result.markdown,
        #         "pages": [
        #             {
        #                 "page_number": p.page_number,
        #                 "markdown": p.markdown,
        #                 "text": getattr(p, "text", p.markdown),
        #                 "needs_ocr": getattr(p, "needs_ocr", False),
        #             }
        #             for p in result.pages
        #         ],
        #         "metadata": {
        #             "pdf_type": getattr(detection, "pdf_type", "unknown"),
        #             "confidence": getattr(detection, "confidence", 1.0),
        #             "has_encoding_issues": getattr(
        #                 detection, "has_encoding_issues", False
        #             ),
        #             "pages_needing_ocr": getattr(
        #                 result, "pages_needing_ocr", []
        #             ),
        #             "total_pages": getattr(result, "total_pages", 0),
        #         },
        #     }
        # except Exception as exc:
        #     raise PDFInspectorError(f"pdf-inspector failed: {exc}") from exc
```

### 3.5 `src/cygnusx/infrastructure/pdf/pypdf_adapter.py`

```python
"""pypdf 降级路径适配器。

复刻现有三处实现的行为，确保降级时输出与旧代码完全一致。
"""

from __future__ import annotations

import logging
from typing import Optional

from pypdf import PdfReader

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
        """
        try:
            reader = PdfReader(file_path)
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
```

### 3.6 `src/cygnusx/application/services/pdf_processor.py`

```python
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
from typing import Optional

import anyio

from cygnusx.application.services.pdf_models import (
    CHAT_ATTACHMENT_CONFIG,
    KNOWLEDGE_BASE_CONFIG,
    PDFMetadata,
    PDFPage,
    PDFProcessResult,
    PDFSource,
    PDFType,
    WORKSPACE_MCP_CONFIG,
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

    def pre_check(self, file_path: str) -> tuple[bool, Optional[str]]:
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

    def check_inspector_result(self, result: dict) -> tuple[bool, Optional[str]]:
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

        # 按场景格式化
        if self.output_format == "plaintext":
            content = self._to_plaintext(result)
        elif self.output_format == "markdown":
            content = result.get("markdown", "")
        elif self.output_format == "json":
            content = self._to_json(result, metadata)
        else:
            content = result.get("markdown", "")

        # 字符截断
        truncated = False
        if len(content) > self.max_chars:
            content = content[: self.max_chars]
            truncated = True

        metadata.truncated = truncated

        return PDFProcessResult(
            success=True,
            content=content,
            pages=pages,
            metadata=metadata,
            source=source,
            raw_markdown=result.get("markdown"),
        )

    def _to_plaintext(self, result: dict) -> str:
        """转换为带分页标记的纯文本（兼容现有格式）。"""
        parts: list[str] = []
        for page in result.get("pages", []):
            text = page.get("text", "").strip()
            if text:
                marker = self.page_marker.format(n=page["page_number"])
                parts.append(f"{marker}\n{text}")
        return "\n\n".join(parts)

    def _to_json(self, result: dict, metadata: PDFMetadata) -> str:
        """转换为 JSON 字符串（MCP 场景）。"""
        payload = {
            "content": result.get("markdown", ""),
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


# ── 统一处理器 ────────────────────────────────────────────


class PDFProcessor:
    """OmiHub 统一 PDF 处理器。

    主路径: pdf-inspector (结构化 Markdown)
    降级路径: pypdf (纯文本，复刻现有行为)

    灰度控制（环境变量）::

        PDF_INSPECTOR_ENABLED=true      # 启用 pdf-inspector 主路径
        PDF_INSPECTOR_ROLLOUT=100       # 100% 流量走主路径
    """

    def __init__(self, config: Optional[dict] = None) -> None:
        self.config = config or CHAT_ATTACHMENT_CONFIG
        self.gate = QualityGate(self.config)
        self.normalizer = PDFOutputNormalizer(self.config)

        self._inspector: Optional[PDFInspectorAdapter] = None
        self._legacy: Optional[PyPDFAdapter] = None

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
```

---

## 4. 修改文件（精确到行号）

### 4.1 `src/cygnusx/application/services/chat_service.py`

**找到 `_extract_pdf_text` 方法（约第 9369 行）**，替换为：

```python
async def _extract_pdf_text(self, file_path: str) -> str:
    """提取 PDF 文本（已迁移至 PDFProcessor）。"""
    from cygnusx.application.services.pdf_processor import (
        PDFProcessor,
        CHAT_ATTACHMENT_CONFIG,
    )

    processor = PDFProcessor(config=CHAT_ATTACHMENT_CONFIG)
    result = await processor.process(file_path)
    return result.content
```

**检查 `_read_attachment_text`（约第 9336 行）的调用链**：
- 如果 `_read_attachment_text` 是 `async def`，改为 `await self._extract_pdf_text(file_path)`
- 如果 `_read_attachment_text` 是 `def`，保持 `anyio.to_thread.run_sync(self._extract_pdf_text, file_path)`（但注意 `_extract_pdf_text` 现在也是 async，需要再包一层）

**更简单的方式**：如果调用链难以改动，在 `_read_attachment_text` 中使用：

```python
from cygnusx.application.services.pdf_processor import PDFProcessor, CHAT_ATTACHMENT_CONFIG

processor = PDFProcessor(config=CHAT_ATTACHMENT_CONFIG)
# 同步调用方式
result = await anyio.to_thread.run_sync(processor.process_sync, file_path)
return result.content
```

### 4.2 `src/cygnusx/application/services/knowledge_asset_service.py`

**找到 `_extract_pdf` 方法（约第 152 行）**，替换为：

```python
async def _extract_pdf(self, file_path: str) -> str:
    """提取 PDF 文本（已迁移至 PDFProcessor）。"""
    from cygnusx.application.services.pdf_processor import (
        PDFProcessor,
        KNOWLEDGE_BASE_CONFIG,
    )

    processor = PDFProcessor(config=KNOWLEDGE_BASE_CONFIG)
    result = await processor.process(file_path)
    return result.content
```

### 4.3 `src/cygnusx/infrastructure/mcp/presets.py`

**找到 `_extract_workspace_pdf_text` 方法（约第 553 行）**，替换为：

```python
async def _extract_workspace_pdf_text(self, file_path: str) -> dict:
    """提取工作区 PDF 文本（已迁移至 PDFProcessor）。"""
    from cygnusx.application.services.pdf_processor import (
        PDFProcessor,
        WORKSPACE_MCP_CONFIG,
    )

    processor = PDFProcessor(config=WORKSPACE_MCP_CONFIG)
    result = await processor.process(file_path)

    return {
        "content": result.content,
        "truncated": result.metadata.truncated,
        "pages_read": result.metadata.total_pages,
        "pdf_type": result.metadata.pdf_type.value,
        "confidence": result.metadata.confidence,
        "source": result.source.value,
        "fallback_reason": result.fallback_reason,
    }
```

---

## 5. 依赖变更

### 5.1 `pyproject.toml`

在 `pypdf>=5.0.0` 附近添加：

```toml
# PDF 处理
"pypdf>=5.0.0",
"pdf-inspector>=0.1.0",  # Phase 2 激活时启用；Phase 1 占位不影响运行
```

### 5.2 `pytest-asyncio` 修复

排查报告指出测试环境缺少 `pytest-asyncio`。确保已安装：

```bash
pip install pytest-asyncio>=0.23.5
```

确认 `pyproject.toml` 已有：

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

---

## 6. Kimi Code 提示词

### 6.1 主提示词：完整重构

将以下提示词直接粘贴给 Kimi Code：

```markdown
# 角色
你是 OmiHub 平台的资深 Python 工程师，负责 PDF 处理流程的重构。

# 背景
当前代码中共有 3 处独立的 PDF 文本提取实现，全部基于 `pypdf`，分别位于：
1. `src/cygnusx/application/services/chat_service.py` ~9369 行 — `_extract_pdf_text`
2. `src/cygnusx/application/services/knowledge_asset_service.py` ~152 行 — `_extract_pdf`
3. `src/cygnusx/infrastructure/mcp/presets.py` ~553 行 — `_extract_workspace_pdf_text`

# 目标
将三处独立实现统一替换为 `PDFProcessor`，采用"pdf-inspector 主路径 + pypdf 降级路径"架构。

# 新建文件清单（请按以下代码创建）

## 文件 1: `src/cygnusx/application/services/pdf_models.py`
[粘贴 3.1 节完整代码]

## 文件 2: `src/cygnusx/infrastructure/pdf/exceptions.py`
[粘贴 3.2 节完整代码]

## 文件 3: `src/cygnusx/infrastructure/pdf/__init__.py`
[粘贴 3.3 节完整代码]

## 文件 4: `src/cygnusx/infrastructure/pdf/inspector_adapter.py`
[粘贴 3.4 节完整代码]

## 文件 5: `src/cygnusx/infrastructure/pdf/pypdf_adapter.py`
[粘贴 3.5 节完整代码]

## 文件 6: `src/cygnusx/application/services/pdf_processor.py`
[粘贴 3.6 节完整代码]

# 修改文件清单

## 修改 1: `src/cygnusx/application/services/chat_service.py`
- 找到 `_extract_pdf_text` 方法（约 9369 行），替换为：
```python
async def _extract_pdf_text(self, file_path: str) -> str:
    from cygnusx.application.services.pdf_processor import (
        PDFProcessor, CHAT_ATTACHMENT_CONFIG,
    )
    processor = PDFProcessor(config=CHAT_ATTACHMENT_CONFIG)
    result = await processor.process(file_path)
    return result.content
```
- 检查 `_read_attachment_text`（约 9336 行）的调用链，确保支持 `await self._extract_pdf_text(file_path)`
- 如果 `_read_attachment_text` 是同步方法，保持 `anyio.to_thread.run_sync` 包装，但注意 `_extract_pdf_text` 现在是 async，需要再包一层 `anyio.run` 或使用 `process_sync`

## 修改 2: `src/cygnusx/application/services/knowledge_asset_service.py`
- 找到 `_extract_pdf` 方法（约 152 行），替换为：
```python
async def _extract_pdf(self, file_path: str) -> str:
    from cygnusx.application.services.pdf_processor import (
        PDFProcessor, KNOWLEDGE_BASE_CONFIG,
    )
    processor = PDFProcessor(config=KNOWLEDGE_BASE_CONFIG)
    result = await processor.process(file_path)
    return result.content
```

## 修改 3: `src/cygnusx/infrastructure/mcp/presets.py`
- 找到 `_extract_workspace_pdf_text` 方法（约 553 行），替换为：
```python
async def _extract_workspace_pdf_text(self, file_path: str) -> dict:
    from cygnusx.application.services.pdf_processor import (
        PDFProcessor, WORKSPACE_MCP_CONFIG,
    )
    processor = PDFProcessor(config=WORKSPACE_MCP_CONFIG)
    result = await processor.process(file_path)
    return {
        "content": result.content,
        "truncated": result.metadata.truncated,
        "pages_read": result.metadata.total_pages,
        "pdf_type": result.metadata.pdf_type.value,
        "confidence": result.metadata.confidence,
        "source": result.source.value,
        "fallback_reason": result.fallback_reason,
    }
```

# 依赖修改
在 `pyproject.toml` 中 `pypdf>=5.0.0` 附近添加：
```toml
"pdf-inspector>=0.1.0",
```

# 约束与注意事项
1. **Phase 1 策略**：`inspector_adapter.py` 目前是占位实现，会主动抛出 `PDFInspectorError` 触发降级。这意味着上线后 100% 走 pypdf 降级路径，行为与现有代码完全一致，零风险。
2. **异步兼容性**：`PDFProcessor.process()` 是 async 方法。如果某处调用链不支持 async，使用 `anyio.to_thread.run_sync(processor.process_sync, file_path)`。
3. **不要删除 pypdf**：保留作为降级路径，不要从依赖中移除。
4. **向后兼容**：MCP 返回的 dict 新增了字段（pdf_type, confidence 等），但不会破坏现有字段。
5. **路径安全**：如果方便，一并增强 `_resolve_attachment_path` 的路径遍历防护（使用 `resolved.relative_to(upload_dir.resolve())`）。

# 输出要求
1. 先列出所有新建文件的创建命令和内容
2. 再列出所有修改文件的 diff（使用 `---` / `+++` / `@@` 格式）
3. 最后列出 `pyproject.toml` 的变更
4. 如果某处修改涉及异步签名变更，请特别标注并给出调用链调整建议
```

### 6.2 快速提示词：仅创建文件

```markdown
请在 `src/cygnusx` 下创建以下 6 个新文件，代码内容如下：

[依次列出 6 个文件的完整代码]

要求：
- 文件路径必须准确
- 代码中的 import 路径基于 `src/cygnusx` 为包根
- 不要修改任何现有文件
- 创建完成后列出所有新建文件的路径
```

### 6.3 快速提示词：仅修改现有文件

```markdown
请修改以下 3 个文件中的 PDF 提取方法，将其替换为对 `PDFProcessor` 的调用。

## 修改 1
文件：`src/cygnusx/application/services/chat_service.py`
方法：`_extract_pdf_text`（约第 9369 行）
替换为：
```python
async def _extract_pdf_text(self, file_path: str) -> str:
    from cygnusx.application.services.pdf_processor import (
        PDFProcessor, CHAT_ATTACHMENT_CONFIG,
    )
    processor = PDFProcessor(config=CHAT_ATTACHMENT_CONFIG)
    result = await processor.process(file_path)
    return result.content
```

## 修改 2
文件：`src/cygnusx/application/services/knowledge_asset_service.py`
方法：`_extract_pdf`（约第 152 行）
替换为：
```python
async def _extract_pdf(self, file_path: str) -> str:
    from cygnusx.application.services.pdf_processor import (
        PDFProcessor, KNOWLEDGE_BASE_CONFIG,
    )
    processor = PDFProcessor(config=KNOWLEDGE_BASE_CONFIG)
    result = await processor.process(file_path)
    return result.content
```

## 修改 3
文件：`src/cygnusx/infrastructure/mcp/presets.py`
方法：`_extract_workspace_pdf_text`（约第 553 行）
替换为：
```python
async def _extract_workspace_pdf_text(self, file_path: str) -> dict:
    from cygnusx.application.services.pdf_processor import (
        PDFProcessor, WORKSPACE_MCP_CONFIG,
    )
    processor = PDFProcessor(config=WORKSPACE_MCP_CONFIG)
    result = await processor.process(file_path)
    return {
        "content": result.content,
        "truncated": result.metadata.truncated,
        "pages_read": result.metadata.total_pages,
        "pdf_type": result.metadata.pdf_type.value,
        "confidence": result.metadata.confidence,
        "source": result.source.value,
        "fallback_reason": result.fallback_reason,
    }
```

注意：
- 如果方法签名需要从 `def` 改为 `async def`，请一并修改
- 检查调用方是否需要添加 `await`
- 如果调用方是同步方法且不便修改，使用 `anyio.to_thread.run_sync(processor.process_sync, file_path)`
```

### 6.4 验证提示词

```markdown
请验证以下事项：

1. 运行 `python -c "from cygnusx.application.services.pdf_processor import PDFProcessor, CHAT_ATTACHMENT_CONFIG; print('import ok')"` 确认无 import 错误
2. 运行 `python -m pytest tests/unit/test_chat_attachment_reading.py -v` 确认测试通过
3. 运行 `python -m pytest tests/unit/test_knowledge_asset_service.py -v` 确认测试通过
4. 检查三处原有 `from pypdf import PdfReader` 是否已被移除（降级路径内部保留，但业务代码中不应再有直接 import）
5. 确认 `pyproject.toml` 中已添加 `pdf-inspector>=0.1.0`

如果测试失败，请分析原因并给出修复建议。
```

---

## 7. 测试验证

### 7.1 单元测试：`tests/unit/test_pdf_processor.py`

```python
"""PDFProcessor 单元测试。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cygnusx.application.services.pdf_models import (
    CHAT_ATTACHMENT_CONFIG,
    KNOWLEDGE_BASE_CONFIG,
    PDFSource,
    PDFType,
    WORKSPACE_MCP_CONFIG,
)
from cygnusx.application.services.pdf_processor import PDFProcessor


@pytest.fixture
def sample_pdf() -> Path:
    """创建一个简单的测试 PDF（使用 pypdf 生成）。"""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
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
    async def test_truncate(self, sample_pdf: Path, monkeypatch) -> None:
        """字符截断应正确标记。"""
        config = {**CHAT_ATTACHMENT_CONFIG, "max_chars": 10}
        processor = PDFProcessor(config=config)
        result = await processor.process(str(sample_pdf))

        assert result.metadata.truncated is True
        assert len(result.content) <= 10
```

### 7.2 集成测试清单

| 测试项 | 命令 | 期望结果 |
|--------|------|---------|
| import 检查 | `python -c "from cygnusx.application.services.pdf_processor import PDFProcessor"` | 无错误 |
| 聊天附件测试 | `pytest tests/unit/test_chat_attachment_reading.py -v` | 全部通过 |
| 知识库测试 | `pytest tests/unit/test_knowledge_asset_service.py -v` | 全部通过 |
| 回归测试 | `pytest tests/unit/test_general_assistant_regression.py -v` | 全部通过 |
| 新处理器测试 | `pytest tests/unit/test_pdf_processor.py -v` | 全部通过 |
| 类型检查 | `mypy src/cygnusx/application/services/pdf_processor.py` | 无类型错误 |

---

## 8. Phase 2 激活检查清单

当准备激活 pdf-inspector 主路径时，按以下步骤操作：

- [ ] 安装 `pdf-inspector`：`pip install pdf-inspector>=0.1.0`
- [ ] 确认 Rust 编译环境就绪（或预编译 wheel 可用）
- [ ] 取消注释 `inspector_adapter.py` 中所有标记为 "Phase 2" 的代码
- [ ] 设置环境变量：`PDF_INSPECTOR_ENABLED=true`
- [ ] 设置灰度比例：`PDF_INSPECTOR_ROLLOUT=5`（从 5% 开始）
- [ ] 运行对比测试：同一批 PDF 分别用新旧路径解析，对比输出质量
- [ ] 监控日志中的 `fallback_reason`，分析降级原因
- [ ] 逐步提升 `PDF_INSPECTOR_ROLLOUT` 至 100%
