"""MCP Builder 文档生成器与代码提取测试。"""

from __future__ import annotations

import pytest

from omichub.infrastructure.mcp.builder.doc_generator import (
    generate_architecture_doc,
    generate_build_doc,
)
from omichub.infrastructure.mcp.builder.generator import extract_python_code

pytestmark = pytest.mark.unit


def test_build_doc_contains_sections():
    doc = generate_build_doc(
        name="pubmed-query",
        requirement="查询 PubMed 文献",
        plan_summary="使用 NCBI E-utilities",
        tools=[{"name": "search", "description": "搜索", "inputSchema": {"required": ["query"]}}],
        test_cases=[
            {"input": {"query": "cancer"}, "expected": "results", "actual": "results", "passed": True},
            {"input": {}, "expected": "error", "actual": "error json", "passed": False},
        ],
        dependencies=["mcp", "httpx"],
        model_used="deepseek-v4-pro",
        build_id="abc-123",
        version="1.1.0",
    )
    assert "# MCP Build Report: pubmed-query" in doc
    assert "查询 PubMed 文献" in doc
    assert "| search |" in doc
    assert "通过 1/2" in doc
    assert "`mcp`" in doc and "`httpx`" in doc
    assert "deepseek-v4-pro" in doc
    assert "1.1.0" in doc


def test_build_doc_empty_cases():
    doc = generate_build_doc(name="x", requirement="r")
    assert "_暂无测试记录_" in doc


def test_architecture_doc_network_and_ttl():
    doc = generate_architecture_doc(
        name="weather",
        needs_network=True,
        allowed_domains=["api.openweathermap.org"],
        ttl_hours=12,
    )
    assert "api.openweathermap.org" in doc
    assert "12 小时" in doc
    assert "sandbox-agent /mcp/call" in doc
    assert "AST 静态检查" in doc


def test_architecture_doc_no_network():
    doc = generate_architecture_doc(name="calc", needs_network=False, ttl_hours=None)
    assert "无外部网络访问" in doc
    assert "永久" in doc


def test_extract_code_from_fence():
    text = "好的，这是代码：\n```python\n__exp_mcp_generated__ = True\nprint(1)\n```\n说明略"
    assert extract_python_code(text) == "__exp_mcp_generated__ = True\nprint(1)"


def test_extract_code_prefers_marked_block():
    text = (
        "```python\nprint('decoy')\n```\n"
        "```python\n__exp_mcp_generated__ = True\nserver = 1\n```\n"
    )
    assert "__exp_mcp_generated__" in extract_python_code(text)


def test_extract_code_plain_text_fallback():
    assert extract_python_code("x = 1") == "x = 1"


def test_slugify():
    from omichub.application.services.mcp_builder_service import _slugify

    assert _slugify("PubMed Query Tool!") == "pubmed-query-tool"
    assert _slugify("纯中文需求") == "tool"  # 无 ASCII → fallback
    assert len(_slugify("a" * 100)) <= 40
