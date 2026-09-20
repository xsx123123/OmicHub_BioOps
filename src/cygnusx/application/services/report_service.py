"""报告应用服务"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.schemas.report import (
    ReportFileResponse,
    ReportFilterParams,
    ReportListResponse,
    ReportResponse,
    ReportVersionTreeResponse,
)
from cygnusx.application.services.flow_service import FlowService
from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import AuthorizationError, NotFoundError
from cygnusx.domain.file.value_objects import FileSource
from cygnusx.infrastructure.database.models.report import ReportFileModel, ReportModel
from cygnusx.infrastructure.database.repositories.report_repository import (
    ReportRepositoryImpl,
)
from cygnusx.infrastructure.storage import get_path_factory, get_storage_backend
from cygnusx.infrastructure.storage.backend import StorageBackend
from cygnusx.infrastructure.storage.file_registry import FileRegistry


class ReportService:
    """报告应用服务"""

    def __init__(
        self,
        db: AsyncSession,
        backend: StorageBackend | None = None,
    ):
        self._db = db
        self._repo = ReportRepositoryImpl(db)
        self._flow_service = FlowService()
        self._settings = get_settings()
        self._factory = get_path_factory()
        self._backend = backend or get_storage_backend()

    def _resolve_report_path(self, path: str) -> Path:
        """校验报告文件路径必须位于 storage_root 内，防止路径穿越。

        历史数据可能存的是绝对路径，故先 resolve 再 relative_to 校验。
        """
        if not path:
            raise NotFoundError("报告路径不能为空")
        target = Path(path).resolve()
        try:
            target.relative_to(Path(self._settings.storage_path).resolve())
        except ValueError as exc:
            raise AuthorizationError("非法报告路径：路径越权") from exc
        return target

    def _rel_path(self, abs_path: Path) -> str:
        """将已校验的绝对路径转为相对 data_root 的路径（供 StorageBackend 使用）。"""
        return self._factory.relative_to_root(abs_path)

    async def _file_nonempty(self, rel_path: str) -> bool:
        """存在且大小非零——把"存在即 completed"收紧为"存在且非空"。"""
        stat_info = await self._backend.stat(rel_path)
        return bool(
            stat_info and not stat_info.get("is_dir") and int(stat_info.get("size") or 0) > 0
        )

    async def _load_result_manifest(self, work_path: Path) -> tuple[dict[str, Any] | None, Path]:
        """按 ARDP §6.2 兜底顺序发现 result_manifest.json；缺失/解析失败返回 (None, root)。

        解析失败只记 WARNING 并回退旧约定（manifest 是流程侧新契约，不得打断存量注册）。
        """
        for root in (work_path, work_path.parent / "data_deliver", work_path / "data_deliver"):
            rel = self._rel_path(root / "result_manifest.json")
            if not await self._backend.exists(rel):
                continue
            try:
                raw = await self._backend.read(rel)
                manifest = json.loads(raw.decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("result_manifest.json 解析失败（{}），回退旧约定: {}", rel, exc)
                return None, root
            if not isinstance(manifest, dict):
                logger.warning("result_manifest.json 顶层不是对象（{}），回退旧约定", rel)
                return None, root
            return manifest, root
        return None, work_path

    async def _evaluate_result_manifest(
        self, manifest: dict[str, Any], root: Path
    ) -> tuple[str | None, str | None, str]:
        """校验 manifest 声明的产物文件：真实存在、大小非零、md5（若声明）一致。

        返回 (status, primary_html_rel, note)；status=None 表示 manifest 缺关键字段，
        调用方回退旧约定判定。校验失败不抛异常——落 failed + 结构化 WARNING 留痕。
        """
        run = manifest.get("run") if isinstance(manifest.get("run"), dict) else {}
        run_status = str(run.get("status") or "")
        if not manifest.get("manifest_version") or run_status not in {
            "completed",
            "completed_no_report",
            "failed",
            "aborted",
        }:
            logger.warning(
                "result_manifest.json 缺少 manifest_version/run.status（{}），回退旧约定", root
            )
            return None, None, ""

        failures: list[str] = []
        for entry in manifest.get("files") or []:
            if not isinstance(entry, dict):
                continue
            rel = str(entry.get("path") or "").strip()
            if not rel or rel.endswith("/") or str(entry.get("type") or "") == "dir":
                continue
            failure = await self._check_manifest_file(root, rel, str(entry.get("md5") or ""))
            if failure:
                failures.append(failure)
        report_block = manifest.get("report") if isinstance(manifest.get("report"), dict) else {}
        entry_rel = str(report_block.get("entry") or "").strip()
        primary_html_rel: str | None = None
        if entry_rel:
            failure = await self._check_manifest_file(root, entry_rel, "")
            if failure:
                failures.append(failure)
            else:
                primary_html_rel = self._rel_path((root / entry_rel).resolve())

        if run_status in {"failed", "aborted"}:
            error = manifest.get("error") if isinstance(manifest.get("error"), dict) else {}
            message = str(error.get("message") or "")[:200]
            note = f"流程终态 {run_status}" + (f"：{message}" if message else "")
            return "failed", None, note
        if failures:
            logger.warning("result_manifest 产物校验失败（{}）: {}", root, failures)
            return "failed", None, f"产物校验失败：{'；'.join(failures[:5])}"[:500]
        return "completed", primary_html_rel, ""

    @staticmethod
    def _resolve_within(root: Path, rel: str) -> Path | None:
        """把 manifest 声明的相对路径解析到 root 内；越权（.. 逃逸）返回 None。"""
        resolved_root = root.resolve()
        target = (resolved_root / rel).resolve()
        try:
            target.relative_to(resolved_root)
        except ValueError:
            return None
        return target

    async def _check_manifest_file(self, root: Path, rel: str, md5: str) -> str:
        """单个 manifest 声明文件的存在性/非空/md5 校验；通过返回空串，失败返回原因。"""
        target = self._resolve_within(root, rel)
        if target is None:
            return f"{rel} 路径越权（禁止 .. 逃逸）"
        storage_rel = self._rel_path(target)
        stat_info = await self._backend.stat(storage_rel)
        if not stat_info or stat_info.get("is_dir"):
            return f"{rel} 不存在"
        if int(stat_info.get("size") or 0) <= 0:
            return f"{rel} 大小为零"
        expected_md5 = md5.strip().lower()
        if expected_md5:
            try:
                content = await self._backend.read(storage_rel)
            except Exception as exc:  # noqa: BLE001
                return f"{rel} 读取失败（{exc}）"
            if hashlib.md5(content).hexdigest() != expected_md5:  # noqa: S324 - 对齐交付协议 md5 字段
                return f"{rel} md5 与声明不一致"
        return ""

    async def list_reports(
        self,
        user_id: str,
        params: ReportFilterParams,
    ) -> ReportListResponse:
        """获取用户报告列表"""
        items, total = await self._repo.list_by_user(
            UUID(user_id),
            keyword=params.keyword,
            flow_id=params.flow_id,
            status=params.status,
            date_range=params.date_range,
            is_starred=params.is_starred,
            page=params.page,
            page_size=params.page_size,
        )
        return ReportListResponse(
            items=[_model_to_response(item) for item in items],
            total=total,
        )

    async def get_report(self, report_id: UUID, user_id: str) -> ReportResponse:
        """获取报告详情"""
        model = await self._repo.get_by_id(report_id)
        if model is None or str(model.user_id) != user_id:
            raise NotFoundError("报告不存在")
        return _model_to_response(model)

    async def list_versions(
        self, report_id: UUID, user_id: str
    ) -> ReportVersionTreeResponse:
        """返回指定报告所属的完整版本树。"""
        target = await self._repo.get_by_id(report_id)
        if target is None or str(target.user_id) != user_id:
            raise NotFoundError("报告不存在")

        candidates = await self._repo.list_version_candidates(UUID(user_id))
        by_id = {item.id: item for item in candidates}
        by_id[target.id] = target

        root = target
        visited: set[UUID] = set()
        while root.parent_id is not None:
            if root.id in visited:
                raise NotFoundError("报告版本树异常")
            visited.add(root.id)
            parent = by_id.get(root.parent_id)
            if parent is None:
                break
            root = parent

        family_ids = {root.id}
        changed = True
        while changed:
            changed = False
            for item in candidates:
                if item.parent_id in family_ids and item.id not in family_ids:
                    family_ids.add(item.id)
                    changed = True

        family = [item for item in candidates if item.id in family_ids]
        if root.id not in {item.id for item in family}:
            family.append(root)
        family.sort(key=lambda item: (item.version, item.created_at, str(item.id)))
        return ReportVersionTreeResponse(
            root_id=root.id,
            current_id=target.id,
            items=[_model_to_response(item) for item in family],
        )

    async def preview_html(self, report_id: UUID, user_id: str) -> str:
        """获取报告 HTML 预览内容"""
        model = await self._repo.get_by_id(report_id)
        if model is None or str(model.user_id) != user_id:
            raise NotFoundError("报告不存在")

        primary = next((f for f in model.files if f.is_primary and f.type == "html"), None)
        if primary is None:
            primary = next((f for f in model.files if f.type == "html"), None)
        if primary is None:
            return "<p>未找到可预览的 HTML 报告</p>"

        rel_path = self._rel_path(self._resolve_report_path(primary.path))
        if not await self._backend.exists(rel_path):
            return "<p>报告文件已丢失，请尝试下载</p>"

        try:
            content = await self._backend.read(rel_path)
            return content.decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            return f"<p>报告读取失败: {exc}</p>"

    async def download_file(self, report_id: UUID, file_id: UUID, user_id: str) -> Path:
        """获取报告文件路径"""
        model = await self._repo.get_by_id(report_id)
        if model is None or str(model.user_id) != user_id:
            raise NotFoundError("报告不存在")

        file_model = await self._repo.get_file_by_id(file_id)
        if file_model is None or file_model.report_id != report_id:
            raise NotFoundError("文件不存在")

        rel_path = self._rel_path(self._resolve_report_path(file_model.path))
        if not await self._backend.exists(rel_path):
            raise NotFoundError("文件已丢失")
        return await self._backend.get_local_path(rel_path)

    async def delete_report(self, report_id: UUID, user_id: str) -> None:
        """删除报告（仅删除记录）"""
        model = await self._repo.get_by_id(report_id)
        if model is None or str(model.user_id) != user_id:
            raise NotFoundError("报告不存在")
        await self._repo.delete(report_id)

    async def toggle_star(self, report_id: UUID, user_id: str, is_starred: bool) -> ReportResponse:
        """切换收藏状态"""
        model = await self._repo.get_by_id(report_id)
        if model is None or str(model.user_id) != user_id:
            raise NotFoundError("报告不存在")
        model.is_starred = is_starred
        await self._repo.save(model)
        return _model_to_response(model)

    async def mark_read(self, report_id: UUID, user_id: str) -> ReportResponse:
        """标记已读"""
        model = await self._repo.get_by_id(report_id)
        if model is None or str(model.user_id) != user_id:
            raise NotFoundError("报告不存在")
        model.is_read = True
        await self._repo.save(model)
        return _model_to_response(model)

    async def create_report_from_task(
        self,
        task_id: str,
        user_id: str,
        flow_id: str,
        work_dir: str,
        sample_count: int,
        duration: int,
    ) -> ReportModel | None:
        """任务完成后扫描目录并创建报告记录"""
        existing = await self._repo.get_by_task_id(UUID(task_id))
        if existing is not None:
            return existing

        flow_detail = self._flow_service.get_flow(flow_id)
        flow_name = flow_detail.meta.name if flow_detail else flow_id
        flow_version = flow_detail.meta.version if flow_detail else ""
        flow_icon = flow_detail.meta.icon or "📄" if flow_detail else "📄"

        now = datetime.now()
        title = f"{flow_name} 分析报告"
        description = ""

        work_path = Path(work_dir)
        report_dir = work_path / "Analysis_Report"
        html_path = report_dir / "index.html"

        # 尝试从 project_summary.json 读取更丰富的元信息
        summary_path = work_path / "report_data" / "project_summary.json"
        summary_rel = self._rel_path(summary_path)
        if await self._backend.exists(summary_rel):
            try:
                summary_bytes = await self._backend.read(summary_rel)
                summary = json.loads(summary_bytes.decode("utf-8"))
                project_meta = summary.get("project_meta", {})
                stats = summary.get("stats", {})
                if project_meta.get("client"):
                    title = f"{project_meta.get('client')} - {flow_name} 分析报告"
                description = (
                    f"物种: {project_meta.get('species', 'N/A')} | "
                    f"基因组: {project_meta.get('genome_version', 'N/A')} | "
                    f"样本数: {stats.get('total_samples', sample_count)}"
                )
                sample_count = stats.get("total_samples", sample_count) or sample_count
            except Exception:  # noqa: BLE001
                pass

        html_rel = self._rel_path(html_path)
        html_ready = await self._file_nonempty(html_rel)
        status = "completed" if html_ready else "failed"

        # ARDP（Protocol/分析流程结果交付协议_v1.md）：产物目录存在 result_manifest.json
        # 时优先按 manifest 判定（声明产物存在/非空/md5 比对）；缺失或无效时回退旧约定。
        manifest, manifest_root = await self._load_result_manifest(work_path)
        if manifest is not None:
            manifest_status, manifest_html_rel, note = await self._evaluate_result_manifest(
                manifest, manifest_root
            )
            if manifest_status is not None:
                status = manifest_status
                if manifest_html_rel:
                    html_rel = manifest_html_rel
                    html_ready = True
                    html_path = Path(self._factory.data_root) / html_rel
                    report_dir = html_path.parent
                if note:
                    description = f"{description} | {note}" if description else note

        report = ReportModel(
            id=uuid.uuid4(),
            task_id=UUID(task_id),
            user_id=UUID(user_id),
            flow_id=flow_id,
            flow_name=flow_name,
            flow_version=flow_version,
            flow_icon=flow_icon,
            title=title,
            description=description,
            status=status,
            sample_count=sample_count,
            duration=duration,
            created_at=now,
            completed_at=now if status == "completed" else None,
        )
        await self._repo.create(report)

        if html_ready:
            stat_info = await self._backend.stat(html_rel)
            file_model = ReportFileModel(
                id=uuid.uuid4(),
                report_id=report.id,
                name=html_path.name,
                type="html",
                size=stat_info["size"] if stat_info else 0,
                path=str(html_path),
                is_primary=True,
            )
            self._db.add(file_model)
            await self._db.flush()

            # 报告文件同时注册到统一文件索引（source=REPORT），使 AI 助手可见
            try:
                path_factory = get_path_factory()
                report_directory = report_dir.relative_to(
                    path_factory.user_root(user_id)
                ).as_posix()
                await FileRegistry(self._db).register(
                    UUID(user_id),
                    html_path,
                    source=FileSource.REPORT,
                    task_id=UUID(task_id),
                    directory=report_directory,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "报告文件注册到 file_records 失败（非阻塞）: {}", exc
                )

            await self._db.refresh(report)

        return report

    async def stats(self, user_id: str) -> dict[str, int]:
        """用户报告统计"""
        return await self._repo.count_by_user(UUID(user_id))


def _model_to_response(model: ReportModel) -> ReportResponse:
    return ReportResponse(
        id=model.id,
        task_id=model.task_id,
        user_id=model.user_id,
        flow_id=model.flow_id,
        flow_name=model.flow_name,
        flow_version=model.flow_version,
        flow_icon=model.flow_icon,
        title=model.title,
        description=model.description,
        status=model.status,
        sample_count=model.sample_count,
        duration=model.duration,
        created_at=model.created_at,
        completed_at=model.completed_at,
        is_read=model.is_read,
        is_starred=model.is_starred,
        parent_id=model.parent_id,
        version=model.version,
        files=[
            ReportFileResponse(
                id=f.id,
                report_id=f.report_id,
                name=f.name,
                type=f.type,
                size=f.size,
                path=f.path,
                is_primary=f.is_primary,
                created_at=f.created_at,
            )
            for f in model.files
        ],
    )
