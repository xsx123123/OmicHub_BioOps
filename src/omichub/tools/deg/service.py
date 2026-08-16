"""DEG 差异表达分析应用服务 —— 提交编排 + 任务查询 + 产物下载。

编排流程（submit）：
1. 轻量校验上传文件（大小 / 表头 / 分组一致性），解析样本分组与比较对；
2. 引擎解析（与 RNAFlow rules/utils/deg_method.py 同口径）：
   method=auto 时任一比较组最小样本数 < min_replicates → edgeR，否则 DESeq2；
   强制 deseq2 但存在 1v1 比较对时提前报错（DESeq2 无法估计离散度）；
3. 创建项目运行目录并写入输入文件快照；
4. 创建通用 Task 记录（flow_id="deg-analysis"）并投递 Celery analysis 队列；
5. Worker 运行 R 容器（DESeq2/edgeR），解析结果 CSV 回写任务；
6. Web 轮询任务状态，完成时返回统计表 + Top 基因 + 产物名单；失败返回错误摘要。
"""

from __future__ import annotations

import asyncio
import csv
import io
import unicodedata
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.core.config import get_settings
from omichub.core.exceptions import NotFoundError, TaskExecutionError, ValidationError
from omichub.domain.task.value_objects import TaskStatus
from omichub.infrastructure.database.models.task import TaskModel
from omichub.infrastructure.storage.path_factory import project_slug
from omichub.infrastructure.task_queue.dispatcher import enqueue_task
from omichub.tools.deg.config import DegConfig, config_manager
from omichub.tools.deg.schema import (
    DegDefaultsDTO,
    DegResultDTO,
    DegTaskDTO,
)

FLOW_ID = "deg-analysis"
RESULTS_SUBDIR = "output"
TOP_GENES_PER_CONTRAST = 500

_SAMPLE_ALIASES = {"sample", "sample_name", "sampleid", "sample_id"}
_GROUP_ALIASES = {"group", "condition", "group_name"}


class DegService:
    """DEG 差异表达分析服务。"""

    def __init__(self) -> None:
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # 默认参数与示例
    # ------------------------------------------------------------------

    def get_defaults(self) -> DegDefaultsDTO:
        """前端表单默认值（来自外置 YAML，热重载）。"""
        cfg = config_manager.get_config()
        return DegDefaultsDTO(
            method=cfg.defaults.method,
            lfc=cfg.defaults.lfc,
            pval=cfg.defaults.pval,
            bcv=cfg.defaults.bcv,
            min_replicates=cfg.defaults.min_replicates,
            max_counts_file_size_mb=cfg.input_limits.max_counts_file_size_mb,
            max_metadata_file_size_mb=cfg.input_limits.max_metadata_file_size_mb,
            max_pairs_file_size_mb=cfg.input_limits.max_pairs_file_size_mb,
            max_annotation_file_size_mb=cfg.input_limits.max_annotation_file_size_mb,
            min_samples=cfg.input_limits.min_samples,
            max_samples=cfg.input_limits.max_samples,
            max_contrasts=cfg.input_limits.max_contrasts,
            max_genes=cfg.input_limits.max_genes,
        )

    async def get_example(self) -> dict[str, str]:
        """读取 tool_configs/deg/examples 示例输入文本，供前端一键填充。"""
        example_dir = Path(self._settings.deg_config_yaml).parent / "examples"
        payload: dict[str, str] = {}
        for key in ("counts", "metadata", "pairs", "annotation"):
            path = example_dir / f"{key}.csv"
            if path.exists():
                payload[key] = await asyncio.to_thread(path.read_text, encoding="utf-8")
        if not payload:
            raise NotFoundError("DEG 示例数据不存在")
        return payload

    # ------------------------------------------------------------------
    # 提交分析
    # ------------------------------------------------------------------

    async def submit(
        self,
        db: AsyncSession,
        user_id: str,
        project_name: str,
        counts_bytes: bytes,
        counts_filename: str,
        metadata_bytes: bytes,
        metadata_filename: str,
        pairs_bytes: bytes,
        pairs_filename: str,
        annotation_bytes: bytes | None = None,
        annotation_filename: str | None = None,
        method: str = "auto",
        lfc: float = 1.0,
        pval: float = 0.05,
        bcv: float = 0.4,
    ) -> DegTaskDTO:
        """创建通用任务记录并投递 Celery；Web 不直接执行 R 容器。"""
        cfg = config_manager.get_config()
        method_norm = self._validate_params(cfg, method, lfc, pval, bcv)
        normalized_project = self._normalize_project_name(project_name)
        project_slug_value = project_slug(normalized_project, fallback="deg-project")

        # ---- 输入解析与校验（全部在 Web 进程内完成，快速失败） ----
        self._check_size("表达矩阵", counts_bytes, cfg.input_limits.max_counts_file_size_mb)
        self._check_size("样本信息表", metadata_bytes, cfg.input_limits.max_metadata_file_size_mb)
        self._check_size("比较对文件", pairs_bytes, cfg.input_limits.max_pairs_file_size_mb)
        if annotation_bytes is not None:
            self._check_size(
                "注释文件",
                annotation_bytes,
                cfg.input_limits.max_annotation_file_size_mb,
            )

        metadata_rows = self._parse_table(metadata_bytes, metadata_filename, "样本信息表")
        sample_col = self._find_column(metadata_rows, _SAMPLE_ALIASES, "样本信息表", "Sample")
        group_col = self._find_column(metadata_rows, _GROUP_ALIASES, "样本信息表", "Group")
        samples: list[tuple[str, str]] = []
        for row in metadata_rows:
            s = (row.get(sample_col) or "").strip()
            g = (row.get(group_col) or "").strip()
            if s and g:
                samples.append((s, g))
        if len(samples) < cfg.input_limits.min_samples:
            raise ValidationError(
                f"有效样本数不足：至少需要 {cfg.input_limits.min_samples} 个（Sample + Group 均非空）"
            )
        if len(samples) > cfg.input_limits.max_samples:
            raise ValidationError(
                f"样本数超过上限 {cfg.input_limits.max_samples}，请检查样本信息表"
            )

        pairs_rows = self._parse_table(pairs_bytes, pairs_filename, "比较对文件")
        treat_col = self._find_column(pairs_rows, {"treat"}, "比较对文件", "Treat")
        ctrl_col = self._find_column(pairs_rows, {"control", "ctrl"}, "比较对文件", "Control")
        contrasts: list[tuple[str, str]] = []
        for row in pairs_rows:
            t = (row.get(treat_col) or "").strip()
            c = (row.get(ctrl_col) or "").strip()
            if t and c:
                contrasts.append((t, c))
        if not contrasts:
            raise ValidationError("比较对文件没有有效行（需含 Treat / Control 两列）")
        if len(contrasts) > cfg.input_limits.max_contrasts:
            raise ValidationError(f"比较对数量超过上限 {cfg.input_limits.max_contrasts}")

        group_counts: dict[str, int] = {}
        for _, g in samples:
            group_counts[g] = group_counts.get(g, 0) + 1
        missing_groups = sorted({g for pair in contrasts for g in pair if g not in group_counts})
        if missing_groups:
            raise ValidationError(
                f"比较对引用的分组在样本信息表中不存在: {missing_groups}；"
                f"可用分组: {sorted(group_counts)}"
            )

        sample_set = {s for s, _ in samples}
        counts_header = self._parse_counts_header(counts_bytes, counts_filename)
        missing_samples = sorted(sample_set - set(counts_header[1:]))
        if missing_samples:
            raise ValidationError(f"表达矩阵缺少样本信息表中的样本列: {missing_samples}")
        gene_count = self._count_data_rows(counts_bytes)
        if gene_count > cfg.input_limits.max_genes:
            raise ValidationError(
                f"表达矩阵基因行数（{gene_count}）超过上限 {cfg.input_limits.max_genes}"
            )

        # ---- 引擎解析（与 RNAFlow deg_method.py 同口径） ----
        engine, no_rep_contrasts = self._resolve_engine(
            method_norm, group_counts, contrasts, cfg.defaults.min_replicates
        )

        # ---- 任务目录与输入落盘 ----
        task_uuid = uuid.uuid4()
        task_id = str(task_uuid)
        work_dir = self._work_dir(user_id, normalized_project)
        input_dir = work_dir / "input"
        results_dir = work_dir / RESULTS_SUBDIR
        await asyncio.to_thread(results_dir.mkdir, parents=True, exist_ok=True)
        from omichub.application.services.file_service import ensure_directory_chain
        from omichub.infrastructure.storage import get_path_factory

        project_relative = work_dir.relative_to(get_path_factory().user_root(user_id)).as_posix()
        await ensure_directory_chain(db, uuid.UUID(user_id), project_relative)

        counts_name = self._safe_input_name(counts_filename, "counts", {".csv", ".tsv", ".txt"})
        metadata_name = self._safe_input_name(
            metadata_filename, "metadata", {".csv", ".tsv", ".txt"}
        )
        pairs_name = self._safe_input_name(pairs_filename, "pairs", {".csv", ".tsv", ".txt"})
        await asyncio.to_thread(
            self._write_inputs,
            input_dir,
            counts_name,
            counts_bytes,
            metadata_name,
            metadata_bytes,
            pairs_name,
            pairs_bytes,
        )
        annotation_name: str | None = None
        if annotation_bytes is not None:
            annotation_name = self._safe_input_name(
                annotation_filename, "annotation", {".csv", ".tsv", ".txt"}
            )
            await asyncio.to_thread((input_dir / annotation_name).write_bytes, annotation_bytes)

        task = TaskModel(
            id=task_uuid,
            flow_id=FLOW_ID,
            user_id=uuid.UUID(user_id),
            name=normalized_project,
            status=TaskStatus.QUEUED.value,
            parameters={
                "project_name": normalized_project,
                "project_slug": project_slug_value,
                "method_requested": method_norm,
                "engine_resolved": engine,
                "no_replicate_contrasts": no_rep_contrasts,
                "lfc": lfc,
                "pval": pval,
                "bcv": bcv,
                "sample_count": len(samples),
                "contrast_count": len(contrasts),
                "input_files": {
                    "counts": counts_name,
                    "metadata": metadata_name,
                    "pairs": pairs_name,
                    "annotation": annotation_name,
                },
            },
            work_dir=str(work_dir),
            progress=0,
            sample_count=len(samples),
        )
        db.add(task)
        await db.commit()

        try:
            from omichub.tools.deg.tasks import run_deg_task

            enqueue_task(run_deg_task, task_id, task_id=task_id)
        except Exception as error:
            task.status = TaskStatus.FAILED.value
            task.error_message = f"DEG 任务投递失败: {error}"[:2000]
            await db.commit()
            raise TaskExecutionError(task.error_message) from error

        return DegTaskDTO(
            task_id=task_id,
            status="queued",
            progress=0,
            message=(
                f"已解析引擎 {engine.upper()}，任务已投递到 Celery Worker"
                + (f"；无重复(1v1)比较对: {no_rep_contrasts}" if no_rep_contrasts else "")
            ),
            project_name=normalized_project,
            method_requested=method_norm,  # type: ignore[arg-type]
            engine_resolved=engine,  # type: ignore[arg-type]
            no_replicate_contrasts=no_rep_contrasts,
            sample_count=len(samples),
            contrast_count=len(contrasts),
            created_at=task.created_at,
        )

    # ------------------------------------------------------------------
    # 任务查询与产物下载
    # ------------------------------------------------------------------

    async def get_task(self, db: AsyncSession, task_id: str, user_id: str) -> DegTaskDTO:
        task = await self._require_task(db, task_id, user_id)
        if task.status == TaskStatus.SUCCESS.value:
            payload = (task.parameters or {}).get("result")
            if isinstance(payload, dict):
                return DegTaskDTO(
                    task_id=task_id,
                    status="completed",
                    progress=100,
                    message="DEG 分析完成",
                    result=DegResultDTO.model_validate(payload),
                    **self._task_metadata(task),
                )
            return DegTaskDTO(
                task_id=task_id,
                status="failed",
                progress=100,
                error_message="任务已完成但结果缺失",
                **self._task_metadata(task),
            )
        if task.status == TaskStatus.FAILED.value:
            return DegTaskDTO(
                task_id=task_id,
                status="failed",
                progress=int(task.progress or 0),
                error_message=task.error_message or "DEG 分析失败",
                **self._task_metadata(task),
            )
        running = task.status == TaskStatus.RUNNING.value
        return DegTaskDTO(
            task_id=task_id,
            status="running" if running else "queued",
            progress=int(task.progress or 0),
            message="R 容器正在执行差异分析" if running else "等待 Celery Worker 执行",
            **self._task_metadata(task),
        )

    async def list_tasks(self, db: AsyncSession, user_id: str, limit: int = 50) -> list[DegTaskDTO]:
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError as error:
            raise NotFoundError("找不到用户 DEG 任务") from error
        result = await db.execute(
            select(TaskModel)
            .where(TaskModel.user_id == user_uuid, TaskModel.flow_id == FLOW_ID)
            .order_by(TaskModel.created_at.desc())
            .limit(limit)
        )
        return [
            DegTaskDTO(
                task_id=str(task.id),
                status=self._task_status(task),
                progress=int(task.progress or 0),
                message=self._task_message(task),
                error_message=task.error_message or None,
                **self._task_metadata(task),
            )
            for task in result.scalars().all()
        ]

    async def get_artifact(
        self, db: AsyncSession, task_id: str, user_id: str, filename: str
    ) -> tuple[Path, str]:
        """按文件名返回结果产物（限定在任务 results 目录内，防路径穿越）。"""
        task = await self._require_task(db, task_id, user_id)
        if task.status != TaskStatus.SUCCESS.value:
            raise NotFoundError("DEG 结果尚不存在")
        safe_name = Path(filename).name
        if not safe_name or safe_name in {".", ".."}:
            raise NotFoundError("非法产物文件名")
        results_dir = Path(task.work_dir) / RESULTS_SUBDIR
        path = (results_dir / safe_name).resolve()
        if results_dir.resolve() not in path.parents or not path.is_file():
            raise NotFoundError("DEG 产物文件不存在")
        return path, safe_name

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _require_task(self, db: AsyncSession, task_id: str, user_id: str) -> TaskModel:
        try:
            task_uuid = uuid.UUID(task_id)
            user_uuid = uuid.UUID(user_id)
        except ValueError as error:
            raise NotFoundError("找不到 DEG 任务") from error
        result = await db.execute(
            select(TaskModel).where(
                TaskModel.id == task_uuid,
                TaskModel.user_id == user_uuid,
                TaskModel.flow_id == FLOW_ID,
            )
        )
        task = result.scalar_one_or_none()
        if task is None:
            raise NotFoundError("找不到 DEG 任务")
        return task

    @staticmethod
    def _validate_params(cfg: DegConfig, method: str, lfc: float, pval: float, bcv: float) -> str:
        method_norm = (method or "auto").strip().lower()
        if method_norm not in {"auto", "deseq2", "edger"}:
            raise ValidationError(f"不支持的分析方法: {method}（可选 auto / deseq2 / edger）")
        if lfc < 0:
            raise ValidationError("LFC 阈值必须 ≥ 0")
        if not 0 < pval <= 1:
            raise ValidationError("P-value 阈值必须大于 0 且不超过 1")
        if bcv <= 0:
            raise ValidationError("BCV 必须 > 0（它是标准差而非方差）")
        return method_norm

    @staticmethod
    def _resolve_engine(
        method: str,
        group_counts: dict[str, int],
        contrasts: list[tuple[str, str]],
        min_replicates: int,
    ) -> tuple[str, list[str]]:
        """解析实际引擎。返回 (engine, 无重复比较对名单)。

        与 RNAFlow rules/utils/deg_method.py 同口径：比较对命名 {Treat}_vs_{Control}
        沿用 R 脚本产物口径（注意 RNAFlow 内部 load_contrasts 是 {Control}_vs_{Treat}，
        此处按前端/R 产物口径）。
        """
        no_rep = [
            f"{treat}_vs_{ctrl}"
            for treat, ctrl in contrasts
            if min(group_counts.get(ctrl, 0), group_counts.get(treat, 0)) < min_replicates
        ]
        if method == "edger":
            return "edger", no_rep
        if method == "deseq2":
            if no_rep:
                raise ValidationError(
                    f"以下比较组没有生物学重复，DESeq2 无法分析: {no_rep}。"
                    "请改用 method=auto（自动切换 edgeR）或 method=edger。"
                )
            return "deseq2", []
        # auto
        return ("edger" if no_rep else "deseq2"), no_rep

    @staticmethod
    def _check_size(label: str, data: bytes, limit_mb: int) -> None:
        if len(data) > limit_mb * 1024 * 1024:
            raise ValidationError(f"{label}超过大小上限 {limit_mb} MB")

    @staticmethod
    def _decode(data: bytes) -> str:
        return data.decode("utf-8-sig", errors="replace")

    def _parse_table(self, data: bytes, filename: str, label: str) -> list[dict[str, str]]:
        """解析 CSV/TSV 为 DictReader 行；分隔符按扩展名，.txt 自动嗅探。"""
        text = self._decode(data)
        suffix = Path(filename or "").suffix.lower()
        if suffix == ".tsv":
            delimiter = "\t"
        elif suffix == ".csv":
            delimiter = ","
        else:
            first_line = text.splitlines()[0] if text.splitlines() else ""
            delimiter = "\t" if first_line.count("\t") > first_line.count(",") else ","
        try:
            reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
            if not reader.fieldnames:
                raise ValidationError(f"{label}为空或缺少表头")
            return [
                {(k or "").strip(): (v or "").strip() for k, v in row.items() if k}
                for row in reader
            ]
        except csv.Error as error:
            raise ValidationError(f"{label}解析失败: {error}") from error

    @staticmethod
    def _find_column(
        rows: list[dict[str, str]], aliases: set[str], label: str, canonical: str
    ) -> str:
        fields = list(rows[0].keys()) if rows else []
        for f in fields:
            if f.strip().lower() in aliases:
                return f
        raise ValidationError(f"{label}缺少必需列 {canonical}（实际列: {fields}）")

    def _parse_counts_header(self, data: bytes, filename: str) -> list[str]:
        """只解析表达矩阵首行（样本列名），避免大文件全量解析。"""
        text = self._decode(data)
        lines = text.splitlines()
        if not lines:
            raise ValidationError("表达矩阵为空")
        suffix = Path(filename or "").suffix.lower()
        if suffix == ".tsv":
            delimiter = "\t"
        elif suffix == ".csv":
            delimiter = ","
        else:
            delimiter = "\t" if lines[0].count("\t") > lines[0].count(",") else ","
        try:
            header = next(csv.reader([lines[0]], delimiter=delimiter))
        except csv.Error as error:
            raise ValidationError(f"表达矩阵表头解析失败: {error}") from error
        cleaned = [h.strip() for h in header if h.strip()]
        if len(cleaned) < 2:
            raise ValidationError("表达矩阵至少需要 1 列基因 ID + 1 列样本")
        return cleaned

    @staticmethod
    def _count_data_rows(data: bytes) -> int:
        """近似基因行数（换行计数，足够用于上限校验）。"""
        return max(data.count(b"\n") - 1, 0)

    @staticmethod
    def _safe_input_name(filename: str | None, stem: str, allowed_suffixes: set[str]) -> str:
        """保留原扩展名（R 按 .csv 后缀分流 csv/tsv 读取），文件名做安全化。"""
        suffix = Path(filename or "").suffix.lower()
        if suffix not in allowed_suffixes:
            suffix = ".csv"
        return f"{stem}{suffix}"

    @staticmethod
    def _write_inputs(
        input_dir: Path,
        counts_name: str,
        counts_bytes: bytes,
        metadata_name: str,
        metadata_bytes: bytes,
        pairs_name: str,
        pairs_bytes: bytes,
    ) -> None:
        input_dir.mkdir(parents=True, exist_ok=True)
        (input_dir / counts_name).write_bytes(counts_bytes)
        (input_dir / metadata_name).write_bytes(metadata_bytes)
        (input_dir / pairs_name).write_bytes(pairs_bytes)

    @staticmethod
    def _normalize_project_name(project_name: str) -> str:
        value = " ".join(unicodedata.normalize("NFKC", project_name or "").split())
        if not value:
            raise ValidationError("项目名称不能为空")
        if len(value) > 100:
            raise ValidationError("项目名称不能超过 100 个字符")
        return value

    @staticmethod
    def _work_dir(self, user_id: str, project_name: str) -> Path:
        """任务目录：users/{uid}/projects/{project}/runs/deg-时间戳/。"""
        from omichub.infrastructure.storage import get_path_factory

        return get_path_factory().create_project_run_dir(user_id, project_name, "deg")

    @staticmethod
    def _task_status(task: TaskModel) -> str:
        if task.status == TaskStatus.SUCCESS.value:
            return "completed"
        if task.status == TaskStatus.FAILED.value:
            return "failed"
        if task.status == TaskStatus.RUNNING.value:
            return "running"
        return "queued"

    @classmethod
    def _task_message(cls, task: TaskModel) -> str:
        return {
            "completed": "DEG 分析完成",
            "failed": "DEG 分析失败",
            "running": "R 容器正在执行差异分析",
            "queued": "等待 Celery Worker 执行",
        }[cls._task_status(task)]

    @staticmethod
    def _task_metadata(task: TaskModel) -> dict[str, object]:
        parameters = task.parameters or {}
        return {
            "project_name": str(parameters.get("project_name") or task.name or "DEG Project"),
            "method_requested": str(parameters.get("method_requested") or "auto"),
            "engine_resolved": parameters.get("engine_resolved"),
            "no_replicate_contrasts": list(parameters.get("no_replicate_contrasts") or []),
            "sample_count": int(parameters.get("sample_count") or task.sample_count or 0),
            "contrast_count": int(parameters.get("contrast_count") or 0),
            "created_at": task.created_at,
            "finished_at": task.finished_at,
        }
