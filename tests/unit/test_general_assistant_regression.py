from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest

from omichub.application.services.arxiv_literature_service import ArxivLiteratureService
from omichub.application.services.chat_service import ChatService
from omichub.infrastructure.mcp.presets import (
    PLATFORM_HANDLERS,
    PLATFORM_PRESET_TOOLS,
    _extract_workspace_pdf_text,
)


def test_general_prompt_keeps_existing_workbench_rules_and_adds_research_modes() -> None:
    prompt = Path("data/ai/prompts/general.md").read_text(encoding="utf-8")

    assert "### 数值计算与表格处理（强制沙盒执行）" in prompt
    assert "### 任务分诊（先于一切执行）" in prompt
    assert "### 文献解读" in prompt
    assert "### 分析规划" in prompt
    assert "### 实验设计" in prompt
    assert "生信任务一律以既有规范为准" in prompt


def test_pdf_workspace_extraction_is_paginated_and_bounded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FakeReader:
        pages = [
            SimpleNamespace(extract_text=lambda: "a" * 30_000),
            SimpleNamespace(extract_text=lambda: "b" * 30_000),
        ]

    monkeypatch.setattr("pypdf.PdfReader", lambda _path: FakeReader())
    result = _extract_workspace_pdf_text(tmp_path / "paper.pdf")

    assert result["truncated"] is True
    assert result["pages_read"] == 2
    assert result["content"].startswith("[Page 1]")
    assert "[Page 2]" in result["content"]
    assert "[已截断，仅覆盖前 2 页]" in result["content"]
    assert len(result["content"]) < 50_200


def test_pdf_workspace_extraction_reports_scanned_or_encrypted_pdf(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakeReader:
        pages = [SimpleNamespace(extract_text=lambda: "")]

    monkeypatch.setattr("pypdf.PdfReader", lambda _path: FakeReader())
    result = _extract_workspace_pdf_text(tmp_path / "scan.pdf")

    assert "无法提取文本" in result["error"]
    assert "OCR" in result["error"]


def test_chat_pdf_extraction_marks_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeReader:
        pages = [
            SimpleNamespace(extract_text=lambda: "x" * 50_100),
            SimpleNamespace(extract_text=lambda: "second page"),
        ]

    monkeypatch.setattr("pypdf.PdfReader", lambda _source: FakeReader())
    result = ChatService._extract_pdf_text(b"not-a-real-pdf")

    assert len(result) <= 50_100
    assert "[第 1 页]" in result
    assert "[已截断，仅覆盖前 1 页]" in result


def test_arxiv_normalization_exposes_unified_evidence_fields() -> None:
    entry = ElementTree.fromstring(
        """<entry xmlns="http://www.w3.org/2005/Atom">
        <id>https://arxiv.org/abs/2608.00001</id>
        <title>  A useful paper  </title>
        <published>2026-08-01T00:00:00Z</published>
        <summary> An abstract for this paper. </summary>
        <author><name>A. Researcher</name></author>
        <category term="cs.LG" />
        </entry>"""
    )

    result = ArxivLiteratureService._normalize(entry)

    assert result is not None
    assert result["title"] == "A useful paper"
    assert result["authors"] == "A. Researcher"
    assert result["year"] == "2026"
    assert result["source"] == "arXiv"
    assert result["link"] == "https://arxiv.org/abs/2608.00001"


def test_arxiv_tool_is_registered_and_research_pack_includes_it() -> None:
    tool = next(item for item in PLATFORM_PRESET_TOOLS if item["name"] == "arxiv_search")

    assert tool["inputSchema"]["required"] == ["query"]
    assert tool["annotations"]["readOnlyHint"] is True
    assert "arxiv_search" in PLATFORM_HANDLERS
    research = Path("data/ai/tools/research.yaml").read_text(encoding="utf-8")
    assert "  - arxiv_search" in research
