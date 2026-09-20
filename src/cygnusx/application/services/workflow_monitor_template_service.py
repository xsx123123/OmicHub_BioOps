"""Workflow monitor template application service."""

from __future__ import annotations

from typing import Any

from cygnusx.application.schemas.workflow_monitor import (
    MonitorTemplateListItem,
    MonitorTemplateListResponse,
    MonitorTemplateResponse,
)
from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import AuthorizationError
from cygnusx.infrastructure.yaml.workflow_monitor_template_loader import (
    WorkflowMonitorTemplateLoader,
)


class WorkflowMonitorTemplateService:
    def __init__(self, loader: WorkflowMonitorTemplateLoader | None = None):
        self._loader = loader or WorkflowMonitorTemplateLoader()
        self._settings = get_settings()

    def list_templates(self, role: str) -> MonitorTemplateListResponse:
        items: list[MonitorTemplateListItem] = []
        for tpl in self._loader.list_templates():
            if self._is_template_visible(tpl, role):
                items.append(
                    MonitorTemplateListItem(
                        id=str(tpl["id"]),
                        name=str(tpl["name"]),
                        version=str(tpl.get("version", "1.0.0")),
                        scope=str(tpl.get("scope", "user")),
                        description=str(tpl.get("description", "")),
                    )
                )
        return MonitorTemplateListResponse(items=items, total=len(items))

    def get_template(self, template_id: str | None, role: str) -> MonitorTemplateResponse:
        resolved_id = template_id or self._settings.workflow_monitor_default_template
        tpl = self._loader.load(resolved_id)
        if not self._is_template_visible(tpl, role):
            raise AuthorizationError("无权访问该流程监控模板")

        filtered = dict(tpl)
        filtered["widgets"] = [
            widget for widget in tpl.get("widgets", []) if self._is_widget_visible(widget, role)
        ]
        return MonitorTemplateResponse(**filtered)

    def reload(self) -> dict[str, Any]:
        count = self._loader.reload()
        return {"loaded": count, "message": f"已重新加载 {count} 个流程监控模板"}

    @staticmethod
    def _is_template_visible(template: dict[str, Any], role: str) -> bool:
        if role == "admin":
            return True
        roles = (template.get("permissions") or {}).get("roles") or ["user", "admin"]
        return role in roles and template.get("scope", "user") != "admin"

    @staticmethod
    def _is_widget_visible(widget: dict[str, Any], role: str) -> bool:
        if role == "admin":
            return True
        roles = (widget.get("visible") or {}).get("roles")
        return not roles or role in roles
