"""报告工具"""

from fastmcp import FastMCP

from client.api_client import CygnusXAPIClient, CygnusXAPIError


def register(mcp: FastMCP, api: CygnusXAPIClient) -> None:

    @mcp.tool()
    async def cygnusx_list_reports(flow_id: str = "", keyword: str = "") -> dict:
        """列出所有分析报告，可按流程 ID 或关键词过滤。

        :param flow_id: 流程 ID 过滤（可选）
        :param keyword: 关键词过滤（可选）
        :return: JSON 格式报告列表，含 report_id、title、flow_id、created_at

        示例:
            await cygnusx_list_reports(flow_id="scrna_v2", keyword="cluster")
            # 返回特定流程的报告列表
        """
        try:
            filters = {}
            if flow_id:
                filters["flow_id"] = flow_id
            if keyword:
                filters["keyword"] = keyword
            data = await api.list_reports(**filters)
            reports = data.get("reports", data) if isinstance(data, dict) else data
            lines = []
            for r in (reports if isinstance(reports, list) else [])[:20]:
                lines.append(
                    f"- {r.get('title', r.get('name', '?'))} "
                    f"(flow={r.get('flow_id', '?')}, created={r.get('created_at', '?')[:10]})"
                )
            return {
                "success": True,
                "summary": f"报告列表:\n" + "\n".join(lines) if lines else "暂无报告",
                "data": data,
            }
        except CygnusXAPIError as e:
            return {"success": False, "summary": f"获取报告列表失败: {e.detail}"}

    @mcp.tool()
    async def cygnusx_get_report(report_id: str) -> dict:
        """获取报告详情：标题、关联流程、文件列表、创建时间。

        :param report_id: 报告 ID
        :return: JSON 格式报告详情，含 title、flow_id、files、created_at

        示例:
            await cygnusx_get_report("report_123")
            # 返回报告元数据和文件清单
        """
        try:
            data = await api.get_report(report_id)
            files = data.get("files", [])
            file_names = [f.get("filename", f.get("name", "?")) for f in files[:10]]
            summary = (
                f"报告: {data.get('title', report_id)}\n"
                f"流程: {data.get('flow_id', '?')}\n"
                f"创建: {data.get('created_at', '?')}\n"
                f"文件: {', '.join(file_names)}\n"
            )
            return {"success": True, "summary": summary, "data": data}
        except CygnusXAPIError as e:
            return {"success": False, "summary": f"获取报告失败: {e.detail}"}

    @mcp.tool()
    async def cygnusx_get_report_content(report_id: str) -> dict:
        """获取报告的 HTML 主文件内容。

        :param report_id: 报告 ID
        :return: HTML 字符串内容

        示例:
            await cygnusx_get_report_content("report_123")
            # 返回报告 HTML 内容
        """
        try:
            content = await api.get_report_content(report_id)
            if isinstance(content, str):
                preview = content[:3000]
                return {
                    "success": True,
                    "summary": f"报告内容 (前 3000 字符):\n{preview}",
                    "data": {"length": len(content), "preview": preview},
                }
            return {"success": True, "summary": "报告内容已获取", "data": content}
        except CygnusXAPIError as e:
            return {"success": False, "summary": f"获取报告内容失败: {e.detail}"}
