"""完整分析流水线 MCP 工具。"""

from __future__ import annotations

from typing import Any

from client.api_client import OmicHubAPIClient, OmicHubAPIError
from fastmcp import FastMCP


def _failure(error: OmicHubAPIError) -> dict[str, Any]:
    return {
        "success": False,
        "error": error.detail,
        "error_code": error.status_code,
        "guidance": "请根据错误信息修正参数或确认当前 API Key 对工作区数据具有访问权限。",
    }


def register(mcp: FastMCP, api: OmicHubAPIClient) -> None:
    async def prepare(pipeline_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await api.prepare_pipeline(pipeline_type, payload)
        except OmicHubAPIError as error:
            return _failure(error)

    async def submit(pipeline_type: str, prepared_params: dict[str, Any]) -> dict[str, Any]:
        try:
            return await api.submit_pipeline(pipeline_type, prepared_params)
        except OmicHubAPIError as error:
            return _failure(error)

    async def status(pipeline_type: str, task_id: str) -> dict[str, Any]:
        try:
            return await api.get_pipeline_status(pipeline_type, task_id)
        except OmicHubAPIError as error:
            return _failure(error)

    async def results(
        pipeline_type: str, task_id: str, result_types: list[str] | None
    ) -> dict[str, Any]:
        try:
            return await api.get_pipeline_results(
                pipeline_type, task_id, result_types or ["summary", "artifacts"]
            )
        except OmicHubAPIError as error:
            return _failure(error)

    @mcp.tool()
    async def rna_seq_prepare(
        raw_data_path: str,
        species: str,
        genome_version: str,
        sample_sheet: list[dict[str, Any]],
        comparisons: list[dict[str, Any]],
        library_type: str,
        project_name: str,
        extra_parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """校验 RNA-seq 参数和工作区数据，返回可提交的 prepared_params。"""
        payload = locals()
        payload["extra_parameters"] = extra_parameters or {}
        return await prepare("rna_seq", payload)

    @mcp.tool()
    async def rna_seq_submit(prepared_params: dict[str, Any]) -> dict[str, Any]:
        """提交经过 rna_seq_prepare 预检的 RNA-seq 任务。"""
        return await submit("rna_seq", prepared_params)

    @mcp.tool()
    async def rna_seq_status(task_id: str) -> dict[str, Any]:
        """查询 RNA-seq 任务状态和进度。"""
        return await status("rna_seq", task_id)

    @mcp.tool()
    async def rna_seq_results(
        task_id: str, result_types: list[str] | None = None
    ) -> dict[str, Any]:
        """获取 RNA-seq 结果摘要、差异基因统计和产物清单。"""
        return await results("rna_seq", task_id, result_types)

    @mcp.tool()
    async def atac_seq_prepare(
        raw_data_path: str,
        species: str,
        genome_version: str,
        sample_sheet: list[dict[str, Any]],
        comparisons: list[dict[str, Any]],
        library_type: str,
        project_name: str,
        extra_parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """校验 ATAC-seq 参数和工作区数据，返回可提交的 prepared_params。"""
        payload = locals()
        payload["extra_parameters"] = extra_parameters or {}
        return await prepare("atac_seq", payload)

    @mcp.tool()
    async def atac_seq_submit(prepared_params: dict[str, Any]) -> dict[str, Any]:
        """提交经过 atac_seq_prepare 预检的 ATAC-seq 任务。"""
        return await submit("atac_seq", prepared_params)

    @mcp.tool()
    async def atac_seq_status(task_id: str) -> dict[str, Any]:
        """查询 ATAC-seq 任务状态和进度。"""
        return await status("atac_seq", task_id)

    @mcp.tool()
    async def atac_seq_results(
        task_id: str, result_types: list[str] | None = None
    ) -> dict[str, Any]:
        """获取 ATAC-seq 结果摘要和产物清单。"""
        return await results("atac_seq", task_id, result_types)

    @mcp.tool()
    async def list_available_pipelines() -> dict[str, Any]:
        """列出当前平台可通过 MCP 调用的完整分析流程。"""
        try:
            pipelines = await api.list_available_pipelines()
            return {"success": True, "pipelines": pipelines}
        except OmicHubAPIError as error:
            return _failure(error)

    @mcp.tool()
    async def check_workspace_data(analysis_type: str, data_path: str) -> dict[str, Any]:
        """检查当前 API Key 所属用户工作区内的数据完整性。"""
        try:
            return await api.check_workspace_data(analysis_type, data_path)
        except OmicHubAPIError as error:
            return _failure(error)
