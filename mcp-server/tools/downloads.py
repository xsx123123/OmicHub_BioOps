"""数据下载工具 — 公共数据库（SRA/GEO）高速下载 + 多云存储下载 + 直链下载"""

from fastmcp import FastMCP

from client.api_client import CygnusXAPIClient, CygnusXAPIError


def register(mcp: FastMCP, api: CygnusXAPIClient) -> None:

    @mcp.tool()
    async def cygnusx_submit_download(
        source: str = "sra",
        accession: str = "",
        download_method: str = "aws",
        multithreads: int = 4,
        aws_threads: int = 8,
        cloud_provider: str = "",
        object_uri: str = "",
        recursive: bool = True,
        links: list[str] | None = None,
        target_directory: str = "",
        dry_run: bool = False,
        user_confirmed: bool = False,
    ) -> dict:
        """提交数据下载任务，产物落到用户工作区 raw_data 目录（可选子目录）。

        支持三类来源（source）：
        1. "sra"（默认）— 公共数据库高速下载，走 EBIDownload 引擎：
           - 支持 NCBI SRA/GEO 系列登录号：项目号（PRJNA/PRJEB/PRJ 开头，如 PRJNA1285930）、
             测序 run（SRR/ERR/DRR 开头）、GEO 样本（GSM 开头）等；
           - download_method: "aws"（推荐，S3 全球镜像最快）/ "aspera" / "ftp"；
           - multithreads: 并发下载 run 数（1-32），aws_threads: 单文件 AWS 并发线程（1-64）；
           - dry_run=True 可先试跑验证登录号，不实际下载。
        2. "cloud_storage" — 云服务商对象存储高速下载：
           - cloud_provider: "aliyun"（oss://）/ "volc"（tos://）/ "huawei"（obs://）；
           - object_uri 必须以对应前缀开头，如 oss://bucket/path；recursive 控制是否递归目录。
        3. "direct_link" — HTTP/HTTPS/FTP 直链批量下载：
           - links 传下载链接列表（禁止内网地址）。

        :param source: 下载来源："sra"（公共数据库）/"cloud_storage"（云存储）/"direct_link"（直链）
        :param accession: 公共数据库登录号（PRJNA…/PRJEB…/SRR…/ERR…/DRR…/GSM…），source="sra" 时必填
        :param download_method: SRA 下载方式 "aws"（默认，最快）/"aspera"/"ftp"，仅 source="sra" 有效
        :param multithreads: 并发下载 run 数，默认 4
        :param aws_threads: 单文件 AWS 并发线程数，默认 8
        :param cloud_provider: 云商 "aliyun"/"volc"/"huawei"，source="cloud_storage" 时必填
        :param object_uri: 对象路径（oss:// / tos:// / obs:// 前缀），source="cloud_storage" 时必填
        :param recursive: 云存储目录是否递归下载，默认 True
        :param links: HTTP/HTTPS/FTP 下载链接列表，source="direct_link" 时必填
        :param target_directory: 下载到用户 raw_data 下的子目录（如 "project_x"），留空=raw_data 根目录
        :param dry_run: True 时仅模拟下载（仅 SRA），用于校验登录号
        :param user_confirmed: 设为 True 确认提交（提交任务前必须经用户确认）
        :return: JSON 格式结果，含 success、summary、data、next_steps

        示例:
            await cygnusx_submit_download("sra", "GSE12345", "aws", aws_threads=16, user_confirmed=True)
            # 提交 GSE12345 的 AWS 高速下载任务
        """
        if not user_confirmed:
            if source == "sra":
                desc = f"{accession}（{download_method} 高速下载）"
            elif source == "cloud_storage":
                desc = f"{cloud_provider}: {object_uri}"
            else:
                desc = f"{len(links or [])} 个直链"
            target = f" -> raw_data/{target_directory}" if target_directory else " -> raw_data"
            return {
                "success": True,
                "needs_confirmation": True,
                "summary": (
                    f"即将提交下载任务: [{source}] {desc}{target}\n"
                    "请向用户确认后，再以 user_confirmed=True 重新调用。"
                ),
                "data": {"source": source, "accession": accession, "object_uri": object_uri},
            }

        payload: dict = {"source": source}
        if source == "sra":
            payload["accession"] = accession
            payload["download_method"] = download_method
            payload["multithreads"] = multithreads
            payload["aws_threads"] = aws_threads
            payload["dry_run"] = dry_run
        elif source == "cloud_storage":
            payload["cloud_provider"] = cloud_provider
            payload["object_uri"] = object_uri
            payload["recursive"] = recursive
        else:
            payload["links"] = links or []
        if target_directory:
            payload["target_directory"] = target_directory

        try:
            result = await api.submit_download(payload)
            task_id = result.get("id", "?")
            return {
                "success": True,
                "summary": (
                    f"下载任务已提交! 任务 ID: {task_id}\n"
                    f"产物目录: 用户 raw_data/{target_directory or ''}（完成后自动登记到数据管理）"
                ),
                "data": result,
                "next_steps": [
                    f"调用 cygnusx_get_download_progress(task_id='{task_id}') 查看逐 run 下载进度",
                    "也可用 cygnusx_list_downloads 查看全部下载任务状态",
                ],
            }
        except CygnusXAPIError as e:
            return {"success": False, "summary": f"提交下载失败: {e.detail}"}

    @mcp.tool()
    async def cygnusx_list_downloads() -> dict:
        """列出用户的数据下载任务（名称、状态、进度、产物目录）。

        :return: JSON 格式结果，含 success、summary、data

        示例:
            await cygnusx_list_downloads()
            # 返回所有下载任务列表
        """
        try:
            data = await api.list_downloads()
            tasks = data.get("items", []) if isinstance(data, dict) else data
            lines = []
            for t in (tasks if isinstance(tasks, list) else []):
                progress = t.get("progress") or 0
                lines.append(
                    f"- [{t.get('status', '?')}] {t.get('name', t.get('id', '?'))} "
                    f"(progress={progress:.0%}, id={t.get('id', '?')})"
                )
            return {
                "success": True,
                "summary": "下载任务:\n" + "\n".join(lines) if lines else "暂无下载任务",
                "data": data,
            }
        except CygnusXAPIError as e:
            return {"success": False, "summary": f"获取下载列表失败: {e.detail}"}

    @mcp.tool()
    async def cygnusx_get_download_progress(task_id: str) -> dict:
        """获取下载任务的逐 run 分阶段进度（下载/解压/压缩）。

        返回每个 SRR run 的 stage（downloading/extracting/compressing/completed/failed）
        与总进度百分比；source="unavailable" 表示任务尚未开始运行或进度接口暂不可用。

        :param task_id: 下载任务 ID
        :return: JSON 格式进度详情，含 success、summary、data、overall_percent

        示例:
            await cygnusx_get_download_progress("download_123")
            # 返回任务进度：总进度 75.3%，SRR123: downloading (60.2%), SRR456: completed (100%)
        """
        try:
            data = await api.get_download_progress(task_id)
            runs = data.get("runs") or {}
            lines = []
            for run_id, r in list(runs.items())[:20]:
                percent = r.get("overall_percent", 0)
                lines.append(f"- {run_id}: {r.get('stage', '?')} ({percent:.1f}%)")
            overall = data.get("overall_percent", 0)
            source = data.get("source", "progress_api")
            if source == "unavailable" and not runs:
                return {
                    "success": True,
                    "summary": "进度暂不可用（任务排队中或进度接口未就绪），请稍后再查。",
                    "data": data,
                }
            return {
                "success": True,
                "summary": f"总进度: {overall:.1f}%\n" + "\n".join(lines),
                "data": data,
            }
        except CygnusXAPIError as e:
            return {"success": False, "summary": f"获取下载进度失败: {e.detail}"}
