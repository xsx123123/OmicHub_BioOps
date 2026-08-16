"""构建文档生成器 — 自动生成 build.md 与 architecture.md.

纯模板渲染，无 IO / 无 DB 依赖，便于单测。
设计参考：docs/26.7.30/mcp_builder_framework.md Phase 5
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def generate_build_doc(
    *,
    name: str,
    requirement: str,
    plan_summary: str = "",
    tools: list[dict[str, Any]] | None = None,
    test_cases: list[dict[str, Any]] | None = None,
    dependencies: list[str] | None = None,
    model_used: str = "",
    build_id: str = "",
    version: str = "1.0.0",
    timestamp: str | None = None,
) -> str:
    """生成构建文档 (build.md) 内容."""
    ts = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tools = tools or []
    test_cases = test_cases or []
    dependencies = dependencies or []

    tool_rows = "\n".join(
        f"| {t.get('name', '')} | {t.get('description', '')} | "
        f"{', '.join((t.get('inputSchema') or {}).get('required') or []) or '—'} |"
        for t in tools
    ) or "| — | — | — |"

    if test_cases:
        test_rows = "\n".join(
            f"| `{_short(tc.get('input'))}` | `{_short(tc.get('expected'))}` | "
            f"`{_short(tc.get('actual'))}` | {'✅' if tc.get('passed') else '❌'} |"
            for tc in test_cases
        )
        passed = sum(1 for tc in test_cases if tc.get("passed"))
        test_section = (
            f"通过 {passed}/{len(test_cases)}\n\n"
            "| 输入 | 期望 | 实际 | 结果 |\n|------|------|------|------|\n" + test_rows
        )
    else:
        test_section = "_暂无测试记录_"

    deps = ", ".join(f"`{d}`" for d in dependencies) or "标准库"

    return f"""# MCP Build Report: {name}

## 需求

{requirement}

## 实现方案

{plan_summary or '_（由 AI 规划，详见构建会话记录）_'}

## 工具清单

| 工具名 | 描述 | 必填参数 |
|--------|------|----------|
{tool_rows}

## 测试记录

{test_section}

## 依赖

{deps}

## 生成信息

- 模型: {model_used or '—'}
- 版本: {version}
- 时间: {ts}
- 构建 ID: `{build_id}`
"""


def generate_architecture_doc(
    *,
    name: str,
    version: str = "1.0.0",
    needs_network: bool = False,
    allowed_domains: list[str] | None = None,
    ttl_hours: int | None = 24,
    version_history: list[dict[str, str]] | None = None,
) -> str:
    """生成架构文档 (architecture.md) 内容."""
    domains = allowed_domains or []
    history = version_history or []

    network_line = (
        f"受 egress proxy 白名单约束：{', '.join(domains) or '（需管理员配置）'}"
        if needs_network
        else "无外部网络访问（纯计算 / 本地数据）"
    )
    ttl_line = f"{ttl_hours} 小时（实验池 TTL，可续期）" if ttl_hours else "永久（正式发布）"

    history_rows = "\n".join(
        f"| {h.get('version', '')} | {h.get('date', '')} | {h.get('changelog', '')} |"
        for h in history
    ) or f"| {version} | {datetime.now().strftime('%Y-%m-%d')} | 初始版本 |"

    return f"""# MCP Server Architecture: {name}

## 组件图

```text
LLM tool_call
    │
    ▼
ChatService ──→ MCPClient
                   │ (实验池: 沙箱桥接)
                   ▼
        StudioSandboxManager (UDS)
                   │
                   ▼
        sandbox-agent /mcp/call
                   │ (STDIO 子进程)
                   ▼
        {name} server.py ──→ [外部 API / 本地计算]
```

## 数据流

1. LLM 输出 tool_call → ChatService 按 server 路由
2. MCPClient → sandbox-agent（Unix Domain Socket）
3. sandbox-agent → STDIO → MCP Server 子进程
4. Server → 外部 API / 文件系统 / 纯计算
5. Server → TextContent(JSON) → 原路返回 LLM

## 安全边界

- 运行环境: Docker 沙箱（uid 10001，非 root）
- 代码审查: AST 静态检查（import 白名单 + 危险调用检测 + 结构验证）
- 网络策略: {network_line}
- 资源限制: CPU 2 核 / Memory 4GB（继承 Studio 沙箱配额）
- 生命周期: {ttl_line}
- 可见性: 创建者 + Admin（实验池）

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
{history_rows}
"""


def _short(value: Any, limit: int = 60) -> str:
    """测试记录单元格截断，避免撑破表格."""
    text = str(value if value is not None else "—").replace("\n", " ").replace("|", "∣")
    return text if len(text) <= limit else text[: limit - 1] + "…"
