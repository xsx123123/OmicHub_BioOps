"""富集分析应用服务 —— 物种列表 + 提交编排。

编排流程（submit）：
1. species_id 从 YAML 权威解析 kegg_code/org_db/id_type（不信任前端回传值）；
2. 创建项目运行目录 ``projects/{project}/runs/enrichment-时间戳/``；
3. 基因列表落盘 ``input/gene_list.txt``（每行一个，去空行去重）；
4. 创建通用 Task 记录并投递 Celery Worker；
5. Worker 运行 R 容器后将 CSV 解析为标准结果行并回写任务；
6. Web 查询任务状态，完成时返回结果；失败时返回错误摘要。

前端轮询任务完成后，按 GO / KEGG 来源分别生成 Plotly 气泡图和统计表。
"""

from __future__ import annotations

import asyncio
import csv
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
from omichub.tools.enrichments.config import (
    EnrichmentConfigManager,
    SpeciesConfig,
    config_manager,
)
from omichub.tools.enrichments.schema import (
    EnrichmentExampleDTO,
    EnrichmentResultDTO,
    EnrichmentRowDTO,
    EnrichmentTaskDTO,
    SpeciesOptionDTO,
)


class EnrichmentService:
    """富集分析服务。"""

    def __init__(
        self,
        manager: EnrichmentConfigManager | None = None,
    ) -> None:
        self._manager = manager or config_manager
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # 物种列表
    # ------------------------------------------------------------------

    def list_species(self) -> list[SpeciesOptionDTO]:
        """返回 enabled 物种，display_name → label 对齐前端。"""
        return [
            SpeciesOptionDTO(
                id=s.id,
                label=s.display_name,
                kegg_code=s.kegg_code,
                org_db=s.org_db,
                id_type=s.id_type,
                analysis_types=s.analysis_types,
                default_p_value_cutoff=s.p_value_cutoff,
                default_q_value_cutoff=s.q_value_cutoff,
            )
            for s in self._manager.list_enabled_species()
        ]

    # ------------------------------------------------------------------
    # 提交分析
    # ------------------------------------------------------------------

    async def submit(
        self,
        db: AsyncSession,
        user_id: str,
        species_id: str,
        gene_text: str | None,
        project_name: str,
        gene_file_bytes: bytes | None = None,
        gene_filename: str | None = None,
        p_value_cutoff: float = 0.05,
        q_value_cutoff: float = 0.1,
    ) -> EnrichmentTaskDTO:
        """创建通用任务记录并投递 Celery；Web 不直接执行 R Docker。"""
        species = self._require_species(species_id)
        self._validate_cutoff("p-value", p_value_cutoff)
        self._validate_cutoff("q-value", q_value_cutoff)
        genes = await asyncio.to_thread(
            self._parse_uploaded_genes,
            gene_text,
            gene_file_bytes,
            gene_filename,
        )
        if not genes:
            raise ValidationError("基因 ID 列表为空")
        normalized_project_name = self._normalize_project_name(project_name)
        project_slug_value = project_slug(normalized_project_name, fallback="enrichment-project")

        task_uuid = uuid.uuid4()
        task_id = str(task_uuid)
        work_dir = self._work_dir(user_id, normalized_project_name)
        await asyncio.to_thread(work_dir.mkdir, parents=True, exist_ok=True)
        from omichub.application.services.file_service import ensure_directory_chain
        from omichub.infrastructure.storage import get_path_factory

        project_relative = work_dir.relative_to(get_path_factory().user_root(user_id)).as_posix()
        await ensure_directory_chain(db, uuid.UUID(user_id), project_relative)

        input_path = work_dir / "input" / "gene_list.txt"
        await asyncio.to_thread(self._write_gene_list, input_path, genes)

        task = TaskModel(
            id=task_uuid,
            flow_id="kegg-enrichment",
            user_id=uuid.UUID(user_id),
            name=normalized_project_name,
            status=TaskStatus.QUEUED.value,
            parameters={
                "species_id": species.id,
                "project_name": normalized_project_name,
                "project_slug": project_slug_value,
                "gene_count": len(genes),
                "p_value_cutoff": p_value_cutoff,
                "q_value_cutoff": q_value_cutoff,
            },
            work_dir=str(work_dir),
            progress=0,
            # 富集分析对象是基因列表而非生物样本：基因数已记入 parameters.gene_count，
            # 这里不能写 len(genes)，否则仪表板/趋势图按 sample_count 聚合时会把基因数误计为样本。
            sample_count=0,
        )
        db.add(task)
        await db.commit()

        try:
            from omichub.tools.enrichments.tasks import run_enrichment_task

            enqueue_task(run_enrichment_task, task_id, task_id=task_id)
        except Exception as error:
            task.status = TaskStatus.FAILED.value
            task.error_message = f"富集任务投递失败: {error}"[:2000]
            await db.commit()
            raise TaskExecutionError(task.error_message) from error

        return EnrichmentTaskDTO(
            task_id=task_id,
            status="queued",
            progress=0,
            message="富集任务已投递到 Celery Worker",
            project_name=normalized_project_name,
            species_id=species.id,
            gene_count=len(genes),
            created_at=task.created_at,
        )

    async def get_example(self) -> EnrichmentExampleDTO:
        """读取 COP1/HY5 1576 基因及其真实 R 富集结果。"""
        example_dir = Path(self._settings.enrichment_config_yaml).parent / "examples"
        gene_path = example_dir / "cop1_hy5_dependent_1576_gene_list.csv"
        result_path = example_dir / "cop1_hy5_dependent_1576_enrichment_result.csv"
        if not gene_path.exists() or not result_path.exists():
            raise NotFoundError("富集示例数据不存在")

        gene_bytes = await asyncio.to_thread(gene_path.read_bytes)
        genes = await asyncio.to_thread(
            self._parse_uploaded_genes,
            None,
            gene_bytes,
            gene_path.name,
        )
        rows = await asyncio.to_thread(self._read_result_csv, result_path)
        return EnrichmentExampleDTO(
            id="cop1-hy5-dependent-1576",
            title="COP1 and HY5 dependent（1576 genes）",
            species_id="tomato_itag4_1",
            gene_count=len(genes),
            gene_text="\n".join(genes),
            p_value_cutoff=0.05,
            q_value_cutoff=0.05,
            result=EnrichmentResultDTO(
                task_id="sample-cop1-hy5-dependent-1576",
                table_data=rows,
            ),
        )

    async def get_task(
        self,
        db: AsyncSession,
        task_id: str,
        user_id: str,
    ) -> EnrichmentTaskDTO:
        """查询富集任务；完成时读取 Worker 写入的标准结果 DTO。"""
        try:
            task_uuid = uuid.UUID(task_id)
            user_uuid = uuid.UUID(user_id)
        except ValueError as error:
            raise NotFoundError("找不到富集任务") from error

        result = await db.execute(
            select(TaskModel).where(
                TaskModel.id == task_uuid,
                TaskModel.user_id == user_uuid,
                TaskModel.flow_id == "kegg-enrichment",
            )
        )
        task = result.scalar_one_or_none()
        if task is None:
            raise NotFoundError("找不到富集任务")

        if task.status == TaskStatus.SUCCESS.value:
            payload = (task.parameters or {}).get("result")
            if isinstance(payload, dict):
                return EnrichmentTaskDTO(
                    task_id=task_id,
                    status="completed",
                    progress=100,
                    message="富集分析完成",
                    result=EnrichmentResultDTO.model_validate(payload),
                    **self._task_metadata(task),
                )
            return EnrichmentTaskDTO(
                task_id=task_id,
                status="failed",
                progress=100,
                error_message="任务已完成但结果文件缺失",
                **self._task_metadata(task),
            )
        if task.status == TaskStatus.FAILED.value:
            return EnrichmentTaskDTO(
                task_id=task_id,
                status="failed",
                progress=int(task.progress or 0),
                error_message=task.error_message or "富集分析失败",
                **self._task_metadata(task),
            )
        return EnrichmentTaskDTO(
            task_id=task_id,
            status="running" if task.status == TaskStatus.RUNNING.value else "queued",
            progress=int(task.progress or 0),
            message="R 容器正在执行富集分析"
            if task.status == TaskStatus.RUNNING.value
            else "等待 Celery Worker 执行",
            **self._task_metadata(task),
        )

    async def list_tasks(
        self,
        db: AsyncSession,
        user_id: str,
        limit: int = 50,
    ) -> list[EnrichmentTaskDTO]:
        """列出当前用户最近的富集任务，不返回大体积结果表。"""
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError as error:
            raise NotFoundError("找不到用户富集任务") from error
        result = await db.execute(
            select(TaskModel)
            .where(
                TaskModel.user_id == user_uuid,
                TaskModel.flow_id == "kegg-enrichment",
            )
            .order_by(TaskModel.created_at.desc())
            .limit(limit)
        )
        return [
            EnrichmentTaskDTO(
                task_id=str(task.id),
                status=self._task_status(task),
                progress=int(task.progress or 0),
                message=self._task_message(task),
                error_message=task.error_message or None,
                **self._task_metadata(task),
            )
            for task in result.scalars().all()
        ]

    async def get_result_file(
        self,
        db: AsyncSession,
        task_id: str,
        user_id: str,
    ) -> tuple[Path, str]:
        """返回当前用户已完成任务的原始 clusterProfiler CSV。"""
        try:
            task_uuid = uuid.UUID(task_id)
            user_uuid = uuid.UUID(user_id)
        except ValueError as error:
            raise NotFoundError("找不到富集结果") from error
        result = await db.execute(
            select(TaskModel).where(
                TaskModel.id == task_uuid,
                TaskModel.user_id == user_uuid,
                TaskModel.flow_id == "kegg-enrichment",
            )
        )
        task = result.scalar_one_or_none()
        if task is None or task.status != TaskStatus.SUCCESS.value:
            raise NotFoundError("富集结果尚不存在")
        path = Path(task.result_path)
        if not await asyncio.to_thread(path.is_file):
            raise NotFoundError("富集原始结果文件不存在")
        project_slug = str((task.parameters or {}).get("project_slug") or "enrichment-project")
        return path, f"{project_slug}_{task_id[:8]}_enrichment_result.csv"

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _require_species(self, species_id: str) -> SpeciesConfig:
        species = self._manager.get_species(species_id)
        if species is None:
            raise NotFoundError(f"未知物种: {species_id}")
        if not species.enabled:
            raise ValidationError(f"物种已禁用: {species_id}")
        return species

    @staticmethod
    def _validate_cutoff(label: str, value: float) -> None:
        if not 0 < value <= 1:
            raise ValidationError(f"{label} 阈值必须大于 0 且不超过 1")

    @staticmethod
    def _normalize_project_name(project_name: str) -> str:
        value = " ".join(unicodedata.normalize("NFKC", project_name or "").split())
        if not value:
            raise ValidationError("项目名称不能为空")
        if len(value) > 100:
            raise ValidationError("项目名称不能超过 100 个字符")
        return value

    @staticmethod
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
        status = cls._task_status(task)
        return {
            "completed": "富集分析完成",
            "failed": "富集分析失败",
            "running": "R 容器正在执行富集分析",
            "queued": "等待 Celery Worker 执行",
        }[status]

    @staticmethod
    def _task_metadata(task: TaskModel) -> dict[str, object]:
        parameters = task.parameters or {}
        return {
            "project_name": str(
                parameters.get("project_name") or task.name or "Enrichment Project"
            ),
            "species_id": str(parameters.get("species_id") or ""),
            "gene_count": int(parameters.get("gene_count") or task.sample_count or 0),
            "created_at": task.created_at,
            "finished_at": task.finished_at,
        }

    @staticmethod
    def _parse_genes(gene_text: str | None) -> list[str]:
        """解析基因列表：按行切分，去空白行，去重保序。"""
        if not gene_text:
            return []
        seen: set[str] = set()
        genes: list[str] = []
        for line in gene_text.splitlines():
            g = line.strip()
            if g and g not in seen:
                seen.add(g)
                genes.append(g)
        return genes

    @classmethod
    def _parse_uploaded_genes(
        cls,
        gene_text: str | None,
        gene_file_bytes: bytes | None,
        gene_filename: str | None,
    ) -> list[str]:
        """从文本或单列 CSV/TSV 上传文件读取 Gene ID。"""
        if gene_file_bytes is None:
            return cls._parse_genes(gene_text)

        suffix = Path(gene_filename or "").suffix.lower()
        if suffix not in {".csv", ".tsv"}:
            raise ValidationError("仅支持仅含一列 Gene ID 的 .csv 或 .tsv 文件")
        text = gene_file_bytes.decode("utf-8-sig", errors="replace")
        delimiter = "\t" if suffix == ".tsv" else ","
        values = [line.split(delimiter, 1)[0].strip() for line in text.splitlines()]
        return cls._drop_header_and_dedupe(values)

    @classmethod
    def _drop_header_and_dedupe(cls, values: list[str]) -> list[str]:
        if values and values[0].strip().lower() in {"geneid", "gene_id", "gene", "id"}:
            values = values[1:]
        return cls._parse_genes("\n".join(values))

    @staticmethod
    def _write_gene_list(path: Path, genes: list[str]) -> None:
        """每行一个基因 ID，无表头（R 端 read.table(header=FALSE)$V1）。"""
        with path.open("w", encoding="utf-8") as f:
            f.write("\n".join(genes))
            f.write("\n")

    def _work_dir(self, user_id: str, project_name: str) -> Path:
        """结果目录：users/{uid}/projects/{project}/runs/enrichment-时间戳/。"""
        from omichub.infrastructure.storage import get_path_factory

        return get_path_factory().create_project_run_dir(user_id, project_name, "enrichment")

    @staticmethod
    def _read_result_csv(path: Path) -> list[EnrichmentRowDTO]:
        """解析 clusterProfiler 输出 CSV → EnrichmentRowDTO[]。

        容错：pvalue/p.adjust/Count 解析失败时回退 0；空结果返回 []。
        """
        if not path.exists():
            return []
        rows: list[EnrichmentRowDTO] = []
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for raw in reader:
                # p.adjust 缺列时回退 pvalue（部分导出工具不输出 p.adjust）
                p_adjust_val = raw.get("p.adjust")
                if p_adjust_val is None:
                    p_adjust_val = raw.get("pvalue")
                rows.append(
                    EnrichmentRowDTO(
                        id=(raw.get("ID") or "").strip(),
                        description=(raw.get("Description") or "").strip(),
                        gene_ratio=(raw.get("GeneRatio") or "").strip(),
                        pvalue=_to_float(raw.get("pvalue")),
                        p_adjust=_to_float(p_adjust_val),
                        q_value=_to_float(raw.get("qvalue")),
                        count=_to_int(raw.get("Count")),
                        source=(raw.get("Source") or "Unknown").strip(),
                    )
                )
        # 显著性升序（最显著在前），供图表与表格默认排序
        rows.sort(key=lambda r: r.p_adjust)
        return rows


def _to_float(v: object) -> float:
    try:
        return float(str(v).strip()) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def _to_int(v: object) -> int:
    try:
        return int(float(str(v).strip())) if v not in (None, "") else 0
    except (TypeError, ValueError):
        return 0
