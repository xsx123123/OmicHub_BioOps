"""PDF 处理基础设施包。"""

from .exceptions import PDFInspectorError, PDFLegacyError, PDFProcessingError, PDFQualityGateError

__all__ = [
    "PDFProcessingError",
    "PDFInspectorError",
    "PDFLegacyError",
    "PDFQualityGateError",
]
