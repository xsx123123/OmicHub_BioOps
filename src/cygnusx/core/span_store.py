"""Span 应用内持久化 — 供管理端 Trace 瀑布图查询（Phase 2 基础）。

设计：
- ``CygnusXSpanProcessor`` 在 span 启动时（仍在业务上下文内）把当前 ContextVar 里的
  session_id / request_id 写为 span 属性（session.id / request.id），使每个 span 都可
  关联到会话与请求。
- ``JsonlSpanExporter`` 把完成的 span 序列化为 JSONL 写入 ``cygnusx.spans.json.log``
  （按大小轮转）。OTel 的 export 在后台线程同步执行，写文件最契合，且与 session_logs
  的「扫描 JSONL」查询模式一致，无需数据库迁移。
- ``read_spans`` / ``build_trace_tree`` 供管理端按 trace_id / session_id 查询并重建 span 树。

遥测自身异常不得中断业务：导出失败仅丢弃该批 span 并告警。
"""

from __future__ import annotations

import json
import threading
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opentelemetry.sdk.trace import SpanProcessor

from cygnusx.core.logging import _resolve_log_dir

SPAN_LOG_NAME = "cygnusx.spans.json.log"
_KEEP_BACKUPS = 3
_write_lock = threading.Lock()


def _jsonable(value: Any) -> Any:
    """把 OTel 属性值转换为可 JSON 序列化结构。"""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


class CygnusXSpanProcessor(SpanProcessor):
    """在 span 启动时注入 session.id / request.id（从 ContextVar 读取）。"""

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        try:
            from cygnusx.middleware.trace_context import request_id_var, session_id_var

            session_id = session_id_var.get()
            if session_id:
                span.set_attribute("session.id", session_id)
            request_id = request_id_var.get()
            if request_id:
                span.set_attribute("request.id", request_id)
        except Exception:  # noqa: BLE001
            pass

    def on_end(self, span: Any) -> None:  # noqa: ARG002
        return

    def shutdown(self) -> None:
        return

    def force_flush(self, timeout_millis: int = 30000) -> bool:  # noqa: ARG002
        return True


def _span_to_dict(span: Any, service_name: str) -> dict[str, Any]:
    """把 ReadableSpan 转换为可序列化的 span 记录。"""
    ctx = span.context
    parent = span.parent
    attrs = dict(span.attributes or {})
    start_ns = span.start_time or 0
    end_ns = span.end_time or start_ns
    duration_ms = (end_ns - start_ns) / 1_000_000 if end_ns and start_ns else 0.0
    status = span.status
    events = []
    for ev in span.events or []:
        events.append(
            {
                "name": ev.name,
                "timestamp": datetime.fromtimestamp(ev.timestamp / 1e9, tz=UTC).isoformat()
                if ev.timestamp
                else "",
                "attributes": {k: _jsonable(v) for k, v in (ev.attributes or {}).items()},
            }
        )
    return {
        "trace_id": f"{ctx.trace_id:032x}",
        "span_id": f"{ctx.span_id:016x}",
        "parent_span_id": f"{parent.span_id:016x}" if parent is not None else None,
        "name": span.name,
        "kind": getattr(span.kind, "name", ""),
        "service": service_name,
        "start_time": datetime.fromtimestamp(start_ns / 1e9, tz=UTC).isoformat() if start_ns else "",
        "end_time": datetime.fromtimestamp(end_ns / 1e9, tz=UTC).isoformat() if end_ns else "",
        "start_ns": start_ns,
        "duration_ms": round(duration_ms, 3),
        "status_code": getattr(status.status_code, "name", "") if status else "",
        "status_message": (status.description if status else "") or "",
        "session_id": attrs.get("session.id", "") or "",
        "request_id": attrs.get("request.id", "") or "",
        "attributes": {k: _jsonable(v) for k, v in attrs.items()},
        "events": events,
    }


class JsonlSpanExporter:
    """把 span 追加写入 JSONL 文件（按大小轮转）。"""

    def __init__(self, max_bytes: int) -> None:
        self._max_bytes = max_bytes

    def _resolve_path(self) -> Path:
        return _resolve_log_dir() / SPAN_LOG_NAME

    def _rotate_if_needed(self, path: Path) -> None:
        try:
            if not path.exists() or path.stat().st_size < self._max_bytes:
                return
            # 滚动备份：.3 丢弃，.2→.3，.1→.2，current→.1
            for i in range(_KEEP_BACKUPS, 1, -1):
                src = path.with_suffix(path.suffix + f".{i - 1}")
                dst = path.with_suffix(path.suffix + f".{i}")
                if src.exists():
                    src.replace(dst)
            path.replace(path.with_suffix(path.suffix + ".1"))
        except OSError:
            pass

    def export(self, spans: Any) -> Any:
        try:
            path = self._resolve_path()
            service_name = ""
            lines: list[str] = []
            for span in spans:
                try:
                    if not service_name:
                        service_name = str(span.resource.attributes.get("service.name", ""))
                    lines.append(json.dumps(_span_to_dict(span, service_name), ensure_ascii=False))
                except Exception:  # noqa: BLE001
                    continue
            if not lines:
                return self._result_success()
            with _write_lock:
                self._rotate_if_needed(path)
                with path.open("a", encoding="utf-8") as fh:
                    fh.write("\n".join(lines) + "\n")
            return self._result_success()
        except Exception as exc:  # noqa: BLE001
            from loguru import logger

            logger.warning(f"span 持久化失败（丢弃该批 {len(list(spans))} 条）: {exc}")
            return self._result_failure()

    @staticmethod
    def _result_success() -> Any:
        from opentelemetry.sdk.trace.export import SpanExportResult

        return SpanExportResult.SUCCESS

    @staticmethod
    def _result_failure() -> Any:
        from opentelemetry.sdk.trace.export import SpanExportResult

        return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        return

    def force_flush(self, timeout_millis: int = 30000) -> bool:  # noqa: ARG002
        return True


# ===== 查询（供管理端） =====


def _read_lines(path: Path) -> list[str]:
    try:
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as zf:
                name = zf.namelist()[0] if zf.namelist() else None
                if not name:
                    return []
                with zf.open(name) as fh:
                    return fh.read().decode("utf-8", errors="replace").splitlines()
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _span_files(log_dir: Path, include_archives: bool) -> list[Path]:
    files: list[Path] = []
    active = log_dir / SPAN_LOG_NAME
    if active.exists():
        files.append(active)
    if include_archives:
        archives = [
            p for p in log_dir.glob(f"{SPAN_LOG_NAME}.*") if p.is_file() and p != active
        ]
        archives.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        files.extend(archives)
    return files


def read_spans(
    log_dir: Path,
    trace_id: str | None = None,
    session_id: str | None = None,
    include_archives: bool = False,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    """按 trace_id / session_id 扫描 span 记录（至少需指定其一）。"""
    if not trace_id and not session_id:
        return []
    needle = trace_id or session_id
    out: list[dict[str, Any]] = []
    for path in _span_files(log_dir, include_archives):
        for line in _read_lines(path):
            line = line.strip()
            if not line or needle not in line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if trace_id and rec.get("trace_id") != trace_id:
                continue
            if session_id and rec.get("session_id") != session_id:
                continue
            out.append(rec)
            if len(out) >= limit:
                return out
    out.sort(key=lambda r: r.get("start_ns") or 0)
    return out


def build_trace_tree(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把同一 trace 的 span 列表重建为树（children 按 start_ns 升序）。"""
    by_id: dict[str, dict[str, Any]] = {}
    for s in spans:
        node = dict(s)
        node["children"] = []
        by_id[node["span_id"]] = node
    roots: list[dict[str, Any]] = []
    for node in by_id.values():
        parent_id = node.get("parent_span_id")
        parent = by_id.get(parent_id) if parent_id else None
        if parent is not None:
            parent["children"].append(node)
        else:
            roots.append(node)
    for node in by_id.values():
        node["children"].sort(key=lambda c: c.get("start_ns") or 0)
    roots.sort(key=lambda r: r.get("start_ns") or 0)
    return roots
