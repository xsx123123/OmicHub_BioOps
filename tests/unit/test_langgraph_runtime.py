"""LangGraph 运行时单元测试：假 provider + 假 tool_executor"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from cygnusx.application.services.chat.runtimes.langgraph_runtime import (
    LangGraphChatRuntime,
)
from cygnusx.application.services.execution_events import validate_event_sequence
from cygnusx.application.services.parallel_subagent_service import (
    PARALLEL_SUBAGENTS_TOOL_NAME,
)
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk
from cygnusx.infrastructure.execution.langgraph_nodes import NodeDeps, llm_call_node, tool_exec_node
from cygnusx.infrastructure.execution.langgraph_runtime import LangGraphRuntimeService

USAGE = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


def _make_stream(rounds: list[list[ChatChunk]]) -> tuple[Any, list[list[dict[str, Any]]]]:
    """构造假 chat_stream：第 N 次调用返回 rounds[N]，并记录收到的 messages"""
    calls: list[list[dict[str, Any]]] = []

    async def _stream(**kwargs: Any) -> AsyncIterator[ChatChunk]:
        calls.append(kwargs["messages"])
        for chunk in rounds[len(calls) - 1]:
            yield chunk

    return _stream, calls


def _tool_calls_chunk(name: str, args: dict[str, Any], call_id: str = "call_1") -> ChatChunk:
    return ChatChunk(
        type="tool_calls",
        metadata={
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }
            ]
        },
    )


def _make_runtime(
    rounds: list[list[ChatChunk]],
    tool_executor: Any = None,
    max_rounds: int = 8,
    emit_execution_events: bool = False,
) -> tuple[LangGraphRuntimeService, list[list[dict[str, Any]]]]:
    stream, calls = _make_stream(rounds)
    deps = NodeDeps(
        model_config=None,
        system_prompt="sys",
        chat_stream=stream,
        tool_executor=tool_executor,
        emit_execution_events=emit_execution_events,
        session_id="session-1",
        run_id="run-1",
        agent_id="agent-general",
    )
    return LangGraphRuntimeService(deps, max_rounds=max_rounds), calls


async def _collect(runtime: LangGraphRuntimeService) -> list[ChatChunk]:
    return [
        chunk
        async for chunk in runtime.stream([{"role": "user", "content": "你好"}])
    ]


async def test_no_tool_call_single_round() -> None:
    """无工具调用：一轮结束，text chunk 按序产出"""
    runtime, _ = _make_runtime(
        [
            [
                ChatChunk(type="text", content="你"),
                ChatChunk(type="text", content="好"),
                ChatChunk(type="done", metadata={"usage": USAGE}),
            ]
        ]
    )

    chunks = await _collect(runtime)

    assert [c.type for c in chunks] == ["text", "text"]
    assert [c.content for c in chunks] == ["你", "好"]
    assert runtime.last_usage == USAGE
    assert runtime.error is None
    # state 消息序列：user → assistant
    assert [m["role"] for m in runtime.last_messages] == ["user", "assistant"]
    assert runtime.last_messages[-1]["content"] == "你好"


async def test_one_tool_round_then_finish() -> None:
    """一轮工具调用回灌后第二轮结束：消息序列 assistant(tool_calls) → tool"""
    executed: list[tuple[str, dict[str, Any], str]] = []

    async def _executor(
        tool_name: str, args: dict[str, Any], tool_call_id: str
    ) -> dict[str, Any]:
        executed.append((tool_name, args, tool_call_id))
        return {"success": True, "result": {"value": 42}}

    runtime, calls = _make_runtime(
        [
            [
                ChatChunk(
                    type="text",
                    content="先分析工具参数",
                    metadata={"is_reasoning": True},
                ),
                _tool_calls_chunk("get_gene", {"gene": "TP53"}),
                ChatChunk(type="done", metadata={"usage": USAGE}),
            ],
            [
                ChatChunk(type="text", content="TP53 是抑癌基因"),
                ChatChunk(type="done", metadata={"usage": USAGE}),
            ],
        ],
        tool_executor=_executor,
    )

    chunks = await _collect(runtime)

    # 首轮的推理文本（is_reasoning）会实时透传给前端，但不并入最终正文
    assert [c.type for c in chunks] == ["text", "tool_call", "tool_result", "text"]
    assert chunks[0].metadata["is_reasoning"] is True
    assert chunks[0].content == "先分析工具参数"
    assert chunks[1].metadata["tool_name"] == "get_gene"
    assert chunks[2].metadata["success"] is True
    assert chunks[2].metadata["result"] == {"value": 42}
    assert executed == [("get_gene", {"gene": "TP53"}, "call_1")]

    # 第二轮 LLM 收到的 messages 末尾：assistant(tool_calls) → role:tool
    second_round = calls[1]
    assert second_round[-2]["role"] == "assistant"
    assert second_round[-2]["tool_calls"][0]["function"]["name"] == "get_gene"
    assert second_round[-2]["reasoning_content"] == "先分析工具参数"
    assert second_round[-1]["role"] == "tool"
    assert second_round[-1]["tool_call_id"] == "call_1"
    assert json.loads(second_round[-1]["content"]) == {"value": 42}

    # 最终 state 消息序列完整
    assert [m["role"] for m in runtime.last_messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    # 两轮 usage 累计合并
    assert runtime.last_usage == {
        "prompt_tokens": 20,
        "completion_tokens": 10,
        "total_tokens": 30,
    }


async def test_execution_event_sequence_proves_tool_reinjection() -> None:
    async def _executor(
        tool_name: str, args: dict[str, Any], tool_call_id: str
    ) -> dict[str, Any]:
        return {"success": True, "result": {"value": 42}}

    emitted: list[ChatChunk] = []

    async def _emit(chunk: ChatChunk) -> None:
        emitted.append(chunk)

    async def _stream(**_kwargs: Any) -> AsyncIterator[ChatChunk]:
        yield _tool_calls_chunk("get_gene", {"gene": "TP53"})
        yield ChatChunk(type="done")

    deps = NodeDeps(
        model_config=None,
        chat_stream=_stream,
        tool_executor=_executor,
        emit=_emit,
        emit_execution_events=True,
        session_id="session-1",
        run_id="run-1",
        agent_id="agent-general",
    )
    state = {
        "messages": [{"role": "user", "content": "读取 TP53"}],
        "rounds": 0,
        "usage": None,
    }
    llm_delta = await llm_call_node(state, deps)
    state["messages"].extend(llm_delta["messages"])
    await tool_exec_node(state, deps)
    execution = [chunk for chunk in emitted if chunk.metadata.get("event_type")]
    event_types = [chunk.type for chunk in execution]
    # agent_turn_started 由外层 Runtime 统一发送（对齐 legacy 每轮一次），图内不重复
    assert event_types == [
        "agent_tool_call",
        "agent_tool_started",
        "agent_tool_result",
        "agent_context_reinjected",
        "agent_turn_continued",
    ]
    assert execution[0].metadata["tool_call_id"] == "call_1"
    assert execution[3].metadata["tool_call_count"] == 1
    assert execution[3].metadata["round"] == 1
    assert execution[4].metadata["round"] == 2
    assert all(chunk.metadata["execution_path"] == "chat_langgraph" for chunk in execution)


async def test_execution_event_sequence_accepts_multiple_tool_batch() -> None:
    async def _executor(
        tool_name: str, args: dict[str, Any], tool_call_id: str
    ) -> dict[str, Any]:
        return {"success": True, "result": {"tool": tool_name, "id": tool_call_id, **args}}

    emitted: list[ChatChunk] = []

    async def _emit(chunk: ChatChunk) -> None:
        emitted.append(chunk)

    async def _stream(**_kwargs: Any) -> AsyncIterator[ChatChunk]:
        yield ChatChunk(
            type="tool_calls",
            metadata={
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_gene",
                            "arguments": json.dumps({"gene": "TP53"}),
                        },
                    },
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "get_pathway",
                            "arguments": json.dumps({"pathway": "p53"}),
                        },
                    },
                ]
            },
        )
        yield ChatChunk(type="done")

    deps = NodeDeps(
        model_config=None,
        chat_stream=_stream,
        tool_executor=_executor,
        emit=_emit,
        emit_execution_events=True,
        session_id="session-1",
        run_id="run-1",
        agent_id="agent-general",
    )
    state = {
        "messages": [{"role": "user", "content": "查询 TP53 和 p53 通路"}],
        "rounds": 0,
        "usage": None,
    }
    llm_delta = await llm_call_node(state, deps)
    state["messages"].extend(llm_delta["messages"])
    await tool_exec_node(state, deps)

    validate_event_sequence([*emitted, "agent_final_result", "done"])
    # 轮级粒度：一批 N 个工具只发一次 agent_context_reinjected（对齐 legacy 每轮一次）
    assert [chunk.type for chunk in emitted].count("agent_context_reinjected") == 1
    assert emitted[-1].type == "agent_turn_continued"


async def test_runtime_events_validate_across_tool_reinjection_round() -> None:
    async def _executor(
        tool_name: str, args: dict[str, Any], tool_call_id: str
    ) -> dict[str, Any]:
        return {"success": True, "result": {"tool": tool_name, **args}}

    runtime, _ = _make_runtime(
        [
            [_tool_calls_chunk("get_gene", {"gene": "TP53"}), ChatChunk(type="done")],
            [ChatChunk(type="text", content="TP53 是抑癌基因"), ChatChunk(type="done")],
        ],
        tool_executor=_executor,
        emit_execution_events=True,
    )

    chunks = await _collect(runtime)

    validate_event_sequence([*chunks, "agent_final_result", "done"])
    # agent_turn_started 由外层 LangGraphChatRuntime 统一发送（对齐 legacy 每轮一次），
    # 图运行时本体（本测试直测的对象）不再重复发送
    assert [chunk.type for chunk in chunks].count("agent_turn_started") == 0


async def test_handoff_tool_ends_current_graph_without_another_llm_round() -> None:
    """Handoff 是控制指令：工具回灌后结束旧 Agent 图，由 ChatService 启动目标图。"""
    directive = {
        "source_agent_id": "agent-scrna",
        "target_agent_id": "agent-rnaseq",
        "reason": "质控已完成，进入差异表达阶段",
        "packet": "## 会话交接",
    }

    async def _executor(
        tool_name: str, args: dict[str, Any], tool_call_id: str
    ) -> dict[str, Any]:
        assert tool_name == "transfer_to_agent"
        return {"success": True, "llm_payload": {"handoff": directive}}

    runtime, calls = _make_runtime(
        [[_tool_calls_chunk("transfer_to_agent", {"target_agent": "agent-rnaseq"})]],
        tool_executor=_executor,
    )

    chunks = await _collect(runtime)

    assert [chunk.type for chunk in chunks] == ["tool_call", "tool_result"]
    assert runtime.last_handoff == directive
    assert len(calls) == 1


async def test_tool_executor_exception_yields_error_chunk() -> None:
    """tool_executor 抛异常：产 error chunk 优雅结束，不向外抛错"""

    async def _executor(
        tool_name: str, args: dict[str, Any], tool_call_id: str
    ) -> dict[str, Any]:
        raise RuntimeError("MCP 连接断开")

    runtime, _ = _make_runtime(
        [
            [
                _tool_calls_chunk("get_gene", {"gene": "TP53"}),
                ChatChunk(type="done", metadata={"usage": USAGE}),
            ]
        ],
        tool_executor=_executor,
    )

    chunks = await _collect(runtime)

    assert [c.type for c in chunks] == ["tool_call", "error"]
    assert "MCP 连接断开" in chunks[-1].content
    assert runtime.error == "MCP 连接断开"


async def test_ask_user_tool_ends_current_graph_without_another_llm_round() -> None:
    """ask_user 是澄清中断：工具回灌后结束当前图，等用户下条消息回答。

    对齐 legacy 手写循环的 stop_after_tools 语义：state["ask_request"]
    携带 tool_call_id 与原始 args，由 ChatService 产出 ask_request 事件。
    """

    async def _executor(
        tool_name: str, args: dict[str, Any], tool_call_id: str
    ) -> dict[str, Any]:
        assert tool_name == "ask_user"
        payload = {
            "questions": args["questions"],
            "question": args["questions"][0]["question"],
            "options": args["questions"][0]["options"],
            "message": "问题已展示给用户，用户将在下一条消息中回答。",
        }
        return {"success": True, "result": {"llm_payload": payload, "ui_payload": payload}}

    ask_args = {
        "questions": [
            {"question": "要分析哪个文件？", "options": ["工作区已有文件", "上传新文件"]}
        ]
    }
    runtime, calls = _make_runtime(
        [[_tool_calls_chunk("ask_user", ask_args)]],
        tool_executor=_executor,
    )

    chunks = await _collect(runtime)

    assert [chunk.type for chunk in chunks] == ["tool_call", "tool_result"]
    assert runtime.last_ask_request == {"tool_call_id": "call_1", "args": ask_args}
    # 图立即结束，不再触发第二轮 LLM
    assert len(calls) == 1


async def test_rounds_exhausted_forces_final_answer_and_sets_flag() -> None:
    """轮次触顶：强制收尾轮不再携带 tool_calls，rounds_exhausted=True。

    ChatService 依据该标志产出 round_limit 事件，由前端弹窗选择是否续轮。
    """

    async def _executor(
        tool_name: str, args: dict[str, Any], tool_call_id: str
    ) -> dict[str, Any]:
        return {"success": True, "result": {"value": 1}}

    runtime, calls = _make_runtime(
        [
            [_tool_calls_chunk("get_gene", {"gene": "TP53"}), ChatChunk(type="done")],
            [_tool_calls_chunk("get_gene", {"gene": "TP53"}), ChatChunk(type="done")],
            [ChatChunk(type="text", content="总结回答"), ChatChunk(type="done")],
        ],
        tool_executor=_executor,
        max_rounds=2,
    )

    await _collect(runtime)

    assert runtime.rounds_exhausted is True
    # 第 3 轮为强制收尾轮：tool_calls 被清空，正文作为最终答复
    assert len(calls) == 3
    assert runtime.last_messages[-1]["role"] == "assistant"
    assert runtime.last_messages[-1]["content"] == "总结回答"
    assert "tool_calls" not in runtime.last_messages[-1]


async def test_normal_finish_does_not_set_rounds_exhausted() -> None:
    """模型主动停止（无 tool_calls）时不判定为触顶。"""

    async def _executor(
        tool_name: str, args: dict[str, Any], tool_call_id: str
    ) -> dict[str, Any]:
        return {"success": True, "result": {"value": 1}}

    runtime, _ = _make_runtime(
        [
            [_tool_calls_chunk("get_gene", {"gene": "TP53"}), ChatChunk(type="done")],
            [ChatChunk(type="text", content="完成"), ChatChunk(type="done")],
        ],
        tool_executor=_executor,
        max_rounds=2,
    )

    await _collect(runtime)

    assert runtime.rounds_exhausted is False


async def test_ask_user_failure_does_not_interrupt_graph() -> None:
    """ask_user 执行失败时按普通工具失败处理：回灌报错信封，循环继续。"""

    async def _executor(
        tool_name: str, args: dict[str, Any], tool_call_id: str
    ) -> dict[str, Any]:
        return {"success": False, "error": "工具 ask_user 未挂载到该 Agent"}

    runtime, calls = _make_runtime(
        [
            [_tool_calls_chunk("ask_user", {"question": "？"}), ChatChunk(type="done")],
            [ChatChunk(type="text", content="好的"), ChatChunk(type="done")],
        ],
        tool_executor=_executor,
    )

    chunks = await _collect(runtime)

    assert [chunk.type for chunk in chunks] == ["tool_call", "tool_result", "text"]
    assert runtime.last_ask_request is None
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# _tool_executor 的 legacy 工具分发分支（mas_plan_preview / parallel_subagents /
# create_agentteams_case / goal 终态工具）：用假 LangGraphRuntimeService 捕获
# NodeDeps.tool_executor 后直接驱动，验证与 legacy chat_service 手写循环的
# 分支语义一致。
# ---------------------------------------------------------------------------


class _CaptureRuntime:
    """假 LangGraphRuntimeService：捕获 NodeDeps（tool_executor/emit），不跑图。"""

    instances: list[_CaptureRuntime] = []

    def __init__(self, deps: NodeDeps, **_: Any) -> None:
        self.deps = deps
        self.last_usage = None
        self.last_handoff = None
        self.last_ask_request = None
        self.rounds_exhausted = False
        self.error = None
        self.emitted: list[ChatChunk] = []
        self.instances.append(self)

    async def stream(self, _: list[dict[str, Any]]) -> AsyncIterator[ChatChunk]:
        async def _sink(chunk: ChatChunk) -> None:
            self.emitted.append(chunk)

        # 对齐真实 RuntimeService.stream：图执行前把 emit 挂到 deps 上
        self.deps.emit = _sink
        if False:  # pragma: no cover - 让本函数成为 async generator
            yield ChatChunk(type="done")


def _chat_service(sandbox_meta: dict | None = None) -> Any:
    service = SimpleNamespace()
    service.update_message_content = AsyncMock()
    service._apply_usage_to_session = AsyncMock()
    service.get_session = AsyncMock(
        return_value=SimpleNamespace(sandbox_meta=sandbox_meta)
    )
    return service


async def _capture_tool_executor(
    monkeypatch: pytest.MonkeyPatch, *, extra: dict | None = None
) -> tuple[Any, list[ChatChunk]]:
    """驱动一次 _stream_agent_chat_langgraph，返回捕获到的 _tool_executor 与 emit 记录。"""
    import cygnusx.infrastructure.execution.langgraph_runtime as runtime_module

    monkeypatch.setattr(runtime_module, "LangGraphRuntimeService", _CaptureRuntime)
    _CaptureRuntime.instances = []
    runtime = LangGraphChatRuntime(_chat_service())
    _ = [
        chunk
        async for chunk in runtime._stream_agent_chat_langgraph(
            user_id="user-1",
            session_id="session-1",
            ai_message_id="message-1",
            model_config=SimpleNamespace(model="test-model"),
            llm_messages=[],
            system_prompt=None,
            tools=[],
            temperature=0.2,
            max_tokens=128,
            deep_thinking=False,
            active_mcp_servers=[],
            mcp_client=SimpleNamespace(),
            tool_context=SimpleNamespace(agent_id="agent-1", extra=extra or {}),
        )
    ]
    assert len(_CaptureRuntime.instances) == 1
    captured = _CaptureRuntime.instances[0]
    return captured.deps.tool_executor, captured.emitted


async def test_tool_executor_mas_plan_preview_returns_adapter_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mas_plan_preview：对齐 legacy chat_service.py:4391-4392，adapt 信封原样返回。"""
    from cygnusx.application.services import mas_plan_adapter

    adapt_calls: list[dict] = []

    class _FakeAdapter:
        def adapt(self, payload: dict) -> dict:
            adapt_calls.append(payload)
            return {
                "success": True,
                "result": {
                    "llm_payload": {"title": "计划", "node_count": 1},
                    "ui_payload": {"mas_plan": {"title": "计划"}},
                },
            }

    monkeypatch.setattr(mas_plan_adapter, "MASPlanPreviewAdapter", _FakeAdapter)
    executor, emitted = await _capture_tool_executor(monkeypatch)

    envelope = await executor(
        "mas_plan_preview", {"title": "计划", "nodes": [{"key": "n1"}]}, "call_mas"
    )

    assert adapt_calls == [{"title": "计划", "nodes": [{"key": "n1"}]}]
    assert envelope["success"] is True
    assert envelope["result"]["llm_payload"]["node_count"] == 1
    assert envelope["result"]["ui_payload"]["mas_plan"] == {"title": "计划"}
    assert emitted == []


async def test_tool_executor_parallel_subagents_rejects_when_case_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case 绑定拒绝：对齐 legacy chat_service.py:4411-4422，双通道均为 success=False。"""
    executor, emitted = await _capture_tool_executor(
        monkeypatch, extra={"agentteams_case_id": "case-1"}
    )

    envelope = await executor(
        PARALLEL_SUBAGENTS_TOOL_NAME,
        {"tasks": [{"agent_id": "agent-a", "task": "t"}]},
        "call_p1",
    )

    assert envelope["success"] is False
    expected = (
        "当前会话已绑定 AgentTeams Case；复杂协作由 Case Work Item 编排，"
        "不会再通过 parallel_subagents 派生子 Agent。"
    )
    assert envelope["result"]["llm_payload"] == {"success": False, "error": expected}
    assert envelope["result"]["ui_payload"] == {"error": expected}
    # 拒绝路径不发 started/aggregated 事件
    assert emitted == []


async def test_tool_executor_parallel_subagents_per_round_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """每轮次数护栏：settings.subagent_max_children_per_message 默认 1，
    同一轮第二次 fanout 被拒（对齐 legacy chat_service.py:4423-4436）。"""
    from cygnusx.application.services import parallel_subagent_tool_service

    run_calls: list[tuple[str, list]] = []

    class _FakeService:
        async def run_parallel_subagents(
            self, *, context_summary: str, tasks: list, context: Any
        ) -> dict:
            run_calls.append((context_summary, tasks))
            return {
                "success": True,
                "llm_payload": {"summary": "全部完成"},
                "ui_payload": {"progress": []},
            }

    monkeypatch.setattr(
        parallel_subagent_tool_service, "ParallelSubAgentToolService", _FakeService
    )
    executor, _ = await _capture_tool_executor(monkeypatch)

    first = await executor(
        PARALLEL_SUBAGENTS_TOOL_NAME,
        {"context_summary": "ctx", "tasks": [{"agent_id": "agent-a", "task": "t"}]},
        "call_p1",
    )
    assert first["success"] is True
    assert len(run_calls) == 1

    second = await executor(
        PARALLEL_SUBAGENTS_TOOL_NAME,
        {"context_summary": "ctx", "tasks": [{"agent_id": "agent-b", "task": "t2"}]},
        "call_p2",
    )
    assert second["success"] is False
    assert "本轮已执行过子 Agent 并行分派" in second["result"]["llm_payload"]["error"]
    assert second["result"]["ui_payload"]["error"] == second["result"]["llm_payload"][
        "error"
    ]
    # 护栏拒绝不消耗执行次数，也不触发实际 fanout
    assert len(run_calls) == 1


async def test_tool_executor_parallel_subagents_emits_started_and_aggregated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正常路径：started/aggregated 事件经 emit 发出，双通道信封封装正确
    （对齐 legacy chat_service.py:4442-4501）。"""
    from cygnusx.application.services import parallel_subagent_tool_service

    class _FakeService:
        async def run_parallel_subagents(
            self, *, context_summary: str, tasks: list, context: Any
        ) -> dict:
            return {
                "success": True,
                "llm_payload": {"summary": "两个子任务均完成"},
                "ui_payload": {"progress": [{"agent_id": "agent-a", "status": "done"}]},
            }

    monkeypatch.setattr(
        parallel_subagent_tool_service, "ParallelSubAgentToolService", _FakeService
    )
    executor, emitted = await _capture_tool_executor(monkeypatch)

    envelope = await executor(
        PARALLEL_SUBAGENTS_TOOL_NAME,
        {
            "context_summary": "ctx",
            "tasks": [
                {"agent_id": "agent-a", "task": "x" * 200},
                {"agent_id": "", "task": 123},
                "not-a-dict",
            ],
        },
        "call_p1",
    )

    sub_chunks = [chunk for chunk in emitted if chunk.type == "subagents"]
    assert [chunk.metadata["phase"] for chunk in sub_chunks] == ["started", "aggregated"]
    started = sub_chunks[0].metadata
    assert started["tool_call_id"] == "call_p1"
    # tasks 截断 120 字、index 从 1 开始、非 dict 项被过滤、非标量转 str
    assert started["tasks"] == [
        {"index": 1, "agent_id": "agent-a", "task": "x" * 120},
        {"index": 2, "agent_id": "", "task": "123"},
    ]
    aggregated = sub_chunks[1].metadata
    assert aggregated["tool_call_id"] == "call_p1"
    assert aggregated["success"] is True
    assert aggregated["summary"] == "两个子任务均完成"
    assert aggregated["progress"] == [{"agent_id": "agent-a", "status": "done"}]
    assert envelope == {
        "success": True,
        "result": {
            "llm_payload": {"summary": "两个子任务均完成"},
            "ui_payload": {"progress": [{"agent_id": "agent-a", "status": "done"}]},
        },
    }


async def test_tool_executor_create_agentteams_case_confirmed_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已确认路径：直调 AgentTeamsCaseToolService.run 并下发 agentteams_case
    卡片事件（对齐 legacy chat_service.py:4556-4584）。"""
    from cygnusx.application.services import agentteams_case_tool_service

    run_calls: list[dict] = []

    class _FakeCaseService:
        async def run(self, **kwargs: Any) -> dict:
            run_calls.append(kwargs)
            return {
                "success": True,
                "llm_payload": {"case_id": "case-1"},
                "ui_payload": {"case_card": {"case_id": "case-1", "title": "目标"}},
            }

    monkeypatch.setattr(
        agentteams_case_tool_service, "AgentTeamsCaseToolService", _FakeCaseService
    )
    executor, emitted = await _capture_tool_executor(monkeypatch)

    envelope = await executor(
        "create_agentteams_case",
        {
            "objective": "obj",
            "project_id": "proj",
            "flow_id": "flow",
            "_confirmed": True,
        },
        "call_c1",
    )

    assert envelope == {
        "success": True,
        "result": {
            "llm_payload": {"case_id": "case-1"},
            "ui_payload": {"case_card": {"case_id": "case-1", "title": "目标"}},
        },
    }
    assert run_calls[0]["objective"] == "obj"
    assert run_calls[0]["sample_context_refs"] == []
    case_chunks = [chunk for chunk in emitted if chunk.type == "agentteams_case"]
    assert len(case_chunks) == 1
    assert case_chunks[0].metadata["phase"] == "created"
    assert case_chunks[0].metadata["tool_call_id"] == "call_c1"
    assert case_chunks[0].metadata["case_id"] == "case-1"


async def test_tool_executor_create_agentteams_case_records_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未确认路径：bridge 预检 needs_confirm 时登记确认请求并入 ui_payload
    （对齐 legacy chat_service.py:4520-4554）。"""
    from cygnusx.application.services import (
        agentteams_case_tool_service,
        tool_bridge_service,
    )

    bridge_calls: list[dict] = []

    class _FakeBridgeService:
        async def execute(self, **kwargs: Any) -> dict:
            bridge_calls.append(kwargs)
            return {
                "success": True,
                "llm_payload": {"needs_confirm": True},
                "ui_payload": {"preview": True},
            }

    record_calls: list[dict] = []

    class _FakeCaseService:
        async def record_confirmation_request(self, **kwargs: Any) -> dict:
            record_calls.append(kwargs)
            return {"confirmation_id": "cfm-1"}

    monkeypatch.setattr(
        tool_bridge_service,
        "get_tool_bridge_service",
        lambda: _FakeBridgeService(),
    )
    monkeypatch.setattr(
        agentteams_case_tool_service, "AgentTeamsCaseToolService", _FakeCaseService
    )
    executor, emitted = await _capture_tool_executor(monkeypatch)

    envelope = await executor(
        "create_agentteams_case",
        {"objective": "obj", "project_id": "proj", "flow_id": "flow"},
        "call_c2",
    )

    assert envelope["success"] is True
    assert envelope["result"]["llm_payload"] == {"needs_confirm": True}
    assert envelope["result"]["ui_payload"] == {
        "preview": True,
        "agentteams_case_confirmation": {"confirmation_id": "cfm-1"},
    }
    assert bridge_calls[0]["tool_name"] == "create_agentteams_case"
    assert record_calls[0]["objective"] == "obj"
    assert record_calls[0]["origin_consultation_id"] is None
    assert [chunk.type for chunk in emitted] == []


async def test_tool_executor_goal_terminal_tools_delegate_to_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """goal_complete/goal_blocked：直调 GoalTerminalToolService.execute 并原样返回
    （对齐 legacy chat_service.py:5026-5033）。"""
    from cygnusx.application.services import goal_terminal_tools

    execute_calls: list[tuple[str, dict]] = []

    class _FakeGoalService:
        async def execute(
            self, tool_name: str, arguments: dict, context: Any
        ) -> dict:
            execute_calls.append((tool_name, arguments))
            return {
                "success": True,
                "result": {
                    "llm_payload": {"action": "complete"},
                    "ui_payload": {"action": "complete"},
                },
            }

    monkeypatch.setattr(goal_terminal_tools, "GoalTerminalToolService", _FakeGoalService)
    executor, emitted = await _capture_tool_executor(monkeypatch)

    envelope = await executor(
        "goal_complete",
        {"evidence": [{"criterion": "c", "evidence": "e"}], "reason": "r"},
        "call_g1",
    )

    assert envelope["success"] is True
    assert envelope["result"]["llm_payload"] == {"action": "complete"}
    assert execute_calls == [
        ("goal_complete", {"evidence": [{"criterion": "c", "evidence": "e"}], "reason": "r"})
    ]
    assert emitted == []


# ===== openai4s 外循环融合（§3.3）：显式 Finalize 动作 + Code Cell 轮次豁免 =====


async def test_submit_output_finalize_ends_graph_with_output() -> None:
    """显式 Finalize 动作：submit_output 成功后图直接结束，finalize 携带 output。"""
    executed: list[tuple[str, dict[str, Any], str]] = []

    async def _executor(
        tool_name: str, args: dict[str, Any], tool_call_id: str
    ) -> dict[str, Any]:
        executed.append((tool_name, args, tool_call_id))
        return {
            "success": True,
            "result": {
                "llm_payload": {"output": args.get("output"), "message": "最终答复已提交，本轮结束。"},
                "ui_payload": {"output": args.get("output"), "message": "最终答复已提交，本轮结束。"},
            },
        }

    runtime, calls = _make_runtime(
        [[_tool_calls_chunk("submit_output", {"output": "最终结论：TP53 是抑癌基因。"})]],
        tool_executor=_executor,
    )
    chunks = await _collect(runtime)

    assert executed == [
        ("submit_output", {"output": "最终结论：TP53 是抑癌基因。"}, "call_1")
    ]
    # finalize 命中后路由到 end：不再有第二轮模型调用
    assert len(calls) == 1
    assert runtime.last_finalize == {
        "tool_call_id": "call_1",
        "output": "最终结论：TP53 是抑癌基因。",
    }
    assert runtime.last_handoff is None
    assert runtime.error is None
    # 工具结果照常回灌（role:tool 消息保留上下文完整性）
    assert [m["role"] for m in runtime.last_messages] == ["user", "assistant", "tool"]
    assert [c.type for c in chunks] == ["tool_call", "tool_result"]


async def test_submit_output_routes_to_end() -> None:
    """route_after_tool：finalize 状态与 ask_user/handoff 一样路由到 end。"""
    from cygnusx.infrastructure.execution.langgraph_nodes import route_after_tool

    assert route_after_tool({"finalize": {"tool_call_id": "c"}}, max_rounds=8) == "end"
    assert route_after_tool({"code_cell_only_round": True}, max_rounds=8) == "llm_call"


async def test_code_cell_only_round_does_not_consume_budget() -> None:
    """Code Cell 不占 tool 轮次预算（§3.3.2）：上一轮全为代码执行工具时
    本轮 llm_call 不递增 rounds；普通工具轮照常递增。"""

    async def _executor(
        tool_name: str, args: dict[str, Any], tool_call_id: str
    ) -> dict[str, Any]:
        return {"success": True, "result": {"ok": True}}

    def _deps_with(stream: Any) -> NodeDeps:
        emitted: list[ChatChunk] = []

        async def _emit(chunk: ChatChunk) -> None:
            emitted.append(chunk)

        return NodeDeps(
            model_config=None,
            chat_stream=stream,
            tool_executor=_executor,
            emit=_emit,
            emit_execution_events=True,
            session_id="session-1",
            run_id="run-1",
            agent_id="agent-general",
        )

    # 第一轮：普通工具轮 → rounds 0 → 1，不标记 code_cell_only
    stream_1, _ = _make_stream([[_tool_calls_chunk("get_gene", {"gene": "TP53"})]])
    deps = _deps_with(stream_1)
    messages: list[dict[str, Any]] = [{"role": "user", "content": "hi"}]
    delta_1 = await llm_call_node({"messages": messages, "rounds": 0}, deps)
    assert delta_1["rounds"] == 1
    messages.extend(delta_1["messages"])
    tool_delta = await tool_exec_node(
        {"messages": messages, "rounds": delta_1["rounds"]}, deps
    )
    assert tool_delta["code_cell_only_round"] is False
    messages.extend(tool_delta["messages"])

    # 第二轮：代码执行工具轮 → rounds 1 → 2，标记 code_cell_only_round=True
    stream_2, _ = _make_stream([[_tool_calls_chunk("chat_sandbox_execute", {"code": "1+1"})]])
    deps_2 = _deps_with(stream_2)
    delta_2 = await llm_call_node(
        {"messages": messages, "rounds": delta_1["rounds"]}, deps_2
    )
    assert delta_2["rounds"] == 2
    messages.extend(delta_2["messages"])
    tool_delta_2 = await tool_exec_node(
        {"messages": messages, "rounds": delta_2["rounds"]}, deps_2
    )
    assert tool_delta_2["code_cell_only_round"] is True
    messages.extend(tool_delta_2["messages"])

    # 第三轮（上一轮全为 Code Cell）：rounds 保持 2，不消耗预算
    stream_3, _ = _make_stream(
        [[ChatChunk(type="text", content="done"), ChatChunk(type="done")]]
    )
    deps_3 = _deps_with(stream_3)
    delta_3 = await llm_call_node(
        {
            "messages": messages,
            "rounds": delta_2["rounds"],
            "code_cell_only_round": tool_delta_2["code_cell_only_round"],
        },
        deps_3,
    )
    assert delta_3["rounds"] == 2


# ===== 落库信封对齐 legacy（payload_hash / cell 字段 / reliability）=====


class _EnvelopeRuntime:
    """假 LangGraphRuntimeService：产出 tool_call + tool_result 帧，

    驱动外层 Runtime 的消费分支，验证落库信封与 legacy chat_service.py:5209-5249 对齐。
    """

    def __init__(self, deps: NodeDeps, **_: Any) -> None:
        self.deps = deps
        self.last_usage = None
        self.last_handoff = None
        self.last_ask_request = None
        self.last_finalize = None
        self.rounds_exhausted = False
        self.error = None

    async def stream(self, _: list[dict[str, Any]]) -> AsyncIterator[ChatChunk]:
        async def _sink(chunk: ChatChunk) -> None:
            return None

        self.deps.emit = _sink
        yield ChatChunk(
            type="tool_call",
            metadata={
                "tool_call_id": "call_1",
                "tool_name": "chat_sandbox_execute",
                "arguments": {"code": "print(1)", "language": "python"},
                "mcp_server": None,
            },
        )
        yield ChatChunk(
            type="tool_result",
            metadata={
                "tool_call_id": "call_1",
                "tool_name": "chat_sandbox_execute",
                "mcp_server": None,
                "success": True,
                "result": {"stdout": "1"},
                "ui_payload": {"stdout": "1"},
                "reliability": {"source": "sandbox"},
            },
        )


async def test_persisted_envelope_matches_legacy_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """落库信封对齐 legacy：payload_hash、cell_index/language、reliability。"""
    import cygnusx.infrastructure.execution.langgraph_runtime as runtime_module

    monkeypatch.setattr(runtime_module, "LangGraphRuntimeService", _EnvelopeRuntime)
    service = _chat_service()
    runtime = LangGraphChatRuntime(service)
    _ = [
        chunk
        async for chunk in runtime._stream_agent_chat_langgraph(
            user_id="user-1",
            session_id="session-1",
            ai_message_id="message-1",
            model_config=SimpleNamespace(model="test-model"),
            llm_messages=[],
            system_prompt=None,
            tools=[],
            temperature=0.2,
            max_tokens=128,
            deep_thinking=False,
            active_mcp_servers=[],
            mcp_client=SimpleNamespace(),
            tool_context=SimpleNamespace(agent_id="agent-1", extra={}),
        )
    ]

    invocations: list[dict[str, Any]] = []
    for call in service.update_message_content.call_args_list:
        metadata = call.args[3] if len(call.args) > 3 else None
        if isinstance(metadata, dict) and metadata.get("tool_invocations"):
            invocations = metadata["tool_invocations"]

    assert len(invocations) == 1
    envelope = invocations[0]
    assert envelope["tool_name"] == "chat_sandbox_execute"
    assert envelope["arguments"] == {"code": "print(1)", "language": "python"}
    assert envelope["cell_index"] == 0
    assert envelope["language"] == "python"
    assert envelope["reliability"] == {"source": "sandbox"}
    # WP2：payload_hash 存在且为 64 位十六进制（sha256），覆盖 cell 字段
    payload_hash = envelope["payload_hash"]
    assert isinstance(payload_hash, str) and len(payload_hash) == 64
    # 小载荷不触发截断标记
    assert "result_truncation" not in envelope
    assert envelope["result"] == {"stdout": "1"}
