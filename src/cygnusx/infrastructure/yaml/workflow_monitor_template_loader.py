"""Workflow monitor dashboard template YAML loader."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import yaml
from loguru import logger

from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import NotFoundError, YAMLConfigError

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

WIDGET_TYPES = {
    "metric",
    "task_table",
    "event_stream",
    "error_list",
    "rule_timeline",
    "worker_status",
}
DATA_SOURCES = {"summary", "tasks", "events", "errors", "task_events", "workers"}


class WorkflowMonitorTemplateLoader:
    """Load monitor templates from YAML with simple mtime based hot reload."""

    def __init__(self, template_dir: str | None = None):
        self._template_dir = Path(template_dir or get_settings().workflow_monitor_template_dir)
        self._cache: dict[str, dict[str, Any]] = {}
        self._mtime: dict[str, float] = {}

    def list_templates(self, force: bool = False) -> list[dict[str, Any]]:
        templates: list[dict[str, Any]] = []
        if not self._template_dir.exists():
            logger.warning(f"流程监控模板目录不存在: {self._template_dir}")
            return templates

        for path in sorted(self._template_dir.glob("*.y*ml")):
            try:
                templates.append(self.load(path.stem, force=force))
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"跳过无效流程监控模板 {path}: {exc}")
        return templates

    def load(self, template_id: str, force: bool = False) -> dict[str, Any]:
        if not _ID_PATTERN.match(template_id):
            raise YAMLConfigError("流程监控模板 ID 只能包含字母、数字、下划线和短横线")

        path = self._resolve_path(template_id)
        if path is None:
            raise NotFoundError("流程监控模板不存在")

        current_mtime = path.stat().st_mtime
        if not force and template_id in self._cache and self._mtime.get(template_id) == current_mtime:
            return self._cache[template_id]

        with open(path, encoding="utf-8") as f:
            raw = cast(dict[str, Any], yaml.safe_load(f) or {})

        self._validate(raw)
        self._cache[template_id] = raw
        self._mtime[template_id] = current_mtime
        return raw

    def reload(self) -> int:
        self._cache.clear()
        self._mtime.clear()
        return len(self.list_templates(force=True))

    def _resolve_path(self, template_id: str) -> Path | None:
        for suffix in (".yaml", ".yml"):
            path = self._template_dir / f"{template_id}{suffix}"
            if path.exists():
                return path
        return None

    @staticmethod
    def _validate(template: dict[str, Any]) -> None:
        template_id = str(template.get("id") or "")
        if not template_id or not _ID_PATTERN.match(template_id):
            raise YAMLConfigError("流程监控模板缺少合法 id")
        if not template.get("name"):
            raise YAMLConfigError(f"流程监控模板 {template_id} 缺少 name")

        widgets = template.get("widgets") or []
        if not isinstance(widgets, list):
            raise YAMLConfigError(f"流程监控模板 {template_id} 的 widgets 必须是列表")

        seen: set[str] = set()
        for widget in widgets:
            if not isinstance(widget, dict):
                raise YAMLConfigError(f"流程监控模板 {template_id} 存在非法 widget")
            widget_id = str(widget.get("id") or "")
            if not widget_id or widget_id in seen:
                raise YAMLConfigError(f"流程监控模板 {template_id} 存在重复或空 widget id")
            seen.add(widget_id)

            widget_type = str(widget.get("type") or "")
            if widget_type not in WIDGET_TYPES:
                raise YAMLConfigError(f"不支持的监控 widget 类型: {widget_type}")

            data_source = str(widget.get("data_source") or "")
            if data_source and data_source not in DATA_SOURCES:
                raise YAMLConfigError(f"不支持的监控数据源: {data_source}")


__all__ = ["WorkflowMonitorTemplateLoader"]
