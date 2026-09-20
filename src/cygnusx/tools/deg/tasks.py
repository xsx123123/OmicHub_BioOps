"""DEG 差异表达分析 Celery 任务。

Web 进程只创建 ``tasks`` 记录并投递本任务；R Docker 容器（DESeq2/edgeR）仅由
独立计算 Worker 启动（tools_design.md §5.1.2：Web 不持有 Docker 权限）。
"""

from __future__ import annotations

import asyncio
import csv
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from celery import shared_task

from cygnusx.domain.task.value_objects import TaskStatus
from cygnusx.infrastructure.database.models.task import TaskModel
from cygnusx.infrastructure.database.session import get_session_factory
from cygnusx.tools.deg.runner import DegDockerRunner, DegRunParams
from cygnusx.tools.deg.schema import (
    DegContrastResultDTO,
    DegContrastStatDTO,
    DegGeneRowDTO,
    DegResultDTO,
)
from cygnusx.tools.deg.service import FLOW_ID, RESULTS_SUBDIR, TOP_GENES_PER_CONTRAST

logger = logging.getLogger(__name__)


@shared_task(  # type: ignore[untyped-decorator]
    bind=True,
    name="cygnusx.tools.deg.tasks.run_deg_task",
    queue="analysis",
    time_limit=7800,
    soft_time_limit=7500,
)
def run_deg_task(self: Any, task_id: str) -> dict[str, Any]:
    """在计算 Worker 中运行 R Docker，并将可序列化结果写回通用任务表。"""
    return asyncio.run(_run_deg(task_id))


async def _run_deg(task_id: str) -> dict[str, Any]:
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        return {"status": "failed", "task_id": task_id, "error": "非法 DEG 任务 ID"}

    factory = get_session_factory()
    async with factory() as db:
        task = await db.get(TaskModel, task_uuid)
        if task is None or task.flow_id != FLOW_ID:
            return {"status": "failed", "task_id": task_id, "error": "DEG 任务不存在"}
        if task.status == TaskStatus.CANCELLED.value:
            return {"status": "cancelled", "task_id": task_id}

        task.status = TaskStatus.RUNNING.value
        task.progress = 10
        task.started_at = datetime.now(UTC)
        task.error_message = ""
        await db.commit()

        try:
            parameters = task.parameters or {}
            engine = str(parameters.get("engine_resolved") or "deseq2")
            if engine not in {"deseq2", "edger"}:
                raise RuntimeError(f"未知引擎: {engine}")
            input_files = parameters.get("input_files") or {}
            work_dir = Path(task.work_dir)
            input_dir = work_dir / "input"
            results_dir = work_dir / RESULTS_SUBDIR
            results_dir.mkdir(parents=True, exist_ok=True)

            counts_path = input_dir / str(input_files.get("counts") or "counts.csv")
            metadata_path = input_dir / str(input_files.get("metadata") or "metadata.csv")
            pairs_path = input_dir / str(input_files.get("pairs") or "pairs.csv")
            if not counts_path.exists() or not metadata_path.exists() or not pairs_path.exists():
                raise RuntimeError("任务输入文件缺失，请重新提交")

            annotation = input_files.get("annotation")
            task.progress = 30
            await db.commit()

            params = DegRunParams(
                engine=engine,
                counts_path=str(counts_path),
                metadata_path=str(metadata_path),
                pairs_path=str(pairs_path),
                output_dir=str(results_dir),
                lfc=float(parameters.get("lfc", 1.0)),
                pval=float(parameters.get("pval", 0.05)),
                bcv=float(parameters.get("bcv", 0.4)),
                annotation_path=str(input_dir / annotation) if annotation else None,
            )
            container_name = f"cygnusx-deg-{task_id[:8]}"
            run_result = await DegDockerRunner().run(params, container_name)
            if run_result.returncode != 0:
                raise RuntimeError(_failure_summary(results_dir, engine, run_result.stderr, run_result.stdout))

            task.progress = 80
            await db.commit()

            result = _parse_results(results_dir, engine, task_id)
            stats_path = results_dir / "All_Contrast_DEG_Statistics.csv"
            task.status = TaskStatus.SUCCESS.value
            task.progress = 100
            task.finished_at = datetime.now(UTC)
            task.result_path = str(stats_path) if stats_path.exists() else str(results_dir)
            task.parameters = {**parameters, "result": result.model_dump(mode="json")}
            await db.commit()
            return {"status": "completed", "task_id": task_id}
        except Exception as error:  # noqa: BLE001
            logger.exception("DEG 任务失败: %s", task_id)
            task.status = TaskStatus.FAILED.value
            task.progress = 100
            task.finished_at = datetime.now(UTC)
            task.error_message = str(error)[:2000]
            await db.commit()
            return {"status": "failed", "task_id": task_id, "error": task.error_message}


def _failure_summary(
    results_dir: Path, engine: str, stderr: str, stdout: str
) -> str:
    """失败错误摘要：优先取 R 运行日志尾部（对用户友好），回退容器 stderr。"""
    log_name = "edger.log" if engine == "edger" else "deseq2.log"
    log_path = results_dir / log_name
    try:
        if log_path.exists():
            tail = log_path.read_text(encoding="utf-8", errors="replace").strip()
            if tail:
                return f"R 脚本执行失败（日志尾部）:\n{tail[-1500:]}"
    except OSError:
        pass
    detail = (stderr or stdout or "").strip()
    return detail[-2000:] or "R 容器异常退出"


def _parse_results(results_dir: Path, engine: str, task_id: str) -> DegResultDTO:
    """解析 R 脚本产物 → DegResultDTO（统计表 + 每对比 Top 基因 + 产物名单）。"""
    statistics: list[DegContrastStatDTO] = []
    stats_path = results_dir / "All_Contrast_DEG_Statistics.csv"
    if stats_path.exists():
        with stats_path.open("r", encoding="utf-8-sig", newline="") as f:
            for raw in csv.DictReader(f):
                statistics.append(
                    DegContrastStatDTO(
                        contrast=_s(raw.get("Contrast")),
                        control=_s(raw.get("Control")),
                        treat=_s(raw.get("Treat")),
                        method=_s(raw.get("Method")),
                        dispersion_assumption=_s(raw.get("Dispersion_Assumption")),
                        n_control=_i(raw.get("N_Control")),
                        n_treat=_i(raw.get("N_Treat")),
                        up_regulated=_i(raw.get("Up_Regulated")),
                        down_regulated=_i(raw.get("Down_Regulated")),
                        total_deg=_i(raw.get("Total_DEG")),
                    )
                )

    contrasts: list[DegContrastResultDTO] = []
    for stat in statistics:
        name = stat.contrast
        deg_csv = results_dir / f"{name}_DEG.csv"
        top_genes: list[DegGeneRowDTO] = []
        total_genes = 0
        if deg_csv.exists():
            with deg_csv.open("r", encoding="utf-8-sig", newline="") as f:
                for raw in csv.DictReader(f):
                    total_genes += 1
                    if len(top_genes) < TOP_GENES_PER_CONTRAST:
                        top_genes.append(
                            DegGeneRowDTO(
                                ensembl=_s(raw.get("ENSEMBL")),
                                symbol=_s(raw.get("Symbol")) or _s(raw.get("ENSEMBL")),
                                log2_fc=_f(raw.get("log2FoldChange")),
                                pvalue=_f(raw.get("pvalue"), default=1.0),
                                padj=_f_opt(raw.get("padj")),
                                base_mean=_f_opt(raw.get("baseMean")),
                                log_cpm=_f_opt(raw.get("logCPM")),
                            )
                        )
        contrasts.append(
            DegContrastResultDTO(
                name=name,
                stat=stat,
                top_genes=top_genes,
                total_genes=total_genes,
                deg_csv=f"{name}_DEG.csv" if deg_csv.exists() else "",
                volcano_png=_if_exists(results_dir, f"{name}_Volcano.png"),
                volcano_labeled_png=_if_exists(results_dir, f"{name}_Volcano_add_gene_id.png"),
            )
        )

    artifacts = sorted(
        p.name for p in results_dir.iterdir() if p.is_file()
    ) if results_dir.exists() else []

    return DegResultDTO(
        task_id=task_id,
        engine=engine,  # type: ignore[arg-type]
        no_replicate_contrasts=[
            c.name for c in contrasts if c.stat.method == "edgeR-NoRep"
        ],
        statistics=statistics,
        contrasts=contrasts,
        pca_png=_if_exists(results_dir, "Global_PCA_Combined.png"),
        artifacts=artifacts,
        log_file=_if_exists(results_dir, "edger.log" if engine == "edger" else "deseq2.log"),
    )


def _if_exists(directory: Path, name: str) -> str:
    return name if (directory / name).exists() else ""


def _s(v: object) -> str:
    return str(v).strip() if v not in (None, "") else ""


def _f(v: object, default: float = 0.0) -> float:
    try:
        return float(str(v).strip()) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _f_opt(v: object) -> float | None:
    if v in (None, "", "NA", "NaN"):
        return None
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _i(v: object) -> int:
    try:
        return int(float(str(v).strip())) if v not in (None, "") else 0
    except (TypeError, ValueError):
        return 0
