"""Regression guards for toolbox schemas and their retrieval metadata."""

from __future__ import annotations

from cygnusx.tools.schema_loader import schema_loader

FORBIDDEN_TERMS = ("极速", "专业", "一站式")
TOOLBOX_PREFIX = "cygnusx_"
TOOLBOX_CATEGORIES = {"toolbox", "enrichment", "visualization", "analysis", "sequence", "genome"}


def test_toolbox_schemas_have_searchable_descriptions() -> None:
    tools = [
        tool
        for tool in schema_loader.list_tools()
        if tool.name.startswith(TOOLBOX_PREFIX) and tool.category in TOOLBOX_CATEGORIES
    ]
    names = [tool.name for tool in tools]

    assert len(names) == len(set(names))
    assert tools
    for tool in tools:
        assert 80 <= len(tool.description) <= 300, tool.name
        assert tool.keywords, tool.name
        assert not any(term in tool.description for term in FORBIDDEN_TERMS), tool.name
        assert "适用于" in tool.description, tool.name
        assert "输入" in tool.description, tool.name


def test_retrieval_mode_falls_back_for_small_catalog() -> None:
    selected, mode = schema_loader.select_tools("基因富集")

    assert mode == "full"
    assert selected


def test_retrieval_uses_keywords_for_new_tool_discovery(tmp_path) -> None:
    config = tmp_path / "tools.yaml"
    config.write_text(
        """tool_selection: {mode: retrieval, top_n: 1}
tools:
  - {key: a, name: cygnusx_alpha, description: '处理普通数据。适用于普通请求；不要用于共线性。输入 text。', keywords: [ordinary], invocation_mode: backend_sync}
  - {key: b, name: cygnusx_run_synteny, description: '分析基因组锚点。适用于共线性；不要用于普通文本。输入 blast。', keywords: [MCScanX, synteny, 共线性], invocation_mode: backend_sync}
  - {key: c, name: cygnusx_gamma, description: '处理另外的数据。适用于其他请求；不要用于共线性。输入 text。', keywords: [other], invocation_mode: backend_sync}
  - {key: d, name: cygnusx_delta, description: '处理补充数据。适用于其他请求；不要用于共线性。输入 text。', keywords: [extra], invocation_mode: backend_sync}
  - {key: e, name: cygnusx_epsilon, description: '处理更多数据。适用于其他请求；不要用于共线性。输入 text。', keywords: [more], invocation_mode: backend_sync}
  - {key: f, name: cygnusx_zeta, description: '处理扩展数据。适用于其他请求；不要用于共线性。输入 text。', keywords: [extended], invocation_mode: backend_sync}
  - {key: g, name: cygnusx_eta, description: '处理序列数据。适用于其他请求；不要用于共线性。输入 text。', keywords: [sequence], invocation_mode: backend_sync}
  - {key: h, name: cygnusx_theta, description: '处理图形数据。适用于其他请求；不要用于共线性。输入 text。', keywords: [plot], invocation_mode: backend_sync}
  - {key: i, name: cygnusx_iota, description: '处理结果数据。适用于其他请求；不要用于共线性。输入 text。', keywords: [result], invocation_mode: backend_sync}
  - {key: j, name: cygnusx_kappa, description: '处理统计数据。适用于其他请求；不要用于共线性。输入 text。', keywords: [stat], invocation_mode: backend_sync}
  - {key: k, name: cygnusx_lambda, description: '处理分析数据。适用于其他请求；不要用于共线性。输入 text。', keywords: [analysis], invocation_mode: backend_sync}
  - {key: l, name: cygnusx_mu, description: '处理生物数据。适用于其他请求；不要用于共线性。输入 text。', keywords: [bio], invocation_mode: backend_sync}
  - {key: m, name: cygnusx_nu, description: '处理研究数据。适用于其他请求；不要用于共线性。输入 text。', keywords: [research], invocation_mode: backend_sync}
  - {key: n, name: cygnusx_xi, description: '处理任务数据。适用于其他请求；不要用于共线性。输入 text。', keywords: [task], invocation_mode: backend_sync}
  - {key: o, name: cygnusx_omicron, description: '处理样本数据。适用于其他请求；不要用于共线性。输入 text。', keywords: [sample], invocation_mode: backend_sync}
  - {key: p, name: cygnusx_pi, description: '处理矩阵数据。适用于其他请求；不要用于共线性。输入 text。', keywords: [matrix], invocation_mode: backend_sync}
""",
        encoding="utf-8",
    )
    from cygnusx.tools.schema_loader import ToolsSchemaLoader

    selected, mode = ToolsSchemaLoader(config).select_tools("MCScanX 共线性")
    assert mode == "retrieval"
    assert [tool.name for tool in selected] == ["cygnusx_run_synteny"]
