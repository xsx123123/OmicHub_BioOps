"""MCP preset 动态 Flow tools 测试。"""

from __future__ import annotations

import pytest

from omichub.infrastructure.mcp.presets import _build_omichub_tools_preset


@pytest.mark.unit
def test_omichub_tools_preset_includes_flow_tools() -> None:
    preset = _build_omichub_tools_preset()

    tool_names = {t["name"] for t in preset["tools"]}
    assert "omichub_prepare_rna_seq_submission" in tool_names
    assert "omichub_prepare_atac_seq_submission" in tool_names
    assert "omichub_get_analysis_task_status" in tool_names
    assert "omichub_get_analysis_task_summary" in tool_names

    handlers = preset["handlers"]
    assert "omichub_prepare_rna_seq_submission" in handlers
    assert "omichub_get_analysis_task_status" in handlers


@pytest.mark.unit
def test_mcp_preset_handlers_accept_context() -> None:
    import inspect

    preset = _build_omichub_tools_preset()
    handler = preset["handlers"]["omichub_prepare_rna_seq_submission"]
    sig = inspect.signature(handler)
    assert "context" in sig.parameters
