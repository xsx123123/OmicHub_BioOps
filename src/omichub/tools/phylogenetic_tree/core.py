"""系统发育树构建核心逻辑（与队列解耦）。

同时被 Celery task 与 ARQ job 调用；通过 progress_callback 上报进度。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from omichub.core.config import get_settings

logger = logging.getLogger(__name__)

PHASE_WEIGHTS = {
    "alignment": 0.35,
    "tree_building": 0.40,
    "bootstrap": 0.20,
    "formatting": 0.05,
}


def _noop_progress(phase: str, progress: float, message: str) -> None:
    pass


async def _call_progress(
    callback: Callable[[str, float, str], Any],
    phase: str,
    progress: float,
    message: str,
) -> None:
    """兼容同步与异步 progress callback。"""
    if asyncio.iscoroutinefunction(callback):
        await callback(phase, progress, message)
    else:
        callback(phase, progress, message)


def _make_runner_callback(
    progress: Callable[[str, float, str], Any],
    phase: str,
    base: float,
    weight: float,
) -> Callable[[float, str], None]:
    """构造给 runner 的同步回调；在异步上下文中调度 _call_progress。"""

    def callback(p: float, msg: str) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_call_progress(progress, phase, base + p * weight, msg))
        except RuntimeError:
            # 无运行事件循环时直接同步调用（不应发生，build_tree 始终在 async 上下文）
            if asyncio.iscoroutinefunction(progress):
                asyncio.run(_call_progress(progress, phase, base + p * weight, msg))
            else:
                progress(phase, base + p * weight, msg)

    return callback


async def build_tree(
    task_id: str,
    task_input: dict[str, Any],
    progress_callback: Callable[[str, float, str], Any] | None = None,
) -> dict[str, Any]:
    """执行系统发育树构建，返回结果字典。"""
    from omichub.tools.phylogenetic_tree.runner import (
        compute_tree_statistics,
        format_results,
        run_alignment,
        run_bootstrap,
        run_tree_building,
    )

    progress = progress_callback or _noop_progress
    start_time = time.time()
    phases_completed: list[str] = []

    configured_run_dir = task_input.get("work_dir")
    output_dir: Path | None = None
    if configured_run_dir:
        run_dir = Path(str(configured_run_dir))
        work_dir = run_dir / "work"
        output_dir = run_dir / "output"
    else:
        settings = get_settings()
        work_dir = Path(settings.storage_path) / "results" / "phylo" / task_id
    work_dir.mkdir(parents=True, exist_ok=True)
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    try:
        # ═══ PHASE 1: 多序列比对 ═══
        if task_input.get("alignment_tool") != "prealigned":
            await _call_progress(progress, "ALIGNING", 0.05, "开始多序列比对...")
            run_alignment(
                task_input,
                work_dir,
                callback=_make_runner_callback(
                    progress, "ALIGNING", 0.05, PHASE_WEIGHTS["alignment"]
                ),
            )
            phases_completed.append("alignment")
        else:
            await _call_progress(progress, "ALIGNING", 0.05, "输入已比对，跳过 MSA")
            run_alignment(task_input, work_dir)
            phases_completed.append("alignment_skipped")

        # ═══ PHASE 2: 进化树构建 ═══
        await _call_progress(progress, "BUILDING", 0.40, "开始构建进化树...")
        run_tree_building(
            task_input,
            work_dir,
            callback=_make_runner_callback(
                progress, "BUILDING", 0.40, PHASE_WEIGHTS["tree_building"]
            ),
        )
        phases_completed.append("tree_building")

        # ═══ PHASE 3: Bootstrap ═══
        if task_input.get("bootstrap_enabled") and task_input.get("tree_method") in (
            "nj",
            "upgma",
            "iqtree",
        ):
            await _call_progress(progress, "BOOTSTRAPPING", 0.80, "开始 Bootstrap 评估...")
            run_bootstrap(
                task_input,
                work_dir,
                callback=_make_runner_callback(
                    progress, "BOOTSTRAPPING", 0.80, PHASE_WEIGHTS["bootstrap"]
                ),
            )
            phases_completed.append("bootstrap")
        else:
            phases_completed.append("bootstrap_skipped")

        # ═══ PHASE 4: 结果格式化 ═══
        await _call_progress(progress, "FORMATTING", 0.95, "格式化输出结果...")
        output_files = format_results(task_input, work_dir)
        if output_dir is not None:
            delivered_files: dict[str, str] = {}
            for format_key, source_path in output_files.items():
                source = Path(source_path)
                destination = output_dir / source.name
                await asyncio.to_thread(shutil.copy2, source, destination)
                delivered_files[format_key] = str(destination)
            output_files = delivered_files
        newick_path = (
            Path(output_files["newick"])
            if isinstance(output_files["newick"], str)
            else output_files["newick"]
        )
        tree_stats = compute_tree_statistics(newick_path)
        phases_completed.append("formatting")

        await _call_progress(progress, "COMPLETED", 1.0, "任务完成！")

        return {
            "task_id": task_id,
            "status": "COMPLETED",
            "output_files": output_files,
            "statistics": tree_stats,
            "execution_time": round(time.time() - start_time, 2),
            "phases_completed": phases_completed,
        }

    except Exception as exc:
        logger.exception("构建系统发育树失败")
        return {
            "status": "FAILED",
            "error": str(exc),
            "phases_completed": phases_completed,
        }
