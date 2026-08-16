"""任务管理工具"""

from fastmcp import FastMCP

from client.api_client import OmicHubAPIClient, OmicHubAPIError


def register(mcp: FastMCP, api: OmicHubAPIClient) -> None:

    @mcp.tool()
    async def omichub_list_tasks(status: str = "") -> dict:
        """列出用户的分析任务。可按状态过滤: pending/queued/running/success/failed/cancelled。"""
        try:
            data = await api.list_tasks(status=status or None)
            tasks = data.get("tasks", data) if isinstance(data, dict) else data
            summary_lines = []
            for t in (tasks if isinstance(tasks, list) else []):
                summary_lines.append(
                    f"- [{t.get('status', '?')}] {t.get('name', t.get('id', '?'))} "
                    f"(flow={t.get('flow_id', '?')}, progress={t.get('progress', 0):.0%})"
                )
            return {
                "success": True,
                "summary": f"共 {len(summary_lines)} 个任务:\n" + "\n".join(summary_lines[:20]),
                "data": data,
            }
        except OmicHubAPIError as e:
            return {"success": False, "summary": f"获取任务列表失败: {e.detail}"}

    @mcp.tool()
    async def omichub_get_task(task_id: str) -> dict:
        """获取任务详情：状态、进度、参数、时间、错误信息。"""
        try:
            t = await api.get_task(task_id)
            status = t.get("status", "unknown")
            progress = t.get("progress", 0)
            summary = (
                f"任务: {t.get('name', task_id)}\n"
                f"状态: {status} | 进度: {progress:.0%}\n"
                f"流程: {t.get('flow_id', '?')}\n"
                f"创建: {t.get('created_at', '?')}\n"
            )
            if t.get("error_message"):
                summary += f"错误: {t['error_message']}\n"
            if t.get("work_dir"):
                summary += f"工作目录: {t['work_dir']}\n"
            return {"success": True, "summary": summary, "data": t}
        except OmicHubAPIError as e:
            return {"success": False, "summary": f"获取任务失败: {e.detail}"}

    @mcp.tool()
    async def omichub_get_task_progress(task_id: str) -> dict:
        """获取任务当前进度百分比和状态。用于轮询监控任务执行。"""
        try:
            t = await api.get_task(task_id)
            status = t.get("status", "unknown")
            progress = t.get("progress", 0)
            is_done = status in ("success", "failed", "cancelled")
            summary = f"状态: {status} | 进度: {progress:.0%}"
            if is_done:
                summary += " | 已完成"
            else:
                summary += " | 执行中，可稍后再次查询"
            return {
                "success": True,
                "summary": summary,
                "data": {"status": status, "progress": progress, "is_done": is_done},
                "next_steps": [] if is_done else ["稍后再次调用 omichub_get_task_progress 查看进度"],
            }
        except OmicHubAPIError as e:
            return {"success": False, "summary": f"查询进度失败: {e.detail}"}

    @mcp.tool()
    async def omichub_get_task_logs(task_id: str, lines: int = 50) -> dict:
        """获取任务执行日志（最近 N 条）。用于排查失败原因或了解执行进展。"""
        try:
            t = await api.get_task(task_id)
            logs = t.get("logs", [])
            recent = logs[-lines:] if len(logs) > lines else logs
            log_text = "\n".join(
                f"[{l.get('level', 'INFO')}] {l.get('message', '')}" for l in recent
            )
            return {
                "success": True,
                "summary": f"最近 {len(recent)} 条日志:\n{log_text}" if recent else "暂无日志",
                "data": {"logs": recent, "total": len(logs)},
            }
        except OmicHubAPIError as e:
            return {"success": False, "summary": f"获取日志失败: {e.detail}"}

    @mcp.tool()
    async def omichub_cancel_task(task_id: str, user_confirmed: bool = False) -> dict:
        """取消正在运行或排队的任务。需要 user_confirmed=True 确认执行。"""
        if not user_confirmed:
            return {
                "success": True,
                "summary": "即将取消任务。请确认无误后设置 user_confirmed=True 重新调用。",
                "needs_confirmation": True,
                "data": {"task_id": task_id},
            }
        try:
            result = await api.cancel_task(task_id)
            return {"success": True, "summary": f"任务已取消", "data": result}
        except OmicHubAPIError as e:
            return {"success": False, "summary": f"取消失败: {e.detail}"}

    @mcp.tool()
    async def omichub_get_task_dag(task_id: str) -> dict:
        """获取任务的 Snakemake DAG 工作流图（DOT 格式文本）。"""
        try:
            data = await api.get_task_dag(task_id)
            dot = data.get("dot", data.get("dag", ""))
            return {
                "success": True,
                "summary": f"DAG 包含 {dot.count('->')} 条边" if dot else "无 DAG 数据",
                "data": data,
            }
        except OmicHubAPIError as e:
            return {"success": False, "summary": f"获取 DAG 失败: {e.detail}"}
