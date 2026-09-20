"""文件浏览工具"""

from fastmcp import FastMCP

from client.api_client import CygnusXAPIClient, CygnusXAPIError
from core.config import settings


def register(mcp: FastMCP, api: CygnusXAPIClient) -> None:

    @mcp.tool()
    async def list_workspace_files(path: str = "", pattern: str = "") -> dict:
        """列出当前用户工作区目录的文件和文件夹，返回 file_id、类型、大小和修改时间。

:param path: 目录路径（可选，默认根目录）
:param pattern: 文件名模式过滤器（可选，如:'*.txt'）
:return: JSON 格式的文件列表，包含 file_id、type、size、mtime

示例:
    await list_workspace_files("/data", "*.fastq")
    # 返回/data 目录下所有 fastq 文件
"""
        try:
            data = await api.list_workspace_files(path=path or None, pattern=pattern or None)
            return {
                "success": True,
                "summary": data.get("summary", "工作区文件列表"),
                "data": data,
            }
        except CygnusXAPIError as e:
            return {"success": False, "summary": f"列出工作区文件失败: {e.detail}"}

    @mcp.tool()
    async def search_workspace_files(query: str, limit: int = 50) -> dict:
        """递归按文件名模糊搜索当前用户工作区文件。

:param query: 搜索关键词
:param limit: 最多返回结果数，默认 50
:return: JSON 格式的搜索结果，包含 items 列表

示例:
    await search_workspace_files("sample_01", limit=20)
    # 返回包含 sample_01 的文件
"""
        try:
            data = await api.search_workspace_files(query=query, limit=limit)
            items = data.get("items", []) if isinstance(data, dict) else []
            lines = [
                f"- {item.get('name', '?')} · {item.get('relative_path', '')} · "
                f"file_id={item.get('file_id', '')}"
                for item in items
            ]
            return {
                "success": True,
                "summary": data.get("summary", "搜索结果:\n" + "\n".join(lines)),
                "data": data,
            }
        except CygnusXAPIError as e:
            return {"success": False, "summary": f"搜索工作区文件失败: {e.detail}"}

    @mcp.tool()
    async def cygnusx_list_files(directory: str = "") -> dict:
        """列出用户文件，可按目录过滤。

:param directory: 目录路径（可选）
:return: JSON 格式的文件列表

示例:
    await cygnusx_list_files("/workspace/project1")
    # 返回指定目录下的文件列表
"""
        try:
            data = await api.list_files(directory=directory or None)
            files = data.get("files", data) if isinstance(data, dict) else data
            lines = []
            for f in (files if isinstance(files, list) else [])[:50]:
                size = f.get("size", 0)
                size_str = f"{size / 1024 / 1024:.1f}MB" if size > 1024 * 1024 else f"{size / 1024:.1f}KB"
                lines.append(f"- {f.get('filename', f.get('name', '?'))} ({size_str})")
            return {
                "success": True,
                "summary": f"文件列表 ({len(lines)} 个):\n" + "\n".join(lines),
                "data": data,
            }
        except CygnusXAPIError as e:
            return {"success": False, "summary": f"获取文件列表失败: {e.detail}"}

    @mcp.tool()
    async def cygnusx_get_file_tree() -> dict:async def cygnusx_get_file_tree() -> dict:
"""获取用户完整文件树（按来源分组：upload/download/pipeline 等）。"""

:return: JSON format result

示例:
    await cygnusx_get_file_tree()
    # Return complete file tree
"""
        try:
            data = await api.get_file_tree()
            groups = list(data.keys()) if isinstance(data, dict) else []
            return {
                "success": True,
                "summary": f"文件树分组: {', '.join(groups)}",
                "data": data,
            }
        except CygnusXAPIError as e:
            return {"success": False, "summary": f"获取文件树失败: {e.detail}"}

    @mcp.tool()
    async def cygnusx_list_directories() -> dict:async def cygnusx_list_directories() -> dict:
"""列出用户的所有目录。"""

:return: JSON format result

示例:
    await cygnusx_list_directories()
    # Return all directories
"""
        try:
            data = await api.list_directories()
            dirs = data if isinstance(data, list) else data.get("directories", [])
            lines = [f"- {d.get('path', d.get('name', '?'))}" for d in dirs[:30]]
            return {
                "success": True,
                "summary": "目录列表:\n" + "\n".join(lines),
                "data": data,
            }
        except CygnusXAPIError as e:
            return {"success": False, "summary": f"获取目录失败: {e.detail}"}

    @mcp.tool()
    async def cygnusx_get_task_outputs(task_id: str) -> dict:async def cygnusx_get_task_outputs(task_id: str) -> dict:
"""获取已完成任务的输出文件列表。任务结果绑定在用户目录下。"""

:param task_id: Task ID
:return: JSON format result

示例:
    await cygnusx_get_task_outputs("task_123")
    # Return task outputs
"""
        try:
            task = await api.get_task(task_id)
            work_dir = task.get("work_dir", "")
            result_path = task.get("result_path", "")
            status = task.get("status", "")

            if status != "success":
                return {
                    "success": False,
                    "summary": f"任务状态为 {status}，尚无输出。需等待任务成功完成。",
                }

            return {
                "success": True,
                "summary": (
                    f"任务输出:\n"
                    f"  工作目录: {work_dir}\n"
                    f"  结果路径: {result_path}\n"
                    f"使用 cygnusx_read_file_content 读取具体文件内容。"
                ),
                "data": {"work_dir": work_dir, "result_path": result_path, "task": task},
                "next_steps": [
                    "使用 cygnusx_read_file_content 读取结果文件 (如 DEG 表格、QC 报告)",
                    "使用 cygnusx_sandbox_execute 在沙箱中加载数据进行深入分析",
                ],
            }
        except CygnusXAPIError as e:
            return {"success": False, "summary": f"获取任务输出失败: {e.detail}"}

    @mcp.tool()
    async def cygnusx_read_file_content(file_path: str, max_lines: int = 50) -> dict:async def cygnusx_read_file_content(file_path: str, max_lines: int = 50) -> dict:
"""读取用户目录下文本文件的前 N 行。路径相对于用户数据根目录。

:param file_path: File path
:param max_lines: Max lines
:return: JSON format result

示例:
    await cygnusx_read_file_content("/path.txt", 50)
    # Return file content
"""
        max_lines = max(1, min(max_lines, settings.max_file_preview_lines))
        try:
            data = await api.preview_file(file_path, max_lines=max_lines)
            lines = data.get("lines", [])
            content = "\n".join(lines)
            truncated = data.get("truncated", False)
            summary = f"文件: {file_path}\n"
            if truncated:
                summary += f"(截断，仅显示前 {max_lines} 行)\n"
            summary += content
            return {"success": True, "summary": summary, "data": data}
        except CygnusXAPIError as e:
            return {"success": False, "summary": f"读取文件失败: {e.detail}"}
