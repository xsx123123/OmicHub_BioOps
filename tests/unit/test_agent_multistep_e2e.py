"""端到端验证：Agent 是否真的「一步一步」运行并最终得到正确结果。

与 test_langgraph_runtime.py 的区别：
- 那里的 test_one_tool_round_then_finish 只覆盖「单轮工具调用 → 收尾」；
- 本测试驱动真实的 LangGraphRuntimeService 跑一个**多步闭环**计算
  `(2 + 3) * 4 - 1 == 19`，每一步的 LLM 决策都依赖上一步回灌的工具结果，
  最终断言答案正确 —— 证明 ReAct 循环不是「一次到位」，而是逐步累积收敛。

假 chat_stream 是**有状态**的：它读取收到的 messages（含历史 tool 结果）
来决定下一步调用哪个工具，因此这是一条真正的反馈回路，而非预先写死的脚本。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from omichub.infrastructure.ai_provider.openai_compatible import ChatChunk
from omichub.infrastructure.execution.langgraph_nodes import NodeDeps
from omichub.infrastructure.execution.langgraph_runtime import LangGraphRuntimeService

USAGE = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
EXPECTED_ANSWER = 19  # (2 + 3) * 4 - 1


def _tool_call(name: str, args: dict[str, Any], call_id: str) -> ChatChunk:
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


def _last_running_value(messages: list[dict[str, Any]]) -> int | None:
    """从历史消息里取最近一次工具回灌的数值（模拟 LLM『读到上一步结果』）"""
    for msg in reversed(messages):
        if msg.get("role") == "tool":
            payload = json.loads(msg["content"])
            return int(payload["value"])
    return None


async def test_agent_runs_step_by_step_to_correct_result() -> None:
    """三步依赖计算：add → mul → sub，每步依赖上一步，最终答案正确。"""
    tool_log: list[tuple[str, dict[str, Any]]] = []
    call_counter = {"n": 0}

    async def _stateful_stream(**kwargs: Any) -> AsyncIterator[ChatChunk]:
        """有状态假 LLM：按『当前累积值』决定下一步，模拟真实 ReAct 决策。"""
        call_counter["n"] += 1
        value = _last_running_value(kwargs["messages"])

        if value is None:
            # 第 1 步：还没有任何工具结果 → 先算 2 + 3
            yield _tool_call("add", {"a": 2, "b": 3}, "call_add")
        elif value == 5:
            # 第 2 步：读到 add 的结果 5 → 算 5 * 4
            yield _tool_call("mul", {"a": 5, "b": 4}, "call_mul")
        elif value == 20:
            # 第 3 步：读到 mul 的结果 20 → 算 20 - 1
            yield _tool_call("sub", {"a": 20, "b": 1}, "call_sub")
        elif value == EXPECTED_ANSWER:
            # 第 4 步：读到最终值 19 → 给出自然语言答案，不再调工具
            yield ChatChunk(type="text", content=f"最终结果是 {value}")
        else:  # 意外值 → 说明回路收敛错误，显式失败
            yield ChatChunk(type="text", content=f"收敛到错误值 {value}")
        yield ChatChunk(type="done", metadata={"usage": USAGE})

    async def _executor(
        tool_name: str, args: dict[str, Any], tool_call_id: str
    ) -> dict[str, Any]:
        """真计算器：工具结果真实参与下一步决策。"""
        a, b = args["a"], args["b"]
        if tool_name == "add":
            result = a + b
        elif tool_name == "mul":
            result = a * b
        elif tool_name == "sub":
            result = a - b
        else:
            raise AssertionError(f"未知工具 {tool_name}")
        tool_log.append((tool_name, args))
        return {"success": True, "result": {"value": result}}

    deps = NodeDeps(
        model_config=None,
        system_prompt="你是一个会逐步计算的助手。",
        chat_stream=_stateful_stream,
        tool_executor=_executor,
    )
    runtime = LangGraphRuntimeService(deps)

    chunks = [
        chunk
        async for chunk in runtime.stream(
            [{"role": "user", "content": "请计算 (2+3)*4-1，分步调用工具。"}]
        )
    ]

    # 1) 工具按依赖顺序真实执行了三次
    assert [name for name, _ in tool_log] == ["add", "mul", "sub"]
    # 2) LLM 被调用了四轮（三次工具决策 + 一次收尾），证明是逐步迭代而非一次到位
    assert call_counter["n"] == 4
    # 3) 事件流：每轮 tool_call → tool_result，最后一段 text
    assert [c.type for c in chunks] == [
        "tool_call", "tool_result",  # add → 5
        "tool_call", "tool_result",  # mul → 20
        "tool_call", "tool_result",  # sub → 19
        "text",                      # 最终答案
    ]
    # 4) 每次回灌的中间值正确累积
    tool_results = [c for c in chunks if c.type == "tool_result"]
    assert [c.metadata["result"]["value"] for c in tool_results] == [5, 20, 19]
    # 5) 最终自然语言答案正确
    final_text = "".join(c.content for c in chunks if c.type == "text")
    assert final_text == f"最终结果是 {EXPECTED_ANSWER}"
    # 6) 无运行时错误
    assert runtime.error is None
    # 7) 消息序列：user → (assistant+tool)×3 → assistant
    roles = [m["role"] for m in runtime.last_messages]
    assert roles == ["user", "assistant", "tool", "assistant", "tool",
                     "assistant", "tool", "assistant"]


async def test_agent_respects_max_rounds_cap() -> None:
    """工具达到上限后必须停调工具，并生成最终答复。"""
    calls = {"n": 0}

    async def _greedy_stream(**kwargs: Any) -> AsyncIterator[ChatChunk]:
        calls["n"] += 1
        if kwargs["tools"] is None:
            yield ChatChunk(type="text", content="工具结果已汇总。")
            yield ChatChunk(type="done", metadata={"usage": USAGE})
            return
        yield _tool_call("add", {"a": 1, "b": 1}, f"call_{calls['n']}")
        yield ChatChunk(type="done", metadata={"usage": USAGE})

    async def _executor(
        tool_name: str, args: dict[str, Any], tool_call_id: str
    ) -> dict[str, Any]:
        return {"success": True, "result": {"value": 2}}

    deps = NodeDeps(
        model_config=None,
        system_prompt="sys",
        tools=[{"name": "add"}],
        chat_stream=_greedy_stream,
        tool_executor=_executor,
    )
    runtime = LangGraphRuntimeService(deps, max_rounds=3)
    chunks = [
        c
        async for c in runtime.stream([{"role": "user", "content": "无限循环"}])
    ]

    # max_rounds=3 → 恰好 3 轮 tool_call/tool_result，随后无工具总结，不会无限执行
    assert [c.type for c in chunks].count("tool_call") == 3
    assert [c.content for c in chunks if c.type == "text"] == ["工具结果已汇总。"]
    assert calls["n"] == 4
    assert runtime.error is None
