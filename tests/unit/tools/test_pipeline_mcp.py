"""omichub-pipelines MCP 参数映射与状态转换测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.schemas.pipeline import PipelinePrepareRequest
from omichub.application.schemas.tool_invocation import ToolInvocationContext
from omichub.application.services.pipeline_controller import PipelineController
from omichub.application.services.pipeline_result_service import PipelineResultService
from omichub.infrastructure.mcp.pipeline_preset import build_pipeline_preset


class _FakeAsyncSession(AsyncSession):
    def __init__(self):
        pass


def _context() -> ToolInvocationContext:
    return ToolInvocationContext(
        user_id="00000000-0000-0000-0000-000000000001",
        session_id="pipeline-test",
        db=_FakeAsyncSession(),  # type: ignore[arg-type]
    )


def _prepare_request() -> PipelinePrepareRequest:
    return PipelinePrepareRequest(
        raw_data_path="inbox/rna",
        species="Homo sapiens",
        genome_version="hg38",
        sample_sheet=[
            {"sample": "S1", "sample_name": "Control", "group": "control"},
            {"sample": "S2", "sample_name": "Treat", "group": "treat"},
        ],
        comparisons=[{"name": "TvsC", "Control": "control", "Treat": "treat"}],
        library_type="fr-unstranded",
        task_name="MCP RNA task",
        project_name="MCP RNA",
    )


def test_pipeline_preset_exposes_required_tools() -> None:
    preset = build_pipeline_preset()
    names = {tool["name"] for tool in preset["tools"]}
    assert names == {
        "rna_seq_prepare",
        "rna_seq_submit",
        "rna_seq_status",
        "rna_seq_results",
        "atac_seq_prepare",
        "atac_seq_submit",
        "atac_seq_status",
        "atac_seq_results",
        "list_available_pipelines",
        "check_workspace_data",
    }
    assert set(preset["handlers"]) == names

    rna_prepare = next(tool for tool in preset["tools"] if tool["name"] == "rna_seq_prepare")
    schema = rna_prepare["inputSchema"]
    assert "task_name" in schema["required"]
    assert schema["properties"]["task_name"]["minLength"] == 1


@pytest.mark.asyncio
async def test_rna_prepare_maps_public_parameters_to_existing_flow() -> None:
    controller = PipelineController(_context())
    controller._flow_service.prepare = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "valid": True,
            "confirmation_id": "confirm-1",
            "resource_hint": {"cores": 8},
        }
    )
    controller.check_workspace_data = AsyncMock(  # type: ignore[method-assign]
        return_value={"valid": True, "warnings": [], "errors": [], "fastq_count": 4}
    )
    controller._resolve_workspace_path = lambda _path: Path("/tmp/rna")  # type: ignore[method-assign]
    controller._missing_sample_files = lambda _path, _sheet: []  # type: ignore[method-assign]

    result = await controller.prepare("rna_seq", _prepare_request())

    controller._flow_service.prepare.assert_awaited_once()
    flow_id, arguments = controller._flow_service.prepare.await_args.args
    assert flow_id == "rna_seq"
    assert arguments["parameters"]["Genome_Version"] == "hg38"
    assert arguments["parameters"]["Library_Types"] == "fr-unstranded"
    assert arguments["name"] == "MCP RNA task"
    assert arguments["sample_sheet"][0]["sample"] == "S1"
    assert result["prepared_params"] == {
        "confirmation_id": "confirm-1",
        "pipeline_type": "rna_seq",
    }


@pytest.mark.asyncio
async def test_pipeline_status_normalizes_terminal_state() -> None:
    controller = PipelineController(_context())
    task = SimpleNamespace(flow_id="rna_seq")
    controller._flow_service.get_task_status = AsyncMock(  # type: ignore[method-assign]
        return_value={"task_id": "11111111-1111-1111-1111-111111111111", "status": "success", "progress": 1.0}
    )
    with patch(
        "omichub.application.services.pipeline_controller.TaskService.get_task",
        new_callable=AsyncMock,
        return_value=task,
    ):
        result = await controller.status("rna_seq", "11111111-1111-1111-1111-111111111111")

    assert result["is_terminal"] is True
    assert result["pipeline_type"] == "rna_seq"
    assert result["result_url"].endswith("/results")


def test_result_summary_counts_up_and_down_regulated_rows(tmp_path) -> None:
    table = tmp_path / "DEG_results.csv"
    table.write_text(
        "gene,log2FoldChange\nA,2.1\nB,-1.2\nC,0\n",
        encoding="utf-8",
    )
    text = table.read_text(encoding="utf-8")
    assert PipelineResultService._summarize_differential_text(text, "csv") == {
        "differential_gene_count": 3,
        "upregulated_count": 1,
        "downregulated_count": 1,
    }


def test_prepare_detects_samples_without_matching_fastq(tmp_path) -> None:
    (tmp_path / "S1_R1.fastq.gz").write_bytes(b"")
    missing = PipelineController._missing_sample_files(
        tmp_path,
        [{"sample": "S1"}, {"sample": "S2"}],
    )
    assert missing == ["S2"]
