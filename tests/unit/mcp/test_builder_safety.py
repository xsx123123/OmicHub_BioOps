"""MCP Builder AST 安全检查器测试。"""

from __future__ import annotations

import pytest

from cygnusx.infrastructure.mcp.builder.safety import (
    GENERATED_MARKER,
    SafetyReport,
    StaticSafetyChecker,
)

pytestmark = pytest.mark.unit


def _wrap(body: str) -> str:
    """把业务代码包成符合结构要求的完整 MCP Server 模板。"""
    return f'''#!/usr/bin/env python3
"""MCP Server: test"""

{GENERATED_MARKER} = True

from mcp.server import Server
from mcp.types import Tool, TextContent
import json

server = Server("test")

@server.list_tools()
async def list_tools() -> list:
    return []

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
{body}
'''


def test_clean_code_passes():
    code = _wrap('    return [TextContent(type="text", text=json.dumps({{"ok": True}}))]')
    report = StaticSafetyChecker().analyze(code)
    assert report.passed is True, report.violations
    assert report.violations == []
    assert "mcp" in report.dependencies
    assert "json" in report.dependencies


def test_empty_code_fails():
    report = StaticSafetyChecker().analyze("")
    assert report.passed is False
    assert "代码为空" in report.violations[0]


def test_syntax_error_fails():
    report = StaticSafetyChecker().analyze("def broken(:\n  pass")
    assert report.passed is False
    assert "语法错误" in report.violations[0]


@pytest.mark.parametrize(
    "bad_import",
    ["import subprocess", "import ctypes", "import pickle", "import socket", "import shutil"],
)
def test_forbidden_imports(bad_import: str):
    code = _wrap("    return []") + f"\n{bad_import}\n"
    report = StaticSafetyChecker().analyze(code)
    assert report.passed is False
    assert any("禁止导入模块" in v for v in report.violations)


def test_from_import_forbidden():
    code = _wrap("    return []").replace(
        "import json", "import json\nfrom subprocess import run"
    )
    report = StaticSafetyChecker().analyze(code)
    assert report.passed is False
    assert any("subprocess" in v for v in report.violations)


def test_relative_import_forbidden():
    code = _wrap("    return []").replace("import json", "import json\nfrom . import evil")
    report = StaticSafetyChecker().analyze(code)
    assert report.passed is False
    assert any("相对导入" in v for v in report.violations)


@pytest.mark.parametrize(
    "call",
    ["eval('1+1')", "exec('x=1')", "compile('x', '', 'exec')", "__import__('os')"],
)
def test_forbidden_calls(call: str):
    code = _wrap(f"    x = {call}\n    return []")
    report = StaticSafetyChecker().analyze(code)
    assert report.passed is False
    assert any("禁止调用" in v for v in report.violations)


def test_os_system_attribute_call():
    code = _wrap("    import os\n    os.system('ls')\n    return []")
    report = StaticSafetyChecker().analyze(code)
    assert report.passed is False
    assert any(".system()" in v for v in report.violations)


def test_pickle_loads_call():
    code = _wrap("    import pickle\n    pickle.loads(b'')\n    return []")
    report = StaticSafetyChecker().analyze(code)
    assert report.passed is False
    assert any(".loads()" in v for v in report.violations)


def test_open_call_forbidden():
    code = _wrap("    f = open('/tmp/x')\n    return []")
    report = StaticSafetyChecker().analyze(code)
    assert report.passed is False
    assert any("open()" in v for v in report.violations)


def test_dunder_attribute_access():
    code = _wrap("    g = (1).__class__.__bases__\n    return []")
    report = StaticSafetyChecker().analyze(code)
    assert report.passed is False
    assert any("__bases__" in v for v in report.violations)


@pytest.mark.parametrize("path", ["/etc/passwd", "/proc/self/environ", "/sys/kernel", "/root/.ssh"])
def test_protected_paths_in_strings(path: str):
    code = _wrap(f'    target = "{path}"\n    return []')
    report = StaticSafetyChecker().analyze(code)
    assert report.passed is False
    assert any("受保护路径" in v for v in report.violations)


def test_internal_ip_warns_but_not_blocks():
    code = _wrap('    url = "http://10.0.0.5/api"\n    return []')
    report = StaticSafetyChecker().analyze(code)
    # 网络访问由 egress proxy 兜底，仅告警
    assert any("内网" in w for w in report.warnings)


def test_missing_marker_fails():
    code = _wrap("    return []").replace(f"{GENERATED_MARKER} = True\n\n", "")
    report = StaticSafetyChecker().analyze(code)
    assert report.passed is False
    assert any("生成标记" in v for v in report.violations)


def test_missing_structure_fails():
    code = f'{GENERATED_MARKER} = True\nprint("hello")\n'
    report = StaticSafetyChecker().analyze(code)
    assert report.passed is False
    assert any("MCP 协议 handler" in v for v in report.violations)


def test_fastmcp_style_passes():
    code = f'''"""FastMCP style"""
{GENERATED_MARKER} = True
from fastmcp import FastMCP

mcp = FastMCP("test")

@mcp.tool()
def hello(name: str) -> str:
    """打招呼"""
    return f"hello {{name}}"
'''
    report = StaticSafetyChecker().analyze(code)
    assert report.passed is True, report.violations


def test_non_whitelist_import_warns():
    code = _wrap("    return []").replace("import json", "import json\nimport somepkg")
    report = StaticSafetyChecker().analyze(code)
    assert report.passed is True  # 仅告警，不阻断
    assert any("somepkg" in w for w in report.warnings)


def test_report_to_dict():
    report = SafetyReport(passed=True, dependencies=["mcp"])
    d = report.to_dict()
    assert d["passed"] is True
    assert d["dependencies"] == ["mcp"]


def test_code_size_limit():
    checker = StaticSafetyChecker(max_code_bytes=100)
    code = _wrap("    return []") + "\n" + "x = 1\n" * 100
    report = checker.analyze(code)
    assert report.passed is False
    assert any("大小上限" in v for v in report.violations)
