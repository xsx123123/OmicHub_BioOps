"""工具调用错误码体系单元测试。

覆盖：
- errors.py 的异常/failure_kind 映射与 retryable 语义；
- ToolBridgeService 信封的 code / retryable 字段；
- 校验器收紧（可强转宽容、不可强转报 VALIDATION_ERROR、ignored_params 提示）。
"""

from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cygnusx.application.services.tool_bridge_service import ToolBridgeService
from cygnusx.core.exceptions import (
    CygnusXError,
    MCPConnectionError,
    NotFoundError,
    RateLimitError,
    TaskExecutionError,
    ValidationError,
)
from cygnusx.infrastructure.config.storage_config import StorageConfig
from cygnusx.infrastructure.storage import LocalStorageBackend
from cygnusx.infrastructure.storage.path_factory import StoragePathFactory
from cygnusx.tools.errors import (
    ToolErrorCode,
    code_from_exception,
    code_from_failure_kind,
    is_retryable,
)
from cygnusx.tools.schema_loader import ToolSchema, ToolsSchemaLoader


class _FakeLoader(ToolsSchemaLoader):
    """不读盘的伪造加载器。"""

    def __init__(self, tools: list[ToolSchema]) -> None:
        self._tools = tools
        self._config = None
        self._mtime = 0.0
        self._tools_by_name = {t.name: t for t in tools}

    def get_config(self):
        from cygnusx.tools.schema_loader import ToolsSchemaRegistry

        return ToolsSchemaRegistry(tools=self._tools)

    def list_tools(self):
        return list(self._tools)

    def get_tool(self, name: str):
        return self._tools_by_name.get(name)


def _volcano_schema() -> ToolSchema:
    return ToolSchema(
        key="volcano",
        name="cygnusx_plot_volcano",
        description="火山图",
        invocation_mode="backend_shim",
        shim_module="cygnusx.tools.shims.volcano",
        input_schema={
            "type": "object",
            "properties": {
                "data_text": {"type": "string"},
                "pval_cutoff": {"type": "number", "default": 0.05},
                "lfc_cutoff": {"type": "number", "default": 1.0},
            },
            "required": ["data_text"],
        },
        llm_result_fields=["stats", "success"],
        ui_result_fields=["plotly_figure"],
    )


def _memory_schema() -> ToolSchema:
    return ToolSchema(
        key="memory-search",
        name="cygnusx_search_memory",
        description="检索记忆",
        invocation_mode="backend_sync",
        service="cygnusx.application.services.agent_memory_tool_service.AgentMemoryToolService",
        method="search_memory",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        llm_result_fields=["summary", "success", "error"],
        ui_result_fields=[],
    )


_SAMPLE = "gene\tlog2FoldChange\tpadj\nTP53\t2.5\t0.001\nBRCA1\t-3.0\t0.0001"

# ---------------------------------------------------------------------------
# errors.py 纯函数映射
# ---------------------------------------------------------------------------


def test_code_from_exception_passthrough_explicit_code() -> None:
    exc = CygnusXError("boom", code="CONTAINER_FAILED")
    assert code_from_exception(exc) == ToolErrorCode.CONTAINER_FAILED


def test_code_from_exception_by_type() -> None:
    assert code_from_exception(ValidationError("x")) == ToolErrorCode.VALIDATION_ERROR
    assert code_from_exception(NotFoundError()) == ToolErrorCode.INPUT_NOT_FOUND
    assert code_from_exception(TaskExecutionError()) == ToolErrorCode.CONTAINER_FAILED
    assert code_from_exception(TimeoutError()) == ToolErrorCode.TIMEOUT
    assert (
        code_from_exception(subprocess.CalledProcessError(1, "cmd"))
        == ToolErrorCode.CONTAINER_FAILED
    )
    assert code_from_exception(MCPConnectionError()) == ToolErrorCode.UPSTREAM_ERROR
    assert code_from_exception(RateLimitError()) == ToolErrorCode.UPSTREAM_ERROR
    assert code_from_exception(RuntimeError("boom")) == ToolErrorCode.SERVICE_ERROR


def test_code_from_exception_ignores_unknown_explicit_code() -> None:
    exc = CygnusXError("boom", code="NOT_A_KNOWN_CODE")
    assert code_from_exception(exc) == ToolErrorCode.SERVICE_ERROR


def test_code_from_failure_kind() -> None:
    assert code_from_failure_kind("timeout") == ToolErrorCode.TIMEOUT
    assert code_from_failure_kind("connection_error") == ToolErrorCode.UPSTREAM_ERROR
    assert code_from_failure_kind("command_not_found") == ToolErrorCode.UPSTREAM_ERROR
    assert code_from_failure_kind("tool_error") == ToolErrorCode.UPSTREAM_ERROR
    assert code_from_failure_kind("file_reference") == ToolErrorCode.INPUT_NOT_FOUND
    assert code_from_failure_kind("something_else") == ToolErrorCode.UPSTREAM_ERROR
    assert code_from_failure_kind(None) == ToolErrorCode.UPSTREAM_ERROR


def test_retryable_semantics() -> None:
    assert is_retryable(ToolErrorCode.TIMEOUT) is True
    assert is_retryable(ToolErrorCode.TASK_SUBMIT_FAILED) is True
    assert is_retryable(ToolErrorCode.UPSTREAM_ERROR) is True
    assert is_retryable(ToolErrorCode.VALIDATION_ERROR) is False
    assert is_retryable(ToolErrorCode.INPUT_NOT_FOUND) is False
    assert is_retryable(ToolErrorCode.CONFIRMATION_REQUIRED) is False
    assert is_retryable(ToolErrorCode.CONFIRMATION_REJECTED) is False
    assert is_retryable(ToolErrorCode.SERVICE_ERROR) is False
    assert is_retryable(ToolErrorCode.CONTAINER_FAILED) is False
    assert is_retryable(ToolErrorCode.INTERNAL_ERROR) is False
    # 未知码一律不可重试
    assert is_retryable("WHATEVER") is False
    assert is_retryable(None) is False


# ---------------------------------------------------------------------------
# 信封 code / retryable 字段
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_tool_error_envelope_carries_code() -> None:
    service = ToolBridgeService(_FakeLoader([]))
    result = await service.execute("u1", "cygnusx_not_exist", {})

    assert result["success"] is False
    assert result["code"] == ToolErrorCode.VALIDATION_ERROR
    assert result["retryable"] is False
    assert result["llm_payload"]["code"] == ToolErrorCode.VALIDATION_ERROR
    assert result["llm_payload"]["retryable"] is False
    # 向后兼容：message 字段不变
    assert "未知工具" in result["llm_payload"]["error"]


@pytest.mark.asyncio
async def test_missing_required_param_maps_validation_error() -> None:
    service = ToolBridgeService(_FakeLoader([_volcano_schema()]))
    result = await service.execute("u1", "cygnusx_plot_volcano", {})

    assert result["code"] == ToolErrorCode.VALIDATION_ERROR
    assert result["llm_payload"]["code"] == ToolErrorCode.VALIDATION_ERROR
    assert result["retryable"] is False


@pytest.mark.asyncio
async def test_upload_ref_not_found_maps_input_not_found(tmp_path, monkeypatch) -> None:
    user_id = "u1"
    upload_dir = tmp_path / "users" / user_id / "workspace" / "chat-uploads"
    upload_dir.mkdir(parents=True)

    path_factory = StoragePathFactory(StorageConfig(data_root=str(tmp_path), users_subdir="users"))
    backend = LocalStorageBackend(path_factory=path_factory)
    monkeypatch.setattr(
        "cygnusx.application.services.tool_bridge_service.get_path_factory",
        lambda: path_factory,
    )

    service = ToolBridgeService(_FakeLoader([_volcano_schema()]), backend=backend)
    result = await service.execute(
        user_id, "cygnusx_plot_volcano", {"data_text": "upload://missing"}
    )

    assert result["success"] is False
    assert result["code"] == ToolErrorCode.INPUT_NOT_FOUND
    assert result["llm_payload"]["code"] == ToolErrorCode.INPUT_NOT_FOUND
    assert result["retryable"] is False


@pytest.mark.asyncio
async def test_workspace_ref_failure_maps_input_not_found(monkeypatch) -> None:
    monkeypatch.setattr(
        "cygnusx.application.services.tool_bridge_service.resolve_workspace_file_refs",
        AsyncMock(side_effect=ValidationError("工作区文件不存在、已移除或无权访问")),
    )
    service = ToolBridgeService(_FakeLoader([_volcano_schema()]))
    result = await service.execute(
        "u1", "cygnusx_plot_volcano", {"data_text": "file://some-id"}, context=MagicMock()
    )

    assert result["code"] == ToolErrorCode.INPUT_NOT_FOUND


@pytest.mark.asyncio
async def test_service_exception_maps_service_error(monkeypatch) -> None:
    async def fake_search(self, *, user_id, query, **_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(
        "cygnusx.application.services.agent_memory_tool_service.AgentMemoryToolService.search_memory",
        fake_search,
    )
    service = ToolBridgeService(_FakeLoader([_memory_schema()]))
    result = await service.execute("u1", "cygnusx_search_memory", {"query": "x"})

    assert result["success"] is False
    assert result["code"] == ToolErrorCode.SERVICE_ERROR
    assert result["llm_payload"]["code"] == ToolErrorCode.SERVICE_ERROR
    assert result["retryable"] is False


@pytest.mark.asyncio
async def test_service_cygnusx_error_code_passthrough(monkeypatch) -> None:
    async def fake_search(self, *, user_id, query, **_kwargs):
        raise CygnusXError("容器退出码 1", code="CONTAINER_FAILED")

    monkeypatch.setattr(
        "cygnusx.application.services.agent_memory_tool_service.AgentMemoryToolService.search_memory",
        fake_search,
    )
    service = ToolBridgeService(_FakeLoader([_memory_schema()]))
    result = await service.execute("u1", "cygnusx_search_memory", {"query": "x"})

    assert result["code"] == ToolErrorCode.CONTAINER_FAILED
    assert result["llm_payload"]["code"] == ToolErrorCode.CONTAINER_FAILED
    assert result["retryable"] is False


@pytest.mark.asyncio
async def test_service_timeout_maps_timeout_code(monkeypatch) -> None:
    async def fake_search(self, *, user_id, query, **_kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(
        "cygnusx.application.services.agent_memory_tool_service.AgentMemoryToolService.search_memory",
        fake_search,
    )
    service = ToolBridgeService(_FakeLoader([_memory_schema()]))
    result = await service.execute("u1", "cygnusx_search_memory", {"query": "x"})

    assert result["code"] == ToolErrorCode.TIMEOUT
    assert result["retryable"] is True


@pytest.mark.asyncio
async def test_service_returned_failure_dict_gets_default_code(monkeypatch) -> None:
    """service 返回 success=False 的业务失败（非异常）走 _package 错误路径，默认 SERVICE_ERROR。"""

    async def fake_search(self, *, user_id, query, **_kwargs):
        return {"success": False, "error": "没有相关记忆"}

    monkeypatch.setattr(
        "cygnusx.application.services.agent_memory_tool_service.AgentMemoryToolService.search_memory",
        fake_search,
    )
    service = ToolBridgeService(_FakeLoader([_memory_schema()]))
    result = await service.execute("u1", "cygnusx_search_memory", {"query": "x"})

    assert result["success"] is False
    assert result["is_error"] is True
    assert result["code"] == ToolErrorCode.SERVICE_ERROR
    assert result["llm_payload"]["code"] == ToolErrorCode.SERVICE_ERROR
    assert result["llm_payload"]["error"] == "没有相关记忆"
    assert result["retryable"] is False


@pytest.mark.asyncio
async def test_requires_confirm_carries_confirmation_code() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    from cygnusx.application.schemas.tool_invocation import ToolInvocationContext

    class _FakeAsyncSession(AsyncSession):
        def __init__(self):
            pass

    schema = _volcano_schema()
    schema.requires_confirm = True
    service = ToolBridgeService(_FakeLoader([schema]))
    context = ToolInvocationContext(
        user_id="u1", session_id="s-test", db=_FakeAsyncSession()  # type: ignore[arg-type]
    )
    result = await service.execute(
        "u1", "cygnusx_plot_volcano", {"data_text": _SAMPLE}, context=context
    )

    assert result["success"] is True
    assert result["llm_payload"]["needs_confirm"] is True
    assert result["llm_payload"]["code"] == ToolErrorCode.CONFIRMATION_REQUIRED
    assert result["ui_payload"]["actions"]["approve"]["url"].startswith(
        "/api/v1/ai/tool-invocations/"
    )


@pytest.mark.asyncio
async def test_arq_enqueue_failure_maps_task_submit_failed() -> None:
    schema = ToolSchema(
        key="phylo",
        name="cygnusx_build_phylogenetic_tree",
        description="构建系统发育树",
        invocation_mode="backend_async",
        input_schema={
            "type": "object",
            "properties": {"file_id": {"type": "string"}},
            "required": ["file_id"],
        },
        llm_result_fields=["success", "error"],
        ui_result_fields=["error"],
    )
    service = ToolBridgeService(_FakeLoader([schema]))

    fake_pool = MagicMock()
    fake_pool.enqueue_job = AsyncMock(return_value=None)

    with patch(
        "cygnusx.infrastructure.task_queue.arq_pool.get_arq_pool",
        new_callable=AsyncMock,
        return_value=fake_pool,
    ):
        result = await service.execute("u1", "cygnusx_build_phylogenetic_tree", {"file_id": "f1"})

    assert result["success"] is False
    assert result["code"] == ToolErrorCode.TASK_SUBMIT_FAILED
    assert result["llm_payload"]["code"] == ToolErrorCode.TASK_SUBMIT_FAILED
    assert result["retryable"] is True
    assert result["llm_payload"]["retryable"] is True


# ---------------------------------------------------------------------------
# 校验器收紧
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_string_number_is_coerced_leniently() -> None:
    """LLM 常传"字符串数字"，应安全强转而不是报错。"""
    service = ToolBridgeService(_FakeLoader([_volcano_schema()]))
    result = await service.execute(
        "u1",
        "cygnusx_plot_volcano",
        {"data_text": _SAMPLE, "pval_cutoff": "0.05", "lfc_cutoff": "1"},
    )

    assert result["success"] is True, result["llm_payload"]
    assert result["llm_payload"]["stats"]["total"] == 2


@pytest.mark.asyncio
async def test_uncoercible_number_returns_validation_error() -> None:
    service = ToolBridgeService(_FakeLoader([_volcano_schema()]))
    result = await service.execute(
        "u1",
        "cygnusx_plot_volcano",
        {"data_text": _SAMPLE, "pval_cutoff": "not-a-number"},
    )

    assert result["success"] is False
    assert result["code"] == ToolErrorCode.VALIDATION_ERROR
    assert "pval_cutoff" in result["llm_payload"]["error"]


@pytest.mark.asyncio
async def test_bool_for_number_returns_validation_error() -> None:
    service = ToolBridgeService(_FakeLoader([_volcano_schema()]))
    result = await service.execute(
        "u1",
        "cygnusx_plot_volcano",
        {"data_text": _SAMPLE, "pval_cutoff": True},
    )

    assert result["success"] is False
    assert result["code"] == ToolErrorCode.VALIDATION_ERROR


@pytest.mark.asyncio
async def test_undeclared_param_reported_as_ignored() -> None:
    """未声明参数仍被丢弃，但 llm_payload 附带 ignored_params 提示。"""
    service = ToolBridgeService(_FakeLoader([_volcano_schema()]))
    result = await service.execute(
        "u1",
        "cygnusx_plot_volcano",
        {"data_text": _SAMPLE, "typo_param": 1},
    )

    assert result["success"] is True
    assert result["llm_payload"]["ignored_params"] == ["typo_param"]


@pytest.mark.asyncio
async def test_control_params_not_reported_as_ignored() -> None:
    """下划线开头的桥接层控制参数（_confirmation_id / _confirmed）不算未声明参数。

    _confirmed 已不再是放行凭证（模型无法自证）；首次带控制参数的调用返回确认卡，
    且不得把控制参数计入 ignored_params。
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    from cygnusx.application.schemas.tool_invocation import ToolInvocationContext

    class _FakeAsyncSession(AsyncSession):
        def __init__(self):
            pass

    schema = _volcano_schema()
    schema.requires_confirm = True
    service = ToolBridgeService(_FakeLoader([schema]))
    context = ToolInvocationContext(
        user_id="u1", session_id="s-test", db=_FakeAsyncSession()  # type: ignore[arg-type]
    )
    result = await service.execute(
        "u1",
        "cygnusx_plot_volcano",
        {"data_text": _SAMPLE, "_confirmed": True},
        context=context,
    )

    assert result["success"] is True
    assert result["llm_payload"]["needs_confirm"] is True
    assert "ignored_params" not in result["llm_payload"]
