"""
src/backend/tasks/jbrowse_tasks.py
JBrowse 2 Celery 异步任务
处理文件索引生成、目录扫描等耗时操作
"""

import os
import subprocess
from pathlib import Path
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from core.jbrowse_config import config_manager


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=3600,  # 1小时软限制
    time_limit=7200,       # 2小时硬限制
)
def index_file_task(self, file_path: str):
    """
    为文件生成索引

    支持的文件类型:
    - FASTA -> .fai (samtools faidx)
    - BAM -> .bai (samtools index)
    - CRAM -> .crai (samtools index)
    - VCF.gz -> .tbi (bcftools index -t)
    - BED.gz -> .tbi (tabix -p bed)
    - GFF3.gz -> .tbi (tabix -p gff)

    Args:
        file_path: 需要索引的文件绝对路径

    Returns:
        dict: 索引结果信息
    """
    path = Path(file_path)

    if not path.exists():
        return {"success": False, "error": "文件不存在", "file": file_path}

    ext = "".join(path.suffixes).lower()

    # 根据扩展名选择索引工具
    index_commands = {
        ".fasta": ["samtools", "faidx", str(path)],
        ".fa": ["samtools", "faidx", str(path)],
        ".bam": ["samtools", "index", str(path)],
        ".cram": ["samtools", "index", str(path)],
        ".vcf.gz": ["bcftools", "index", "-t", str(path)],
        ".bed.gz": ["tabix", "-p", "bed", str(path)],
        ".gff3.gz": ["tabix", "-p", "gff", str(path)],
    }

    # 处理 .gz 双扩展名
    if ext.endswith(".gz"):
        base_ext = ext[:-3]
        if base_ext in [".vcf", ".bed", ".gff3"]:
            ext = base_ext + ".gz"

    command = index_commands.get(ext)

    if not command:
        return {
            "success": False,
            "error": f"不支持的文件类型: {ext}",
            "file": file_path
        }

    # 检查是否已存在索引
    index_ext_map = {
        ".fasta": ".fai",
        ".fa": ".fai",
        ".bam": ".bai",
        ".cram": ".crai",
        ".vcf.gz": ".tbi",
        ".bed.gz": ".tbi",
        ".gff3.gz": ".tbi",
    }

    expected_index = str(path) + index_ext_map.get(ext, "")
    if Path(expected_index).exists():
        return {
            "success": True,
            "message": "索引已存在，跳过生成",
            "file": file_path,
            "index": expected_index
        }

    # 执行索引命令
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=3000  # 50分钟超时
        )

        if result.returncode == 0:
            # 验证索引文件是否生成
            if Path(expected_index).exists():
                index_size = Path(expected_index).stat().st_size
                return {
                    "success": True,
                    "message": "索引生成成功",
                    "file": file_path,
                    "index": expected_index,
                    "index_size": index_size,
                    "index_size_human": f"{index_size / 1024 / 1024:.2f} MB"
                }
            else:
                return {
                    "success": False,
                    "error": "命令执行成功但索引文件未生成",
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }
        else:
            # 重试逻辑
            if self.request.retries < self.max_retries:
                raise self.retry(exc=Exception(f"索引失败: {result.stderr}"))

            return {
                "success": False,
                "error": f"索引命令失败 (exit {result.returncode})",
                "stderr": result.stderr,
                "stdout": result.stdout
            }

    except SoftTimeLimitExceeded:
        return {
            "success": False,
            "error": "索引任务超时（超过1小时）",
            "file": file_path
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "索引命令执行超时（50分钟）",
            "file": file_path
        }

    except Exception as e:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)

        return {
            "success": False,
            "error": f"索引异常: {str(e)}",
            "file": file_path
        }


@shared_task
def scan_and_index_user_directory(user_id: str):
    """
    扫描用户目录并自动为缺失索引的文件生成索引

    可配置为 Celery beat 定时任务，每 N 分钟执行一次
    """
    from services.jbrowse_service import jbrowse_service

    config = config_manager.get_config()
    if not config.auto_scan.enabled or not config.auto_scan.auto_index:
        return {"message": "自动扫描或自动索引已禁用"}

    files = jbrowse_service.scan_user_directory(user_id)

    # 筛选出未索引的文件
    to_index = [f for f in files if not f["indexed"] and f["can_load"] is False]

    task_ids = []
    for file_info in to_index:
        task = index_file_task.delay(file_info["path"])
        task_ids.append({
            "file": file_info["path"],
            "task_id": task.id
        })

    return {
        "user_id": user_id,
        "scanned_files": len(files),
        "indexed_files": sum(1 for f in files if f["indexed"]),
        "missing_index": len(to_index),
        "queued_tasks": len(task_ids),
        "tasks": task_ids
    }


@shared_task
def cleanup_old_uploads(user_id: str, days: int = 30):
    """
    清理用户上传目录中超过 N 天的旧文件

    可配置为定时任务，每周执行一次
    """
    import time
    from datetime import datetime, timedelta

    upload_dir = config_manager.get_user_upload_dir(user_id)
    cutoff = datetime.now() - timedelta(days=days)
    cutoff_timestamp = cutoff.timestamp()

    deleted = []
    errors = []

    for file_path in upload_dir.iterdir():
        if file_path.is_file():
            try:
                mtime = file_path.stat().st_mtime
                if mtime < cutoff_timestamp:
                    file_path.unlink()
                    deleted.append(str(file_path))
            except Exception as e:
                errors.append({"file": str(file_path), "error": str(e)})

    return {
        "user_id": user_id,
        "cutoff_date": cutoff.isoformat(),
        "deleted_count": len(deleted),
        "deleted_files": deleted,
        "errors": errors
    }
