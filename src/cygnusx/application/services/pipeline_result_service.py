"""分析流水线结果的受控读取与摘要。"""

from __future__ import annotations

import csv
import io
import json
import statistics
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select

from cygnusx.application.schemas.tool_invocation import ToolInvocationContext
from cygnusx.application.services.task_service import TaskService
from cygnusx.core.exceptions import ValidationError
from cygnusx.infrastructure.database.models.file import FileRecordModel
from cygnusx.infrastructure.storage import get_path_factory, get_storage_backend
from cygnusx.infrastructure.storage.backend import StorageBackend


class PipelineResultService:
    _MAX_FILES = 200
    _MAX_TABLE_BYTES = 10 * 1024 * 1024

    def __init__(
        self,
        context: ToolInvocationContext,
        backend: StorageBackend | None = None,
    ):
        self.context = context
        self._factory = get_path_factory()
        self._backend = backend or get_storage_backend()

    async def get_task_summary(self, task_id: str) -> dict[str, Any]:
        task = await TaskService(self.context.db).get_task(UUID(task_id), self.context.user_id)
        task_root = self._task_root(task_id, task.work_dir)
        roots = await self._result_roots(task_root, task.result_path, task.work_dir)
        records = await self.context.db.scalars(
            select(FileRecordModel).where(
                FileRecordModel.user_id == UUID(self.context.user_id),
                FileRecordModel.task_id == UUID(task_id),
                FileRecordModel.status == "active",
            )
        )
        return {
            "task_id": task_id,
            "status": task.status,
            "flow_id": task.flow_id,
            "parameters": task.parameters,
            "progress": task.progress,
            "metrics": await self._task_metrics(task.parameters, task_root, roots),
            "artifacts": await self._list_artifacts(task_root, roots),
            "file_records": [
                {
                    "file_id": str(record.id),
                    "name": record.original_name,
                    "path": record.storage_path,
                    "size": record.size,
                    "type": record.file_type,
                }
                for record in records.all()
            ],
            "error_excerpt": str(task.error_message or "")[-500:],
        }

    async def preview_task_file(
        self, task_id: str, path: str, *, max_bytes: int = 20_000
    ) -> dict[str, Any]:
        task = await TaskService(self.context.db).get_task(UUID(task_id), self.context.user_id)
        task_root = self._task_root(task_id, task.work_dir)
        candidate = await self._resolve_preview_path(task_root, path)
        rel_path = self._factory.relative_to_root(candidate)
        content = await self._backend.read(rel_path, limit=max_bytes)
        stat_info = await self._backend.stat(rel_path)
        size = stat_info["size"] if stat_info else len(content)
        return {
            "task_id": task_id,
            "path": candidate.relative_to(task_root).as_posix(),
            "size": size,
            "truncated": size > len(content),
            "content": content.decode("utf-8", errors="replace"),
        }

    async def preview_workspace_file(
        self, workspace: Path, path: str, *, max_bytes: int = 20_000
    ) -> dict[str, Any]:
        """预览用户工作区（workspace_dir）内的文件，供 AgentTeams 等外部入口复用。"""
        candidate = await self._resolve_preview_path(workspace, path)
        rel_path = self._factory.relative_to_root(candidate)
        content = await self._backend.read(rel_path, limit=max_bytes)
        stat_info = await self._backend.stat(rel_path)
        size = stat_info["size"] if stat_info else len(content)
        return {
            "path": candidate.relative_to(workspace).as_posix(),
            "size": size,
            "truncated": size > len(content),
            "content": content.decode("utf-8", errors="replace"),
        }

    async def get_results(
        self,
        task_id: str,
        pipeline_type: str,
        result_types: list[str],
    ) -> dict[str, Any]:
        task = await TaskService(self.context.db).get_task(UUID(task_id), self.context.user_id)
        if task.flow_id != pipeline_type:
            raise ValidationError(f"任务 {task_id} 不属于 {pipeline_type} 流程")
        if str(task.status).lower() != "success":
            raise ValidationError("任务尚未成功完成，暂不能读取最终结果")

        task_root = self._task_root(task_id, task.work_dir)
        roots = await self._result_roots(task_root, task.result_path, task.work_dir)
        artifacts = await self._list_artifacts(task_root, roots)
        metrics = (
            await self._task_metrics(task.parameters, task_root, roots)
            if "summary" in result_types
            else {}
        )

        payload: dict[str, Any] = {
            "task_id": task_id,
            "pipeline_type": pipeline_type,
            "status": task.status,
            "progress": task.progress,
            "report_url": f"/tasks/{task_id}/report",
            "metrics": metrics,
        }
        if "artifacts" in result_types:
            payload["artifacts"] = artifacts
        return payload

    def _task_root(self, task_id: str, work_dir: str) -> Path:
        """新项目目录与历史 UUID 任务目录兼容解析。"""
        work_path = Path(work_dir).resolve() if work_dir else None
        projects_root = self._factory.projects_dir(self.context.user_id).resolve()
        if work_path is not None:
            try:
                work_path.relative_to(projects_root)
            except ValueError:
                pass
            else:
                return work_path.parent if work_path.name == "work" else work_path
        return self._factory.task_dir(self.context.user_id, task_id).resolve()

    async def _result_roots(
        self, task_root: Path, result_path: str, work_dir: str
    ) -> list[Path]:
        roots: list[Path] = []
        for raw_path in (result_path, str(task_root / "output"), work_dir):
            if not raw_path:
                continue
            candidate = Path(raw_path).resolve()  # noqa: ASYNC240
            try:
                candidate.relative_to(task_root)
            except ValueError:
                continue
            rel = self._factory.relative_to_root(candidate)
            stat_info = await self._backend.stat(rel)
            if stat_info is not None and candidate not in roots:
                roots.append(candidate)
        return roots

    async def _iter_result_entries(
        self, task_root: Path, roots: list[Path]
    ):
        """遍历结果根目录下的所有文件，产出统一条目。

        产出字段：rel_data（相对 data_root）、rel_task（相对 task_root）、
        name、suffix（不含点）、size。
        """
        task_root_rel = Path(self._factory.relative_to_root(task_root))
        for root in roots:
            root_rel_str = self._factory.relative_to_root(root)
            root_rel = Path(root_rel_str)
            stat_info = await self._backend.stat(root_rel_str)
            is_file = stat_info is not None and not stat_info.get("is_dir", False)
            if is_file:
                if await self._backend.is_symlink(root_rel_str):
                    continue
                try:
                    rel_task = root_rel.relative_to(task_root_rel).as_posix()
                except ValueError:
                    continue
                yield {
                    "rel_data": root_rel_str,
                    "rel_task": rel_task,
                    "name": root_rel.name,
                    "suffix": root_rel.suffix.lower().lstrip("."),
                    "size": stat_info["size"] if stat_info else 0,
                }
                continue

            entries = await self._backend.list(root_rel_str, recursive=True)
            for entry in entries:
                if entry["type"] != "file":
                    continue
                entry_rel = Path(entry["path"])
                if await self._backend.is_symlink(entry["path"]):
                    continue
                try:
                    rel_task = entry_rel.relative_to(task_root_rel).as_posix()
                except ValueError:
                    continue
                yield {
                    "rel_data": entry["path"],
                    "rel_task": rel_task,
                    "name": entry_rel.name,
                    "suffix": entry_rel.suffix.lower().lstrip("."),
                    "size": entry["size"] or 0,
                }

    async def _list_artifacts(self, task_root: Path, roots: list[Path]) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        seen: set[str] = set()
        async for entry in self._iter_result_entries(task_root, roots):
            if len(artifacts) >= self._MAX_FILES:
                return artifacts
            if entry["rel_data"] in seen:
                continue
            seen.add(entry["rel_data"])
            artifacts.append(
                {
                    "name": entry["name"],
                    "path": entry["rel_task"],
                    "size": entry["size"],
                    "type": entry["suffix"] or "file",
                }
            )
        return artifacts

    async def _extract_metrics(self, task_root: Path, roots: list[Path]) -> dict[str, Any]:
        async for entry in self._iter_result_entries(task_root, roots):
            if entry["size"] > self._MAX_TABLE_BYTES:
                continue
            if entry["suffix"] not in {"csv", "tsv", "txt"}:
                continue
            if not any(
                token in entry["name"].lower()
                for token in ("deg", "differential", "diff_gene")
            ):
                continue
            summary = await self._summarize_differential_table(
                entry["rel_data"], entry["suffix"]
            )
            if summary:
                return summary
        return {}

    async def _task_metrics(
        self, parameters: dict[str, Any], task_root: Path, roots: list[Path]
    ) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        for key in ("qc_metrics", "metrics"):
            raw = parameters.get(key)
            if isinstance(raw, dict):
                metrics.update(self._canonical_metrics(raw))
        async for entry in self._iter_result_entries(task_root, roots):
            if entry["size"] > self._MAX_TABLE_BYTES:
                continue
            lower_name = entry["name"].lower()
            if not any(
                token in lower_name for token in ("qc", "metric", "multiqc", "summary")
            ):
                continue
            if entry["suffix"] == "json":
                try:
                    payload = json.loads(
                        (await self._backend.read(entry["rel_data"])).decode("utf-8")
                    )
                except (OSError, json.JSONDecodeError):
                    continue
                if isinstance(payload, dict):
                    metrics.update(self._canonical_metrics(payload))
            elif entry["suffix"] in {"csv", "tsv", "txt"}:
                metrics.update(await self._metrics_from_table(entry["rel_data"], entry["suffix"]))
        metrics.update(await self._extract_metrics(task_root, roots))
        return metrics

    @classmethod
    def _canonical_metrics(cls, payload: dict[str, Any]) -> dict[str, float]:
        aliases = {
            "mapping_rate": ("mapping_rate", "mapped_rate", "mapping_pct", "mapping_percent"),
            "q30": ("q30", "q30_rate", "q30_pct", "percent_q30", "avg_q30"),
            "duplicate_rate": (
                "duplicate_rate",
                "duplication_rate",
                "duplicate_pct",
                "percent_duplicates",
            ),
        }
        flattened: dict[str, Any] = {}

        def visit(value: Any) -> None:
            if not isinstance(value, dict):
                return
            for key, nested in value.items():
                normalized = str(key).strip().lower().replace(" ", "_").replace("%", "pct")
                flattened[normalized] = nested
                visit(nested)

        visit(payload)
        result: dict[str, float] = {}
        for canonical, candidates in aliases.items():
            values = [cls._rate(flattened[name]) for name in candidates if name in flattened]
            valid = [value for value in values if value is not None]
            if valid:
                result[canonical] = float(statistics.median(valid))
        return result

    async def _metrics_from_table(self, rel_path: str, suffix: str) -> dict[str, float]:
        try:
            content = await self._backend.read(rel_path)
            text = content.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return {}
        sample = text[:4096]
        delimiter = "\t" if sample.count("\t") >= sample.count(",") else ","
        rows = list(csv.DictReader(io.StringIO(text), delimiter=delimiter))
        collected: dict[str, list[float]] = {
            "mapping_rate": [],
            "q30": [],
            "duplicate_rate": [],
        }
        for row in rows:
            canonical = self._canonical_metrics(row)
            for key, value in canonical.items():
                collected[key].append(value)
        return {
            key: float(statistics.median(values)) for key, values in collected.items() if values
        }

    @staticmethod
    def _rate(value: Any) -> float | None:
        try:
            rate = float(str(value).strip().rstrip("%"))
        except (TypeError, ValueError):
            return None
        if rate > 1:
            rate /= 100
        return rate if 0 <= rate <= 1 else None

    async def _resolve_preview_path(self, root: Path, requested: str) -> Path:
        if str(requested).strip().startswith("file://"):
            raise ValidationError("不支持的引用协议，应为工作区相对路径（projects/... 或 inbox/...）")
        relative = Path(requested)
        if not requested.strip() or relative.is_absolute() or ".." in relative.parts:
            raise ValidationError("文件路径必须是工作区内的安全相对路径")
        resolved_root = root.resolve()
        current_rel = self._factory.relative_to_root(resolved_root)
        for part in relative.parts:
            current_rel = f"{current_rel}/{part}".strip("/")
            if await self._backend.is_symlink(current_rel):
                raise ValidationError("禁止预览符号链接")
        resolved = resolved_root / relative
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise ValidationError("文件路径超出任务目录") from exc
        stat_info = await self._backend.stat(current_rel)
        if stat_info is None or stat_info.get("is_dir"):
            if stat_info is None:
                raise ValidationError("路径不存在")
            raise ValidationError("路径是目录，不是普通文件")
        return resolved

    async def _summarize_differential_table(
        self, rel_path: str, suffix: str
    ) -> dict[str, int]:
        try:
            content = await self._backend.read(rel_path)
            text = content.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return {}
        return self._summarize_differential_text(text, suffix)

    @staticmethod
    def _summarize_differential_text(text: str, suffix: str) -> dict[str, int]:
        delimiter = "\t" if suffix.lower() in {"tsv", "txt"} else ","
        total = up = down = 0
        try:
            reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
            fieldnames = reader.fieldnames
            if not fieldnames:
                return {}
            fold_column = next(
                (
                    name
                    for name in fieldnames
                    if name.lower() in {"log2foldchange", "log2fc", "logfc", "fold_change"}
                ),
                None,
            )
            for row in reader:
                total += 1
                if total > 100_000:
                    break
                if not fold_column:
                    continue
                try:
                    value = float(row.get(fold_column, ""))
                except (TypeError, ValueError):
                    continue
                if value > 0:
                    up += 1
                elif value < 0:
                    down += 1
        except Exception:  # noqa: BLE001
            return {}
        return {
            "differential_gene_count": total,
            "upregulated_count": up,
            "downregulated_count": down,
        }
