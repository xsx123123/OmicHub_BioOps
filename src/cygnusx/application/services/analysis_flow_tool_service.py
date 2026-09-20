"""分析流程 AI 工具服务。

把任务中心的分析流程暴露为 AI 可调用的工具：
- 发现 / 详情
- 预检（prepare）
- 确认并提交（confirm）
- 状态 / 摘要查询
"""

from __future__ import annotations

from typing import Any

from cygnusx.application.schemas.tool_invocation import ToolInvocationContext
from cygnusx.application.services.flow_service import FlowService
from cygnusx.application.services.managed_file_resolver import ManagedFileResolver
from cygnusx.application.services.task_service import TaskService
from cygnusx.application.services.tool_confirmation_service import (
    ToolConfirmationService,
    get_tool_confirmation_service,
)
from cygnusx.domain.flow.entities import FlowConfig
from cygnusx.domain.flow.submission_validator import FlowSubmissionValidator
from cygnusx.domain.flow.value_objects import FlowAIConfig


class FlowAIError(Exception):
    """Flow AI 工具错误"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class AnalysisFlowToolService:
    """分析流程 AI 工具服务。"""

    def __init__(
        self,
        context: ToolInvocationContext,
        flow_service: FlowService | None = None,
        file_resolver: ManagedFileResolver | None = None,
        validator: FlowSubmissionValidator | None = None,
        confirmation_service: ToolConfirmationService | None = None,
    ):
        self.context = context
        self._flow_service = flow_service or FlowService()
        self._file_resolver = file_resolver or ManagedFileResolver()
        self._validator = validator or FlowSubmissionValidator(self._file_resolver)
        self._confirmation_service = confirmation_service or get_tool_confirmation_service()

    # ===== 发现 =====
    async def discover(self) -> list[dict[str, Any]]:
        """列出当前用户可见的 AI-enabled Flow。"""
        flows = self._flow_service.list_ai_enabled_flows()
        return [
            {
                "flow_id": flow.meta.id,
                "name": flow.meta.name,
                "category": flow.meta.category,
                "description": (flow.ai.assistant_summary if flow.ai else None)
                or flow.meta.description,
                "requires_confirmation": (flow.ai.requires_confirmation if flow.ai else True),
                "allowed_execution_modes": (
                    flow.ai.allowed_execution_modes if flow.ai else ["local"]
                ),
            }
            for flow in flows
        ]

    # ===== 详情 =====
    async def describe(self, flow_id: str) -> dict[str, Any]:
        """返回单个 Flow 的完整参数、样本表、比较组说明与 AI 提示。"""
        flow = self._get_flow_config(flow_id)
        self._assert_ai_enabled(flow)

        from cygnusx.tools.flow_schema_compiler import FlowToolSchemaCompiler

        compiler = FlowToolSchemaCompiler()
        return {
            "flow_id": flow.meta.id,
            "name": flow.meta.name,
            "description": flow.meta.description,
            "assistant_summary": flow.ai.assistant_summary if flow.ai else "",
            "parameter_schema": compiler.compile_parameters(flow, flow.ai or FlowAIConfig(enabled=False)),
            "sample_sheet_schema": (
                compiler._compile_sample_sheet(flow.sample_sheet) if flow.sample_sheet else None
            ),
            "comparison_schema": compiler._compile_comparisons(flow) if self._has_comparisons(flow) else None,
        }

    # ===== 预检 =====
    async def prepare(self, flow_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """预检参数，生成确认预览。"""
        flow = self._get_flow_config(flow_id)
        self._assert_ai_enabled(flow)

        validation = await self._validator.validate(self.context, flow, arguments)
        if not validation.valid:
            return {
                "valid": False,
                "errors": [e.model_dump() for e in validation.errors],
                "warnings": [w.model_dump() for w in validation.warnings],
            }

        assert validation.normalized_request is not None

        # 创建确认记录
        record = await self._confirmation_service.create(
            context=self.context,
            flow_id=flow_id,
            flow_name=flow.meta.name,
            normalized_request=validation.normalized_request,
        )

        sample_count = len(validation.normalized_request.sample_sheet)
        comparison_count = len(validation.normalized_request.comparisons or [])
        resource_hint = (
            flow.ai.default_resource_hint if flow.ai else {}
        ) or {
            "cores": flow.execution.default_resources.cores,
            "memory": flow.execution.default_resources.memory,
            "time": flow.execution.default_resources.time,
        }

        return {
            "valid": True,
            "confirmation_id": record.confirmation_id,
            "flow_id": flow_id,
            "flow_name": flow.meta.name,
            "sample_count": sample_count,
            "comparison_count": comparison_count,
            "resource_hint": resource_hint,
            "parameter_preview": validation.normalized_request.parameters,
            "expires_at": record.expires_at.isoformat(),
            "requires_confirmation": flow.ai.requires_confirmation if flow.ai else True,
        }

    # ===== 确认提交 =====
    async def confirm_and_submit(self, confirmation_id: str) -> dict[str, Any]:
        """消费确认记录，提交任务。"""
        task_service = TaskService(self.context.db)
        result = await self._confirmation_service.approve(
            context=self.context,
            confirmation_id=confirmation_id,
            task_service=task_service,
        )
        if result.status != "SUBMITTED":
            raise FlowAIError("CONFIRMATION_FAILED", result.message or "确认失败")

        return {
            "task_id": result.task_id,
            "status": "QUEUED",
            "task_url": f"/tasks/{result.task_id}",
            "task_card": result.task_card,
        }

    # ===== 查询 =====
    async def get_task_status(self, task_id: str) -> dict[str, Any]:
        """查询当前用户自己的任务状态。"""
        from uuid import UUID

        task_service = TaskService(self.context.db)
        task = await task_service.get_task(UUID(task_id), self.context.user_id)
        return {
            "task_id": str(task.id),
            "status": task.status,
            "progress": task.progress,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "finished_at": task.finished_at.isoformat() if task.finished_at else None,
            "error_summary": task.error_message if task.status.lower() == "failed" else None,
        }

    async def get_task_summary(self, task_id: str) -> dict[str, Any]:
        """任务完成后返回受控摘要。"""
        from uuid import UUID

        task_service = TaskService(self.context.db)
        task = await task_service.get_task(UUID(task_id), self.context.user_id)
        if task.status.lower() != "success":
            raise FlowAIError("TASK_NOT_COMPLETED", "任务尚未完成，无法获取摘要")

        # 受控摘要：仅返回少量指标与报告链接，不读取大文件
        return {
            "task_id": str(task.id),
            "status": task.status,
            "flow_id": task.flow_id,
            "name": task.name,
            "report_url": f"/tasks/{task.id}/report",
            "result_path": task.result_path,
            "metrics": {
                "sample_count": task.parameters.get("_sample_count"),
                "comparison_count": task.parameters.get("_comparison_count"),
            },
        }

    def _get_flow_config(self, flow_id: str) -> FlowConfig:
        return self._flow_service.get_flow_config(flow_id)

    def _assert_ai_enabled(self, flow: FlowConfig) -> None:
        if not flow.ai or not flow.ai.enabled:
            raise FlowAIError("AI_DISABLED", f"流程 '{flow.meta.id}' 未启用 AI 助手接入")

    @staticmethod
    def _has_comparisons(flow: FlowConfig) -> bool:
        return any(p.name == "comparisons" for p in flow.parameters)
