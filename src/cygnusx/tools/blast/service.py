"""BLAST 应用服务 —— 上传、提交、状态、结果、下载、数据库管理。"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from celery.result import AsyncResult
from fastapi import UploadFile
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import NotFoundError, TaskExecutionError, ValidationError
from cygnusx.infrastructure.celery_app.celery import celery_app
from cygnusx.infrastructure.database.models.blast import BlastDatabaseModel, BlastTaskModel
from cygnusx.infrastructure.database.models.user import UserModel
from cygnusx.infrastructure.task_queue.dispatcher import enqueue_task
from cygnusx.tools.blast.cache import build_result_cache_key, get_cached_result
from cygnusx.tools.blast.config import config_manager
from cygnusx.tools.blast.core import detect_sequence_type, ensure_fasta, infer_program
from cygnusx.tools.blast.events import publish_blast_event
from cygnusx.tools.blast.schema import (
    BlastAdminTaskListResponse,
    BlastBuildStatusResponse,
    BlastDatabaseCreateRequest,
    BlastDatabaseDTO,
    BlastDatabaseUploadInitRequest,
    BlastDatabaseUploadInitResponse,
    BlastMethodsResponse,
    BlastResultDTO,
    BlastStatisticsDTO,
    BlastSubmitRequest,
    BlastTaskListItemDTO,
    BlastTaskListResponse,
    BlastTaskResponse,
)
from cygnusx.tools.blast.tasks import build_blast_database_task, run_blast_search_task
from cygnusx.tools.blast.yaml_sync import blast_db_yaml_manager

logger = logging.getLogger(__name__)


def _sync_blast_db_yaml(models: list[BlastDatabaseModel]) -> None:
    """将数据库列表同步到 blast_db.yaml。"""
    try:
        blast_db_yaml_manager.sync_from_models(models)
    except Exception:
        logger.exception("同步 blast_db.yaml 失败")


class BlastService:
    """BLAST 业务服务。"""

    def __init__(self) -> None:
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # 路径助手
    # ------------------------------------------------------------------

    def _db_root(self) -> Path:
        from cygnusx.infrastructure.storage import get_path_factory

        return get_path_factory().blast_db_dir()

    def _upload_dir(self, user_id: str, project_name: str) -> Path:
        from cygnusx.infrastructure.storage import get_path_factory

        return get_path_factory().create_project_run_dir(user_id, project_name, "blast") / "input"

    def _legacy_task_result_dir(self, user_id: str, task_id: str) -> Path:
        """历史 UUID 任务结果目录，仅用于读取兼容。"""
        from cygnusx.infrastructure.storage import get_path_factory

        return get_path_factory().task_output_dir(user_id, task_id)

    def _legacy_result_dir(self, task_id: str) -> Path:
        """旧版结果目录（兼容历史任务）：blast/results/{task_id}/"""
        return Path(self._settings.storage_path) / self._settings.blast_results_dir / task_id

    def _db_upload_dir(self, user_id: str, upload_id: str) -> Path:
        """数据库分片上传暂存目录。"""
        return self._db_root() / ".uploads" / user_id / upload_id

    def _resolve_result_xml(self, task: BlastTaskModel) -> Path | None:
        """解析任务结果 XML 路径，优先使用记录路径，支持新版/旧版目录回退。"""
        if task.result_path:
            path = Path(task.result_path)
            if path.exists():
                return path

        query_path = Path(task.query_file_path or "")
        if query_path.name == "query.fasta" and query_path.parent.name == "input":
            project_path = query_path.parent.parent / "output" / "result.xml"
            if project_path.exists():
                return project_path

        user_id = str(task.user_id)
        legacy_task_path = self._legacy_task_result_dir(user_id, task.task_id) / "result.xml"
        if legacy_task_path.exists():
            return legacy_task_path

        # 旧版目录回退
        legacy_path = self._legacy_result_dir(task.task_id) / "result.xml"
        if legacy_path.exists():
            return legacy_path

        return None

    # ------------------------------------------------------------------
    # 数据库元数据 CRUD
    # ------------------------------------------------------------------

    async def list_databases(
        self, db: AsyncSession, user_id: str, db_type: str | None = None
    ) -> list[BlastDatabaseDTO]:
        """返回当前用户可见的可用数据库列表。"""
        stmt = select(BlastDatabaseModel).where(
            BlastDatabaseModel.build_status == "ready",
            BlastDatabaseModel.is_public.is_(True),
            BlastDatabaseModel.is_active.is_(True),
        )
        if db_type:
            stmt = stmt.where(BlastDatabaseModel.db_type == db_type)
        stmt = stmt.order_by(BlastDatabaseModel.created_at.desc())
        result = await db.execute(stmt)
        return [BlastDatabaseDTO.model_validate(row) for row in result.scalars().all()]

    async def list_all_databases(
        self, db: AsyncSession, db_type: str | None = None
    ) -> list[BlastDatabaseDTO]:
        """管理员查看全部数据库（含 pending/building/failed/deprecated）。"""
        stmt = select(BlastDatabaseModel)
        if db_type:
            stmt = stmt.where(BlastDatabaseModel.db_type == db_type)
        stmt = stmt.order_by(BlastDatabaseModel.created_at.desc())
        result = await db.execute(stmt)
        return [BlastDatabaseDTO.model_validate(row) for row in result.scalars().all()]

    async def create_database(
        self,
        db: AsyncSession,
        user_id: str,
        request: BlastDatabaseCreateRequest,
        fasta_file: UploadFile,
    ) -> BlastDatabaseDTO:
        """管理员上传 FASTA 并创建数据库记录，投递构建任务。"""
        if not re.match(r"^[a-z0-9_]+$", request.db_key):
            raise ValidationError("db_key 只能包含小写字母、数字和下划线")

        existing = await db.execute(
            select(BlastDatabaseModel).where(
                (BlastDatabaseModel.db_key == request.db_key)
                | (BlastDatabaseModel.name == request.name)
            )
        )
        if existing.scalar_one_or_none():
            raise ValidationError("数据库标识或名称已存在")

        db_dir = self._db_root() / request.db_key
        db_dir.mkdir(parents=True, exist_ok=True)
        source_fasta = db_dir / f"{request.db_key}.fasta"

        if fasta_file.filename is None:
            raise ValidationError("缺少文件名")
        suffix = Path(fasta_file.filename).suffix.lower()
        if suffix not in (".fasta", ".fa", ".fna", ".faa"):
            raise ValidationError("仅支持 FASTA 格式文件 (.fasta/.fa/.fna/.faa)")

        max_upload_bytes = (
            config_manager.get_config().input_limits.max_database_file_size_mb * 1024 * 1024
        )
        uploaded_bytes = 0
        try:
            with source_fasta.open("wb") as output:
                while chunk := fasta_file.file.read(1024 * 1024):
                    uploaded_bytes += len(chunk)
                    if uploaded_bytes > max_upload_bytes:
                        raise ValidationError(
                            f"FASTA 文件不能超过 {max_upload_bytes // (1024 * 1024)} MB"
                        )
                    output.write(chunk)
        except Exception:
            shutil.rmtree(db_dir, ignore_errors=True)
            raise
        finally:
            await fasta_file.close()

        try:
            with source_fasta.open("r", encoding="utf-8") as source:
                first_content_line = next((line.strip() for line in source if line.strip()), "")
        except UnicodeDecodeError as exc:
            shutil.rmtree(db_dir, ignore_errors=True)
            raise ValidationError("FASTA 文件必须是 UTF-8 文本") from exc
        if not first_content_line.startswith(">"):
            shutil.rmtree(db_dir, ignore_errors=True)
            raise ValidationError("FASTA 文件缺少以 > 开头的序列头")

        model = BlastDatabaseModel(
            name=request.name,
            db_key=request.db_key,
            db_type=request.db_type,
            source_species=request.source_species,
            source_version=request.source_version,
            version_group=request.version_group or request.db_key,
            is_active=False,
            file_path=str(db_dir / request.db_key),
            is_public=request.is_public,
            created_by=uuid.UUID(user_id),
            build_status="pending",
        )
        db.add(model)
        await db.commit()
        await db.refresh(model)

        # 投递构建任务
        enqueue_task(build_blast_database_task, str(model.id))

        # 同步到 YAML
        all_models = (await db.execute(select(BlastDatabaseModel))).scalars().all()
        _sync_blast_db_yaml(list(all_models))

        return BlastDatabaseDTO.model_validate(model)

    async def init_database_upload(
        self, user_id: str, request: BlastDatabaseUploadInitRequest
    ) -> BlastDatabaseUploadInitResponse:
        limits = config_manager.get_config().input_limits
        max_size = limits.max_database_file_size_mb * 1024 * 1024
        if request.total_size > max_size:
            raise ValidationError(
                f"数据库 FASTA 文件不能超过 {limits.max_database_file_size_mb} MB"
            )
        suffix = Path(request.filename).suffix.lower()
        if suffix not in (".fasta", ".fa", ".fna", ".faa"):
            raise ValidationError("仅支持 FASTA 格式文件 (.fasta/.fa/.fna/.faa)")

        chunk_size_bytes = limits.database_upload_chunk_size_mb * 1024 * 1024
        total_chunks = math.ceil(request.total_size / chunk_size_bytes)
        if total_chunks > 10000:
            raise ValidationError("数据库文件分片数量超过 10000")

        upload_id = uuid.uuid4().hex
        upload_dir = self._db_upload_dir(user_id, upload_id)
        await asyncio.to_thread(upload_dir.mkdir, parents=True, exist_ok=False)
        manifest = {**request.model_dump(mode="json"), "total_chunks": total_chunks}
        await asyncio.to_thread(
            (upload_dir / "manifest.json").write_text,
            json.dumps(manifest, ensure_ascii=False, indent=2),
            "utf-8",
        )
        return BlastDatabaseUploadInitResponse(
            upload_id=upload_id,
            chunk_size_bytes=chunk_size_bytes,
            total_chunks=total_chunks,
        )

    async def save_database_upload_chunk(
        self, user_id: str, upload_id: str, chunk_index: int, chunk: UploadFile
    ) -> dict[str, int | str]:
        _validate_upload_id(upload_id)
        upload_dir = self._db_upload_dir(user_id, upload_id)
        manifest = await asyncio.to_thread(_load_upload_manifest, upload_dir)
        total_chunks = int(manifest["total_chunks"])
        if chunk_index < 0 or chunk_index >= total_chunks:
            raise ValidationError("分片序号超出范围")

        limits = config_manager.get_config().input_limits
        max_chunk_size = limits.database_upload_chunk_size_mb * 1024 * 1024
        chunk_path = upload_dir / f"chunk-{chunk_index:06d}"
        try:
            size = await asyncio.to_thread(
                _copy_upload_chunk, chunk.file, chunk_path, max_chunk_size
            )
        finally:
            await chunk.close()
        return {"upload_id": upload_id, "chunk_index": chunk_index, "size": size}

    async def complete_database_upload(
        self, db: AsyncSession, user_id: str, upload_id: str
    ) -> BlastDatabaseDTO:
        _validate_upload_id(upload_id)
        upload_dir = self._db_upload_dir(user_id, upload_id)
        manifest = await asyncio.to_thread(_load_upload_manifest, upload_dir)
        total_chunks = int(manifest["total_chunks"])
        combined_path = upload_dir / "combined.fasta"
        try:
            combined_size = await asyncio.to_thread(
                _combine_upload_chunks, upload_dir, combined_path, total_chunks
            )
            if combined_size != int(manifest["total_size"]):
                raise ValidationError("分片合并后的文件大小与声明不一致")

            request = BlastDatabaseCreateRequest(
                name=manifest["name"],
                db_key=manifest["db_key"],
                db_type=manifest["db_type"],
                source_species=manifest.get("source_species"),
                source_version=manifest.get("source_version"),
                version_group=manifest.get("version_group"),
                is_public=manifest.get("is_public", True),
            )
            with combined_path.open("rb") as source:
                upload = UploadFile(file=source, filename=manifest["filename"])
                return await self.create_database(db, user_id, request, upload)
        finally:
            await asyncio.to_thread(shutil.rmtree, upload_dir, True)

    async def get_database(self, db: AsyncSession, db_id: str) -> BlastDatabaseModel:
        model = await db.get(BlastDatabaseModel, uuid.UUID(db_id))
        if not model:
            raise NotFoundError(f"找不到数据库: {db_id}")
        return model

    async def get_database_build_status(
        self, db: AsyncSession, db_id: str
    ) -> BlastBuildStatusResponse:
        model = await self.get_database(db, db_id)
        return BlastBuildStatusResponse(
            db_id=str(model.id),
            build_status=model.build_status,
            progress={"pending": 0, "building": 50, "ready": 100}.get(model.build_status, 0),
            sequence_count=model.sequence_count,
            file_size_mb=model.file_size_mb,
            build_log=model.build_log,
        )

    async def rebuild_database(self, db: AsyncSession, db_id: str) -> BlastBuildStatusResponse:
        model = await self.get_database(db, db_id)
        model.build_status = "pending"
        model.build_log = None
        await db.commit()
        enqueue_task(build_blast_database_task, str(model.id))

        # 同步到 YAML（状态会由任务完成后再次同步，但 pending 时也可先写入）
        all_models = (await db.execute(select(BlastDatabaseModel))).scalars().all()
        _sync_blast_db_yaml(list(all_models))

        return await self.get_database_build_status(db, db_id)

    async def activate_database(self, db: AsyncSession, db_id: str) -> BlastDatabaseDTO:
        """激活指定版本，并停用同版本族的其他数据库。"""
        model = await self.get_database(db, db_id)
        if model.build_status != "ready":
            raise ValidationError("只能激活构建完成的数据库版本")

        result = await db.execute(
            select(BlastDatabaseModel).where(
                BlastDatabaseModel.version_group == model.version_group
            )
        )
        for sibling in result.scalars().all():
            sibling.is_active = sibling.id == model.id
        await db.commit()
        await db.refresh(model)

        all_models = (await db.execute(select(BlastDatabaseModel))).scalars().all()
        _sync_blast_db_yaml(list(all_models))
        return BlastDatabaseDTO.model_validate(model)

    async def delete_database(
        self, db: AsyncSession, db_id: str, hard_delete: bool = False
    ) -> dict[str, Any]:
        model = await self.get_database(db, db_id)
        if hard_delete:
            # 检查是否有关联任务
            task_count = await db.scalar(
                select(func.count()).where(BlastTaskModel.db_id == model.id)
            )
            if task_count and task_count > 0:
                raise ValidationError("该数据库存在关联任务，不能硬删除")
            db_dir = Path(model.file_path).parent
            if db_dir.exists():
                shutil.rmtree(db_dir)
            await db.delete(model)
        else:
            was_active = model.is_active
            model.build_status = "deprecated"
            model.is_active = False
            if was_active:
                replacement_result = await db.execute(
                    select(BlastDatabaseModel)
                    .where(
                        BlastDatabaseModel.version_group == model.version_group,
                        BlastDatabaseModel.id != model.id,
                        BlastDatabaseModel.build_status == "ready",
                    )
                    .order_by(BlastDatabaseModel.created_at.desc())
                    .limit(1)
                )
                replacement = replacement_result.scalar_one_or_none()
                if replacement:
                    replacement.is_active = True
        await db.commit()

        # 同步到 YAML
        all_models = (await db.execute(select(BlastDatabaseModel))).scalars().all()
        _sync_blast_db_yaml(list(all_models))

        return {"db_id": db_id, "deleted": hard_delete}

    async def sync_from_yaml(self, db: AsyncSession, user_id: str) -> list[BlastDatabaseDTO]:
        """将 blast_db.yaml 中新增的数据库条目导入 PostgreSQL。

        - YAML 中已存在的 db_key 不会被覆盖。
        - 如果目标目录已包含完整索引文件，状态设为 ready；否则为 pending 并触发构建。
        """
        existing_models = (await db.execute(select(BlastDatabaseModel))).scalars().all()
        existing_keys = {m.db_key for m in existing_models}

        document = blast_db_yaml_manager.load()
        to_add = [entry for entry in document.databases if entry.db_key not in existing_keys]

        created: list[BlastDatabaseModel] = []
        for entry in to_add:
            db_dir = Path(entry.path).parent
            db_path = db_dir / entry.db_key

            # 判断索引文件是否已存在
            is_ready = await asyncio.to_thread(_blast_index_exists, db_path, entry.db_type)

            version_group = entry.version_group or entry.db_key
            has_active_version = any(
                candidate.version_group == version_group and candidate.is_active
                for candidate in [*existing_models, *created]
            )

            model = BlastDatabaseModel(
                name=entry.name,
                db_key=entry.db_key,
                db_type=entry.db_type,
                source_species=entry.source_species,
                source_version=entry.source_version,
                version_group=version_group,
                is_active=entry.is_active or (is_ready and not has_active_version),
                file_path=str(db_path),
                is_public=entry.is_public,
                created_by=uuid.UUID(user_id),
                build_status="ready" if is_ready else "pending",
            )
            db.add(model)
            created.append(model)

        await db.commit()
        for model in created:
            await db.refresh(model)
            if model.build_status == "pending":
                enqueue_task(build_blast_database_task, str(model.id))

        # 重写 YAML，确保格式统一
        all_models = (await db.execute(select(BlastDatabaseModel))).scalars().all()
        _sync_blast_db_yaml(list(all_models))

        return [BlastDatabaseDTO.model_validate(m) for m in created]

    # ------------------------------------------------------------------
    # 任务提交
    # ------------------------------------------------------------------

    async def submit(
        self, db: AsyncSession, user_id: str, request: BlastSubmitRequest
    ) -> BlastTaskResponse:
        """提交 BLAST 查询任务。"""
        db_model = await self.get_database(db, request.db_id)
        if db_model.build_status != "ready":
            raise ValidationError("目标数据库尚未就绪")
        if not db_model.is_public:
            raise ValidationError("目标数据库不可用")

        query_sequence = (request.query_sequence or "").strip()
        if not query_sequence:
            raise ValidationError("查询序列不能为空")

        fasta_text = ensure_fasta(query_sequence, request.query_title)
        title, sequence = _parse_fasta_internal(fasta_text)
        limits = config_manager.get_config().input_limits
        if len(sequence) > limits.max_query_sequence_length:
            raise ValidationError(
                f"查询序列长度不能超过 {limits.max_query_sequence_length:,} 个字符"
            )
        if request.max_target_seqs > limits.max_target_seqs:
            raise ValidationError(f"最大匹配数不能超过 {limits.max_target_seqs}")

        query_type = detect_sequence_type(sequence)
        if query_type == "unknown":
            raise ValidationError("无法识别查询序列类型，请检查输入")

        program: str = request.program or ""
        if not program:
            program = infer_program(query_type, db_model.db_type)

        # 校验 program 与数据库类型兼容性（允许用户强制指定，但做基本校验）
        expected = infer_program(query_type, db_model.db_type)
        if (
            program != expected
            and (query_type, db_model.db_type, program) not in _allowed_override_programs()
        ):
            raise ValidationError(
                f"program {program} 与查询类型 {query_type}/数据库类型 {db_model.db_type} 不兼容"
            )

        cache_key = build_result_cache_key(
            db_id=str(db_model.id),
            db_version=_database_cache_version(db_model),
            program=program,
            query_sequence=fasta_text,
            evalue=request.evalue,
            max_target_seqs=request.max_target_seqs,
            word_size=request.word_size,
            gapopen=request.gapopen,
            gapextend=request.gapextend,
        )
        cached_result = await get_cached_result(cache_key)

        task_id = uuid.uuid4().hex
        model = BlastTaskModel(
            task_id=task_id,
            user_id=uuid.UUID(user_id),
            db_id=uuid.UUID(request.db_id),
            program=program,
            query_title=request.query_title or title,
            query_sequence=fasta_text,
            evalue=request.evalue,
            max_target_seqs=request.max_target_seqs,
            word_size=request.word_size,
            gapopen=request.gapopen,
            gapextend=request.gapextend,
            status="completed" if cached_result else "queued",
            progress=100 if cached_result else 0,
            result_format=request.result_format,
            result_path=cached_result.get("result_path") if cached_result else None,
            result_size_kb=cached_result.get("result_size_kb") if cached_result else None,
            hit_count=cached_result.get("hit_count") if cached_result else None,
            top_hit_identity=cached_result.get("top_hit_identity") if cached_result else None,
            top_hit_evalue=cached_result.get("top_hit_evalue") if cached_result else None,
            started_at=datetime.utcnow() if cached_result else None,
            completed_at=datetime.utcnow() if cached_result else None,
        )
        db.add(model)
        await db.commit()
        await db.refresh(model)

        # 查询序列保存到用户可见的项目目录；任务 UUID 只保留在数据库记录中。
        upload_dir = self._upload_dir(user_id, request.project_name)
        upload_dir.mkdir(parents=True, exist_ok=True)
        query_file = upload_dir / "query.fasta"
        query_file.write_text(fasta_text, encoding="utf-8")
        model.query_file_path = str(query_file)
        from cygnusx.application.services.file_service import ensure_directory_chain
        from cygnusx.infrastructure.storage import get_path_factory

        project_relative = upload_dir.parent.relative_to(
            get_path_factory().user_root(user_id)
        ).as_posix()
        await ensure_directory_chain(db, uuid.UUID(user_id), project_relative)
        await db.commit()

        if not cached_result:
            enqueue_task(run_blast_search_task, task_id, task_id=task_id)

        return BlastTaskResponse(
            task_id=task_id,
            status="completed" if cached_result else "queued",
            progress=100 if cached_result else 0,
            message="命中缓存，已直接返回结果" if cached_result else "任务已投递",
            submitted_at=model.submitted_at,
        )

    # ------------------------------------------------------------------
    # 任务状态 / 结果
    # ------------------------------------------------------------------

    async def get_task(
        self, db: AsyncSession, task_id: str, user_id: str | None = None
    ) -> BlastTaskModel:
        stmt = select(BlastTaskModel).where(BlastTaskModel.task_id == task_id)
        if user_id is not None:
            stmt = stmt.where(BlastTaskModel.user_id == uuid.UUID(user_id))
        result = await db.execute(stmt)
        task = result.scalar_one_or_none()
        if not task:
            raise NotFoundError(f"找不到任务: {task_id}")
        return task

    async def get_status(self, db: AsyncSession, task_id: str, user_id: str) -> BlastTaskResponse:
        task = await self.get_task(db, task_id, user_id)
        return BlastTaskResponse(
            task_id=task_id,
            status=task.status,
            progress=task.progress,
            message="",
            error_message=task.error_message,
            submitted_at=task.submitted_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            db_id=str(task.db_id),
            query_sequence=task.query_sequence,
            query_title=task.query_title,
            program=task.program,
            evalue=task.evalue,
            max_target_seqs=task.max_target_seqs,
            word_size=task.word_size,
            gapopen=task.gapopen,
            gapextend=task.gapextend,
            result_format=task.result_format,
        )

    async def get_result(
        self, db: AsyncSession, task_id: str, user_id: str, result_format: str = "json"
    ) -> BlastResultDTO:
        task = await self.get_task(db, task_id, user_id)
        if task.status != "completed":
            raise TaskExecutionError("任务尚未完成")

        db_model = await db.get(BlastDatabaseModel, task.db_id)
        db_name = db_model.name if db_model else ""

        hits: list[dict[str, Any]] = []
        source_xml = self._resolve_result_xml(task)
        if source_xml is not None:
            from cygnusx.tools.blast.core import parse_blast_xml

            try:
                stats = parse_blast_xml(source_xml)
                hits = stats.get("hits", [])
            except Exception:
                logger.exception("解析 BLAST 结果 XML 失败")

        return BlastResultDTO(
            task_id=task_id,
            status="completed",
            hits=hits,
            statistics=BlastStatisticsDTO(
                hit_count=task.hit_count or 0,
                top_hit_identity=task.top_hit_identity,
                top_hit_evalue=task.top_hit_evalue,
                db_name=db_name,
                program=task.program,
                query_title=task.query_title or "",
            ),
            result_path=task.result_path,
            xml_url=f"/api/v1/blast/download/{task_id}/xml",
            json_url=f"/api/v1/blast/download/{task_id}/json",
            text_url=f"/api/v1/blast/download/{task_id}/text",
            query_len=stats.get("query_len", 0),
            program=stats.get("program", task.program or ""),
            db_name=stats.get("db_name", db_name),
            query_def=stats.get("query_def", ""),
            db_display_name=db_name,
            query_params={
                "evalue": task.evalue,
                "max_target_seqs": task.max_target_seqs,
                "word_size": task.word_size,
                "gapopen": task.gapopen,
                "gapextend": task.gapextend,
                "program": task.program,
            },
        )

    async def cancel(self, db: AsyncSession, task_id: str, user_id: str) -> BlastTaskResponse:
        task = await self.get_task(db, task_id, user_id)
        if task.status not in ("queued", "running"):
            raise ValidationError("只能取消 queued 或 running 状态的任务")

        AsyncResult(task_id, app=celery_app).revoke(terminate=True)
        task.status = "cancelled"
        task.error_message = None
        await db.commit()
        await publish_blast_event(task_id, "cancelled", task.progress, "任务已取消")
        return BlastTaskResponse(
            task_id=task_id,
            status="cancelled",
            progress=0,
            message="任务已取消",
        )

    async def list_user_tasks(
        self,
        db: AsyncSession,
        user_id: str,
        status: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> BlastTaskListResponse:
        """分页返回当前用户的 BLAST 任务历史。"""
        stmt = (
            select(BlastTaskModel, BlastDatabaseModel.name, UserModel.username, UserModel.nickname)
            .join(BlastDatabaseModel, BlastTaskModel.db_id == BlastDatabaseModel.id)
            .outerjoin(UserModel, BlastTaskModel.user_id == UserModel.id)
            .where(BlastTaskModel.user_id == uuid.UUID(user_id))
        )
        if status:
            stmt = stmt.where(BlastTaskModel.status == status)
        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    BlastTaskModel.task_id.ilike(pattern),
                    BlastTaskModel.query_title.ilike(pattern),
                )
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = await db.scalar(count_stmt) or 0

        stmt = (
            stmt.order_by(desc(BlastTaskModel.submitted_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await db.execute(stmt)

        items: list[BlastTaskListItemDTO] = []
        for task, db_name, username, nickname in result.all():
            items.append(
                BlastTaskListItemDTO(
                    task_id=task.task_id,
                    user_id=str(task.user_id) if task.user_id else None,
                    username=username,
                    nickname=nickname,
                    db_id=str(task.db_id),
                    db_name=db_name or "",
                    program=task.program,
                    query_title=task.query_title,
                    status=task.status,
                    progress=task.progress,
                    hit_count=task.hit_count,
                    top_hit_identity=task.top_hit_identity,
                    top_hit_evalue=task.top_hit_evalue,
                    submitted_at=task.submitted_at,
                    completed_at=task.completed_at,
                    error_message=task.error_message,
                )
            )

        return BlastTaskListResponse(items=items, total=total, page=page, page_size=page_size)

    async def list_all_tasks(
        self,
        db: AsyncSession,
        status: str | None = None,
        user_id: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> BlastAdminTaskListResponse:
        """管理员查看全平台 BLAST 任务。"""
        stmt = (
            select(BlastTaskModel, BlastDatabaseModel.name, UserModel.username, UserModel.nickname)
            .join(BlastDatabaseModel, BlastTaskModel.db_id == BlastDatabaseModel.id)
            .join(UserModel, BlastTaskModel.user_id == UserModel.id)
        )
        if status:
            stmt = stmt.where(BlastTaskModel.status == status)
        if user_id:
            stmt = stmt.where(BlastTaskModel.user_id == uuid.UUID(user_id))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = await db.scalar(count_stmt) or 0

        stmt = (
            stmt.order_by(desc(BlastTaskModel.submitted_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await db.execute(stmt)

        items: list[BlastTaskListItemDTO] = []
        for task, db_name, username, nickname in result.all():
            items.append(
                BlastTaskListItemDTO(
                    task_id=task.task_id,
                    user_id=str(task.user_id) if task.user_id else None,
                    username=username,
                    nickname=nickname,
                    db_id=str(task.db_id),
                    db_name=db_name or "",
                    program=task.program,
                    query_title=task.query_title,
                    status=task.status,
                    progress=task.progress,
                    hit_count=task.hit_count,
                    top_hit_identity=task.top_hit_identity,
                    top_hit_evalue=task.top_hit_evalue,
                    submitted_at=task.submitted_at,
                    completed_at=task.completed_at,
                    error_message=task.error_message,
                )
            )

        return BlastAdminTaskListResponse(items=items, total=total, page=page, page_size=page_size)

    async def get_download_path(
        self, db: AsyncSession, task_id: str, user_id: str, format_key: str
    ) -> Path:
        task = await self.get_task(db, task_id, user_id)
        if task.status != "completed":
            raise TaskExecutionError("任务尚未完成")

        source_xml = self._resolve_result_xml(task)
        if source_xml is None:
            raise NotFoundError("结果文件不存在或已被清理")

        if format_key == "xml":
            path = source_xml
        elif format_key == "json":
            path = source_xml.parent / "result.json"
            result = await self.get_result(db, task_id, user_id, "json")
            path.write_text(
                json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        elif format_key == "text":
            path = source_xml.with_name("result.txt")
        else:
            raise NotFoundError(f"不支持的下载格式: {format_key}")

        if not path.exists():
            raise NotFoundError("结果文件不存在或已被清理")
        return path

    # ------------------------------------------------------------------
    # 管理员数据清理
    # ------------------------------------------------------------------

    async def cleanup_old_tasks(self, db: AsyncSession, days: int = 7) -> dict[str, Any]:
        """清理 N 天前完成的 BLAST 任务结果文件，保留数据库记录（状态改为 cleaned）。"""
        cutoff = datetime.utcnow() - timedelta(days=days)

        result = await db.execute(
            select(BlastTaskModel).where(
                BlastTaskModel.status.in_(["completed", "failed"]),
                BlastTaskModel.completed_at < cutoff,
                BlastTaskModel.result_path.isnot(None),  # type: ignore[union-attr]
            )
        )
        tasks = result.scalars().all()

        deleted_count = 0
        for task in tasks:
            if await self._cleanup_task_files(task):
                deleted_count += 1

        await db.commit()
        return {
            "message": f"已清理 {deleted_count} 个任务的结果文件",
            "cutoff_date": cutoff.isoformat(),
            "deleted_count": deleted_count,
        }

    async def cleanup_all_tasks(self, db: AsyncSession, confirm: bool) -> dict[str, Any]:
        """清理所有 BLAST 任务结果文件（保留数据库索引和元数据记录）。"""
        if not confirm:
            raise ValidationError("请设置 confirm=true 以确认清理所有数据。此操作不可恢复！")

        result = await db.execute(
            select(BlastTaskModel).where(
                BlastTaskModel.status.in_(["completed", "failed", "cleaned"])
            )
        )
        tasks = result.scalars().all()

        deleted_count = 0
        for task in tasks:
            if await self._cleanup_task_files(task):
                deleted_count += 1

        await db.commit()
        return {
            "message": f"已清理所有 {deleted_count} 个任务的结果文件",
            "deleted_count": deleted_count,
        }

    async def _cleanup_task_files(self, task: BlastTaskModel) -> bool:
        """删除单个任务的结果文件和上传文件，返回是否成功。"""
        success = True

        def _remove_file(path: Path) -> None:
            if path.exists():
                path.unlink()

        # 删除结果文件及关联的 json/txt 文件
        if task.result_path:
            result_path = Path(task.result_path)
            try:
                await asyncio.to_thread(_remove_file, result_path)
                for ext in [".json", ".txt"]:
                    alt_path = result_path.with_suffix(ext)
                    await asyncio.to_thread(_remove_file, alt_path)
            except Exception as exc:
                logger.warning("删除结果文件失败: %s - %s", task.result_path, exc)
                success = False

        # 删除上传的查询序列文件
        if task.query_file_path:
            query_path = Path(task.query_file_path)
            try:
                await asyncio.to_thread(_remove_file, query_path)
            except Exception as exc:
                logger.warning("删除查询文件失败: %s - %s", task.query_file_path, exc)
                success = False

        # 标记为已清理（保留元数据记录）
        task.result_path = None
        task.query_file_path = None
        task.result_size_kb = None
        task.status = "cleaned"
        return success

    async def get_storage_stats(self, db: AsyncSession) -> dict[str, Any]:
        """获取 BLAST 结果存储统计。"""
        total_tasks = await db.scalar(select(func.count()).select_from(BlastTaskModel)) or 0
        completed_tasks = (
            await db.scalar(
                select(func.count())
                .select_from(BlastTaskModel)
                .where(BlastTaskModel.status == "completed")
            )
            or 0
        )
        cleaned_tasks = (
            await db.scalar(
                select(func.count())
                .select_from(BlastTaskModel)
                .where(BlastTaskModel.status == "cleaned")
            )
            or 0
        )

        completed_paths = (
            await db.scalars(
                select(BlastTaskModel.result_path).where(BlastTaskModel.status == "completed")
            )
        ).all()

        def _calc_paths_size(paths: list[str | None]) -> int:
            total = 0
            for path_value in paths:
                if not path_value:
                    continue
                try:
                    path = Path(path_value)
                    if path.is_file():
                        total += path.stat().st_size
                except OSError:
                    continue
            return total

        total_size = await asyncio.to_thread(_calc_paths_size, completed_paths)

        return {
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "cleaned_tasks": cleaned_tasks,
            "storage_mb": round(total_size / (1024 * 1024), 2),
            "result_dir": "按任务实际 result_path 统计",
        }

    # ------------------------------------------------------------------
    # 方法列表
    # ------------------------------------------------------------------

    def list_methods(self) -> BlastMethodsResponse:
        cfg = config_manager.get_config()
        programs = [
            {"key": item.program, "query_type": item.query_type, "db_type": item.db_type}
            for item in cfg.program_map
        ]
        return BlastMethodsResponse(
            programs=programs,
            db_types=["nucl", "prot"],
            defaults=cfg.defaults,
        )


# ------------------------------------------------------------------
# 模块内辅助
# ------------------------------------------------------------------


def _validate_upload_id(upload_id: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{32}", upload_id):
        raise ValidationError("无效的分片上传 ID")


def _load_upload_manifest(upload_dir: Path) -> dict[str, Any]:
    manifest_path = upload_dir / "manifest.json"
    if not manifest_path.is_file():
        raise NotFoundError("分片上传会话不存在或已过期")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _copy_upload_chunk(source: Any, destination: Path, max_size: int) -> int:
    size = 0
    with destination.open("wb") as output:
        while data := source.read(1024 * 1024):
            size += len(data)
            if size > max_size:
                destination.unlink(missing_ok=True)
                raise ValidationError("上传分片超过配置的分片大小")
            output.write(data)
    return size


def _combine_upload_chunks(upload_dir: Path, destination: Path, total_chunks: int) -> int:
    total_size = 0
    with destination.open("wb") as output:
        for chunk_index in range(total_chunks):
            chunk_path = upload_dir / f"chunk-{chunk_index:06d}"
            if not chunk_path.is_file():
                raise ValidationError(f"缺少上传分片: {chunk_index}")
            with chunk_path.open("rb") as source:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            total_size += chunk_path.stat().st_size
    return total_size


def _database_cache_version(model: BlastDatabaseModel) -> str:
    updated_at = model.updated_at.isoformat() if model.updated_at else ""
    return f"{model.source_version or ''}:{updated_at}"


def _blast_index_exists(db_path: Path, db_type: str) -> bool:
    suffixes = [".nhr", ".nin", ".nsq"] if db_type == "nucl" else [".phr", ".pin", ".psq"]
    return all(Path(f"{db_path}{suffix}").exists() for suffix in suffixes)


def _parse_fasta_internal(fasta_text: str) -> tuple[str, str]:
    lines = [line.strip() for line in fasta_text.strip().splitlines()]
    title = ""
    seq_lines: list[str] = []
    for line in lines:
        if not line:
            continue
        if line.startswith(">"):
            title = line[1:].strip().split()[0]
            continue
        seq_lines.append(line)
    return title, "".join(seq_lines)


def _allowed_override_programs() -> set[tuple[str, str, str]]:
    """允许用户显式覆盖的 program 组合。"""
    return {
        ("nucl", "nucl", "blastn"),
        ("nucl", "nucl", "tblastx"),
        ("prot", "prot", "blastp"),
        ("nucl", "prot", "blastx"),
        ("prot", "nucl", "tblastn"),
    }


# 模块级单例
blast_service = BlastService()
