"""Unified Run monitoring and plan confirmation tools."""

from fastmcp import FastMCP

from client.api_client import CygnusXAPIClient, CygnusXAPIError


def register(mcp: FastMCP, api: CygnusXAPIClient) -> None:
    @mcp.tool()
    async def cygnusx_list_runs(project_slug: str = "", status: str = "") -> dict:
        """列出统一 Run，可按项目或状态过滤。"""
        try:
            data = await api.list_runs(project_slug or None, status or None)
            return {"success": True, "summary": f"共 {len(data)} 个 Run", "data": data}
        except CygnusXAPIError as exc:
            return {"success": False, "summary": f"获取 Run 失败: {exc.detail}"}

    @mcp.tool()
    async def cygnusx_get_run_status(run_id: str) -> dict:
        """获取 Run 计划状态和关联 task_id。"""
        try:
            data = await api.get_run(run_id)
            return {"success": True, "summary": f"Run 状态: {data.get('status')}", "data": data}
        except CygnusXAPIError as exc:
            return {"success": False, "summary": f"获取 Run 状态失败: {exc.detail}"}

    @mcp.tool()
    async def cygnusx_get_run_logs(run_id: str, limit: int = 200) -> dict:
        """获取 Run 的持久化事件日志。"""
        try:
            data = await api.get_run_events(run_id, max(1, min(limit, 500)))
            return {"success": True, "summary": f"共 {len(data.get('events', []))} 条事件", "data": data}
        except CygnusXAPIError as exc:
            return {"success": False, "summary": f"获取 Run 事件失败: {exc.detail}"}

    @mcp.tool()
    async def cygnusx_verify_artifact(run_id: str) -> dict:
        """查询 Run 已登记的产物及其平台校验 checksum。"""
        try:
            data = await api.get_run_artifacts(run_id)
            return {"success": True, "summary": f"共 {len(data.get('artifacts', []))} 个产物", "data": data}
        except CygnusXAPIError as exc:
            return {"success": False, "summary": f"查询产物失败: {exc.detail}"}

    @mcp.tool()
    async def cygnusx_confirm_run_plan(run_id: str, user_confirmed: bool = False) -> dict:
        """确认 Run 计划；必须由用户明确确认，Agent 不得自行确认。"""
        if not user_confirmed:
            return {"success": True, "needs_confirmation": True, "summary": "请在用户明确同意后再次调用。"}
        try:
            data = await api.confirm_run(run_id, True)
            return {"success": True, "summary": "Run 已确认并进入任务队列", "data": data}
        except CygnusXAPIError as exc:
            return {"success": False, "summary": f"确认 Run 失败: {exc.detail}"}
