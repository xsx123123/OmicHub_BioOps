"""RNA-seq / ATAC-seq MCP 流水线统一控制器。"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from cygnusx.application.schemas.pipeline import PipelinePrepareRequest
from cygnusx.application.schemas.tool_invocation import ToolInvocationContext
from cygnusx.application.services.analysis_flow_tool_service import AnalysisFlowToolService
from cygnusx.application.services.atac_seq_pipeline import ATACSeqPipeline
from cygnusx.application.services.pipeline_result_service import PipelineResultService
from cygnusx.application.services.rna_seq_pipeline import RNASeqPipeline
from cygnusx.application.services.task_service import TaskService
from cygnusx.core.exceptions import ValidationError
from cygnusx.infrastructure.storage import get_path_factory


class PipelineController:
    def __init__(self, context: ToolInvocationContext):
        self.context = context
        self._flow_service = AnalysisFlowToolService(context=context)
        self._result_service = PipelineResultService(context=context)
        self._pipelines = {
            "rna_seq": RNASeqPipeline(),
            "atac_seq": ATACSeqPipeline(),
        }

    async def prepare(
        self, pipeline_type: str, request: PipelinePrepareRequest | dict[str, Any]
    ) -> dict[str, Any]:
        pipeline = self._get_pipeline(pipeline_type)
        parsed = request if isinstance(request, PipelinePrepareRequest) else PipelinePrepareRequest(**request)
        workspace_report = await self.check_workspace_data(pipeline_type, parsed.raw_data_path)
        if not workspace_report["valid"]:
            messages = workspace_report.get("errors") or workspace_report.get("warnings") or []
            return {
                "valid": False,
                "pipeline_type": pipeline_type,
                "prepared_params": None,
                "errors": [
                    {
                        "field": "raw_data_path",
                        "code": "INVALID_WORKSPACE_DATA",
                        "message": message,
                    }
                    for message in messages
                ],
                "warnings": workspace_report.get("warnings", []),
                "workspace_report": workspace_report,
            }
        resolved_data_path = self._resolve_workspace_path(parsed.raw_data_path)
        missing_samples = self._missing_sample_files(resolved_data_path, parsed.sample_sheet)
        if missing_samples:
            return {
                "valid": False,
                "pipeline_type": pipeline_type,
                "prepared_params": None,
                "errors": [
                    {
                        "field": "sample_sheet",
                        "code": "SAMPLE_FASTQ_NOT_FOUND",
                        "message": f"样本未匹配到 FASTQ 文件: {sample}",
                    }
                    for sample in missing_samples
                ],
                "warnings": workspace_report.get("warnings", []),
                "workspace_report": workspace_report,
            }
        parsed = parsed.model_copy(update={"raw_data_path": str(resolved_data_path)})
        result = await self._flow_service.prepare(
            pipeline.flow_id,
            pipeline.build_prepare_arguments(parsed),
        )
        return {
            **result,
            "pipeline_type": pipeline_type,
            "workspace_report": workspace_report,
            "prepared_params": {
                "confirmation_id": result.get("confirmation_id"),
                "pipeline_type": pipeline_type,
            }
            if result.get("valid")
            else None,
        }

    async def submit(self, pipeline_type: str, prepared_params: dict[str, Any]) -> dict[str, Any]:
        self._get_pipeline(pipeline_type)
        if prepared_params.get("pipeline_type") not in (None, pipeline_type):
            raise ValidationError("prepared_params 与目标流程不匹配")
        confirmation_id = str(prepared_params.get("confirmation_id") or "")
        if not confirmation_id:
            raise ValidationError("prepared_params 缺少 confirmation_id")
        result = await self._flow_service.confirm_and_submit(confirmation_id)
        task_id = str(result["task_id"])
        return {
            **result,
            "task_id": task_id,
            "pipeline_type": pipeline_type,
            "progress": 0,
            "progress_url": f"/api/v1/pipelines/{pipeline_type}/{task_id}/status",
            "result_url": f"/api/v1/pipelines/{pipeline_type}/{task_id}/results",
        }

    async def status(self, pipeline_type: str, task_id: str) -> dict[str, Any]:
        self._get_pipeline(pipeline_type)
        task = await TaskService(self.context.db).get_task(UUID(task_id), self.context.user_id)
        if task.flow_id != pipeline_type:
            raise ValidationError(f"任务 {task_id} 不属于 {pipeline_type} 流程")
        result = await self._flow_service.get_task_status(task_id)
        return {
            **result,
            "pipeline_type": pipeline_type,
            "is_terminal": str(result["status"]).lower()
            in {"success", "failed", "cancelled"},
            "result_url": f"/api/v1/pipelines/{pipeline_type}/{task_id}/results",
        }

    async def results(
        self, pipeline_type: str, task_id: str, result_types: list[str]
    ) -> dict[str, Any]:
        self._get_pipeline(pipeline_type)
        return await self._result_service.get_results(task_id, pipeline_type, result_types)

    async def list_available(self) -> list[dict[str, Any]]:
        discovered = await self._flow_service.discover()
        available: list[dict[str, Any]] = []
        for item in discovered:
            flow_id = str(item["flow_id"])
            if flow_id not in self._pipelines:
                continue
            details = await self._flow_service.describe(flow_id)
            properties = details.get("parameter_schema", {}).get("properties", {})
            required = details.get("parameter_schema", {}).get("required", [])
            available.append(
                {
                    "name": flow_id,
                    "description": item["description"],
                    "required_params": [
                        {"name": name, "description": properties.get(name, {}).get("description", "")}
                        for name in required
                    ],
                    "estimated_time": self._estimated_time(flow_id),
                }
            )
        return available

    async def check_workspace_data(self, analysis_type: str, data_path: str) -> dict[str, Any]:
        self._get_pipeline(analysis_type)
        resolved = self._resolve_workspace_path(data_path)
        if not resolved.exists() or not resolved.is_dir():
            return {
                "valid": False,
                "analysis_type": analysis_type,
                "data_path": data_path,
                "errors": ["数据目录不存在或不是目录"],
                "warnings": [],
            }

        fastq_files = sorted(
            path
            for path in resolved.rglob("*")
            if path.is_file()
            and path.name.lower().endswith((".fastq", ".fq", ".fastq.gz", ".fq.gz"))
        )
        r1 = [path for path in fastq_files if any(token in path.name for token in ("_R1", "_1."))]
        r2 = [path for path in fastq_files if any(token in path.name for token in ("_R2", "_2."))]
        warnings: list[str] = []
        if not fastq_files:
            warnings.append("未发现 FASTQ 文件")
        if (r1 or r2) and len(r1) != len(r2):
            warnings.append(f"双端文件数量不匹配：R1={len(r1)}，R2={len(r2)}")
        total_size = sum(path.stat().st_size for path in fastq_files)
        return {
            "valid": bool(fastq_files) and not any("不匹配" in item for item in warnings),
            "analysis_type": analysis_type,
            "data_path": data_path,
            "fastq_count": len(fastq_files),
            "paired_end": bool(r1 and r2),
            "r1_count": len(r1),
            "r2_count": len(r2),
            "total_size_bytes": total_size,
            "estimated_samples": max(len(r1), len(r2), len(fastq_files)),
            "warnings": warnings,
            "errors": [],
        }

    def _resolve_workspace_path(self, data_path: str) -> Path:
        path_factory = get_path_factory()
        user_root = path_factory.user_root(self.context.user_id).resolve()
        raw = data_path.removeprefix("directory://").strip()
        candidate = Path(raw)
        if ".." in candidate.parts:
            raise ValidationError("数据路径包含非法路径穿越")
        resolved = candidate.resolve() if candidate.is_absolute() else (user_root / candidate).resolve()
        try:
            resolved.relative_to(user_root)
        except ValueError as exc:
            raise ValidationError("只能检查当前用户工作区内的数据") from exc
        return resolved

    @staticmethod
    def _missing_sample_files(
        data_path: Path, sample_sheet: list[dict[str, Any]]
    ) -> list[str]:
        fastq_names = [
            path.name.lower()
            for path in data_path.rglob("*")
            if path.is_file()
            and path.name.lower().endswith((".fastq", ".fq", ".fastq.gz", ".fq.gz"))
        ]
        missing: list[str] = []
        for row in sample_sheet:
            sample = str(row.get("sample") or row.get("sample_name") or "").strip()
            if sample and not any(name.startswith(sample.lower()) for name in fastq_names):
                missing.append(sample)
        return missing

    def _get_pipeline(self, pipeline_type: str) -> RNASeqPipeline | ATACSeqPipeline:
        pipeline = self._pipelines.get(pipeline_type)
        if pipeline is None:
            raise ValidationError(f"不支持的分析流程: {pipeline_type}")
        return pipeline

    @staticmethod
    def _estimated_time(pipeline_type: str) -> str:
        return "2-6 小时" if pipeline_type == "rna_seq" else "3-8 小时"
