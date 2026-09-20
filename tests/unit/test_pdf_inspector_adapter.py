"""pdf-inspector 适配器的版本兼容性测试。"""

from types import SimpleNamespace

from cygnusx.infrastructure.pdf.inspector_adapter import PDFInspectorAdapter


class _InspectorWithoutOptions:
    def __init__(self) -> None:
        self.processed_path: str | None = None

    def detect_pdf(self, path: str) -> SimpleNamespace:
        assert path == "example.pdf"
        return SimpleNamespace(pdf_type="digital", confidence=0.98)

    def process_pdf(self, path: str) -> SimpleNamespace:
        self.processed_path = path
        return SimpleNamespace(
            markdown="# Example",
            pages=[SimpleNamespace(page_number=1, markdown="# Example")],
            pages_needing_ocr=[],
            total_pages=1,
        )


def test_extract_uses_pdf_inspector_process_pdf_signature() -> None:
    inspector = _InspectorWithoutOptions()
    adapter = PDFInspectorAdapter(config={"enable_ocr": True})
    adapter._inspector = inspector

    result = adapter.extract("example.pdf")

    assert inspector.processed_path == "example.pdf"
    assert result["markdown"] == "# Example"
    assert result["metadata"]["total_pages"] == 1
