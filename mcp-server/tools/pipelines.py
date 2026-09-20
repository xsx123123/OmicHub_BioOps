"""完整分析流水线 MCP 工具。"""

from __future__ import annotations

from typing import Any

from client.api_client import CygnusXAPIClient, CygnusXAPIError
from fastmcp import FastMCP


def _failure(error: CygnusXAPIError) -> dict[str, Any]:
    return {
        "success": False,
        "summary": f"调用失败: {error.detail}",
        "error": error.detail,
        "error_code": error.status_code,
        "guidance": "请根据错误信息修正参数或确认当前 API Key 对工作区数据具有访问权限。",
    }


def _needs_confirmation(
    pipeline_label: str, prepared_params: dict[str, Any]
) -> dict[str, Any]:
    """写操作确认门 — 与 tools/analysis.py 的 needs_confirmation 摘要风格一致。"""
    sample_sheet = prepared_params.get("sample_sheet")
    comparisons = prepared_params.get("comparisons")
    return {
        "success": True,
        "needs_confirmation": True,
        "summary": (
            "即将提交分析任务:\n"
            f"  流程: {pipeline_label}\n"
            f"  项目: {prepared_params.get('project_name') or '(未命名)'}\n"
            f"  样本数: {len(sample_sheet) if sample_sheet else 0}\n"
            f"  比较组: {len(comparisons) if comparisons else 0}\n"
            "请确认参数无误后设置 user_confirmed=True 重新调用。"
        ),
        "data": {"prepared_params": prepared_params},
    }


def register(mcp: FastMCP, api: CygnusXAPIClient) -> None:
    async def prepare(pipeline_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await api.prepare_pipeline(pipeline_type, payload)
        except CygnusXAPIError as error:
            return _failure(error)

    async def submit(pipeline_type: str, prepared_params: dict[str, Any]) -> dict[str, Any]:
        try:
            return await api.submit_pipeline(pipeline_type, prepared_params)
        except CygnusXAPIError as error:
            return _failure(error)

    async def status(pipeline_type: str, task_id: str) -> dict[str, Any]:
        try:
            return await api.get_pipeline_status(pipeline_type, task_id)
        except CygnusXAPIError as error:
            return _failure(error)

    async def results(
        pipeline_type: str, task_id: str, result_types: list[str] | None
    ) -> dict[str, Any]:
        try:
            return await api.get_pipeline_results(
                pipeline_type, task_id, result_types or ["summary", "artifacts"]
            )
        except CygnusXAPIError as error:
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
    ) -> dict[str, Any]:async def rna_seq_prepare(
        raw_data_path: str,
        species: str,
        genome_version: str,
        sample_sheet: list[dict[str, Any]],
        comparisons: list[dict[str, Any]],
        library_type: str,
        project_name: str,
        extra_parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
"""校验 RNA-seq 参数和工作区数据，返回可提交的 prepared_params。

:param flow_id: Flow ID
:param sample_sheet: Sample sheet
:param parameters: Params
:return: JSON format result

示例:
    await rna_seq_prepare("rna_v2", "samples.csv", {})
    # Prepare RNA-seq
"""
        payload = locals()
        payload["extra_parameters"] = extra_parameters or {}
        return await prepare("rna_seq", payload)

    @mcp.tool()
    async def rna_seq_submit(
        prepared_params: dict[str, Any], user_confirmed: bool = False
    ) -> dict[str, Any]:async def rna_seq_submit(
        prepared_params: dict[str, Any], user_confirmed: bool = False
    ) -> dict[str, Any]:
"""提交经过 rna_seq_prepare 预检的 RNA-seq 任务。需要 user_confirmed=True 确认执行。"""

:param flow_id: Flow ID
:param name: Name
:param parameters: Params
:param sample_sheet: Sample sheet
:param comparisons: Comparisons
:param user_confirmed: Confirmed
:return: JSON format result

示例:
    await rna_seq_submit("rna_v2", "my_task", {}, [], [], True)
    # Submit RNA-seq
"""
        if not user_confirmed:
            return _needs_confirmation("rna_seq", prepared_params)
        return await submit("rna_seq", prepared_params)

    @mcp.tool()
    async def rna_seq_status(task_id: str) -> dict[str, Any]:
        """查询 RNA-seq 任务状态和进度。
        
        :param task_id: 任务唯一标识符
        :return: JSON 格式的任务状态
        
        示例:
            await rna_seq_status("task_123456")
            # 返回任务当前状态
        """
        return await status("rna_seq", task_id)

    @mcp.tool()
    async def rna_seq_results(
        task_id: str, result_types: list[str] | None = None
    ) -> dict[str, Any]:async def rna_seq_results(
        task_id: str, result_types: list[str] | None = None
    ) -> dict[str, Any]:
"""获取 RNA-seq 结果摘要、差异基因统计和产物清单。"""

:param task_id: Task ID
:return: JSON format result

示例:
    await rna_seq_results("task_123")
    # Return results
"""
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
    ) -> dict[str, Any]:async def atac_seq_prepare(
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

:param flow_id: Flow ID
:param sample_sheet: Sample sheet
:param parameters: Params
:return: JSON format result

示例:
    await atac_seq_prepare("atac_v2", "samples.csv", {})
    # Prepare ATAC-seq
"""
        payload = locals()
        payload["extra_parameters"] = extra_parameters or {}
        return await prepare("atac_seq", payload)

    @mcp.tool()
    async def atac_seq_submit(
        prepared_params: dict[str, Any], user_confirmed: bool = False
    ) -> dict[str, Any]:async def atac_seq_submit(
        prepared_params: dict[str, Any], user_confirmed: bool = False
    ) -> dict[str, Any]:
"""提交经过 atac_seq_prepare 预检的 ATAC-seq 任务。需要 user_confirmed=True 确认执行。"""

:param flow_id: Flow ID
:param name: Name
:param parameters: Params
:param sample_sheet: Sample sheet
:param user_confirmed: Confirmed
:return: JSON format result

示例:
    await atac_seq_submit("atac_v2", "my_task", {}, [], True)
    # Submit ATAC-seq
"""
        if not user_confirmed:
            return _needs_confirmation("atac_seq", prepared_params)
        return await submit("atac_seq", prepared_params)

    @mcp.tool()
    async def atac_seq_status(task_id: str) -> dict[str, Any]:async def atac_seq_status(task_id: str) -> dict[str, Any]:
"""查询 ATAC-seq 任务状态和进度。"""

:param task_id: Task ID
:return: JSON format result

示例:
    await atac_seq_status("task_123")
    # Return status
"""
        return await status("atac_seq", task_id)

    @mcp.tool()
    async def atac_seq_results(
        task_id: str, result_types: list[str] | None = None
    ) -> dict[str, Any]:async def atac_seq_results(
        task_id: str, result_types: list[str] | None = None
    ) -> dict[str, Any]:
"""获取 ATAC-seq 结果摘要和产物清单。"""

:param task_id: Task ID
:return: JSON format result

示例:
    await atac_seq_results("task_123")
    # Return results
"""
        return await results("atac_seq", task_id, result_types)

    @mcp.tool()
    async def list_available_pipelines() -> dict[str, Any]:async def list_available_pipelines() -> dict[str, Any]:
"""列出当前平台可通过 MCP 调用的完整分析流程。"""

:param category: Category (optional)
:return: JSON format result

示例:
    await list_available_pipelines("rna_seq")
    # Return pipelines
"""
        try:
            pipelines = await api.list_available_pipelines()
            return {"success": True, "pipelines": pipelines}
        except CygnusXAPIError as error:
            return _failure(error)

    @mcp.tool()
    async def check_workspace_data(analysis_type: str, data_path: str) -> dict[str, Any]:async def check_workspace_data(analysis_type: str, data_path: str) -> dict[str, Any]:
"""检查当前 API Key 所属用户工作区内的数据完整性。"""

:param workspace_path: Workspace path
:return: JSON format result

示例:
    await check_workspace_data("/workspace")
    # Check data integrity
"""
        try:
            return await api.check_workspace_data(analysis_type, data_path)
        except CygnusXAPIError as error:
            return _failure(error)
