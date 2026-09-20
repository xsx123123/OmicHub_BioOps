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
