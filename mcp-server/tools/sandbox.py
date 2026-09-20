"""沙箱执行工具"""

from fastmcp import FastMCP

from client.api_client import CygnusXAPIClient, CygnusXAPIError
from core.config import settings


def register(mcp: FastMCP, api: CygnusXAPIClient) -> None:

    @mcp.tool()
    async def cygnusx_sandbox_create(language: str = "python") -> dict:
        """创建/复用沙箱会话（Python/R），预装常用科学计算库。

        :param language: 编程语言："python"（默认）/"R"
        :param session_id: 会话 ID（留空则自动创建新会话）
        :return: JSON 格式会话信息，含 session_id、language、status

        示例:
            await cygnusx_sandbox_create("python")
            # 创建 Python 沙箱会话
        """
        try:
            data = await api.sandbox_create_session(language)
            session_id = data.get("id", "?")
            return {
                "success": True,
                "summary": (
                    f"沙箱会话就绪: {session_id}\n"
                    f"语言: {language} | 状态: {data.get('status', '?')}\n"
                    f"环境: mambaforge (scanpy, anndata, Seurat, DESeq2 等已安装)\n"
                    f"使用 cygnusx_sandbox_execute 执行代码。"
                ),
                "data": data,
            }
        except CygnusXAPIError as e:
            return {"success": False, "summary": f"创建沙箱失败: {e.detail}"}

    @mcp.tool()
    async def cygnusx_sandbox_execute(code: str, session_id: str = "", timeout: int = 300) -> dict:
        """在沙箱中执行代码（超时 300 秒）。

        :param code: 要执行的代码字符串
        :param session_id: 会话 ID（留空使用默认会话）
        :param timeout: 执行超时时间（秒），clamp 到 300
        :return: JSON 格式执行结果，含 stdout、stderr、exit_code

        示例:
            await cygnusx_sandbox_execute("import scanpy; print('OK')", session_id="sess_1")
            # 执行 Python 代码并返回输出
        """
        timeout = max(1, min(timeout, settings.sandbox_timeout))
        try:
            if not session_id:
                session = await api.sandbox_create_session("python")
                session_id = session.get("id", "")

            result = await api.sandbox_execute(session_id, code, timeout)
            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")
            error = result.get("error")
            images = result.get("images", [])
            echarts = result.get("echarts", [])

            if error:
                return {
                    "success": False,
                    "summary": f"执行错误: {error}\n{stderr[-1000:] if stderr else ''}",
                    "data": result,
                }

            summary_parts = []
            if stdout:
                tail = stdout[-2000:] if len(stdout) > 2000 else stdout
                summary_parts.append(f"输出:\n{tail}")
            if stderr:
                summary_parts.append(f"警告/错误:\n{stderr[-500:]}")
            if images:
                summary_parts.append(f"生成 {len(images)} 张图片")
            if echarts:
                summary_parts.append(f"生成 {len(echarts)} 个图表")

            return {
                "success": True,
                "summary": "\n".join(summary_parts) or "执行完成（无输出）",
                "data": {
                    "stdout": stdout[-3000:] if len(stdout) > 3000 else stdout,
                    "stderr": stderr[-1000:] if len(stderr) > 1000 else stderr,
                    "images_count": len(images),
                    "echarts_count": len(echarts),
                    "session_id": session_id,
                },
                "next_steps": [
                    f"分析完成后调用 cygnusx_sandbox_destroy(session_id='{session_id}') 释放容器资源",
                ],
            }
        except CygnusXAPIError as e:
            return {"success": False, "summary": f"沙箱执行失败: {e.detail}"}

    @mcp.tool()
    async def cygnusx_sandbox_list() -> dict:
        """列出所有活跃沙箱会话。

        :return: JSON 格式会话列表，含 session_id、language、created_at

        示例:
            await cygnusx_sandbox_list()
            # 返回所有活跃会话
        """
        try:
            data = await api.sandbox_list_sessions()
            sessions = data if isinstance(data, list) else []
            lines = [
                f"- {s.get('id', '?')} ({s.get('language', '?')}, {s.get('status', '?')})"
                for s in sessions
            ]
            return {
                "success": True,
                "summary": "沙箱会话:\n" + "\n".join(lines) if lines else "无活跃会话",
                "data": data,
            }
        except CygnusXAPIError as e:
            return {"success": False, "summary": f"获取会话列表失败: {e.detail}"}

    @mcp.tool()
    async def cygnusx_sandbox_destroy(session_id: str) -> dict:
        """销毁指定会话，释放资源。

        :param session_id: 要销毁的会话 ID
        :return: JSON 格式结果，含 success、summary

        示例:
            await cygnusx_sandbox_destroy("sess_1")
            # 删除指定会话
        """
        try:
            await api.sandbox_delete_session(session_id)
            return {"success": True, "summary": f"会话 {session_id} 已销毁"}
        except CygnusXAPIError as e:
            return {"success": False, "summary": f"销毁失败: {e.detail}"}
