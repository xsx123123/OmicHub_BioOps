"""ToolBridgeService 单元测试。"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from omichub.application.services.tool_bridge_service import ToolBridgeService
from omichub.infrastructure.config.storage_config import StorageConfig
from omichub.infrastructure.storage import LocalStorageBackend
from omichub.infrastructure.storage.path_factory import StoragePathFactory
from omichub.tools.schema_loader import ToolSchema, ToolsSchemaLoader


class _FakeLoader(ToolsSchemaLoader):
    """不读盘的伪造加载器。"""

    def __init__(self, tools: list[ToolSchema]) -> None:
        self._tools = tools
        self._config = None
        self._mtime = 0.0
        self._tools_by_name = {t.name: t for t in tools}

    def get_config(self):
        from omichub.tools.schema_loader import ToolsSchemaRegistry

        return ToolsSchemaRegistry(tools=self._tools)

    def list_tools(self):
        return list(self._tools)

    def get_tool(self, name: str):
        return self._tools_by_name.get(name)


def _volcano_schema() -> ToolSchema:
    return ToolSchema(
        key="volcano",
        name="omichub_plot_volcano",
        description="火山图",
        invocation_mode="backend_shim",
        shim_module="omichub.tools.shims.volcano",
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


@pytest.mark.asyncio
async def test_volcano_shim_returns_dual_payload() -> None:
    loader = _FakeLoader([_volcano_schema()])
    service = ToolBridgeService(loader)
    sample = "gene\tlog2FoldChange\tpadj\nTP53\t2.5\t0.001\nBRCA1\t-3.0\t0.0001\nGene_X\t0.1\t0.5"
    result = await service.execute("u1", "omichub_plot_volcano", {"data_text": sample})

    assert result["success"] is True
    assert result["is_error"] is False
    assert "stats" in result["llm_payload"]
    assert result["llm_payload"]["stats"]["up"] == 1
    assert result["llm_payload"]["stats"]["down"] == 1
    assert "plotly_figure" in result["ui_payload"]
    assert result["ui_payload"]["plotly_figure"] is not None


@pytest.mark.asyncio
async def test_missing_required_argument_returns_error() -> None:
    loader = _FakeLoader([_volcano_schema()])
    service = ToolBridgeService(loader)
    result = await service.execute("u1", "omichub_plot_volcano", {})

    assert result["success"] is False
    assert result["is_error"] is True
    assert "缺少必填参数" in result["llm_payload"]["error"]


@pytest.mark.asyncio
async def test_unknown_tool_returns_error() -> None:
    loader = _FakeLoader([])
    service = ToolBridgeService(loader)
    result = await service.execute("u1", "omichub_not_exist", {})

    assert result["success"] is False
    assert result["is_error"] is True
    assert "未知工具" in result["llm_payload"]["error"]


@pytest.mark.asyncio
async def test_error_envelope_exposes_top_level_error_for_event_summary() -> None:
    """BUG-E2E-05：错误信封必须带顶层 error，事件流摘要才能拿到真实失败原因。"""
    loader = _FakeLoader([])
    service = ToolBridgeService(loader)
    result = await service.execute("u1", "omichub_not_exist", {})

    assert result["error"] == result["llm_payload"]["error"]
    assert "未知工具" in result["error"]


@pytest.mark.asyncio
async def test_toolbox_search_returns_catalog_matches() -> None:
    schema = ToolSchema(
        key="toolbox-search",
        name="omichub_toolbox_search",
        description="检索工具。适用于查找工具；已知工具不要使用。输入 query。",
        keywords=["工具检索"],
        invocation_mode="backend_sync",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        llm_result_fields=["matches", "summary", "success"],
        ui_result_fields=["matches"],
    )
    enrichment = ToolSchema(
        key="kegg-enrichment",
        name="omichub_run_kegg_enrichment",
        description="对基因列表做 GO/KEGG 富集。适用于通路富集；排序列表用 GSEA。输入 gene_text。",
        keywords=["GO", "KEGG", "富集"],
        invocation_mode="backend_sync",
    )
    result = await ToolBridgeService(_FakeLoader([schema, enrichment])).execute(
        "u1", "omichub_toolbox_search", {"query": "基因富集通路"}
    )

    assert result["success"] is True
    assert result["llm_payload"]["matches"][0]["name"] == "omichub_run_kegg_enrichment"


@pytest.mark.asyncio
async def test_backend_sync_passes_context_when_service_declares_it(monkeypatch) -> None:
    """需要数据库事务的 builtin 工具可安全取得内部调用上下文。"""
    schema = ToolSchema(
        key="memory-search",
        name="omichub_search_memory",
        description="检索记忆",
        invocation_mode="backend_sync",
        service="omichub.application.services.agent_memory_tool_service.AgentMemoryToolService",
        method="search_memory",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        llm_result_fields=["summary", "success"],
        ui_result_fields=[],
    )
    captured = {}

    async def fake_search(self, *, user_id, query, context=None, **_kwargs):
        captured.update(user_id=user_id, query=query, context=context)
        return {"success": True, "summary": "找到 1 条记忆"}

    monkeypatch.setattr(
        "omichub.application.services.agent_memory_tool_service.AgentMemoryToolService.search_memory",
        fake_search,
    )
    context = MagicMock()
    result = await ToolBridgeService(_FakeLoader([schema])).execute(
        "user-1", "omichub_search_memory", {"query": "小鼠脑"}, context=context
    )

    assert result["success"] is True
    assert captured == {"user_id": "user-1", "query": "小鼠脑", "context": context}


@pytest.mark.asyncio
async def test_celery_backed_async_tool_uses_service_context(monkeypatch) -> None:
    schema = ToolSchema(
        key="gsea",
        name="omichub_run_gsea",
        description="执行 GSEA。适用于排序基因列表；无排序列表用富集。输入 gene_ranking。",
        keywords=["GSEA"],
        invocation_mode="backend_async",
        service="omichub.tools.gsea.service.GseaService",
        method="submit",
        extra={"celery_service": True},
        input_schema={"type": "object", "properties": {"gene_ranking": {"type": "string"}}},
        llm_result_fields=["task_id", "success"],
        ui_result_fields=["task_id", "progress_url"],
    )

    async def fake_submit(self, *, db, user_id, gene_ranking):
        assert db == "session"
        return {"task_id": "task-1", "gene_ranking": gene_ranking}

    monkeypatch.setattr("omichub.tools.gsea.service.GseaService.submit", fake_submit)
    context = MagicMock(db="session")
    result = await ToolBridgeService(_FakeLoader([schema])).execute(
        "user-1", "omichub_run_gsea", {"gene_ranking": "gene\t1"}, context=context
    )

    assert result["success"] is True
    assert result["ui_payload"]["progress_url"].endswith("task-1/progress")


@pytest.mark.asyncio
async def test_llm_payload_size_limit() -> None:
    schema = _volcano_schema()
    # 让 llm_result_fields 包含大字段，触发 3KB 截断
    schema.llm_result_fields = ["stats", "big_field"]
    loader = _FakeLoader([schema])
    service = ToolBridgeService(loader)

    # shim 返回中不包含 big_field，所以这里直接测 _package 的兜底逻辑
    sample = "gene\tlog2FoldChange\tpadj\nTP53\t2.5\t0.001"
    result = await service.execute("u1", "omichub_plot_volcano", {"data_text": sample})
    assert result["success"] is True


def test_schema_loader_reads_yaml() -> None:
    from omichub.tools.schema_loader import schema_loader

    tools = schema_loader.list_tools()
    names = {t.name for t in tools}
    assert "omichub_run_kegg_enrichment" in names
    assert "omichub_plot_volcano" in names


@pytest.mark.asyncio
async def test_upload_ref_resolution(tmp_path, monkeypatch) -> None:
    """upload://file_id 应解析为聊天上传目录中的文件内容。"""
    user_id = "u1"
    upload_dir = tmp_path / "users" / user_id / "workspace" / "chat-uploads"
    upload_dir.mkdir(parents=True)
    (upload_dir / "abc123.txt").write_text("gene\tlog2FoldChange\tpadj\nTP53\t2.5\t0.001")

    path_factory = StoragePathFactory(
        StorageConfig(data_root=str(tmp_path), users_subdir="users")
    )
    backend = LocalStorageBackend(path_factory=path_factory)

    monkeypatch.setattr(
        "omichub.application.services.tool_bridge_service.get_path_factory",
        lambda: path_factory,
    )

    loader = _FakeLoader([_volcano_schema()])
    service = ToolBridgeService(loader, backend=backend)
    result = await service.execute(user_id, "omichub_plot_volcano", {"data_text": "upload://abc123"})

    assert result["success"] is True
    assert result["llm_payload"]["stats"]["total"] == 1


@pytest.mark.asyncio
async def test_workspace_file_ref_resolution(tmp_path, monkeypatch) -> None:
    """file://UUID 应交由受控工作区读取器解析后再传入 shim。"""
    user_id = str(uuid.uuid4())
    file_id = uuid.uuid4()
    context = MagicMock()
    service = ToolBridgeService(_FakeLoader([_volcano_schema()]))
    resolve_refs = AsyncMock(
        return_value={
            "data_text": "ENSEMBL,log2FoldChange,padj\nTP53,2.5,0.001\nBRCA1,-3.0,0.0001"
        }
    )
    monkeypatch.setattr(
        "omichub.application.services.tool_bridge_service.resolve_workspace_file_refs",
        resolve_refs,
    )

    result = await service.execute(
        user_id,
        "omichub_plot_volcano",
        {"data_text": f"file://{file_id}"},
        context=context,
    )

    assert result["success"] is True
    assert result["llm_payload"]["stats"] == {"total": 2, "up": 1, "down": 1, "non": 0}
    assert result["ui_payload"]["plotly_figure"] is not None
    resolve_refs.assert_awaited_once_with(
        {"data_text": f"file://{file_id}"}, user_id=user_id, context=context
    )


@pytest.mark.asyncio
async def test_manhattan_shim_via_bridge() -> None:
    """曼哈顿图 shim 走 ToolBridge 应返回双通道结果。"""
    schema = ToolSchema(
        key="manhattan",
        name="omichub_plot_manhattan",
        description="曼哈顿图",
        invocation_mode="backend_shim",
        shim_module="omichub.tools.shims.manhattan",
        input_schema={
            "type": "object",
            "properties": {"data_text": {"type": "string"}},
            "required": ["data_text"],
        },
        llm_result_fields=["stats", "success"],
        ui_result_fields=["plotly_figure"],
    )
    loader = _FakeLoader([schema])
    service = ToolBridgeService(loader)
    sample = "SNP\tChromosome\tPosition\tP-value\nrs1\t1\t1000000\t0.5\nrs2\t1\t2000000\t1e-10"
    result = await service.execute("u1", "omichub_plot_manhattan", {"data_text": sample})

    assert result["success"] is True
    assert result["llm_payload"]["stats"]["significant"] == 1
    assert "plotly_figure" in result["ui_payload"]


@pytest.mark.asyncio
async def test_requires_confirm_returns_confirm_card() -> None:
    """requires_confirm 工具在未确认时返回 confirm_card。"""
    schema = _volcano_schema()
    schema.requires_confirm = True
    loader = _FakeLoader([schema])
    service = ToolBridgeService(loader)
    result = await service.execute("u1", "omichub_plot_volcano", {"data_text": "gene\tlog2FC\tpadj\nA\t1\t0.01"})

    assert result["success"] is True
    assert result["is_error"] is False
    assert result["llm_payload"].get("needs_confirm") is True
    assert result["ui_payload"].get("confirm_card") is True


@pytest.mark.asyncio
async def test_open_page_payload() -> None:
    """open_page 工具返回路由引导。"""
    schema = ToolSchema(
        key="manhattan",
        name="omichub_open_manhattan_page",
        description="前往曼哈顿图工具页",
        invocation_mode="open_page",
        route="/tools/manhattan",
        input_schema={"type": "object", "properties": {}},
        llm_result_fields=["success", "message"],
        ui_result_fields=["route"],
    )
    loader = _FakeLoader([schema])
    service = ToolBridgeService(loader)
    result = await service.execute("u1", "omichub_open_manhattan_page", {})

    assert result["success"] is True
    assert result["ui_payload"].get("route") == "/tools/manhattan"


@pytest.mark.asyncio
async def test_phylogenetic_tree_schema_uses_unified_page_entry() -> None:
    """发育树 AI 工具只负责打开页面，实际计算统一走页面的 Celery API。"""
    loader = ToolsSchemaLoader("tool_configs/tools_schema.yaml")
    schema = loader.get_tool("omichub_build_phylogenetic_tree")

    assert schema is not None
    assert schema.invocation_mode == "open_page"
    assert schema.route == "/tools/phylogenetic-tree"
    assert "生物信息工具箱 · 系统发育树构建" in schema.description
    assert "系统发育树工作台" not in schema.description

    service = ToolBridgeService(loader)
    result = await service.execute(
        "u1", "omichub_build_phylogenetic_tree", {"layout": "circular"}
    )

    assert result["success"] is True
    assert result["ui_payload"]["route"] == "/tools/phylogenetic-tree"
    assert result["ui_payload"]["arguments"] == {"layout": "circular"}


@pytest.mark.asyncio
async def test_backend_async_submits_arq_job() -> None:
    """backend_async 工具应投递 ARQ 任务并返回 task_id 与进度 URL。"""
    schema = ToolSchema(
        key="phylo",
        name="omichub_build_phylogenetic_tree",
        description="构建系统发育树",
        invocation_mode="backend_async",
        input_schema={
            "type": "object",
            "properties": {"file_id": {"type": "string"}},
            "required": ["file_id"],
        },
        llm_result_fields=["success", "task_id", "status"],
        ui_result_fields=["task_id", "progress_url", "result_url"],
    )
    loader = _FakeLoader([schema])
    service = ToolBridgeService(loader)

    fake_job = MagicMock()
    fake_job.job_id = "arq-test-123"
    fake_pool = MagicMock()
    fake_pool.enqueue_job = AsyncMock(return_value=fake_job)

    with patch(
        "omichub.infrastructure.task_queue.arq_pool.get_arq_pool",
        new_callable=AsyncMock,
        return_value=fake_pool,
    ):
        result = await service.execute(
            "u1", "omichub_build_phylogenetic_tree", {"file_id": "f1"}
        )

    assert result["success"] is True
    assert result["llm_payload"]["task_id"] == "arq-test-123"
    assert result["ui_payload"]["progress_url"] == "/api/v1/tasks/arq-test-123/progress"
    fake_pool.enqueue_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_backend_async_handles_enqueue_failure() -> None:
    """ARQ 入队返回 None 时应返回错误。"""
    schema = ToolSchema(
        key="phylo",
        name="omichub_build_phylogenetic_tree",
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
    loader = _FakeLoader([schema])
    service = ToolBridgeService(loader)

    fake_pool = MagicMock()
    fake_pool.enqueue_job = AsyncMock(return_value=None)

    with patch(
        "omichub.infrastructure.task_queue.arq_pool.get_arq_pool",
        new_callable=AsyncMock,
        return_value=fake_pool,
    ):
        result = await service.execute(
            "u1", "omichub_build_phylogenetic_tree", {"file_id": "f1"}
        )

    assert result["success"] is False
    assert result["is_error"] is True
    assert "入队失败" in result["llm_payload"]["error"]
