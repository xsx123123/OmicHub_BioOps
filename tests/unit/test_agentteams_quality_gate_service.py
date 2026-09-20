"""通用域报告交付轻量质量门控：引用完整性 + 文件可打开。"""

from __future__ import annotations

import zipfile

import pytest

from cygnusx.application.services.agentteams_quality_gate_service import (
    AgentTeamsQualityGateService,
)


@pytest.fixture()
def gate() -> AgentTeamsQualityGateService:
    return AgentTeamsQualityGateService(registry=object())  # type: ignore[arg-type]


def _write_docx(path) -> None:
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("[Content_Types].xml", "<Types/>")


def test_report_delivery_passes_with_cited_evidence_and_openable_files(
    gate: AgentTeamsQualityGateService, tmp_path
) -> None:
    docx = tmp_path / "report.docx"
    _write_docx(docx)
    html = tmp_path / "report.html"
    html.write_text("<!doctype html><html><body>ok</body></html>", encoding="utf-8")

    result = gate.evaluate_report_delivery(
        deliverables=[{"path": str(docx)}, {"path": str(html)}],
        citations=[{"entity": "TP53", "source": "https://pubmed.ncbi.nlm.nih.gov/1"}],
    )

    assert result["decision"] == "PASSED"
    assert {check["metric"] for check in result["checks"]} == {
        "citation_completeness",
        "file_openable",
    }
    assert result["audit_event"]["event_type"] == "quality.light_gate"
    assert result["audit_event"]["flow_id"] == "general"


def test_report_delivery_blocks_on_missing_citation_source(
    gate: AgentTeamsQualityGateService, tmp_path
) -> None:
    docx = tmp_path / "report.docx"
    _write_docx(docx)

    result = gate.evaluate_report_delivery(
        deliverables=[{"path": str(docx)}],
        citations=[{"entity": "TP53", "source": ""}],
    )

    assert result["decision"] == "BLOCKED"
    assert "缺少来源" in result["audit_event"]["reason"]


@pytest.mark.parametrize("filename", ["report.docx", "report.html"])
def test_report_delivery_blocks_on_unopenable_files(
    gate: AgentTeamsQualityGateService, tmp_path, filename: str
) -> None:
    missing = tmp_path / "missing.docx"
    garbage = tmp_path / filename
    garbage.write_bytes(b"this is not a real document")

    missing_result = gate.evaluate_report_delivery(deliverables=[{"path": str(missing)}])
    garbage_result = gate.evaluate_report_delivery(deliverables=[{"path": str(garbage)}])

    assert missing_result["decision"] == "BLOCKED"
    assert garbage_result["decision"] == "BLOCKED"


def test_report_delivery_empty_input_requires_manual_review(
    gate: AgentTeamsQualityGateService,
) -> None:
    result = gate.evaluate_report_delivery(deliverables=[])

    assert result["decision"] == "MANUAL_REVIEW"
    assert result["checks"] == []
