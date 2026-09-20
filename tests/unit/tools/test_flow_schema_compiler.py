"""FlowToolSchemaCompiler 单元测试。"""

from __future__ import annotations

import pytest

from cygnusx.application.services.flow_service import FlowService
from cygnusx.tools.flow_schema_compiler import FlowToolSchemaCompiler


@pytest.fixture
def compiler() -> FlowToolSchemaCompiler:
    return FlowToolSchemaCompiler()


@pytest.fixture
def rna_flow():
    return FlowService().get_flow_config("rna_seq")


@pytest.mark.unit
def test_compile_prepare_tool_for_rna_seq(compiler: FlowToolSchemaCompiler, rna_flow) -> None:
    tool_def = compiler.compile_prepare_tool(rna_flow)

    assert tool_def["name"] == "cygnusx_prepare_rna_seq_submission"
    assert "RNA-seq" in tool_def["description"]

    schema = tool_def["input_schema"]
    assert schema["type"] == "object"
    assert "name" in schema["required"]
    assert "parameters" in schema["required"]
    assert "sample_sheet" in schema["required"]
    assert schema["properties"]["name"]["minLength"] == 1

    params = schema["properties"]["parameters"]
    assert params["type"] == "object"
    assert "project_name" in params["properties"]
    assert "Genome_Version" in params["properties"]
    assert params["properties"]["Genome_Version"].get("enum") is not None


@pytest.mark.unit
def test_compile_sample_sheet_schema(compiler: FlowToolSchemaCompiler, rna_flow) -> None:
    sample_schema = compiler._compile_sample_sheet(rna_flow.sample_sheet)

    assert "oneOf" in sample_schema
    assert sample_schema["oneOf"][0]["pattern"] == "^sample_sheet_ref://"
    assert sample_schema["oneOf"][1]["type"] == "array"

    item_schema = sample_schema["oneOf"][1]["items"]
    assert "sample" in item_schema["properties"]
    assert "group" in item_schema["required"]


@pytest.mark.unit
def test_compile_comparisons_schema(compiler: FlowToolSchemaCompiler, rna_flow) -> None:
    comp_schema = compiler._compile_comparisons(rna_flow)

    assert comp_schema["type"] == "array"
    assert "Control" in comp_schema["items"]["properties"]
    assert "Treat" in comp_schema["items"]["properties"]
    assert comp_schema["items"]["required"] == ["name", "Control", "Treat"]


@pytest.mark.unit
def test_compile_status_and_summary_tools(compiler: FlowToolSchemaCompiler) -> None:
    status = compiler.compile_status_tool()
    assert status["name"] == "cygnusx_get_analysis_task_status"
    assert "task_id" in status["input_schema"]["required"]

    summary = compiler.compile_summary_tool()
    assert summary["name"] == "cygnusx_get_analysis_task_summary"
    assert "task_id" in summary["input_schema"]["required"]


@pytest.mark.unit
def test_dynamic_tools_loaded_by_schema_loader() -> None:
    from cygnusx.tools.schema_loader import schema_loader

    tool = schema_loader.get_tool("cygnusx_prepare_rna_seq_submission")
    assert tool is not None
    assert tool.invocation_mode == "analysis_flow"
    assert tool.extra["flow_id"] == "rna_seq"

    names = {t.name for t in schema_loader.list_tools()}
    assert "cygnusx_prepare_rna_seq_submission" in names
    assert "cygnusx_prepare_atac_seq_submission" in names
    assert "cygnusx_get_analysis_task_status" in names
    assert "cygnusx_get_analysis_task_summary" in names
