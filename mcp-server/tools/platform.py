"""平台信息工具"""

from fastmcp import FastMCP

from client.api_client import CygnusXAPIClient, CygnusXAPIError


def register(mcp: FastMCP, api: CygnusXAPIClient) -> None:

    @mcp.tool()
    async def cygnusx_get_user_info() -> dict:
        """获取当前用户信息与存储配额。

        :return: JSON 格式用户信息，含 user_id、storage_quota、storage_used

        示例:
            await cygnusx_get_user_info()
            # 返回用户信息和存储使用情况
        """
        try:
            user = await api.get_me()
            quota = await api.get_quota()
            used_gb = quota.get("used", 0) / 1024 / 1024 / 1024
            total_gb = quota.get("total", 0) / 1024 / 1024 / 1024
            summary = (
                f"用户: {user.get('username', '?')} ({user.get('email', '?')})\n"
                f"角色: {user.get('role', '?')}\n"
                f"存储: {used_gb:.1f}GB / {total_gb:.1f}GB ({quota.get('percent', 0):.0%})\n"
            )
            return {"success": True, "summary": summary, "data": {"user": user, "quota": quota}}
        except CygnusXAPIError as e:
            return {"success": False, "summary": f"获取用户信息失败: {e.detail}"}

    @mcp.tool()
    async def cygnusx_get_platform_status() -> dict:
        """获取平台概览：任务统计、可用流程数量、存储总量。

        :return: JSON 格式平台状态，含 task_stats、pipeline_count、storage_total

        示例:
            await cygnusx_get_platform_status()
            # 返回平台运行状态摘要
        """
        try:
            tasks = await api.list_tasks()
            flows = await api.list_flows()
            quota = await api.get_quota()

            task_list = tasks.get("tasks", tasks) if isinstance(tasks, dict) else tasks
            flow_list = flows.get("flows", flows) if isinstance(flows, dict) else flows

            status_counts: dict[str, int] = {}
            for t in (task_list if isinstance(task_list, list) else []):
                s = t.get("status", "unknown")
                status_counts[s] = status_counts.get(s, 0) + 1

            status_lines = [f"  {k}: {v}" for k, v in status_counts.items()]
            summary = (
                f"平台状态:\n"
                f"  可用流程: {len(flow_list) if isinstance(flow_list, list) else '?'} 个\n"
                f"  任务统计:\n" + "\n".join(status_lines) + "\n"
                f"  存储使用: {quota.get('percent', 0):.0%}\n"
            )
            return {
                "success": True,
                "summary": summary,
                "data": {"tasks": status_counts, "quota": quota},
            }
        except CygnusXAPIError as e:
            return {"success": False, "summary": f"获取平台状态失败: {e.detail}"}
