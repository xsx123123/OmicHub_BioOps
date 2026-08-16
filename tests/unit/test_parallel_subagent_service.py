"""并行子 Agent fan-out 的无网络服务测试。

覆盖：并行成立、失败隔离、防递归工具剥离、超时、工具回环与独占 session、
开关与 spawnable 白名单校验。
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.services import parallel_subagent_service as pss
from omichub.infrastructure.ai_provider.openai_compatible import ChatChunk

# --- 桩件 -----------------------------------------------------------------


def _ctx(agent_id: str, tools: list | None = None, spawnable: bool = True):
    return SimpleNamespace(
        agent=SimpleNamespace(agent_id=agent_id, name=f"{agent_id} 名称"),
        model_config=SimpleNamespace(),
        system_prompt="系统提示",
        tools=tools or [],
        features={"subagents_spawnable": spawnable},
        mcp_servers=[],
        skills=[],
        max_tokens=4096,
    )


class AgentServiceStub:
    """按 agent_id 返回预置上下文；记录是否被顺序调用。"""

    def __init__(self, contexts: dict):
        self._contexts = contexts

    async def assemble_context(self, agent_id: str):
        return self._contexts.get(agent_id)


class FakeSession(AsyncSession):
    """ToolInvocationContext.db 按 isinstance(AsyncSession) 校验，故继承真类；
    不调用 super().__init__，仅作占位桩。"""

    created = 0

    def __init__(self):
        type(self).created += 1

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class FakeSessionCM:
    def __init__(self):
        self.session: FakeSession | None = None

    async def __aenter__(self) -> FakeSession:
        self.session = FakeSession()
        return self.session

    async def __aexit__(self, *exc) -> bool:
        return False


class FakeSessionFactory:
    def __call__(self) -> FakeSessionCM:
        return FakeSessionCM()


class FakeBridge:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, user_id, tool_name, arguments, context=None):
        self.calls.append((tool_name, dict(arguments or {})))
        return {"success": True, "llm_payload": {"echo": arguments}}


_SCHEMA_REGISTRY = {
    "workspace_read": SimpleNamespace(invocation_mode="backend_sync", requires_confirm=False),
    "parallel_subagents": SimpleNamespace(invocation_mode="backend_sync", requires_confirm=False),
    "transfer_to_agent": SimpleNamespace(invocation_mode="backend_sync", requires_confirm=False),
    "long_task": SimpleNamespace(invocation_mode="analysis_flow", requires_confirm=False),
    "danger_tool": SimpleNamespace(invocation_mode="backend_sync", requires_confirm=True),
}


@pytest.fixture
def env(monkeypatch, tmp_path):
    """统一打桩：settings / schema_loader / session factory / bridge。"""
    settings = pss.get_settings()
    monkeypatch.setattr(settings, "subagent_fanout_enabled", True)
    monkeypatch.setattr(settings, "subagent_max_parallel", 4)
    monkeypatch.setattr(settings, "subagent_max_concurrent", 3)
    monkeypatch.setattr(settings, "subagent_child_timeout_seconds", 60)
    monkeypatch.setattr(settings, "subagent_max_rounds_per_child", 6)
    monkeypatch.setattr(settings, "subagent_max_children_per_message", 1)
    monkeypatch.setattr(settings, "storage_path", str(tmp_path))

    monkeypatch.setattr(
        pss, "schema_loader", SimpleNamespace(get_tool=lambda name: _SCHEMA_REGISTRY.get(name))
    )
    bridge = FakeBridge()
    monkeypatch.setattr(
        "omichub.application.services.tool_bridge_service.get_tool_bridge_service",
        lambda: bridge,
    )
    FakeSession.created = 0
    monkeypatch.setattr(pss, "get_session_factory", lambda: FakeSessionFactory())

    # DB 平台设置开关桩：默认关（env 开关在 settings 上单独控制）
    class SiteSettingsServiceStub:
        db_flag = False

        def __init__(self, db):
            pass

        async def is_subagent_fanout_enabled(self) -> bool:
            return type(self).db_flag

    monkeypatch.setattr(
        "omichub.application.services.site_settings_service.SiteSettingsService",
        SiteSettingsServiceStub,
    )
    return SimpleNamespace(
        settings=settings, bridge=bridge, tmp_path=tmp_path, site=SiteSettingsServiceStub
    )


def _patch_provider(monkeypatch, handler):
    """handler(messages, kwargs) 为异步生成器函数，按 messages 首条内容路由子任务行为。"""
    seen: dict[str, object] = {"tools": []}

    async def fake_stream(*, config, messages, system_prompt=None, **kwargs):
        seen["tools"].append(kwargs.get("tools"))
        async for chunk in handler(messages, kwargs):
            yield chunk

    monkeypatch.setattr(pss, "provider_manager", SimpleNamespace(chat_stream=fake_stream))
    return seen


# --- 测试 -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_fanout_parallel_success_and_tool_filtering(env, monkeypatch) -> None:
    contexts = {
        "agent-a": _ctx(
            "agent-a",
            tools=[
                {"function": {"name": "parallel_subagents"}},  # C2 必须被剥离
                {"function": {"name": "transfer_to_agent"}},  # C3 必须被剥离
                {"function": {"name": "danger_tool"}},  # C4 必须被剥离
                {"function": {"name": "long_task"}},  # analysis_flow 必须被剥离
                {"function": {"name": "workspace_read"}},  # 唯一保留
                {"function": {"name": "some_mcp_tool"}},  # 桥外工具必须被剥离
            ],
        ),
        "agent-b": _ctx("agent-b"),
    }
    monkeypatch.setattr(pss, "AgentService", lambda db: AgentServiceStub(contexts))

    async def slow_text(messages, kwargs):
        await asyncio.sleep(0.1)
        first = messages[0]["content"]
        yield ChatChunk(type="text", content=f"结论：{'A' if 'task-a' in first else 'B'}")

    seen = _patch_provider(monkeypatch, slow_text)

    started = time.monotonic()
    result = await pss.ParallelSubAgentService().run(
        user_id="user-1",
        parent_agent_id="agent-general",
        parent_session_id="sess-1",
        context_summary="共享背景",
        tasks=[
            {"agent_id": "agent-a", "task": "task-a 内容"},
            {"agent_id": "agent-b", "task": "task-b 内容"},
        ],
        db=SimpleNamespace(),
    )
    elapsed = time.monotonic() - started

    assert result["success"] is True
    assert result["llm_payload"]["summary"].startswith("2/2 个子任务成功")
    statuses = [item["status"] for item in result["llm_payload"]["results"]]
    assert statuses == ["ok", "ok"]
    # 并行成立：两个各睡 0.1s 的子任务总墙钟应明显小于串行 0.2s
    assert elapsed < 0.19, f"fan-out 未并行执行，elapsed={elapsed:.3f}s"
    # 防递归/控制工具剥离：任何子循环都见不到被禁工具；agent-a 只保留 workspace_read
    forbidden = {
        "parallel_subagents",
        "transfer_to_agent",
        "long_task",
        "some_mcp_tool",
    }
    name_sets = [
        {(t.get("function") or {}).get("name") for t in (tools or [])} for tools in seen["tools"]
    ]
    assert all(names.isdisjoint(forbidden) for names in name_sets)
    assert any("workspace_read" in names for names in name_sets)


@pytest.mark.asyncio
async def test_fanout_preserves_long_stage_output_for_downstream_agents(env, monkeypatch) -> None:
    contexts = {"agent-general": _ctx("agent-general")}
    monkeypatch.setattr(pss, "AgentService", lambda db: AgentServiceStub(contexts))
    marker = "LONG_PLAN_FINAL_CONTRACT"
    long_plan = "研究步骤与数据契约。" * 300 + marker

    async def handler(_messages, _kwargs):
        yield ChatChunk(type="text", content=long_plan)

    _patch_provider(monkeypatch, handler)
    result = await pss.ParallelSubAgentService().run(
        user_id="user-1",
        parent_agent_id="manager",
        parent_session_id="sess-1",
        context_summary="研究背景",
        tasks=[{"agent_id": "agent-general", "task": "形成完整研究计划"}],
        db=SimpleNamespace(),
    )

    answer = result["llm_payload"]["results"][0]["answer"]
    assert marker in answer
    assert len(answer) > 1200


@pytest.mark.asyncio
async def test_fanout_accumulates_text_across_tool_rounds(env, monkeypatch) -> None:
    contexts = {"agent-code": _ctx("agent-code", tools=[{"function": {"name": "workspace_read"}}])}
    monkeypatch.setattr(pss, "AgentService", lambda db: AgentServiceStub(contexts))

    async def fake_execute(*_args, **_kwargs):
        return {"success": True, "result": {"content": "upstream"}}

    monkeypatch.setattr(pss, "execute_studio_tool", fake_execute)

    async def handler(messages, _kwargs):
        if len(messages) == 1:
            yield ChatChunk(type="text", content="第一阶段完整设计。")
            yield ChatChunk(
                type="tool_calls",
                metadata={
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "function": {
                                "name": "workspace_read",
                                "arguments": '{"path":"output/upstream.md"}',
                            },
                        }
                    ]
                },
            )
        else:
            yield ChatChunk(type="text", content="第二阶段完整代码与交付说明。")

    _patch_provider(monkeypatch, handler)
    result = await pss.ParallelSubAgentService().run(
        user_id="user-1",
        parent_agent_id="manager",
        parent_session_id="sess-1",
        context_summary="",
        tasks=[{"agent_id": "agent-code", "task": "生成完整代码", "workspace_access": True}],
        db=SimpleNamespace(),
    )

    answer = result["llm_payload"]["results"][0]["answer"]
    assert "第一阶段完整设计" in answer
    assert "第二阶段完整代码与交付说明" in answer


@pytest.mark.asyncio
async def test_fanout_continues_after_model_output_length_limit(env, monkeypatch) -> None:
    contexts = {"agent-scrna": _ctx("agent-scrna")}
    monkeypatch.setattr(pss, "AgentService", lambda db: AgentServiceStub(contexts))
    calls = 0

    async def handler(messages, _kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield ChatChunk(type="text", content="第一部分单细胞方案。")
            yield ChatChunk(type="done", metadata={"finish_reason": "length"})
            return
        assert "从中断处继续" in messages[-1]["content"]
        yield ChatChunk(type="text", content="第二部分免疫耐受机制与交付项。")
        yield ChatChunk(type="done", metadata={"finish_reason": "stop"})

    _patch_provider(monkeypatch, handler)
    result = await pss.ParallelSubAgentService().run(
        user_id="user-1",
        parent_agent_id="manager",
        parent_session_id="sess-1",
        context_summary="",
        tasks=[{"agent_id": "agent-scrna", "task": "写完整方案"}],
        db=SimpleNamespace(),
    )

    answer = result["llm_payload"]["results"][0]["answer"]
    assert calls == 2
    assert "第一部分单细胞方案" in answer
    assert "第二部分免疫耐受机制与交付项" in answer


@pytest.mark.asyncio
async def test_fanout_merges_token_usage_across_rounds_and_children(env, monkeypatch) -> None:
    """done chunk 的 usage 跨轮累加，并经 run() 合并各子任务用量后透出。"""
    contexts = {"agent-a": _ctx("agent-a"), "agent-b": _ctx("agent-b")}
    monkeypatch.setattr(pss, "AgentService", lambda db: AgentServiceStub(contexts))

    async def handler(messages, _kwargs):
        first = messages[0]["content"]
        # task-a 首轮以 length 中断触发续写；续写轮 messages 已扩展，按长度区分轮次
        if "task-a" in first and len(messages) == 1:
            yield ChatChunk(type="text", content="上半段。")
            yield ChatChunk(
                type="done",
                metadata={
                    "finish_reason": "length",
                    "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
                },
            )
            return
        yield ChatChunk(type="text", content=f"结论：{'A' if 'task-a' in first else 'B'}")
        yield ChatChunk(
            type="done",
            metadata={
                "finish_reason": "stop",
                "usage": {"prompt_tokens": 160, "completion_tokens": 50, "total_tokens": 210},
            },
        )

    _patch_provider(monkeypatch, handler)
    result = await pss.ParallelSubAgentService().run(
        user_id="user-1",
        parent_agent_id="manager",
        parent_session_id="sess-1",
        context_summary="",
        tasks=[
            {"agent_id": "agent-a", "task": "task-a 内容"},
            {"agent_id": "agent-b", "task": "task-b 内容"},
        ],
        db=SimpleNamespace(),
    )

    # agent-a 两轮 140+210，agent-b 一轮 210，合计 350/260/90
    assert result["usage"] == {
        "prompt_tokens": 260 + 160,
        "completion_tokens": 90 + 50,
        "total_tokens": 350 + 210,
    }


@pytest.mark.asyncio
async def test_fanout_separates_reasoning_from_worker_answer(env, monkeypatch) -> None:
    contexts = {"agent-general": _ctx("agent-general")}
    monkeypatch.setattr(pss, "AgentService", lambda db: AgentServiceStub(contexts))
    events: list[dict] = []

    async def handler(_messages, _kwargs):
        yield ChatChunk(
            type="text",
            content="INTERNAL_REASONING",
            metadata={"is_reasoning": True},
        )
        yield ChatChunk(type="text", content="FINAL_ANSWER")

    _patch_provider(monkeypatch, handler)
    result = await pss.ParallelSubAgentService().run(
        user_id="user-1",
        parent_agent_id="manager",
        parent_session_id="sess-1",
        context_summary="",
        tasks=[{"agent_id": "agent-general", "task": "形成方案"}],
        db=SimpleNamespace(),
        on_event=events.append,
    )

    worker = result["llm_payload"]["results"][0]
    assert worker["answer"] == "FINAL_ANSWER"
    assert worker["thought"] == "INTERNAL_REASONING"
    assert any(event["type"] == "worker_reasoning_delta" for event in events)


def test_child_tools_include_research_tools_and_bound_mcp() -> None:
    ctx = _ctx("agent-general", tools=[{"function": {"name": "remote_lookup"}}])
    ctx.features["web_search"] = {"mode": "required_for_freshness"}
    ctx.mcp_servers = [SimpleNamespace(tools=[SimpleNamespace(tool_name="remote_lookup")])]

    tools = pss.ParallelSubAgentService._prepare_child_tools(ctx)
    names = {(tool.get("function") or {}).get("name") for tool in tools}

    assert {"ask_user", "knowledge_search", "web_search", "remote_lookup"} <= names


def test_child_tools_respect_explicit_web_search_disable() -> None:
    ctx = _ctx("agent-general")
    ctx.features["web_search"] = {"mode": "off"}

    names = {
        (tool.get("function") or {}).get("name")
        for tool in pss.ParallelSubAgentService._prepare_child_tools(ctx)
    }

    assert "knowledge_search" in names
    assert "web_search" not in names


def test_child_tools_add_workspace_execution_only_after_explicit_access() -> None:
    ctx = _ctx("agent-code")

    default_names = {
        (tool.get("function") or {}).get("name")
        for tool in pss.ParallelSubAgentService._prepare_child_tools(ctx)
    }
    enabled_names = {
        (tool.get("function") or {}).get("name")
        for tool in pss.ParallelSubAgentService._prepare_child_tools(ctx, workspace_access=True)
    }

    assert "sandbox_execute" not in default_names
    assert {"workspace_read", "workspace_write", "sandbox_execute"}.issubset(enabled_names)


def test_child_tools_workspace_access_grants_full_workbench_except_update_plan() -> None:
    ctx = _ctx("agent-code")

    names = {
        (tool.get("function") or {}).get("name")
        for tool in pss.ParallelSubAgentService._prepare_child_tools(ctx, workspace_access=True)
    }

    # 对齐 AI 工作台全集（execute_studio_tool 可直接分发的平台联动工具）
    assert {
        "sandbox_execute",
        "workspace_write",
        "workspace_edit",
        "workspace_read",
        "workspace_list",
        "datahub_import",
        "platform_result_import",
        "artifact_register",
        "pipeline_query",
    }.issubset(names)
    # update_plan 是 Studio 计划 UI 工具，不授予子 Agent
    assert "update_plan" not in names


def test_goal_safe_child_tools_only_keep_read_only_capabilities(monkeypatch) -> None:
    readonly_schema = SimpleNamespace(
        invocation_mode="backend_sync",
        requires_confirm=False,
        annotations=SimpleNamespace(read_only_hint=True),
    )
    unsafe_schema = SimpleNamespace(
        invocation_mode="backend_sync",
        requires_confirm=False,
        annotations=SimpleNamespace(read_only_hint=False),
    )
    schemas = {"readonly_lookup": readonly_schema, "unsafe_mutation": unsafe_schema}
    monkeypatch.setattr(
        pss,
        "schema_loader",
        SimpleNamespace(get_tool=lambda name: schemas.get(name)),
    )
    ctx = _ctx(
        "agent-general",
        tools=[
            {"function": {"name": "readonly_lookup"}},
            {"function": {"name": "unsafe_mutation"}},
            {"function": {"name": "remote_lookup"}},
        ],
    )
    ctx.features["web_search"] = {"mode": "required_for_freshness"}
    ctx.mcp_servers = [SimpleNamespace(tools=[SimpleNamespace(tool_name="remote_lookup")])]

    tools = pss.ParallelSubAgentService._prepare_child_tools(
        ctx,
        workspace_access=True,
        safe_only=True,
    )
    names = {(tool.get("function") or {}).get("name") for tool in tools}

    assert {"ask_user", "knowledge_search", "web_search", "readonly_lookup"} <= names
    assert {"unsafe_mutation", "remote_lookup", "workspace_write", "sandbox_execute"}.isdisjoint(
        names
    )


@pytest.mark.asyncio
async def test_child_workspace_tool_uses_parent_workspace_after_user_confirmation(
    env, monkeypatch
) -> None:
    calls: list[tuple[str, str, dict]] = []

    async def fake_execute(name, args, session_id, **_kwargs):
        calls.append((name, session_id, args))
        return {"success": True, "result": {"llm_payload": {"path": args.get("path")}}}

    monkeypatch.setattr(pss, "execute_studio_tool", fake_execute)
    result = await pss.ParallelSubAgentService._execute_child_tool(
        user_id="user-1",
        agent_id="agent-code",
        child_session_id="session:sub:run:1",
        parent_session_id="session-parent",
        tool_name="workspace_write",
        args={"path": "scripts/run.py", "content": "print('ok')"},
        workdir=env.tmp_path,
        run_id="run",
        ctx=_ctx("agent-code"),
        workspace_access=True,
    )

    assert result["success"] is True
    assert calls == [
        (
            "workspace_write",
            "session-parent",
            {"path": "scripts/run.py", "content": "print('ok')"},
        )
    ]


@pytest.mark.asyncio
async def test_child_executes_bound_mcp_tool_with_child_context(env, monkeypatch) -> None:
    calls: list[tuple[str, dict, str]] = []

    class FakeMCPClient:
        async def call_tool(self, server, tool_name, arguments, *, user_id, context):
            calls.append((tool_name, arguments, context.session_id))
            return {"success": True, "result": {"source": server.name}}

    monkeypatch.setattr("omichub.infrastructure.mcp.client.MCPClient", FakeMCPClient)
    server = SimpleNamespace(
        name="research-mcp",
        tools=[SimpleNamespace(tool_name="remote_lookup")],
    )
    ctx = _ctx("agent-general")
    ctx.mcp_servers = [server]

    result = await pss.ParallelSubAgentService._execute_child_tool(
        user_id="user-1",
        agent_id="agent-general",
        child_session_id="session:sub:run:1",
        tool_name="remote_lookup",
        args={"query": "TP53"},
        workdir=env.tmp_path,
        run_id="run",
        ctx=ctx,
    )

    assert result["success"] is True
    assert calls == [("remote_lookup", {"query": "TP53"}, "session:sub:run:1")]


@pytest.mark.asyncio
async def test_fanout_isolates_child_failure(env, monkeypatch) -> None:
    contexts = {"agent-a": _ctx("agent-a"), "agent-b": _ctx("agent-b")}
    monkeypatch.setattr(pss, "AgentService", lambda db: AgentServiceStub(contexts))

    async def handler(messages, kwargs):
        if "task-a" in messages[0]["content"]:
            yield ChatChunk(type="text", content="A 正常完成")
        else:
            raise RuntimeError("模型端点故障")

    _patch_provider(monkeypatch, handler)

    result = await pss.ParallelSubAgentService().run(
        user_id="user-1",
        parent_agent_id="agent-general",
        parent_session_id="sess-1",
        context_summary="",
        tasks=[
            {"agent_id": "agent-a", "task": "task-a"},
            {"agent_id": "agent-b", "task": "task-b"},
        ],
        db=SimpleNamespace(),
    )

    assert result["success"] is True  # 部分成功仍视为可用汇总
    assert result["llm_payload"]["summary"].startswith("1/2 个子任务成功")
    by_agent = {item["agent_id"]: item for item in result["llm_payload"]["results"]}
    assert by_agent["agent-a"]["status"] == "ok"
    assert by_agent["agent-b"]["status"] == "failed"
    assert "模型端点故障" in by_agent["agent-b"]["error"]


@pytest.mark.asyncio
async def test_fanout_disabled_flag(env, monkeypatch) -> None:
    env.settings.subagent_fanout_enabled = False
    result = await pss.ParallelSubAgentService().run(
        user_id="user-1",
        parent_agent_id="agent-general",
        parent_session_id="sess-1",
        context_summary="",
        tasks=[
            {"agent_id": "agent-a", "task": "x"},
            {"agent_id": "agent-b", "task": "y"},
        ],
        db=SimpleNamespace(),
    )
    assert result["success"] is False
    assert "未启用" in result["llm_payload"]["error"]


@pytest.mark.asyncio
async def test_fanout_enabled_by_db_flag_alone(env, monkeypatch) -> None:
    """env 关、管理端平台设置开 → 仍可 fan-out（运行时主开关语义）。"""
    env.settings.subagent_fanout_enabled = False
    env.site.db_flag = True
    contexts = {"agent-a": _ctx("agent-a"), "agent-b": _ctx("agent-b")}
    monkeypatch.setattr(pss, "AgentService", lambda db: AgentServiceStub(contexts))

    async def text(messages, kwargs):
        yield ChatChunk(type="text", content="完成")

    _patch_provider(monkeypatch, text)
    result = await pss.ParallelSubAgentService().run(
        user_id="user-1",
        parent_agent_id="agent-general",
        parent_session_id="sess-1",
        context_summary="",
        tasks=[
            {"agent_id": "agent-a", "task": "x"},
            {"agent_id": "agent-b", "task": "y"},
        ],
        db=SimpleNamespace(),
    )
    assert result["success"] is True
    assert result["llm_payload"]["summary"].startswith("2/2")


@pytest.mark.asyncio
async def test_fanout_rejects_non_spawnable(env, monkeypatch) -> None:
    contexts = {
        "agent-a": _ctx("agent-a", spawnable=False),
        "agent-b": _ctx("agent-b"),
    }
    monkeypatch.setattr(pss, "AgentService", lambda db: AgentServiceStub(contexts))
    result = await pss.ParallelSubAgentService().run(
        user_id="user-1",
        parent_agent_id="agent-general",
        parent_session_id="sess-1",
        context_summary="",
        tasks=[
            {"agent_id": "agent-a", "task": "x"},
            {"agent_id": "agent-b", "task": "y"},
        ],
        db=SimpleNamespace(),
    )
    assert result["success"] is False
    assert "subagents_spawnable" in result["llm_payload"]["error"]


@pytest.mark.asyncio
async def test_fanout_child_timeout(env, monkeypatch) -> None:
    env.settings.subagent_child_timeout_seconds = 1
    contexts = {"agent-a": _ctx("agent-a"), "agent-b": _ctx("agent-b")}
    monkeypatch.setattr(pss, "AgentService", lambda db: AgentServiceStub(contexts))

    async def hang(messages, kwargs):
        await asyncio.sleep(5)
        yield ChatChunk(type="text", content="不该出现")

    _patch_provider(monkeypatch, hang)
    started = time.monotonic()
    result = await pss.ParallelSubAgentService().run(
        user_id="user-1",
        parent_agent_id="agent-general",
        parent_session_id="sess-1",
        context_summary="",
        tasks=[
            {"agent_id": "agent-a", "task": "x"},
            {"agent_id": "agent-b", "task": "y"},
        ],
        db=SimpleNamespace(),
    )
    elapsed = time.monotonic() - started
    assert result["success"] is False
    assert {item["status"] for item in result["llm_payload"]["results"]} == {"timeout"}
    assert elapsed < 4, f"超时未生效，elapsed={elapsed:.3f}s"


@pytest.mark.asyncio
async def test_fanout_child_tool_roundtrip_with_dedicated_session(env, monkeypatch) -> None:
    contexts = {
        "agent-a": _ctx("agent-a", tools=[{"function": {"name": "workspace_read"}}]),
        "agent-b": _ctx("agent-b"),
    }
    monkeypatch.setattr(pss, "AgentService", lambda db: AgentServiceStub(contexts))

    call_counts: dict[str, int] = {}

    async def handler(messages, kwargs):
        first = messages[0]["content"]
        key = "a" if "task-a" in first else "b"
        call_counts[key] = call_counts.get(key, 0) + 1
        if key == "a" and call_counts[key] == 1:
            yield ChatChunk(
                type="tool_calls",
                metadata={
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "workspace_read",
                                "arguments": '{"path": "x.txt"}',
                            },
                        }
                    ]
                },
            )
        else:
            yield ChatChunk(type="text", content=f"{key} 完成")

    _patch_provider(monkeypatch, handler)

    result = await pss.ParallelSubAgentService().run(
        user_id="user-1",
        parent_agent_id="agent-general",
        parent_session_id="sess-1",
        context_summary="",
        tasks=[
            {"agent_id": "agent-a", "task": "task-a"},
            {"agent_id": "agent-b", "task": "task-b"},
        ],
        db=SimpleNamespace(),
    )

    assert result["success"] is True
    assert env.bridge.calls == [("workspace_read", {"path": "x.txt"})]
    # C1：子任务工具执行创建了独占 session
    assert FakeSession.created >= 1


@pytest.mark.asyncio
async def test_budget_exhaustion_with_user_request_becomes_awaiting_input(env, monkeypatch) -> None:
    contexts = {
        "agent-a": _ctx("agent-a", tools=[{"function": {"name": "workspace_read"}}]),
    }
    monkeypatch.setattr(pss, "AgentService", lambda db: AgentServiceStub(contexts))
    model_calls = 0

    async def handler(_messages, _kwargs):
        nonlocal model_calls
        model_calls += 1
        yield ChatChunk(type="text", content="请补充 treefile 文件后继续。")
        yield ChatChunk(
            type="tool_calls",
            metadata={
                "tool_calls": [
                    {
                        "id": f"call-{model_calls}",
                        "type": "function",
                        "function": {
                            "name": "workspace_read",
                            "arguments": '{"path": "input/treefile"}',
                        },
                    }
                ]
            },
        )

    _patch_provider(monkeypatch, handler)
    result = await pss.ParallelSubAgentService().run(
        user_id="user-1",
        parent_agent_id="agent-general",
        parent_session_id="sess-1",
        context_summary="",
        tasks=[{"agent_id": "agent-a", "task": "读取树文件并继续处理"}],
        db=SimpleNamespace(),
    )

    child = result["llm_payload"]["results"][0]
    assert model_calls == 6
    assert result["success"] is True
    assert child["status"] == "awaiting_input"
    assert child["packet"]["needs_user_input"] is True
    assert child["packet"]["status"] == "awaiting_input"
    assert child["packet"]["error"] == ""


@pytest.mark.asyncio
async def test_fanout_escalates_confirm_tool_without_child_execution(env, monkeypatch) -> None:
    contexts = {
        "agent-a": _ctx("agent-a", tools=[{"function": {"name": "danger_tool"}}]),
    }
    monkeypatch.setattr(pss, "AgentService", lambda db: AgentServiceStub(contexts))

    async def handler(_messages, _kwargs):
        yield ChatChunk(
            type="tool_calls",
            metadata={
                "tool_calls": [
                    {
                        "id": "call-confirm",
                        "type": "function",
                        "function": {"name": "danger_tool", "arguments": '{"sample": "S1"}'},
                    }
                ]
            },
        )

    _patch_provider(monkeypatch, handler)
    result = await pss.ParallelSubAgentService().run(
        user_id="user-1",
        parent_agent_id="agent-general",
        parent_session_id="sess-1",
        context_summary="",
        tasks=[{"agent_id": "agent-a", "task": "submit"}],
        db=SimpleNamespace(),
    )

    child = result["llm_payload"]["results"][0]
    assert child["status"] == "approval_pending"
    assert child["packet"]["approval_requests"] == [
        {"tool_name": "danger_tool", "arguments": {"sample": "S1"}}
    ]
    assert env.bridge.calls == []


@pytest.mark.asyncio
async def test_fanout_validation_rules(env, monkeypatch) -> None:
    service = pss.ParallelSubAgentService()
    kwargs = dict(
        user_id="user-1",
        parent_agent_id="agent-general",
        parent_session_id="sess-1",
        context_summary="",
        db=SimpleNamespace(),
    )
    single = service._validate_tasks([{"agent_id": "a", "task": "x"}], max_parallel=4)
    assert single == [{"agent_id": "a", "task": "x"}]

    long_dependency_packet = "上游研究计划。" * 1000
    accepted = service._validate_tasks(
        [{"agent_id": "a", "task": long_dependency_packet}], max_parallel=4
    )
    assert accepted == [{"agent_id": "a", "task": long_dependency_packet}]

    too_many = await service.run(
        tasks=[{"agent_id": "a", "task": f"t{i}"} for i in range(5)], **kwargs
    )
    assert too_many["success"] is False and "最多" in too_many["llm_payload"]["error"]

    missing = await service.run(
        tasks=[{"agent_id": "a", "task": "x"}, {"agent_id": "", "task": "y"}], **kwargs
    )
    assert missing["success"] is False and "缺少" in missing["llm_payload"]["error"]
