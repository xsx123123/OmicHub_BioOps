"""JBrowse 2 Celery 异步任务 —— 文件索引生成 + 用户目录扫描补索引。

索引工具依赖：samtools / bcftools / tabix。worker 镜像未安装对应二进制时，
任务返回明确的失败信息（不抛异常、不重试到死），前端据此提示"请联系管理员安装索引工具"。

任务命名遵循 storage.py 约定：omichub.tools.jbrowse.tasks.<name>，
便于 celery_app.conf.task_routes 统一路由到 analysis 队列。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from omichub.infrastructure.task_queue.dispatcher import enqueue_task

# 扩展名 → 索引命令（首元素为二进制名，便于 shutil.which 探测可用性）
_INDEX_COMMANDS: dict[str, list[str]] = {
    ".fasta": ["samtools", "faidx"],
    ".fa": ["samtools", "faidx"],
    ".bam": ["samtools", "index"],
    ".cram": ["samtools", "index"],
    ".vcf.gz": ["bcftools", "index", "-t"],
    ".bed.gz": ["tabix", "-p", "bed"],
    ".gff3.gz": ["tabix", "-p", "gff"],
}

# 扩展名 → 生成的索引扩展名
_INDEX_EXT: dict[str, str] = {
    ".fasta": ".fai",
    ".fa": ".fai",
    ".bam": ".bai",
    ".cram": ".crai",
    ".vcf.gz": ".tbi",
    ".bed.gz": ".tbi",
    ".gff3.gz": ".tbi",
}


def _norm_ext(path: Path) -> str:
    """归一化扩展名：.vcf.gz 等保留双扩展。"""
    suffixes = path.suffixes
    if not suffixes:
        return ""
    joined = "".join(suffixes).lower()
    if joined.endswith(".gz") and len(suffixes) >= 2:
        return "".join(suffixes[-2:]).lower()
    return suffixes[-1].lower()


@shared_task(
    name="omichub.tools.jbrowse.tasks.index_file",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    soft_time_limit=3600,  # 1 小时软限制
    time_limit=7200,  # 2 小时硬限制
)
def index_file(self, file_path: str) -> dict:
    """为文件生成索引。

    支持类型：FASTA→.fai / BAM→.bai / CRAM→.crai / VCF.gz→.tbi / BED.gz→.tbi / GFF3.gz→.tbi。
    已存在索引时直接跳过；二进制缺失或命令失败时返回失败 dict（不抛异常）。
    """
    path = Path(file_path)
    if not path.exists():
        return {"success": False, "error": "文件不存在", "file": file_path}

    ext = _norm_ext(path)
    cmd_prefix = _INDEX_COMMANDS.get(ext)
    if not cmd_prefix:
        return {"success": False, "error": f"不支持的文件类型: {ext}", "file": file_path}

    # 二进制可用性探测：缺失则直接失败，避免 subprocess 抛 FileNotFoundError 进重试循环
    binary = cmd_prefix[0]
    if not shutil.which(binary):
        return {
            "success": False,
            "error": f"索引工具未安装: {binary}（请在 worker 镜像内安装 samtools/bcftools/tabix）",
            "file": file_path,
        }

    expected_index = str(path) + _INDEX_EXT[ext]
    if Path(expected_index).exists():
        return {
            "success": True,
            "message": "索引已存在，跳过生成",
            "file": file_path,
            "index": expected_index,
        }

    command = [*cmd_prefix, str(path)]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=3000,  # 50 分钟单次命令超时
        )
    except SoftTimeLimitExceeded:
        return {"success": False, "error": "索引任务超时（超过1小时）", "file": file_path}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "索引命令执行超时（50分钟）", "file": file_path}
    except Exception as e:
        # 真正的异常才重试（二进制缺失已在上面拦截）
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e) from e
        return {"success": False, "error": f"索引异常: {e}", "file": file_path}

    if result.returncode != 0:
        # 命令失败：重试一次，仍失败则返回
        if self.request.retries < self.max_retries:
            raise self.retry(exc=Exception(f"索引失败: {result.stderr.strip()}"))
        return {
            "success": False,
            "error": f"索引命令失败 (exit {result.returncode})",
            "stderr": result.stderr,
            "stdout": result.stdout,
            "file": file_path,
        }

    if not Path(expected_index).exists():
        return {
            "success": False,
            "error": "命令执行成功但索引文件未生成",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "file": file_path,
        }

    index_size = Path(expected_index).stat().st_size
    return {
        "success": True,
        "message": "索引生成成功",
        "file": file_path,
        "index": expected_index,
        "index_size": index_size,
        "index_size_human": f"{index_size / 1024 / 1024:.2f} MB",
    }


@shared_task(name="omichub.tools.jbrowse.tasks.scan_and_index")
def scan_and_index(user_id: str) -> dict:
    """扫描用户目录并为缺失索引的文件排队生成索引。

    可由前端「选中所有已索引」旁的批量操作触发，或后续接入 Celery beat 定时执行。
    """
    import asyncio

    return asyncio.run(_scan_and_index(user_id))


async def _scan_and_index(user_id: str) -> dict:
    from omichub.tools.jbrowse.config import config_manager
    from omichub.tools.jbrowse.service import jbrowse_service

    config = config_manager.get_config()
    if not config.auto_scan.enabled or not config.auto_scan.auto_index:
        return {"message": "自动扫描或自动索引已禁用"}

    files = await jbrowse_service.scan_user_directory(user_id)
    to_index = [f for f in files if not f.indexed]

    task_ids = []
    for file_info in to_index:
        task = enqueue_task(index_file, file_info.path)
        task_ids.append({"file": file_info.path, "task_id": task.id})

    return {
        "user_id": user_id,
        "scanned_files": len(files),
        "indexed_files": sum(1 for f in files if f.indexed),
        "missing_index": len(to_index),
        "queued_tasks": len(task_ids),
        "tasks": task_ids,
    }
