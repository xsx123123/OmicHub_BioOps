"""系统发育树应用服务 —— 上传、提交、状态、结果、下载、方法列表、参数校验。"""

from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from celery.result import AsyncResult
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.core.config import get_settings
from omichub.core.exceptions import NotFoundError, TaskExecutionError, ValidationError
from omichub.infrastructure.celery_app.celery import celery_app
from omichub.infrastructure.task_queue.dispatcher import enqueue_task
from omichub.tools.phylogenetic_tree.config import config_manager
from omichub.tools.phylogenetic_tree.runner import (
    parse_and_validate_input,
    select_resource_profile,
)
from omichub.tools.phylogenetic_tree.schema import (
    PhyloMethodOptionDTO,
    PhyloMethodsResponse,
    PhyloResultDTO,
    PhyloSubmitRequest,
    PhyloTaskResponse,
    PhyloUploadResponse,
    PhyloValidateRequest,
    PhyloValidateResponse,
    TreeStatisticsDTO,
)
from omichub.tools.phylogenetic_tree.tasks import build_phylogenetic_tree


class PhylogeneticTreeService:
    """系统发育树服务。"""

    def __init__(self) -> None:
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # 上传
    # ------------------------------------------------------------------

    def _upload_dir(self, user_id: str) -> Path:
        return Path(self._settings.storage_path) / "uploads" / "phylo" / str(user_id)

    async def upload_file(
        self,
        user_id: str,
        upload_file: UploadFile,
        expected_format: str | None = None,
    ) -> PhyloUploadResponse:
        """接收上传文件、校验格式并保存元数据。"""
        if upload_file.filename is None:
            raise ValidationError("缺少文件名")

        file_id = uuid.uuid4().hex
        suffix = Path(upload_file.filename).suffix.lower()
        if suffix in (".fasta", ".fa", ".fas"):
            ext = ".fasta"
        elif suffix in (".phylip", ".phy"):
            ext = ".phylip"
        elif suffix in (".nex", ".nexus"):
            ext = ".nex"
        elif suffix in (".nwk", ".newick", ".tree"):
            ext = ".nwk"
        else:
            ext = suffix if suffix else ".fasta"

        upload_dir = self._upload_dir(user_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / f"{file_id}{ext}"
        meta_path = upload_dir / f"{file_id}.meta.json"

        try:
            with file_path.open("wb") as f:
                shutil.copyfileobj(upload_file.file, f)
        finally:
            await upload_file.close()

        records, fmt, seq_type, is_aligned = parse_and_validate_input(file_path)
        if expected_format and fmt != expected_format:
            raise ValidationError(f"文件格式与预期不符: {fmt} != {expected_format}")

        total_length = sum(len(r.seq) for r in records)
        meta = {
            "file_id": file_id,
            "filename": upload_file.filename,
            "format": fmt,
            "sequence_type": seq_type,
            "sequence_count": len(records),
            "total_length": total_length,
            "is_aligned": is_aligned,
            "input_path": str(file_path),
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        return PhyloUploadResponse(
            file_id=file_id,
            file_path=str(file_path),
            filename=upload_file.filename,
            format=fmt,
            sequence_count=len(records),
            sequence_type=seq_type,
            total_length=total_length,
            is_aligned=is_aligned,
        )

    # ------------------------------------------------------------------
    # 提交任务
    # ------------------------------------------------------------------

    def _load_meta(self, user_id: str, file_id: str) -> dict[str, Any]:
        meta_path = self._upload_dir(user_id) / f"{file_id}.meta.json"
        if not meta_path.exists():
            raise NotFoundError(f"找不到文件记录: {file_id}")
        return json.loads(meta_path.read_text(encoding="utf-8"))

    async def submit(
        self,
        user_id: str,
        request: PhyloSubmitRequest,
        db: AsyncSession | None = None,
    ) -> PhyloTaskResponse:
        """提交树构建任务。"""
        meta = self._load_meta(user_id, request.file_id)

        # 参数合法性校验
        validation = self._validate_request(
            PhyloValidateRequest(
                alignment_tool=request.alignment_tool,
                tree_method=request.tree_method,
                substitution_model=request.substitution_model,
                bootstrap_enabled=request.bootstrap_enabled,
                bootstrap_type=request.bootstrap_type,
                bootstrap_replicates=request.bootstrap_replicates,
            )
        )
        if not validation.valid:
            raise ValidationError(validation.message)

        # 自动判定序列类型
        seq_type = request.sequence_type
        if seq_type == "auto":
            seq_type = meta.get("sequence_type", "dna") or "dna"

        # 若选择 prealigned 但输入未比对，报错
        if request.alignment_tool == "prealigned" and not meta.get("is_aligned"):
            raise ValidationError("选择跳过比对时，输入序列长度必须一致")

        from omichub.infrastructure.storage import get_path_factory

        run_dir = get_path_factory().create_project_run_dir(
            user_id,
            request.project_name,
            "phylogenetic-tree",
        )
        for name in ("input", "output", "work", "logs"):
            (run_dir / name).mkdir(parents=True, exist_ok=True)

        source_input = Path(str(meta["input_path"]))
        if not await asyncio.to_thread(source_input.exists):
            raise NotFoundError("上传文件已不存在，请重新上传")
        input_name = Path(str(meta.get("filename") or source_input.name)).name or source_input.name
        project_input = run_dir / "input" / input_name
        await asyncio.to_thread(shutil.copy2, source_input, project_input)

        if db is not None:
            from omichub.application.services.file_service import ensure_directory_chain

            relative_run_dir = run_dir.relative_to(get_path_factory().user_root(user_id)).as_posix()
            await ensure_directory_chain(db, uuid.UUID(user_id), relative_run_dir)

        task_input = {
            "input_path": str(project_input),
            "work_dir": str(run_dir),
            "project_name": request.project_name,
            "alignment_tool": request.alignment_tool,
            "alignment_mode": request.alignment_mode,
            "tree_method": request.tree_method,
            "substitution_model": request.substitution_model,
            "bootstrap_enabled": request.bootstrap_enabled,
            "bootstrap_type": request.bootstrap_type,
            "bootstrap_replicates": request.bootstrap_replicates,
            "sequence_type": seq_type,
            "advanced_params": request.advanced_params,
            "user_id": str(user_id),
        }

        # 资源画像仅用于文档/监控，实际队列仍由任务装饰器 queue 决定
        seq_count = meta.get("sequence_count", 0)
        avg_length = meta.get("total_length", 0) // max(seq_count, 1)
        profile = select_resource_profile(seq_count, avg_length, request.tree_method)
        task_input["resource_profile"] = profile

        task = enqueue_task(
            build_phylogenetic_tree,
            task_input,
            queue=profile.get("queue", "phylo_tree"),
        )

        return PhyloTaskResponse(
            task_id=str(task.id),
            status="PENDING",
            phase="PENDING",
            progress=0.0,
            message="任务已投递",
        )

    # ------------------------------------------------------------------
    # 任务状态
    # ------------------------------------------------------------------

    async def get_status(self, task_id: str) -> PhyloTaskResponse:
        result = AsyncResult(task_id, app=celery_app)
        state = result.state

        if state == "PENDING":
            return PhyloTaskResponse(
                task_id=task_id, status="PENDING", phase="PENDING", progress=0.0, message="等待执行"
            )
        if state == "PROGRESS":
            meta = result.info or {}
            return PhyloTaskResponse(
                task_id=task_id,
                status="PROGRESS",
                phase=meta.get("phase", ""),
                progress=meta.get("progress", 0.0),
                message=meta.get("message", ""),
            )
        if state == "SUCCESS":
            payload = result.result or {}
            return PhyloTaskResponse(
                task_id=task_id,
                status="SUCCESS",
                phase="COMPLETED",
                progress=1.0,
                message="任务完成",
                result=payload,
            )
        if state == "FAILURE":
            error = "任务执行失败"
            if result.info and isinstance(result.info, dict):
                error = result.info.get("error", error)
            elif isinstance(result.info, Exception):
                error = str(result.info)
            return PhyloTaskResponse(
                task_id=task_id, status="FAILURE", phase="FAILED", progress=0.0, message=error
            )
        if state == "REVOKED":
            return PhyloTaskResponse(
                task_id=task_id,
                status="REVOKED",
                phase="CANCELLED",
                progress=0.0,
                message="任务已取消",
            )

        return PhyloTaskResponse(
            task_id=task_id, status=state, phase=state, progress=0.0, message=""
        )

    # ------------------------------------------------------------------
    # 结果
    # ------------------------------------------------------------------

    async def get_result(self, task_id: str) -> PhyloResultDTO:
        result = AsyncResult(task_id, app=celery_app)
        if result.state != "SUCCESS":
            raise TaskExecutionError("任务尚未完成或执行失败")
        payload = result.result or {}
        if payload.get("status") != "COMPLETED":
            raise TaskExecutionError(payload.get("error", "任务执行失败"))

        stats = TreeStatisticsDTO(**payload.get("statistics", {}))
        return PhyloResultDTO(
            task_id=task_id,
            status="COMPLETED",
            output_files=payload.get("output_files", {}),
            statistics=stats,
            execution_time=payload.get("execution_time", 0.0),
            phases_completed=payload.get("phases_completed", []),
        )

    def get_result_file_path(self, task_id: str, format_key: str) -> Path:
        result = AsyncResult(task_id, app=celery_app)
        if result.state != "SUCCESS":
            raise TaskExecutionError("任务尚未完成或执行失败")
        payload = result.result or {}
        output_files = payload.get("output_files", {})
        if format_key not in output_files:
            raise NotFoundError(f"不支持的输出格式: {format_key}")
        path = Path(output_files[format_key])
        if not path.exists():
            raise NotFoundError("结果文件不存在或已被清理")
        return path

    # ------------------------------------------------------------------
    # 取消
    # ------------------------------------------------------------------

    async def cancel(self, task_id: str) -> PhyloTaskResponse:
        result = AsyncResult(task_id, app=celery_app)
        result.revoke(terminate=True)
        return PhyloTaskResponse(
            task_id=task_id,
            status="REVOKED",
            phase="CANCELLED",
            progress=0.0,
            message="任务已取消",
        )

    # ------------------------------------------------------------------
    # 方法列表
    # ------------------------------------------------------------------

    def list_methods(self) -> PhyloMethodsResponse:
        cfg = config_manager.get_config()
        defaults = config_manager.get_defaults()
        sm = cfg.supported_methods

        return PhyloMethodsResponse(
            alignment_tools=[
                PhyloMethodOptionDTO(**item.model_dump()) for item in sm.alignment_tools
            ],
            tree_methods=[PhyloMethodOptionDTO(**item.model_dump()) for item in sm.tree_methods],
            substitution_models=sm.substitution_models,
            bootstrap_types=[
                PhyloMethodOptionDTO(**item.model_dump()) for item in sm.bootstrap_types
            ],
            presets={
                key: value.model_dump(exclude_none=True) for key, value in defaults.defaults.items()
            },
        )

    # ------------------------------------------------------------------
    # 参数校验
    # ------------------------------------------------------------------

    def validate(self, request: PhyloValidateRequest) -> PhyloValidateResponse:
        return self._validate_request(request)

    def _validate_request(self, request: PhyloValidateRequest) -> PhyloValidateResponse:
        cfg = config_manager.get_config()
        supported = cfg.supported_methods

        valid_alignment = {item.key for item in supported.alignment_tools}
        if request.alignment_tool not in valid_alignment:
            return PhyloValidateResponse(
                valid=False, message=f"不支持的比对工具: {request.alignment_tool}"
            )

        tree_methods = {item.key: item for item in supported.tree_methods}
        if request.tree_method not in tree_methods:
            return PhyloValidateResponse(
                valid=False, message=f"不支持的树构建方法: {request.tree_method}"
            )

        # Bootstrap 与方法兼容性
        tree_meta = tree_methods[request.tree_method]
        if request.bootstrap_enabled and not tree_meta.supports_bootstrap:
            return PhyloValidateResponse(
                valid=False,
                message=f"当前方法 {request.tree_method} 不支持 Bootstrap",
            )

        if request.bootstrap_replicates < 10 or request.bootstrap_replicates > 10000:
            return PhyloValidateResponse(
                valid=False, message="Bootstrap 重复次数须在 10-10000 之间"
            )

        valid_bootstrap_types = {item.key for item in supported.bootstrap_types}
        if request.bootstrap_type not in valid_bootstrap_types:
            return PhyloValidateResponse(
                valid=False, message=f"不支持的 Bootstrap 类型: {request.bootstrap_type}"
            )

        return PhyloValidateResponse(valid=True, message="参数组合合法")


# 模块级单例
phylo_service = PhylogeneticTreeService()
