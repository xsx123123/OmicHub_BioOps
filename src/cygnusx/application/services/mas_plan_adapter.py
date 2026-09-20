"""Adapter for safe, preview-only MAS plans emitted by Chat and Studio."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from cygnusx.application.services.flow_registry import get_flow_registry
from cygnusx.application.services.mas_plan_validator import MASPlanValidator
from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import ValidationError
from cygnusx.domain.mas.models import ExecutionPlan
from cygnusx.infrastructure.mas.agent_capabilities import load_agent_capabilities
from cygnusx.infrastructure.mas.artifact_schemas import load_artifact_schemas

MAS_PLAN_PREVIEW_TOOL_NAME = "mas_plan_preview"
MAS_PLAN_PREVIEW_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": MAS_PLAN_PREVIEW_TOOL_NAME,
        "description": "生成可供用户确认的多智能体分析计划预览。此工具绝不创建或执行任务；仅在用户明确要组织 EBI 下载、RNAFlow、QC 和火山图等可支持步骤时调用。",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {"type": "string", "minLength": 1, "maxLength": 200},
                "nodes": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "key": {"type": "string"},
                            "agent_id": {"type": "string"},
                            "intent": {"type": "string"},
                            "depends_on": {"type": "array", "items": {"type": "string"}},
                            "input_contract": {"type": "object"},
                            "output_contract": {"type": "object"},
                            "parameters": {"type": "object"},
                            "resources": {"type": "object"},
                            "max_attempts": {"type": "integer", "minimum": 1, "maximum": 10},
                            "allow_skipped_dependencies": {"type": "boolean"},
                        },
                        "required": ["key", "agent_id", "intent"],
                    },
                },
                "context_summary": {"type": "object"},
            },
            "required": ["title", "nodes"],
        },
    },
}
MAS_PLAN_PREVIEW_PROMPT_SUFFIX = """当用户明确希望组织可支持的多步骤分析（如 EBI 下载、RNAFlow、QC 阻断、火山图）时，先调用 mas_plan_preview 生成计划卡片。该工具只生成预览，绝不表示已执行；计划必须使用已注册的 Agent 和能力，火山图必须经 quality-gate。信息不足时先提问，不要臆造样本、accession、文件路径或参数。"""


class MASPlanPreviewAdapter:
    """Validates an LLM tool payload and exposes a frontend-only plan preview."""

    def __init__(self) -> None:
        settings = get_settings()
        self._validator = MASPlanValidator(
            load_agent_capabilities(settings.mas_agent_capabilities_yaml),
            load_artifact_schemas(settings.mas_artifact_schemas_yaml),
            get_flow_registry(),
        )

    def adapt(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            plan = ExecutionPlan.model_validate(
                {"title": payload.get("title"), "nodes": payload.get("nodes", [])}
            )
            self._validator.validate(plan)
            context_summary = self._safe_context_summary(payload.get("context_summary", {}))
        except (PydanticValidationError, ValidationError, TypeError, ValueError) as exc:
            return {"success": False, "error": f"MAS 计划校验失败：{exc}"}

        plan_payload = plan.model_dump(mode="json")
        return {
            "success": True,
            "result": {
                "llm_payload": {
                    "title": plan.title,
                    "node_count": len(plan.nodes),
                    "message": "已生成待确认的 MAS 计划预览；用户确认前不会创建或执行 Run。",
                },
                "ui_payload": {
                    "mas_plan": plan_payload,
                    "context_summary": context_summary,
                },
            },
        }

    @staticmethod
    def _safe_context_summary(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        try:
            serialized = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return {}
        if len(serialized) > 4096:
            return {"note": "上下文摘要过长，已省略；请在确认前补充必要参数。"}
        return json.loads(serialized)
