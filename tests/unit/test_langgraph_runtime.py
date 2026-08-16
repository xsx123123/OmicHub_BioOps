"""LangGraph 运行时单元测试：假 provider + 假 tool_executor"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from omichub.infrastructure.ai_provider.openai_compatible import ChatChunk
from omichub.infrastructure.execution.langgraph_nodes import NodeDeps
from omichub.infrastructure.execution.langgraph_runtime import LangGraphRuntimeService

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
) -> tuple[LangGraphRuntimeService, list[list[dict[str, Any]]]]:
    stream, calls = _make_stream(rounds)
    deps = NodeDeps(
        model_config=None,
        system_prompt="sys",
        chat_stream=stream,
        tool_executor=tool_executor,
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

    chunks = await _collect(runtime)

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
