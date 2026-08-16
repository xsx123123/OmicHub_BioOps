"""沙箱执行工具"""

from fastmcp import FastMCP

from client.api_client import OmicHubAPIClient, OmicHubAPIError


def register(mcp: FastMCP, api: OmicHubAPIClient) -> None:

    @mcp.tool()
    async def omichub_sandbox_create(language: str = "python") -> dict:
        """创建或复用沙箱会话。沙箱环境: mambaforge + Python 3.11 + scanpy/anndata/R/Seurat。

        Args:
            language: 编程语言 - "python" 或 "r"
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
                    f"使用 omichub_sandbox_execute 执行代码。"
                ),
                "data": data,
            }
        except OmicHubAPIError as e:
            return {"success": False, "summary": f"创建沙箱失败: {e.detail}"}

    @mcp.tool()
    async def omichub_sandbox_execute(code: str, session_id: str = "", timeout: int = 300) -> dict:
        """在沙箱中执行代码。沙箱已预装生物信息学依赖 (scanpy, anndata, DESeq2, Seurat 等)。

        适用场景:
        - 加载分析结果进行二次分析 (差异基因筛选、富集分析)
        - 生成自定义可视化 (火山图、热图、PCA)
        - 运行统计检验或机器学习模型
        - 数据格式转换和质控

        Args:
            code: 要执行的代码 (Python 或 R)
            session_id: 沙箱会话 ID (空则自动创建)
            timeout: 超时秒数 (默认 300)
        """
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
            }
        except OmicHubAPIError as e:
            return {"success": False, "summary": f"沙箱执行失败: {e.detail}"}

    @mcp.tool()
    async def omichub_sandbox_list() -> dict:
        """列出当前活跃的沙箱会话。"""
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
        except OmicHubAPIError as e:
            return {"success": False, "summary": f"获取会话列表失败: {e.detail}"}

    @mcp.tool()
    async def omichub_sandbox_destroy(session_id: str) -> dict:
        """销毁沙箱会话，释放容器资源。"""
        try:
            await api.sandbox_delete_session(session_id)
            return {"success": True, "summary": f"会话 {session_id} 已销毁"}
        except OmicHubAPIError as e:
            return {"success": False, "summary": f"销毁失败: {e.detail}"}
