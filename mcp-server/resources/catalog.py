"""MCP Resources — 只读数据源"""

import json

from fastmcp import FastMCP

from client.api_client import CygnusXAPIClient, CygnusXAPIError


def register(mcp: FastMCP, api: CygnusXAPIClient) -> None:

    @mcp.resource("cygnusx://flows/catalog")
    async def flow_catalog() -> str:
        """所有可用分析流程的 JSON 目录"""
        try:
            data = await api.list_flows()
            return json.dumps(data, ensure_ascii=False, indent=2)
        except CygnusXAPIError as e:
            return json.dumps({"error": str(e.detail)})

    @mcp.resource("cygnusx://user/storage")
    async def user_storage() -> str:
        """用户存储配额和目录结构"""
        try:
            quota = await api.get_quota()
            dirs = await api.list_directories()
            return json.dumps({"quota": quota, "directories": dirs}, ensure_ascii=False, indent=2)
        except CygnusXAPIError as e:
            return json.dumps({"error": str(e.detail)})

    @mcp.resource("cygnusx://tasks/{task_id}/outputs")
    async def task_outputs(task_id: str) -> str:
        """指定任务的输出文件信息"""
        try:
            task = await api.get_task(task_id)
            return json.dumps(
                {
                    "task_id": task_id,
                    "status": task.get("status"),
                    "work_dir": task.get("work_dir"),
                    "result_path": task.get("result_path"),
                },
                ensure_ascii=False,
                indent=2,
            )
        except CygnusXAPIError as e:
            return json.dumps({"error": str(e.detail)})

    @mcp.resource("cygnusx://reports/{report_id}")
    async def report_meta(report_id: str) -> str:
        """报告元数据"""
        try:
            data = await api.get_report(report_id)
            return json.dumps(data, ensure_ascii=False, indent=2, default=str)
        except CygnusXAPIError as e:
            return json.dumps({"error": str(e.detail)})
