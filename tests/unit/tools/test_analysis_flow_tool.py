"""分析流程 AI 工具链路单元测试。

验证 ToolBridge 能正确分发 analysis_flow 模式工具到 AnalysisFlowToolService，
并返回确认卡 / 任务卡等双通道结果。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.schemas.task import TaskResponse
from cygnusx.application.schemas.tool_invocation import ToolInvocationContext
from cygnusx.application.services.tool_bridge_service import ToolBridgeService
from cygnusx.domain.task.value_objects import ExecutionMode
from cygnusx.tools.schema_loader import ToolSchema, ToolsSchemaLoader


class _FakeAsyncSession(AsyncSession):
    def __init__(self):
        pass


class _FakeLoader(ToolsSchemaLoader):
    """伪造加载器，仅包含动态 RNA-seq Flow tool。"""

    def __init__(self) -> None:
        self._config = None
        self._mtime = 0.0
        self._tools_by_name = {}
        self._flow_tools: list[ToolSchema] = []

    def get_config(self):
        from cygnusx.tools.schema_loader import ToolsSchemaRegistry

        return ToolsSchemaRegistry(tools=[])

    def list_tools(self):
        return self._flow_tools

    def get_tool(self, name: str):
        return self._tools_by_name.get(name)

    def add_tool(self, tool: ToolSchema) -> None:
        self._flow_tools.append(tool)
        self._tools_by_name[tool.name] = tool


def _make_context() -> ToolInvocationContext:
    return ToolInvocationContext(
        user_id="test-user",
        session_id="test-session",
        db=_FakeAsyncSession(),  # type: ignore[arg-type]
    )


def _rna_tool_schema() -> ToolSchema:
    return ToolSchema(
        key="flow-rna_seq",
        name="cygnusx_prepare_rna_seq_submission",
        description="RNA-seq prepare",
        category="workflow",
        invocation_mode="analysis_flow",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "parameters": {"type": "object"},
                "sample_sheet": {"type": "array"},
                "comparisons": {"type": "array"},
            },
            "required": ["parameters", "sample_sheet"],
        },
        llm_result_fields=["valid", "confirmation_id", "summary"],
        ui_result_fields=["confirmation_card"],
        extra={"flow_id": "rna_seq", "tool_role": "prepare"},
    )


@pytest.fixture
def bridge() -> ToolBridgeService:
    loader = _FakeLoader()
    loader.add_tool(_rna_tool_schema())
    return ToolBridgeService(loader)


@pytest.mark.asyncio
async def test_analysis_flow_prepare_returns_confirmation_card(bridge: ToolBridgeService) -> None:
    context = _make_context()
    arguments = {
        "name": "Test",
        "parameters": {
            "project_name": "TestProject",
            "Genome_Version": "hg38",
            "species": "Homo sapiens",
            "client": "Test",
            "raw_data_path": "/data/raw",
            "execution_mode": "local",
            "queue_id": "default",
            "Library_Types": "fr-unstranded",
        },
        "sample_sheet": [
            {"sample": "S1", "sample_name": "Sample1", "group": "ctrl"},
            {"sample": "S2", "sample_name": "Sample2", "group": "treat"},
        ],
        "comparisons": [{"name": "TvsC", "Control": "ctrl", "Treat": "treat"}],
    }

    result = await bridge.execute("test-user", "cygnusx_prepare_rna_seq_submission", arguments, context=context)

    assert result["success"] is True
    assert result["is_error"] is False
    assert result["llm_payload"]["valid"] is True
    assert "confirmation_id" in result["llm_payload"]
    assert result["ui_payload"]["type"] == "confirmation_card"
    assert result["ui_payload"]["sample_count"] == 2
    assert result["ui_payload"]["comparison_count"] == 1


@pytest.mark.asyncio
async def test_analysis_flow_prepare_validation_error(bridge: ToolBridgeService) -> None:
    context = _make_context()
    arguments = {
        "parameters": {},  # 缺少必填参数
        "sample_sheet": [],
    }

    result = await bridge.execute("test-user", "cygnusx_prepare_rna_seq_submission", arguments, context=context)

    assert result["success"] is True  # 校验失败以正常 tool_result 返回
    assert result["llm_payload"]["valid"] is False
    assert result["ui_payload"]["type"] == "error_card"
    assert len(result["ui_payload"]["errors"]) > 0


@pytest.mark.asyncio
async def test_analysis_flow_requires_context(bridge: ToolBridgeService) -> None:
    arguments = {
        "parameters": {"project_name": "Test"},
        "sample_sheet": [{"sample": "S1", "sample_name": "Sample1", "group": "ctrl"}],
    }

    result = await bridge.execute("test-user", "cygnusx_prepare_rna_seq_submission", arguments)

    assert result["success"] is False
    assert "需要 ToolInvocationContext" in result["llm_payload"]["error"]


@pytest.mark.asyncio
async def test_analysis_flow_confirm_and_submit(bridge: ToolBridgeService) -> None:
    context = _make_context()
    arguments = {
        "name": "Test",
        "parameters": {
            "project_name": "TestProject",
            "Genome_Version": "hg38",
            "species": "Homo sapiens",
            "client": "Test",
            "raw_data_path": "/data/raw",
            "execution_mode": "local",
            "queue_id": "default",
            "Library_Types": "fr-unstranded",
        },
        "sample_sheet": [
            {"sample": "S1", "sample_name": "Sample1", "group": "ctrl"},
            {"sample": "S2", "sample_name": "Sample2", "group": "treat"},
        ],
        "comparisons": [{"name": "TvsC", "Control": "ctrl", "Treat": "treat"}],
    }

    # 先 prepare
    result = await bridge.execute("test-user", "cygnusx_prepare_rna_seq_submission", arguments, context=context)
    confirmation_id = result["llm_payload"]["confirmation_id"]

    from datetime import datetime

    fake_response = TaskResponse(
        id=uuid4(),
        flow_id="rna_seq",
        user_id=uuid4(),
        name="Test",
        status="queued",
        execution_mode=ExecutionMode.LOCAL.value,
        parameters={},
        work_dir="/tmp",
        result_path="",
        error_message="",
        progress=0.0,
        logs=[],
        created_at=datetime.now(),
        started_at=None,
        finished_at=None,
    )

    with patch(
        "cygnusx.application.services.tool_confirmation_service.TaskService.submit",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        from cygnusx.application.services.analysis_flow_tool_service import (
            AnalysisFlowToolService,
        )
        from cygnusx.application.services.tool_confirmation_service import ConfirmationError

        # 模型通道：PENDING 未经人类确认必须被拒绝（确认门不可自证）
        service = AnalysisFlowToolService(context=context)
        with pytest.raises(ConfirmationError) as exc_info:
            await service.confirm_and_submit(confirmation_id)
        assert exc_info.value.code == "CONFIRMATION_REQUIRED"

        # 人类 JWT 通道（ai.py approve 端点语义）：一步消费 PENDING 并提交
        human_context = ToolInvocationContext(
            user_id="test-user",
            session_id="test-session",
            db=_FakeAsyncSession(),  # type: ignore[arg-type]
            extra={"human_confirmed": True},
        )
        human_service = AnalysisFlowToolService(context=human_context)
        submit_result = await human_service.confirm_and_submit(confirmation_id)

        # 记录已 SUBMITTED：模型侧重发同一流水线时幂等回放，不重复建任务
        replay_result = await service.confirm_and_submit(confirmation_id)

    assert submit_result["task_id"] is not None
    assert submit_result["status"] == "QUEUED"
    assert submit_result["task_card"]["type"] == "task_card"
    assert replay_result["task_id"] == submit_result["task_id"]


@pytest.mark.asyncio
async def test_context_is_not_serializable() -> None:
    context = _make_context()
    with pytest.raises(RuntimeError):
        context.model_dump()
