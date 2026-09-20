"""超频模式第一期的编排与容错契约测试。"""

from __future__ import annotations

import inspect
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import cygnusx.application.services.chat_service as chat_module
from cygnusx.application.services.chat_service import (
    ChatService,
    _extract_route_json,
)
from cygnusx.application.services.chat.overdrive_control import (
    _build_overdrive_followup_assignments,
    _default_overdrive_assignments,
    _effective_overdrive,
    _extract_overdrive_intake_slots,
    _filter_overdrive_questions,
    _normalize_overdrive_assignments,
    _overdrive_assignment_waves,
    _overdrive_capability_profile,
    _overdrive_followup_choices,
    _overdrive_preflight_questions,
    _overdrive_summary_exposes_internal_instructions,
    _resolve_overdrive_keyword_toggle,
    _resolve_overdrive_router_toggle,
)
from cygnusx.application.services.domain_registry import get_domain_registry
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk

legacy_preconfirmation_execution = pytest.mark.skip(
    reason="retired: Overdrive now freezes a plan and waits for user confirmation before worker dispatch"
)


class _FakeAgentService:
    agents: list[object] = []

    def __init__(self, _db) -> None:
        pass

    async def list_agents(self, *, active_only: bool = False):
        assert active_only
        return self.agents

    async def assemble_context(
        self,
        _agent_id: str,
        *,
        user_id: str | None = None,
        tool_query: str | None = None,
    ):
        return None


def _agent(
    agent_id: str,
    name: str,
    *,
    spawnable: bool = True,
    category: str = "analysis",
) -> object:
    return SimpleNamespace(
        agent_id=agent_id,
        name=name,
        avatar="🧬",
        color="#2a8",
        description=f"{name} 专家",
        category=category,
        features={"subagents_spawnable": True} if spawnable else {},
    )


def _manager_ctx() -> object:
    return SimpleNamespace(
        agent=_agent("manager", "Manager"),
        model_config=SimpleNamespace(name="test-model"),
    )


@pytest.mark.parametrize(
    ("raw", "expected_ids"),
    [
        ('{"speech":"分工","assignments":[]}', []),
        (
            '思考\n{"speech":"分工","assignments":[{"agent_id":"a","task":"A"},{"agent_id":"b","task":"B"}]}',
            ["a", "b"],
        ),
        ("纯文本", []),
        ('{"speech":"分工","assignments":[{"agent_id":"a","task":"A"}]}', ["a"]),
    ],
)
def test_extract_overdrive_manager_json_shapes(raw: str, expected_ids: list[str]) -> None:
    parsed = _extract_route_json(raw)
    if expected_ids:
        assert parsed is not None
        assert [item["agent_id"] for item in parsed["assignments"]] == expected_ids
    elif raw == "纯文本":
        assert parsed is None
    else:
        assert parsed == {"speech": "分工", "assignments": []}


@pytest.mark.parametrize(
    ("text", "enabled", "expected"),
    [
        ("请进入超频模式", False, True),
        ("开启超频模式", False, True),
        ("我想让你用超频模式帮我拆分任务", False, True),
        ("用超频模式帮我做 TP53 RNA-seq 方案", False, True),
        ("通过超频模式组织多专家协作", False, True),
        ("turn on overdrive", False, True),
        ("平台的超频模式是什么", False, None),
        ("超频模式是什么", False, None),
        ("如何开启超频模式？", False, None),
        ("OVERDRIVE", False, None),
        ("退出超频模式", True, False),
        ("关闭超频后继续", True, False),
        ("别进超频模式，正常回答", False, None),
        ("已经在超频模式", True, None),
    ],
)
def test_overdrive_keyword_toggle_priority(text: str, enabled: bool, expected: bool | None) -> None:
    assert _resolve_overdrive_keyword_toggle(text, enabled) is expected


@pytest.mark.parametrize(
    ("route_info", "enabled", "expected"),
    [
        ({"overdrive_intent": "enable", "intent": "fanout", "confidence": 0.92}, False, True),
        ({"overdrive_intent": "enable", "intent": "consult", "confidence": 0.75}, False, True),
        ({"overdrive_intent": "enable", "intent": "chat", "confidence": 0.99}, False, None),
        ({"overdrive_intent": "enable", "intent": "fanout", "confidence": 0.74}, False, None),
        ({"overdrive_intent": "disable", "intent": "chat", "confidence": 0.99}, True, False),
        ({"overdrive_intent": "none", "intent": "fanout", "confidence": 0.99}, False, None),
        (None, False, None),
    ],
)
def test_overdrive_router_toggle_requires_user_requested_actionable_collaboration(
    route_info: dict[str, object] | None, enabled: bool, expected: bool | None
) -> None:
    assert _resolve_overdrive_router_toggle(route_info, enabled) is expected


@pytest.mark.parametrize(
    ("request_value", "stored_value", "expected"),
    [
        (True, False, True),
        (False, True, False),
        (None, True, True),
        (None, False, False),
    ],
)
def test_overdrive_request_value_has_priority(
    request_value: bool | None, stored_value: bool, expected: bool
) -> None:
    assert _effective_overdrive(request_value, {"overdrive": stored_value}) is expected


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("这是基于专家结论的简要方案。", False),
        ("用户要求只基于专家的最终结论生成简短汇总。", True),
        ("根据规则，我应该直接输出这句话。", True),
        ("系统消息要求我不要复述过程。", True),
    ],
)
def test_overdrive_summary_internal_instruction_guard(content: str, expected: bool) -> None:
    assert _overdrive_summary_exposes_internal_instructions(content) is expected


def test_overdrive_assignment_waves_follow_declared_dependencies() -> None:
    assignments = _normalize_overdrive_assignments(
        [
            {"task_id": "research", "agent_id": "general", "task": "研究计划"},
            {
                "task_id": "code",
                "agent_id": "code",
                "task": "代码设计",
                "depends_on": ["research"],
            },
            {
                "task_id": "viz",
                "agent_id": "viz",
                "task": "可视化设计",
                "depends_on": ["research", "code"],
            },
        ],
        {"general", "code", "viz"},
    )

    assert [
        [item["task_id"] for item in wave] for wave in _overdrive_assignment_waves(assignments)
    ] == [
        ["research"],
        ["code"],
        ["viz"],
    ]


def test_overdrive_minimizes_existing_tree_task_to_visualization_agent() -> None:
    assignments = _normalize_overdrive_assignments(
        [
            {"task_id": "research", "agent_id": "agent-general", "task": "研究计划"},
            {"task_id": "code", "agent_id": "agent-code", "task": "代码设计"},
            {"task_id": "viz", "agent_id": "agent-viz", "task": "可视化设计"},
        ],
        {"agent-general", "agent-code", "agent-viz"},
    )
    catalog = {
        "agent-general": {"agent_id": "agent-general", "name": "通用助手", "category": "general"},
        "agent-code": {"agent_id": "agent-code", "name": "代码助手", "category": "code"},
        "agent-viz": {"agent_id": "agent-viz", "name": "可视化助手", "category": "visualization"},
    }

    minimized = get_domain_registry().minimize_assignments(
        assignments, catalog, {"task_type": "tree_visualization"}
    )

    assert [item["agent_id"] for item in minimized] == ["agent-viz"]
    assert minimized[0]["depends_on"] == []


def test_overdrive_default_bulk_schedule_uses_minimal_domain_expert() -> None:
    assignments = _default_overdrive_assignments(
        "请为 bulk RNA-seq 的 TP53 分组制定详细分析计划",
        [
            {"agent_id": "agent-general", "name": "通用助手", "category": "general"},
            {"agent_id": "agent-rnaseq", "name": "RNA-seq 分析师", "category": "analysis"},
            {"agent_id": "agent-code", "name": "代码助手", "category": "code"},
            {"agent_id": "agent-viz", "name": "可视化助手", "category": "visualization"},
        ],
    )

    assert [item["agent_id"] for item in assignments] == ["agent-rnaseq"]
    assert assignments[0]["depends_on"] == []


def test_overdrive_tree_slots_and_questions_follow_selected_branch() -> None:
    slots = _extract_overdrive_intake_slots(
        """您的核心需求是什么？
回答：处理/美化已有树（我有 Newick 树文件）
输入格式回答：treefile 文件"""
    )
    questions = _filter_overdrive_questions(
        [
            {"question": "蛋白质序列是否已完成多序列比对（MSA）？", "options": []},
            {"question": "您偏好的 IQ-TREE 建树算法是什么？", "options": []},
            {"question": "是否需要添加分支颜色和标签注释？", "options": []},
        ],
        slots,
    )

    assert slots == {"task_type": "tree_visualization", "input_format": "treefile"}
    assert [item["question"] for item in questions] == ["是否需要添加分支颜色和标签注释？"]

    unresolved_questions = _filter_overdrive_questions(
        [
            {
                "question": "您的核心需求是从头构建，还是处理/美化已有树？",
                "options": ["从头构建", "处理/美化已有树"],
            },
            {"question": "如果从头建树，是否已经完成 MSA？", "options": []},
        ],
        {"input_format": "treefile"},
    )
    assert [item["question"] for item in unresolved_questions] == [
        "您的核心需求是从头构建，还是处理/美化已有树？"
    ]


def test_overdrive_default_existing_tree_schedule_uses_visualization_only() -> None:
    assignments = _default_overdrive_assignments(
        "帮我处理这个系统发育树",
        [
            {"agent_id": "agent-general", "name": "通用助手", "category": "general"},
            {"agent_id": "agent-code", "name": "代码助手", "category": "code"},
            {"agent_id": "agent-viz", "name": "可视化助手", "category": "visualization"},
        ],
        {"task_type": "tree_visualization", "input_format": "treefile"},
    )

    assert [item["agent_id"] for item in assignments] == ["agent-viz"]
    assert "不要重新执行序列比对或建树" in assignments[0]["task"]


def test_overdrive_capability_profile_prefers_yaml_contract() -> None:
    profile = _overdrive_capability_profile(
        agent_id="agent-code",
        name="代码助手",
        category="code",
        features={
            "capability_tags": ["python", "r", "sandbox-execution"],
            "accepts_inputs": ["research-plan", "workspace-files"],
            "produces_outputs": ["analysis-script", "result-table"],
            "default_stage": "code-design",
        },
    )

    assert profile["capability_scope"] == ["python", "r", "sandbox-execution"]
    assert profile["accepts_inputs"] == ["research-plan", "workspace-files"]
    assert profile["produces_outputs"] == ["analysis-script", "result-table"]
    assert profile["default_stage"] == "code-design"


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (
            "保存到 output/results/ 并更新 output/README.md（推荐）；已准备好，请按计划开始分析（推荐）",
            (True, True),
        ),
        ("暂不保存；尚未准备好，先保留分析计划", (False, False)),
        ("请保存报告；数据尚未准备好", (True, False)),
    ],
)
def test_overdrive_followup_choices(answer: str, expected: tuple[bool, bool]) -> None:
    assert _overdrive_followup_choices(answer) == expected


def test_overdrive_followup_builds_execution_then_visualization_dag() -> None:
    speech, assignments = _build_overdrive_followup_assignments(
        catalog_items=[
            {"agent_id": "agent-code", "name": "代码助手", "category": "code"},
            {"agent_id": "agent-viz", "name": "可视化助手", "category": "visualization"},
        ],
        save_requested=True,
        data_ready=True,
    )

    assert "先保存" in speech
    assert [item["task_id"] for item in assignments] == [
        "execute-analysis",
        "visualize-results",
    ]
    assert assignments[0]["workspace_access"] is True
    assert assignments[1]["depends_on"] == ["execute-analysis"]


@pytest.mark.asyncio
@legacy_preconfirmation_execution
async def test_overdrive_executes_dependency_chain_and_passes_upstream_outputs(monkeypatch) -> None:
    _FakeAgentService.agents = [
        _agent("agent-general", "通用助手", category="general"),
        _agent("agent-code", "代码助手", category="code"),
        _agent("agent-viz", "可视化助手", category="visualization"),
    ]
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )
    manager_outputs = iter(
        [
            (
                '{"speech":"按依赖顺序执行。","assignments":['
                '{"task_id":"research","agent_id":"agent-general","task":"形成研究计划","depends_on":[]},'
                '{"task_id":"code","agent_id":"agent-code","task":"形成代码设计","depends_on":["research"]},'
                '{"task_id":"viz","agent_id":"agent-viz","task":"形成可视化方案","depends_on":["research","code"]}'
                "]}"
            ),
            "## 综合报告\n\n已整合研究计划、代码设计和可视化方案。",
        ]
    )

    async def fake_stream(**_kwargs):
        yield ChatChunk(type="text", content=next(manager_outputs))

    fanout_calls: list[list[dict[str, str]]] = []
    answers = {
        "agent-general": "GENERAL_RESEARCH_PLAN",
        "agent-code": "CODE_IMPLEMENTATION_DESIGN",
        "agent-viz": "FINAL_VISUALIZATION_PLAN",
    }

    async def fake_fanout(self, *, tasks, **_kwargs):
        fanout_calls.append(tasks)
        task = tasks[0]
        return {
            "success": True,
            "llm_payload": {
                "results": [
                    {
                        "index": 1,
                        "agent_id": task["agent_id"],
                        "status": "ok",
                        "answer": answers[task["agent_id"]],
                    }
                ]
            },
        }

    session = SimpleNamespace(sandbox_meta={})
    monkeypatch.setattr(chat_module.provider_manager, "chat_stream", fake_stream)
    monkeypatch.setattr(
        "cygnusx.application.services.parallel_subagent_tool_service.ParallelSubAgentToolService.run_parallel_subagents",
        fake_fanout,
    )
    service = ChatService(MagicMock(spec=AsyncSession))
    service.get_session = AsyncMock(return_value=session)  # type: ignore[method-assign]
    service.add_message = AsyncMock(  # type: ignore[method-assign]
        side_effect=lambda *_args, **_kwargs: SimpleNamespace(message_id="message")
    )

    chunks = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user",
            session_id="session",
            user_content=(
                "请为 bulk RNA-seq 的 TP53 敲除/过表达 vs 对照写详细研究计划；"
                "每组 30 个样本，已有 count 表达矩阵。"
            ),
            manager_ctx=_manager_ctx(),
        )
    ]

    assert [[task["agent_id"] for task in call] for call in fanout_calls] == [
        ["agent-general"],
        ["agent-code"],
        ["agent-viz"],
    ]
    assert "GENERAL_RESEARCH_PLAN" in fanout_calls[1][0]["task"]
    assert "GENERAL_RESEARCH_PLAN" in fanout_calls[2][0]["task"]
    assert "CODE_IMPLEMENTATION_DESIGN" in fanout_calls[2][0]["task"]
    assert any(chunk.type == "ask_request" for chunk in chunks)
    assert session.sandbox_meta["overdrive_followup"]["status"] == "awaiting_input"
    assert session.sandbox_meta["overdrive_followup"]["root_request"] == (
        "请为 bulk RNA-seq 的 TP53 敲除/过表达 vs 对照写详细研究计划；"
        "每组 30 个样本，已有 count 表达矩阵。"
    )
    assert "已确认信息：" not in session.sandbox_meta["overdrive_followup"]["root_request"]


@pytest.mark.asyncio
@legacy_preconfirmation_execution
async def test_budget_exhausted_code_task_blocks_visualization_wave(monkeypatch) -> None:
    _FakeAgentService.agents = [
        _agent("agent-general", "通用助手", category="general"),
        _agent("agent-code", "代码助手", category="code"),
        _agent("agent-viz", "可视化助手", category="visualization"),
    ]
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )
    manager_outputs = iter(
        [
            (
                '{"speech":"按依赖顺序执行。","assignments":['
                '{"task_id":"research","agent_id":"agent-general","task":"研究计划","depends_on":[]},'
                '{"task_id":"code","agent_id":"agent-code","task":"完整代码","depends_on":["research"]},'
                '{"task_id":"viz","agent_id":"agent-viz","task":"绘图方案","depends_on":["code"]}'
                "]}"
            ),
            "## 综合报告\n\n代码任务未完整完成，因此未启动绘图任务。",
        ]
    )

    async def fake_stream(**_kwargs):
        yield ChatChunk(type="text", content=next(manager_outputs))

    fanout_agents: list[str] = []

    async def fake_fanout(self, *, tasks, **_kwargs):
        agent_id = tasks[0]["agent_id"]
        fanout_agents.append(agent_id)
        if agent_id == "agent-code":
            return {
                "success": True,
                "llm_payload": {
                    "results": [
                        {
                            "index": 1,
                            "agent_id": agent_id,
                            "status": "budget_exhausted",
                            "answer": "仅生成了部分代码",
                            "error": "工具轮次预算耗尽",
                        }
                    ]
                },
            }
        return {
            "success": True,
            "llm_payload": {
                "results": [
                    {"index": 1, "agent_id": agent_id, "status": "ok", "answer": "完整研究计划"}
                ]
            },
        }

    monkeypatch.setattr(chat_module.provider_manager, "chat_stream", fake_stream)
    monkeypatch.setattr(
        "cygnusx.application.services.parallel_subagent_tool_service.ParallelSubAgentToolService.run_parallel_subagents",
        fake_fanout,
    )
    service = ChatService(MagicMock(spec=AsyncSession))
    service.add_message = AsyncMock(return_value=SimpleNamespace(message_id="message"))  # type: ignore[method-assign]

    chunks = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user",
            session_id="session-budget-gate",
            user_content="请完成研究、代码和绘图交付",
            manager_ctx=_manager_ctx(),
        )
    ]

    assert fanout_agents == ["agent-general", "agent-code"]
    task_rows = [
        task
        for chunk in chunks
        if chunk.type == "overdrive_progress"
        for task in chunk.metadata.get("tasks", [])
    ]
    viz_rows = [task for task in task_rows if task.get("task_id") == "viz"]
    assert viz_rows and viz_rows[-1]["status"] == "skipped"


@pytest.mark.asyncio
@legacy_preconfirmation_execution
async def test_budget_exhausted_user_request_pauses_visualization_instead_of_skipping(
    monkeypatch,
) -> None:
    _FakeAgentService.agents = [
        _agent("agent-code", "代码助手", category="code"),
        _agent("agent-viz", "可视化助手", category="visualization"),
    ]
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )
    session = SimpleNamespace(sandbox_meta={})

    async def fake_stream(**_kwargs):
        yield ChatChunk(
            type="text",
            content=(
                '{"speech":"先完成代码处理，再生成图表。","assignments":['
                '{"task_id":"code","agent_id":"agent-code","task":"处理输入文件","depends_on":[]},'
                '{"task_id":"viz","agent_id":"agent-viz","task":"生成图表","depends_on":["code"]}'
                "]}"
            ),
        )

    fanout_agents: list[str] = []

    async def fake_fanout(self, *, tasks, **_kwargs):
        fanout_agents.append(tasks[0]["agent_id"])
        return {
            "success": True,
            "llm_payload": {
                "results": [
                    {
                        "index": 1,
                        "agent_id": "agent-code",
                        "status": "budget_exhausted",
                        "answer": "请补充缺少的输入文件后继续。",
                        "error": "子循环超过 6 轮工具上限，返回阶段性结论",
                        "packet": {
                            "status": "budget_exhausted",
                            "final_answer": "",
                            "needs_user_input": True,
                            "user_request": "请补充缺少的输入文件后继续。",
                            "questions": [{"question": "请上传缺少的输入文件", "options": []}],
                            "approval_requests": [],
                            "error": "子循环超过 6 轮工具上限，返回阶段性结论",
                        },
                    }
                ]
            },
        }

    monkeypatch.setattr(chat_module.provider_manager, "chat_stream", fake_stream)
    monkeypatch.setattr(
        "cygnusx.application.services.parallel_subagent_tool_service.ParallelSubAgentToolService.run_parallel_subagents",
        fake_fanout,
    )
    service = ChatService(MagicMock(spec=AsyncSession))
    service.get_session = AsyncMock(return_value=session)  # type: ignore[method-assign]
    service.add_message = AsyncMock(return_value=SimpleNamespace(message_id="message"))  # type: ignore[method-assign]

    chunks = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user",
            session_id="session-awaiting-code",
            user_content="请完成代码处理后再生成可视化图表",
            manager_ctx=_manager_ctx(),
        )
    ]

    assert fanout_agents == ["agent-code"]
    progress_tasks = [
        task
        for chunk in chunks
        if chunk.type == "overdrive_progress"
        for task in chunk.metadata.get("tasks", [])
    ]
    code_rows = [task for task in progress_tasks if task.get("task_id") == "code"]
    viz_rows = [task for task in progress_tasks if task.get("task_id") == "viz"]
    assert code_rows and code_rows[-1]["status"] == "awaiting_input"
    assert viz_rows and viz_rows[-1]["status"] == "pending"
    assert not any(task.get("status") == "skipped" for task in viz_rows)
    assert session.sandbox_meta["overdrive_intake"]["source_task_id"] == "code"
    assert any(chunk.type == "ask_request" for chunk in chunks)
    assert any(
        chunk.type == "overdrive_progress"
        and "暂停而非跳过" in str(chunk.metadata.get("label") or "")
        for chunk in chunks
    )


@pytest.mark.asyncio
@legacy_preconfirmation_execution
async def test_overdrive_worker_reasoning_stream_is_persisted_separately(monkeypatch) -> None:
    _FakeAgentService.agents = [_agent("agent-general", "通用助手", category="general")]
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )
    manager_outputs = iter(
        [
            '{"speech":"开始处理。","assignments":[{"task_id":"task","agent_id":"agent-general","task":"形成结论","depends_on":[]}]}',
            "Manager 汇总结论。",
        ]
    )

    async def fake_stream(**_kwargs):
        yield ChatChunk(type="text", content=next(manager_outputs))

    async def fake_fanout(self, *, tasks, on_event, **_kwargs):
        await on_event({"type": "worker_started", "index": 1, "agent_id": "agent-general"})
        await on_event(
            {
                "type": "worker_reasoning_delta",
                "index": 1,
                "agent_id": "agent-general",
                "content": "REASONING_DELTA",
            }
        )
        await on_event(
            {
                "type": "worker_text_delta",
                "index": 1,
                "agent_id": "agent-general",
                "content": "FINAL_DELTA",
            }
        )
        await on_event(
            {
                "type": "worker_finished",
                "index": 1,
                "agent_id": "agent-general",
                "status": "ok",
            }
        )
        return {
            "success": True,
            "llm_payload": {
                "results": [
                    {
                        "index": 1,
                        "agent_id": tasks[0]["agent_id"],
                        "status": "ok",
                        "answer": "FINAL_DELTA",
                        "thought": "REASONING_DELTA",
                    }
                ]
            },
        }

    persisted: list[dict] = []

    async def fake_add_message(_session, _role, content, **kwargs):
        persisted.append({"content": content, **kwargs})
        return SimpleNamespace(message_id=f"message-{len(persisted)}")

    monkeypatch.setattr(chat_module.provider_manager, "chat_stream", fake_stream)
    monkeypatch.setattr(
        "cygnusx.application.services.parallel_subagent_tool_service.ParallelSubAgentToolService.run_parallel_subagents",
        fake_fanout,
    )
    service = ChatService(MagicMock(spec=AsyncSession))
    service.add_message = fake_add_message  # type: ignore[method-assign]

    chunks = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user",
            session_id="session",
            user_content="请协作形成结论",
            manager_ctx=_manager_ctx(),
        )
    ]

    deltas = [chunk for chunk in chunks if chunk.type == "room_speech_delta"]
    assert [chunk.content for chunk in deltas] == [
        "REASONING_DELTA",
        "FINAL_DELTA",
        "Manager 汇总结论。",
    ]
    assert deltas[0].metadata["is_reasoning"] is True
    assert "is_reasoning" not in deltas[1].metadata
    # Manager 综合报告同样以 room_speech_delta 真流式下发，
    # worker_key 与最终收束的 room_speech 对应，供前端合并为同一条消息。
    summary_delta = deltas[2]
    assert summary_delta.metadata["worker_key"] == "manager-final"
    assert summary_delta.metadata["sender"]["role"] == "manager"
    assert "is_reasoning" not in summary_delta.metadata
    manager_speech = next(
        chunk
        for chunk in chunks
        if chunk.type == "room_speech"
        and chunk.metadata["sender"]["role"] == "manager"
        and chunk.metadata.get("worker_key") == "manager-final"
    )
    assert manager_speech.content == "Manager 汇总结论。"
    worker_speech = next(
        chunk
        for chunk in chunks
        if chunk.type == "room_speech" and chunk.metadata["sender"]["role"] == "worker"
    )
    assert worker_speech.content == "FINAL_DELTA"
    assert worker_speech.metadata["thought"] == "REASONING_DELTA"
    worker_record = next(
        item
        for item in persisted
        if item.get("metadata", {}).get("senderAgent", {}).get("role") == "worker"
    )
    assert worker_record["metadata"]["thought"] == "REASONING_DELTA"


@pytest.mark.asyncio
@legacy_preconfirmation_execution
async def test_overdrive_followup_saves_report_then_executes_and_visualizes(monkeypatch) -> None:
    _FakeAgentService.agents = [
        _agent("agent-code", "代码助手", category="code"),
        _agent("agent-viz", "可视化助手", category="visualization"),
    ]
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )
    session = SimpleNamespace(
        sandbox_meta={
            "overdrive_followup": {
                "status": "awaiting_input",
                "root_request": "bulk RNA-seq TP53 研究计划",
                "final_report": "FINAL_INTEGRATED_REPORT",
            }
        }
    )
    workspace_calls: list[tuple[str, str, dict]] = []

    async def fake_execute_studio_tool(name, args, session_id, **_kwargs):
        workspace_calls.append((name, session_id, args))
        if name == "workspace_read":
            return {
                "success": True,
                "result": {"llm_payload": {"content": "# Existing Output"}},
            }
        return {"success": True, "result": {"llm_payload": {"path": args.get("path")}}}

    async def fake_stream(**_kwargs):
        yield ChatChunk(
            type="text",
            content="## 执行汇总\n\n报告已保存，分析与可视化均基于真实工作区产物完成。",
        )

    fanout_calls: list[list[dict[str, object]]] = []

    async def fake_fanout(self, *, tasks, **_kwargs):
        fanout_calls.append(tasks)
        task = tasks[0]
        answer = (
            "CODE_RUN_RESULT: output/results/deg.csv"
            if task["agent_id"] == "agent-code"
            else "VIZ_RESULT: output/figures/volcano.png"
        )
        return {
            "success": True,
            "llm_payload": {
                "results": [
                    {
                        "index": 1,
                        "agent_id": task["agent_id"],
                        "status": "ok",
                        "answer": answer,
                    }
                ]
            },
        }

    monkeypatch.setattr(chat_module, "execute_studio_tool", fake_execute_studio_tool)
    monkeypatch.setattr(chat_module.provider_manager, "chat_stream", fake_stream)
    monkeypatch.setattr(
        "cygnusx.application.services.parallel_subagent_tool_service.ParallelSubAgentToolService.run_parallel_subagents",
        fake_fanout,
    )
    service = ChatService(MagicMock(spec=AsyncSession))
    service.get_session = AsyncMock(return_value=session)  # type: ignore[method-assign]
    service.add_message = AsyncMock(  # type: ignore[method-assign]
        side_effect=lambda *_args, **_kwargs: SimpleNamespace(message_id="message")
    )

    _ = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user",
            session_id="session",
            user_content=(
                "保存到 output/results/ 并更新 output/README.md（推荐）；"
                "已准备好，请按计划开始分析（推荐）"
            ),
            manager_ctx=_manager_ctx(),
        )
    ]

    assert [call[0] for call in workspace_calls] == [
        "workspace_write",
        "workspace_read",
        "workspace_write",
    ]
    assert "FINAL_INTEGRATED_REPORT" in workspace_calls[0][2]["content"]
    assert [[task["agent_id"] for task in call] for call in fanout_calls] == [
        ["agent-code"],
        ["agent-viz"],
    ]
    assert fanout_calls[0][0]["workspace_access"] is True
    assert "CODE_RUN_RESULT" in str(fanout_calls[1][0]["task"])
    assert "overdrive_followup" not in session.sandbox_meta


def test_overdrive_preflight_requests_context_before_tp53_plan_dispatch() -> None:
    questions = _overdrive_preflight_questions(
        "我现在有2个TP53分组，要如何发现新颖发现，请写一个详细计划"
    )

    assert len(questions) == 3
    assert "数据属于哪种模态" in questions[0]["question"]
    assert "TP53 分组" in questions[1]["question"]


def test_overdrive_preflight_skips_plan_when_critical_context_is_supplied() -> None:
    questions = _overdrive_preflight_questions(
        "请为 bulk RNA-seq 的 TP53 突变 vs 野生型研究写计划；每组有 30 个样本，已有 count 矩阵。"
    )

    assert questions == []


def test_overdrive_preflight_blocks_any_operational_task_without_input() -> None:
    questions = _overdrive_preflight_questions("帮我做一下 RNA-seq 分析")

    assert questions
    assert "真实输入" in questions[0]["question"]
    assert "我会上传/引用输入后执行（推荐）" in questions[0]["options"]


def test_overdrive_preflight_does_not_block_conceptual_discussion() -> None:
    assert _overdrive_preflight_questions("介绍一下 RNA-seq 的基本流程") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("assignment_count", [0, 2, 5])
@legacy_preconfirmation_execution
async def test_overdrive_room_speech_sequence_and_persistence(
    monkeypatch, assignment_count: int
) -> None:
    candidates = [_agent(f"agent-{index}", f"专家{index}") for index in range(5)]
    _FakeAgentService.agents = candidates
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )

    manager_response = {
        "speech": "我先拆分任务。",
        "assignments": [
            {"agent_id": f"agent-{index}", "task": f"子任务 {index}"}
            for index in range(assignment_count)
        ],
    }
    llm_outputs = [str(manager_response).replace("'", '"')]
    if assignment_count:
        llm_outputs.append("汇总结论")

    async def fake_stream(**_kwargs):
        yield ChatChunk(type="text", content=llm_outputs.pop(0))

    monkeypatch.setattr(chat_module.provider_manager, "chat_stream", fake_stream)

    fanout_calls: list[list[dict[str, str]]] = []

    async def fake_fanout(self, *, tasks, **_kwargs):
        fanout_calls.append(tasks)
        return {
            "success": True,
            "llm_payload": {
                "results": [
                    {
                        "index": position,
                        "agent_id": task["agent_id"],
                        "status": "ok",
                        "answer": f"{task['agent_id']} 结论",
                    }
                    for position, task in enumerate(tasks, start=1)
                ]
            },
        }

    monkeypatch.setattr(
        "cygnusx.application.services.parallel_subagent_tool_service.ParallelSubAgentToolService.run_parallel_subagents",
        fake_fanout,
    )

    service = ChatService(MagicMock(spec=AsyncSession))
    persisted: list[dict] = []

    async def fake_add_message(_session, _role, content, **kwargs):
        persisted.append({"content": content, **kwargs})
        return SimpleNamespace(message_id=f"message-{len(persisted)}")

    service.add_message = fake_add_message  # type: ignore[method-assign]
    chunks = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user-1",
            session_id="session-1",
            user_content="请协作分析",
            manager_ctx=_manager_ctx(),
        )
    ]

    speeches = [chunk for chunk in chunks if chunk.type == "room_speech"]
    progress = [chunk for chunk in chunks if chunk.type == "overdrive_progress"]
    assert len(speeches) == (1 if not assignment_count else assignment_count * 2 + 2)
    assert progress
    assert speeches[0].metadata["sender"]["role"] == "manager"
    assert all(
        item["metadata"]["senderAgent"] == chunk.metadata["sender"]
        for item, chunk in zip(persisted, speeches, strict=True)
    )
    if assignment_count:
        assert len(fanout_calls) == (3 if assignment_count > 4 else 2)
        assert all(len(call) <= 4 for call in fanout_calls[:-1])
        assert [chunk.metadata["sender"]["role"] for chunk in speeches] == ["manager"] + [
            "worker"
        ] * (assignment_count * 2) + ["manager"]
        assert speeches[0].metadata["sender"]["name"] == "超频 Manager"
        assert all("交叉复核" in task["task"] for task in fanout_calls[-1])
    else:
        assert fanout_calls == []


@pytest.mark.asyncio
@legacy_preconfirmation_execution
async def test_overdrive_peer_review_shares_all_expert_conclusions(monkeypatch) -> None:
    _FakeAgentService.agents = [_agent("agent-a", "专家A"), _agent("agent-b", "专家B")]
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )
    outputs = iter(
        [
            '{"speech":"开始协作","assignments":[{"agent_id":"agent-a","task":"任务A"},{"agent_id":"agent-b","task":"任务B"}]}',
            "最终整合",
        ]
    )
    manager_prompts: list[str] = []

    async def fake_stream(**kwargs):
        manager_prompts.append(kwargs["messages"][0]["content"])
        yield ChatChunk(type="text", content=next(outputs))

    calls: list[list[dict[str, str]]] = []

    async def fake_fanout(self, *, tasks, **_kwargs):
        calls.append(tasks)
        answers = (
            ["A 初步结论", "B 初步结论"] if len(calls) == 1 else ["A 复核后结论", "B 复核后结论"]
        )
        return {
            "success": True,
            "llm_payload": {
                "results": [
                    {
                        "index": index,
                        "agent_id": task["agent_id"],
                        "status": "ok",
                        "answer": answers[index - 1],
                    }
                    for index, task in enumerate(tasks, start=1)
                ]
            },
        }

    monkeypatch.setattr(chat_module.provider_manager, "chat_stream", fake_stream)
    monkeypatch.setattr(
        "cygnusx.application.services.parallel_subagent_tool_service.ParallelSubAgentToolService.run_parallel_subagents",
        fake_fanout,
    )
    service = ChatService(MagicMock(spec=AsyncSession))
    service.add_message = AsyncMock(  # type: ignore[method-assign]
        side_effect=lambda *_args, **_kwargs: SimpleNamespace(message_id="message")
    )

    chunks = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user",
            session_id="session",
            user_content="跨领域协作",
            manager_ctx=_manager_ctx(),
        )
    ]

    assert len(calls) == 2
    for task in calls[1]:
        assert "A 初步结论" in task["task"]
        assert "B 初步结论" in task["task"]
    review_speeches = [
        chunk
        for chunk in chunks
        if chunk.type == "room_speech" and "交叉复核" in chunk.metadata["sender"]["name"]
    ]
    assert [chunk.content for chunk in review_speeches] == ["A 复核后结论", "B 复核后结论"]
    assert "A 复核后结论" in manager_prompts[-1]
    assert "B 复核后结论" in manager_prompts[-1]
    assert "A 初步结论" not in manager_prompts[-1]
    manager = [
        chunk
        for chunk in chunks
        if chunk.type == "room_speech" and chunk.metadata["sender"]["role"] == "manager"
    ][-1]
    assert manager.metadata["round"] == 3


@pytest.mark.asyncio
async def test_overdrive_excludes_non_spawnable_agents_from_manager_catalog(monkeypatch) -> None:
    _FakeAgentService.agents = [
        _agent("agent-ready", "可派生专家"),
        _agent("agent-disabled", "不可派生专家", spawnable=False),
    ]
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )

    async def fake_stream(**kwargs):
        assert "agent-ready" in kwargs["messages"][0]["content"]
        assert "agent-disabled" not in kwargs["messages"][0]["content"]
        yield ChatChunk(
            type="text",
            content='{"speech":"安排可用专家处理","assignments":[{"agent_id":"agent-disabled","task":"不应执行"}]}',
        )

    monkeypatch.setattr(chat_module.provider_manager, "chat_stream", fake_stream)
    service = ChatService(MagicMock(spec=AsyncSession))
    service.add_message = AsyncMock(return_value=SimpleNamespace(message_id="message"))  # type: ignore[method-assign]

    chunks = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user",
            session_id="session",
            user_content="协作",
            manager_ctx=_manager_ctx(),
        )
    ]

    assert [chunk.type for chunk in chunks if chunk.type == "room_speech"] == ["room_speech"]
    assert (
        next(chunk for chunk in chunks if chunk.type == "room_speech").metadata["sender"]["name"]
        == "超频 Manager"
    )


@pytest.mark.asyncio
async def test_overdrive_preflight_emits_manager_question_before_dispatch(monkeypatch) -> None:
    _FakeAgentService.agents = [_agent("agent-1", "专家1")]
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )

    async def should_not_call_model(**_kwargs):
        raise AssertionError("缺少关键上下文时应先由 Manager 发起 ask_user，而不是调用模型分派")
        yield ChatChunk(type="text", content="")

    monkeypatch.setattr(chat_module.provider_manager, "chat_stream", should_not_call_model)
    service = ChatService(MagicMock(spec=AsyncSession))
    service.add_message = AsyncMock(return_value=SimpleNamespace(message_id="message"))  # type: ignore[method-assign]

    chunks = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user",
            session_id="session",
            user_content="我现在有2个TP53分组，我要如何发现TP53相关的新颖发现，请写详细计划",
            manager_ctx=_manager_ctx(),
        )
    ]

    speeches = [chunk for chunk in chunks if chunk.type == "room_speech"]
    question_event = next(chunk for chunk in chunks if chunk.type == "ask_request")
    assert len(speeches) == 1
    assert speeches[0].metadata["sender"]["name"] == "超频 Manager"
    assert len(question_event.metadata["questions"]) == 3
    assert not any(chunk.type == "room_speech_delta" for chunk in chunks)


@pytest.mark.asyncio
async def test_tnpd_request_asks_for_real_phylogeny_inputs_before_freezing_plan(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        chat_module.OverdrivePlanningTelemetryService,
        "record",
        AsyncMock(),
    )
    _FakeAgentService.agents = [
        _agent("agent-general", "通用助手", category="general"),
        _agent("agent-code", "代码助手", category="code"),
        _agent("agent-viz", "可视化助手", category="visualization"),
    ]
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )

    async def should_not_call_model(**_kwargs):
        raise AssertionError("TnpD 输入尚未提供时不应生成或冻结执行计划")
        yield ChatChunk(type="text", content="")

    monkeypatch.setattr(chat_module.provider_manager, "chat_stream", should_not_call_model)
    session = SimpleNamespace(sandbox_meta={})
    service = ChatService(MagicMock(spec=AsyncSession))
    service.get_session = AsyncMock(return_value=session)  # type: ignore[method-assign]
    service.add_message = AsyncMock(return_value=SimpleNamespace(message_id="message"))  # type: ignore[method-assign]

    chunks = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user",
            session_id="session",
            user_content="我要将tnpd序列对比到20个基因组进行进化分析与建树",
            manager_ctx=_manager_ctx(),
        )
    ]

    question_event = next(chunk for chunk in chunks if chunk.type == "ask_request")
    manager_speech = next(chunk for chunk in chunks if chunk.type == "room_speech")
    questions = [item["question"] for item in question_event.metadata["questions"]]
    assert manager_speech.metadata["planning_mode"] == "rule_preflight"
    assert any("序列类型" in question for question in questions)
    assert any("20 个基因组" in question for question in questions)
    assert not any("数据属于哪种模态" in question for question in questions)
    assert not any(
        chunk.type == "ask_request" and chunk.metadata.get("kind") == "plan_confirmation"
        for chunk in chunks
    )
    assert session.sandbox_meta["overdrive_intake"]["root_request"].startswith("我要将tnpd")


@pytest.mark.asyncio
async def test_tnpd_invalid_manager_plan_repairs_then_rule_merges_authoritative_dag(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        chat_module.OverdrivePlanningTelemetryService,
        "record",
        AsyncMock(),
    )
    _FakeAgentService.agents = [
        _agent("agent-general", "通用助手", category="general"),
        _agent("agent-code", "代码助手", category="code"),
        _agent("agent-viz", "可视化助手", category="visualization"),
    ]
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )
    monkeypatch.setattr(
        _FakeAgentService,
        "assemble_context",
        AsyncMock(return_value=None),
        raising=False,
    )

    manager_calls = 0

    async def fake_stream(**_kwargs):
        nonlocal manager_calls
        manager_calls += 1
        yield ChatChunk(
            type="text",
            content=(
                '{"speech":"交给通用助手处理","assignments":['
                '{"task_id":"general-intake","agent_id":"agent-general",'
                '"task":"只询问用户，不制定领域计划"}]}'
            ),
        )

    run = SimpleNamespace(
        run_id="overdrive:tnpd",
        status="RECEIVED",
        research={},
        plan={},
        control={},
        lead_planner_agent_id="agent-code",
    )
    monkeypatch.setattr(chat_module.provider_manager, "chat_stream", fake_stream)
    monkeypatch.setattr(
        "cygnusx.application.services.overdrive_run_service.OverdriveRunService.get_active_for_session",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "cygnusx.application.services.overdrive_run_service.OverdriveRunService.create_run",
        AsyncMock(return_value=run),
    )
    captured: dict[str, object] = {}

    class FakePlanningService:
        def __init__(self, _run_service, _research_service, plan_builder):
            self.plan_builder = plan_builder

        async def prepare_plan(self, *_args, **_kwargs):
            plan = self.plan_builder()
            captured["tasks"] = plan["tasks"]
            run.research = {
                source: {"status": "completed", "evidence_ids": []}
                for source in ("knowledge_base", "web", "model_knowledge")
            }
            return {
                "path": "output/overdrive/session/overdrive-tnpd/plan.v1.md",
                "version": 1,
                "hash": f"sha256:{'b' * 64}",
                "summary": plan["summary"],
            }

    monkeypatch.setattr(chat_module, "OverdrivePlanningService", FakePlanningService)
    session = chat_module.ChatSessionModel(
        session_id="session",
        user_id="user",
        model_id=chat_module.uuid.uuid4(),
        sandbox_meta={},
        project_id=None,
        mode="chat",
    )
    monkeypatch.setattr(
        chat_module,
        "execute_studio_tool",
        AsyncMock(return_value={
            "success": True,
            "result": {"llm_payload": {"entries": []}, "ui_payload": {"entries": []}},
        }),
    )
    service = ChatService(MagicMock(spec=AsyncSession))
    service.get_session = AsyncMock(return_value=session)  # type: ignore[method-assign]
    service.add_message = AsyncMock(return_value=SimpleNamespace(message_id="message"))  # type: ignore[method-assign]
    service._commit_stream_anchor = AsyncMock()  # type: ignore[method-assign]

    chunks = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user",
            session_id="session",
            user_content=(
                "我要将 TnpD 蛋白质序列对比到20个基因组进行进化分析与建树；"
                "已上传 query.faa、20个基因组 FASTA/GFF，将用 DIAMOND 检索同源序列。"
            ),
            manager_ctx=_manager_ctx(),
        )
    ]

    tasks = captured["tasks"]
    assert isinstance(tasks, list)
    assert [task["task_id"] for task in tasks] == [
        "tnpd-homolog-search",
        "tnpd-phylogeny",
        "general-intake",
    ]
    assert tasks[1]["depends_on"] == ["tnpd-homolog-search"]
    assert manager_calls == 2
    manager_speech = next(chunk for chunk in chunks if chunk.type == "room_speech")
    assert manager_speech.metadata["planning_mode"] == "rule_merge"
    assert manager_speech.metadata["repair_attempted"] is True
    assert "固定执行链" not in manager_speech.content
    assert any(
        chunk.type == "ask_request" and chunk.metadata.get("kind") == "plan_confirmation"
        for chunk in chunks
    )
    assert session.mode == "studio"
    assert any(chunk.type == "studio_promoted" for chunk in chunks)
    planning_tools = [
        chunk for chunk in chunks
        if chunk.type == "tool_call" and chunk.metadata.get("tool_name") in {"workspace_list", "sandbox_execute"}
    ]
    assert [chunk.metadata["tool_name"] for chunk in planning_tools] == [
        "workspace_list",
        "sandbox_execute",
    ]
    assert all(chunk.metadata.get("mcp_server") == "studio" for chunk in planning_tools)


@pytest.mark.asyncio
async def test_overdrive_manager_failure_uses_honest_neutral_fallback(monkeypatch) -> None:
    _FakeAgentService.agents = [_agent("agent-general", "通用助手", category="general")]
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )
    monkeypatch.setattr(
        chat_module.OverdrivePlanningTelemetryService,
        "record",
        AsyncMock(),
    )

    async def failed_stream(**_kwargs):
        raise RuntimeError("provider unavailable")
        yield ChatChunk(type="text", content="")

    monkeypatch.setattr(chat_module.provider_manager, "chat_stream", failed_stream)
    service = ChatService(MagicMock(spec=AsyncSession))
    service.get_session = AsyncMock(return_value=SimpleNamespace(sandbox_meta={}))  # type: ignore[method-assign]
    service.add_message = AsyncMock(return_value=SimpleNamespace(message_id="message"))  # type: ignore[method-assign]

    chunks = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user",
            session_id="session",
            user_content="你好",
            manager_ctx=_manager_ctx(),
        )
    ]

    manager_speech = next(chunk for chunk in chunks if chunk.type == "room_speech")
    assert manager_speech.content == "Manager 暂时不可用，暂未生成执行计划，请稍后重试。"
    assert manager_speech.metadata["planning_mode"] == "rule_merge"
    assert manager_speech.metadata["repair_attempted"] is False


@pytest.mark.asyncio
async def test_overdrive_preflight_is_generated_by_manager_and_persists_intake(monkeypatch) -> None:
    _FakeAgentService.agents = [
        _agent("agent-general", "通用助手"),
        _agent("agent-scrna", "单细胞专家"),
    ]
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )

    manager_prompts: list[str] = []

    async def fake_stream(**kwargs):
        manager_prompts.append(kwargs["messages"][0]["content"])
        yield ChatChunk(
            type="text",
            content=(
                '{"speech":"先确认数据来源和讨论目标，避免错误选择单细胞分析路线。",'
                '"questions":[{"question":"这次希望基于真实数据执行，还是先讨论 TP53 '
                '小鼠肺癌单细胞的分析方案？","options":["先讨论方法与分析路线",'
                '"我会上传/引用数据后执行"]}],"assignments":[]}'
            ),
        )

    async def fake_fanout(self, **kwargs):
        raise AssertionError("预检问题不应被包装成 general-intake 执行任务")

    session = SimpleNamespace(sandbox_meta={})
    monkeypatch.setattr(chat_module.provider_manager, "chat_stream", fake_stream)
    monkeypatch.setattr(
        "cygnusx.application.services.parallel_subagent_tool_service.ParallelSubAgentToolService.run_parallel_subagents",
        fake_fanout,
    )
    service = ChatService(MagicMock(spec=AsyncSession))
    service.get_session = AsyncMock(return_value=session)  # type: ignore[method-assign]
    service.add_message = AsyncMock(return_value=SimpleNamespace(message_id="message"))  # type: ignore[method-assign]

    chunks = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user",
            session_id="session",
            user_content="我有两个 TP53 分组，想挖掘新颖发现，请写详细计划",
            manager_ctx=_manager_ctx(),
        )
    ]

    assert session.sandbox_meta["overdrive_intake"]["status"] == "awaiting_input"
    manager_speech = next(chunk for chunk in chunks if chunk.type == "room_speech")
    assert manager_speech.content == "先确认数据来源和讨论目标，避免错误选择单细胞分析路线。"
    assert manager_speech.metadata["planning_mode"] == "llm"
    ask_request = next(chunk for chunk in chunks if chunk.type == "ask_request")
    assert ask_request.metadata["questions"][0]["question"].startswith("这次希望基于真实数据执行")
    assert manager_prompts and "我有两个 TP53 分组" in manager_prompts[0]
    assert not any(chunk.type == "plan_confirmation" for chunk in chunks)


@pytest.mark.asyncio
async def test_overdrive_preflight_uses_safe_fallback_when_manager_omits_questions(monkeypatch) -> None:
    _FakeAgentService.agents = [_agent("agent-general", "通用助手")]
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )

    async def invalid_preflight_stream(**_kwargs):
        yield ChatChunk(
            type="text",
            content='{"speech":"我会直接开始分析。","questions":[],"assignments":[]}',
        )

    session = SimpleNamespace(sandbox_meta={})
    monkeypatch.setattr(chat_module.provider_manager, "chat_stream", invalid_preflight_stream)
    service = ChatService(MagicMock(spec=AsyncSession))
    service.get_session = AsyncMock(return_value=session)  # type: ignore[method-assign]
    service.add_message = AsyncMock(return_value=SimpleNamespace(message_id="message"))  # type: ignore[method-assign]

    chunks = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user",
            session_id="session",
            user_content="帮我做一下 RNA-seq 分析",
            manager_ctx=_manager_ctx(),
        )
    ]

    manager_speech = next(chunk for chunk in chunks if chunk.type == "room_speech")
    assert manager_speech.metadata["planning_mode"] == "rule_preflight"
    ask_request = next(chunk for chunk in chunks if chunk.type == "ask_request")
    assert "真实输入" in ask_request.metadata["questions"][0]["question"]


@pytest.mark.asyncio
@legacy_preconfirmation_execution
async def test_overdrive_resumes_pending_intake_with_original_and_user_answer(monkeypatch) -> None:
    _FakeAgentService.agents = [
        _agent("agent-general", "通用助手"),
        _agent("agent-rnaseq", "RNA专家"),
    ]
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )
    session = SimpleNamespace(
        sandbox_meta={
            "overdrive_intake": {
                "status": "awaiting_input",
                "original_request": "我有两个 TP53 分组，想挖掘新颖发现，请写详细计划",
            }
        }
    )
    seen_prompt = ""

    manager_outputs = iter(
        [
            '{"speech":"信息已补全","assignments":[]}',
            "已基于补充信息形成分析方案。",
        ]
    )

    async def fake_stream(**kwargs):
        nonlocal seen_prompt
        seen_prompt = kwargs["messages"][0]["content"]
        yield ChatChunk(type="text", content=next(manager_outputs))

    async def fake_fanout(self, *, tasks, **_kwargs):
        return {
            "success": True,
            "llm_payload": {
                "results": [
                    {
                        "index": index,
                        "agent_id": task["agent_id"],
                        "status": "ok",
                        "answer": f"{task['agent_id']} 默认调度结论",
                    }
                    for index, task in enumerate(tasks, start=1)
                ]
            },
        }

    monkeypatch.setattr(chat_module.provider_manager, "chat_stream", fake_stream)
    monkeypatch.setattr(
        "cygnusx.application.services.parallel_subagent_tool_service.ParallelSubAgentToolService.run_parallel_subagents",
        fake_fanout,
    )
    service = ChatService(MagicMock(spec=AsyncSession))
    service.get_session = AsyncMock(return_value=session)  # type: ignore[method-assign]
    service.add_message = AsyncMock(return_value=SimpleNamespace(message_id="message"))  # type: ignore[method-assign]

    chunks = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user",
            session_id="session",
            user_content="bulk RNA-seq，TP53 突变 vs 野生型，每组 30 个样本，已有 count 矩阵",
            manager_ctx=_manager_ctx(),
        )
    ]

    assert "原始请求" in seen_prompt and "用户补充信息" in seen_prompt
    assert "TP53 突变 vs 野生型" in seen_prompt
    assert "overdrive_intake" not in session.sandbox_meta
    followup = [chunk for chunk in chunks if chunk.type == "ask_request"]
    assert len(followup) == 1
    assert "保存" in followup[0].metadata["questions"][0]["question"]
    assert "数据" in followup[0].metadata["questions"][1]["question"]


@pytest.mark.asyncio
@legacy_preconfirmation_execution
async def test_overdrive_tree_intake_keeps_root_slots_and_dispatches_visualization_only(
    monkeypatch,
) -> None:
    _FakeAgentService.agents = [
        _agent("agent-general", "通用助手", category="general"),
        _agent("agent-code", "代码助手", category="code"),
        _agent("agent-viz", "可视化助手", category="visualization"),
    ]
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )
    session = SimpleNamespace(sandbox_meta={})
    manager_prompts: list[str] = []
    manager_outputs = iter(
        [
            json.dumps(
                {
                    "speech": "需要先确认任务类型。",
                    "questions": [
                        {
                            "question": "您的核心需求是从头构建，还是处理/美化已有树？",
                            "options": ["从头构建", "处理/美化已有树"],
                        },
                        {"question": "如果从头建树，是否已经完成 MSA？", "options": []},
                    ],
                    "assignments": [],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "speech": "安排通用、代码和可视化助手处理。",
                    "questions": [{"question": "蛋白质序列是否已经完成 MSA？", "options": []}],
                    "assignments": [
                        {
                            "task_id": "plan",
                            "agent_id": "agent-general",
                            "task": "制定树处理计划",
                        },
                        {
                            "task_id": "code",
                            "agent_id": "agent-code",
                            "task": "编写树解析代码",
                        },
                        {
                            "task_id": "viz",
                            "agent_id": "agent-viz",
                            "task": "生成系统发育树图表",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            "已完成已有系统发育树的美化与注释方案。",
        ]
    )

    async def fake_stream(**kwargs):
        manager_prompts.append(kwargs["messages"][0]["content"])
        yield ChatChunk(type="text", content=next(manager_outputs))

    fanout_calls: list[list[dict[str, object]]] = []

    async def fake_fanout(self, *, tasks, **_kwargs):
        fanout_calls.append(tasks)
        return {
            "success": True,
            "llm_payload": {
                "results": [
                    {
                        "index": 1,
                        "agent_id": tasks[0]["agent_id"],
                        "status": "ok",
                        "answer": "已验证 treefile 并生成出版级树图。",
                    }
                ]
            },
        }

    monkeypatch.setattr(chat_module.provider_manager, "chat_stream", fake_stream)
    monkeypatch.setattr(
        "cygnusx.application.services.parallel_subagent_tool_service.ParallelSubAgentToolService.run_parallel_subagents",
        fake_fanout,
    )
    service = ChatService(MagicMock(spec=AsyncSession))
    service.get_session = AsyncMock(return_value=session)  # type: ignore[method-assign]
    service.add_message = AsyncMock(return_value=SimpleNamespace(message_id="message"))  # type: ignore[method-assign]

    first_turn = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user",
            session_id="session",
            user_content="帮我构建一下这个系统发育树，输入是 treefile 文件",
            manager_ctx=_manager_ctx(),
        )
    ]

    first_questions = next(chunk for chunk in first_turn if chunk.type == "ask_request")
    assert len(first_questions.metadata["questions"]) == 1
    intake = session.sandbox_meta["overdrive_intake"]
    assert intake["root_request"] == "帮我构建一下这个系统发育树，输入是 treefile 文件"
    assert intake["slots"] == {"input_format": "treefile"}

    second_turn = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user",
            session_id="session",
            user_content="处理/美化已有树（我有 Newick 树文件）",
            manager_ctx=_manager_ctx(),
        )
    ]

    assert "overdrive_intake" not in session.sandbox_meta
    assert len(fanout_calls) == 1
    assert [task["agent_id"] for task in fanout_calls[0]] == ["agent-viz"]
    assert manager_prompts[1].count("原始请求：") == 1
    assert '"task_type": "tree_visualization"' in manager_prompts[1]
    assert not any(chunk.type == "ask_request" for chunk in second_turn)


@pytest.mark.asyncio
async def test_tp53_ambiguous_request_reaches_frozen_plan_after_intake(monkeypatch) -> None:
    """完整旅程：Manager intake → 用户补充 → 冻结计划确认。"""
    _FakeAgentService.agents = [
        _agent("agent-general", "通用助手"),
        _agent("agent-rnaseq", "RNA-seq 专家"),
        _agent("agent-viz", "可视化专家"),
    ]
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )
    session = SimpleNamespace(sandbox_meta={})
    manager_prompts: list[str] = []
    manager_outputs = iter(
        [
            (
                '{"speech":"先确认数据类型与分析边界，避免错误制定研究路线。",'
                '"questions":[{"question":"这是先讨论方法，还是基于已准备数据执行？",'
                '"options":["先讨论方法与分析路线","上传数据后执行"]}],"assignments":[]}'
            ),
            (
                '{"speech":"信息已补全，开始分派。","assignments":['
                '{"agent_id":"agent-rnaseq","task":"设计 bulk RNA-seq TP53 比较与新颖性分析"},'
                '{"agent_id":"agent-viz","task":"设计结果展示与证据图谱"}]}'
            ),
        ]
    )

    async def fake_stream(**kwargs):
        manager_prompts.append(kwargs["messages"][0]["content"])
        yield ChatChunk(
            type="text",
            content=next(manager_outputs),
        )

    active_run_calls = 0

    def fake_active_run(*_args, **_kwargs):
        nonlocal active_run_calls
        active_run_calls += 1
        if active_run_calls < 3:
            return None
        return SimpleNamespace(
            status="AWAITING_PLAN_CONFIRMATION",
            run_id="overdrive:tp53",
            control={},
            plan={
                "path": "output/overdrive/session/overdrive-tp53/plan.v1.md",
                "version": 1,
                "hash": f"sha256:{'a' * 64}",
                "summary": {"title": "TP53 执行计划"},
            },
        )

    monkeypatch.setattr(chat_module.provider_manager, "chat_stream", fake_stream)
    monkeypatch.setattr(
        "cygnusx.application.services.overdrive_run_service.OverdriveRunService.get_active_for_session",
        fake_active_run,
    )
    service = ChatService(MagicMock(spec=AsyncSession))
    service.get_session = AsyncMock(return_value=session)  # type: ignore[method-assign]
    service.add_message = AsyncMock(  # type: ignore[method-assign]
        side_effect=lambda *_args, **_kwargs: SimpleNamespace(message_id="message")
    )

    first_turn = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user",
            session_id="session",
            user_content="我有两个 TP53 分组，想挖掘新颖发现，请写详细计划",
            manager_ctx=_manager_ctx(),
        )
    ]

    assert any(chunk.type == "ask_request" for chunk in first_turn)
    assert session.sandbox_meta["overdrive_intake"]["status"] == "awaiting_input"
    assert len(manager_prompts) == 1
    assert "我有两个 TP53 分组" in manager_prompts[0]

    second_turn = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user",
            session_id="session",
            user_content="bulk RNA-seq；TP53 突变 vs 野生型；每组 30 例；已有 count 矩阵和临床信息",
            manager_ctx=_manager_ctx(),
        )
    ]

    assert "overdrive_intake" not in session.sandbox_meta
    assert "原始请求" in manager_prompts[1]
    assert "bulk RNA-seq" in manager_prompts[1]
    confirmation = next(
        chunk
        for chunk in second_turn
        if chunk.type == "ask_request" and chunk.metadata.get("kind") == "plan_confirmation"
    )
    assert confirmation.metadata["run_id"] == "overdrive:tp53"
    assert confirmation.metadata["summary"]["title"] == "TP53 执行计划"


@pytest.mark.asyncio
@legacy_preconfirmation_execution
async def test_overdrive_worker_failure_becomes_room_speech(monkeypatch) -> None:
    _FakeAgentService.agents = [_agent("agent-1", "专家1"), _agent("agent-2", "专家2")]
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )

    responses = iter(
        [
            '{"speech":"开始分工","assignments":[{"agent_id":"agent-1","task":"A"},{"agent_id":"agent-2","task":"B"}]}',
            "最终汇总",
        ]
    )

    async def fake_stream(**_kwargs):
        yield ChatChunk(type="text", content=next(responses))

    async def fake_fanout(self, **_kwargs):
        return {
            "success": True,
            "llm_payload": {
                "results": [
                    {"index": 1, "agent_id": "agent-1", "status": "failed", "error": "模型不可用"},
                    {"index": 2, "agent_id": "agent-2", "status": "ok", "answer": "正常结论"},
                ]
            },
        }

    monkeypatch.setattr(chat_module.provider_manager, "chat_stream", fake_stream)
    monkeypatch.setattr(
        "cygnusx.application.services.parallel_subagent_tool_service.ParallelSubAgentToolService.run_parallel_subagents",
        fake_fanout,
    )

    service = ChatService(MagicMock(spec=AsyncSession))

    async def fake_add_message(_session, _role, _content, **_kwargs):
        return SimpleNamespace(message_id="message")

    service.add_message = fake_add_message  # type: ignore[method-assign]
    chunks = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user",
            session_id="session",
            user_content="协作",
            manager_ctx=_manager_ctx(),
        )
    ]

    worker = next(
        chunk
        for chunk in chunks
        if chunk.type == "room_speech" and chunk.metadata["sender"]["role"] == "worker"
    )
    assert "子任务执行失败：模型不可用" in worker.content


@pytest.mark.asyncio
@legacy_preconfirmation_execution
async def test_overdrive_same_agent_clones_run_independent_tasks(monkeypatch) -> None:
    """同一专家可被指派多个独立子任务（分身并行）：结果按下标对齐，身份以 #n 区分。"""
    _FakeAgentService.agents = [_agent("agent-1", "专家1")]
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )

    responses = iter(
        [
            '{"speech":"拆成两个分身","assignments":[{"agent_id":"agent-1","task":"任务A"},{"agent_id":"agent-1","task":"任务B"}]}',
            "最终汇总",
        ]
    )

    async def fake_stream(**_kwargs):
        yield ChatChunk(type="text", content=next(responses))

    async def fake_fanout(self, *, tasks, **_kwargs):
        assert [task["agent_id"] for task in tasks] == ["agent-1", "agent-1"]
        return {
            "success": True,
            "llm_payload": {
                "results": [
                    {"index": 1, "agent_id": "agent-1", "status": "ok", "answer": "A 结论"},
                    {"index": 2, "agent_id": "agent-1", "status": "ok", "answer": "B 结论"},
                ]
            },
        }

    monkeypatch.setattr(chat_module.provider_manager, "chat_stream", fake_stream)
    monkeypatch.setattr(
        "cygnusx.application.services.parallel_subagent_tool_service.ParallelSubAgentToolService.run_parallel_subagents",
        fake_fanout,
    )

    service = ChatService(MagicMock(spec=AsyncSession))

    async def fake_add_message(_session, _role, _content, **_kwargs):
        return SimpleNamespace(message_id="message")

    service.add_message = fake_add_message  # type: ignore[method-assign]
    chunks = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user",
            session_id="session",
            user_content="协作",
            manager_ctx=_manager_ctx(),
        )
    ]

    speeches = [chunk for chunk in chunks if chunk.type == "room_speech"]
    assert [chunk.metadata["sender"]["role"] for chunk in speeches] == [
        "manager",
        "worker",
        "worker",
        "manager",
    ]
    assert speeches[1].metadata["sender"]["name"] == "专家1 #1"
    assert speeches[1].content == "A 结论"
    assert speeches[2].metadata["sender"]["name"] == "专家1 #2"
    assert speeches[2].content == "B 结论"


def test_overdrive_turn_has_no_external_room_side_effects() -> None:
    source = inspect.getsource(ChatService._run_overdrive_turn)

    assert "AgentTeamsRoomGatewayService" not in source
    assert "matrix_room_id" not in source
    assert "element_room_url" not in source


def test_chat_api_no_longer_exposes_matrix_room_event_stream() -> None:
    import cygnusx.api.v1.chat as chat_api

    assert "/sessions/{session_id}/room-events" not in {
        route.path for route in chat_api.router.routes
    }


@pytest.mark.asyncio
@legacy_preconfirmation_execution
async def test_overdrive_does_not_repeat_worker_request_for_user_input(monkeypatch) -> None:
    _FakeAgentService.agents = [_agent("agent-1", "专家1")]
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )

    manager_calls = 0

    async def fake_stream(**_kwargs):
        nonlocal manager_calls
        manager_calls += 1
        yield ChatChunk(
            type="text",
            content='{"speech":"我先请专家确认数据类型。","assignments":[{"agent_id":"agent-1","task":"确认分析输入"}]}',
        )

    async def fake_fanout(self, **_kwargs):
        return {
            "success": True,
            "llm_payload": {
                "results": [
                    {
                        "index": 1,
                        "agent_id": "agent-1",
                        "status": "awaiting_input",
                        "answer": "请补充数据类型：Bulk RNA-seq 还是单细胞 RNA-seq？",
                        "packet": {
                            "status": "awaiting_input",
                            "final_answer": "",
                            "needs_user_input": True,
                            "questions": [
                                {
                                    "question": "请选择数据类型",
                                    "options": ["Bulk RNA-seq", "单细胞 RNA-seq"],
                                }
                            ],
                            "approval_requests": [],
                            "error": "",
                        },
                    }
                ]
            },
        }

    monkeypatch.setattr(chat_module.provider_manager, "chat_stream", fake_stream)
    monkeypatch.setattr(
        "cygnusx.application.services.parallel_subagent_tool_service.ParallelSubAgentToolService.run_parallel_subagents",
        fake_fanout,
    )
    service = ChatService(MagicMock(spec=AsyncSession))
    service.add_message = AsyncMock(return_value=SimpleNamespace(message_id="message"))  # type: ignore[method-assign]

    chunks = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user",
            session_id="session",
            user_content="做 RNA-seq",
            manager_ctx=_manager_ctx(),
        )
    ]

    speeches = [chunk for chunk in chunks if chunk.type == "room_speech"]
    assert [chunk.metadata["sender"]["role"] for chunk in speeches] == ["manager", "worker"]
    assert manager_calls == 1
    worker = speeches[-1]
    assert worker.metadata["task_status"] == "awaiting_input"
    assert worker.metadata.get("error_summary", "") == ""
    assert any(chunk.type == "ask_request" for chunk in chunks)
    assert not any(
        task.get("status") == "failed"
        for chunk in chunks
        if chunk.type == "overdrive_progress"
        for task in chunk.metadata.get("tasks", [])
    )
    assert any(
        chunk.type == "overdrive_progress" and chunk.metadata["phase"] == "awaiting_input"
        for chunk in chunks
    )


@pytest.mark.asyncio
@legacy_preconfirmation_execution
async def test_overdrive_persists_approval_and_skips_manager_summary(monkeypatch) -> None:
    _FakeAgentService.agents = [_agent("agent-1", "专家1")]
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )

    calls = 0

    async def fake_stream(**_kwargs):
        nonlocal calls
        calls += 1
        yield ChatChunk(
            type="text",
            content='{"speech":"我让专家准备提交。","assignments":[{"agent_id":"agent-1","task":"提交任务"}]}',
        )

    async def fake_fanout(self, **_kwargs):
        return {
            "success": True,
            "llm_payload": {
                "results": [
                    {
                        "index": 1,
                        "agent_id": "agent-1",
                        "status": "approval_pending",
                        "packet": {
                            "final_answer": "",
                            "needs_user_input": False,
                            "approval_requests": [
                                {"tool_name": "danger_tool", "arguments": {"sample": "S1"}}
                            ],
                        },
                    }
                ]
            },
        }

    monkeypatch.setattr(chat_module.provider_manager, "chat_stream", fake_stream)
    monkeypatch.setattr(
        "cygnusx.application.services.parallel_subagent_tool_service.ParallelSubAgentToolService.run_parallel_subagents",
        fake_fanout,
    )
    db = MagicMock(spec=AsyncSession)
    db.flush = AsyncMock()
    service = ChatService(db)
    session = SimpleNamespace(sandbox_meta={}, agent_id="manager")
    service.get_session = AsyncMock(return_value=session)  # type: ignore[method-assign]
    service.add_message = AsyncMock(return_value=SimpleNamespace(message_id="message"))  # type: ignore[method-assign]

    chunks = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user", session_id="session", user_content="提交", manager_ctx=_manager_ctx()
        )
    ]

    approval_events = [chunk for chunk in chunks if chunk.type == "overdrive_approval_request"]
    assert len(approval_events) == 1
    assert approval_events[0].metadata["approval"]["tool_name"] == "danger_tool"
    assert session.sandbox_meta["overdrive_approvals"][0]["status"] == "pending"
    assert calls == 1


@pytest.mark.asyncio
async def test_approve_overdrive_approval_executes_original_call_once(monkeypatch) -> None:
    db = MagicMock(spec=AsyncSession)
    db.flush = AsyncMock()
    service = ChatService(db)
    approval = {
        "approval_id": "overdrive-approval:1",
        "run_id": "overdrive:1",
        "task_id": "agentteams:overdrive:1:1",
        "manager_agent_id": "manager",
        "worker_agent_id": "worker",
        "tool_name": "danger_tool",
        "arguments": {"sample": "S1"},
        "status": "pending",
    }
    session = SimpleNamespace(sandbox_meta={"overdrive_approvals": [approval]}, agent_id="manager")
    service.get_session = AsyncMock(return_value=session)  # type: ignore[method-assign]

    bridge = SimpleNamespace(
        execute=AsyncMock(return_value={"success": True, "llm_payload": {"summary": "submitted"}})
    )
    monkeypatch.setattr(
        "cygnusx.application.services.tool_bridge_service.get_tool_bridge_service", lambda: bridge
    )

    resolved = await service.approve_overdrive_approval(
        session_id="session", user_id="user", approval_id="overdrive-approval:1"
    )

    assert resolved["status"] == "completed"
    assert bridge.execute.await_count == 1
    assert bridge.execute.await_args.kwargs["arguments"] == {"sample": "S1", "_confirmed": True}


@pytest.mark.asyncio
async def test_manager_planning_streams_reasoning_as_thought_delta(monkeypatch) -> None:
    """规划阶段 Manager 的思考过程必须以 is_reasoning delta 流式下发,且不混入计划 JSON。"""
    _FakeAgentService.agents = [
        _agent("agent-general", "通用助手", category="general"),
        _agent("agent-code", "代码助手", category="code"),
    ]
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )
    plan_json = (
        '{"speech":"按依赖顺序执行。","assignments":['
        '{"task_id":"code","agent_id":"agent-code","task":"形成代码设计","depends_on":[]}'
        "]}"
    )

    async def fake_stream(**_kwargs):
        yield ChatChunk(
            type="text", content="思考中:需要先明确分组。", metadata={"is_reasoning": True}
        )
        yield ChatChunk(type="text", content=plan_json)

    run = SimpleNamespace(
        run_id="overdrive:thought",
        status="RECEIVED",
        research={},
        plan={},
        control={},
        lead_planner_agent_id="agent-code",
    )
    monkeypatch.setattr(chat_module.provider_manager, "chat_stream", fake_stream)
    monkeypatch.setattr(
        "cygnusx.application.services.overdrive_run_service.OverdriveRunService.get_active_for_session",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "cygnusx.application.services.overdrive_run_service.OverdriveRunService.create_run",
        AsyncMock(return_value=run),
    )

    class FakePlanningService:
        def __init__(self, _run_service, _research_service, plan_builder):
            self.plan_builder = plan_builder

        async def prepare_plan(self, *_args, **_kwargs):
            plan = self.plan_builder()
            return {
                "path": "output/overdrive/session/overdrive-thought/plan.v1.md",
                "version": 1,
                "hash": f"sha256:{'c' * 64}",
                "summary": plan["summary"],
            }

    monkeypatch.setattr(chat_module, "OverdrivePlanningService", FakePlanningService)
    session = chat_module.ChatSessionModel(
        session_id="session",
        user_id="user",
        model_id=chat_module.uuid.uuid4(),
        sandbox_meta={},
        project_id=None,
        mode="chat",
    )
    monkeypatch.setattr(
        chat_module,
        "execute_studio_tool",
        AsyncMock(return_value={
            "success": True,
            "result": {"llm_payload": {"entries": []}, "ui_payload": {"entries": []}},
        }),
    )
    service = ChatService(MagicMock(spec=AsyncSession))
    service.get_session = AsyncMock(return_value=session)  # type: ignore[method-assign]
    service.add_message = AsyncMock(return_value=SimpleNamespace(message_id="message"))  # type: ignore[method-assign]
    service._commit_stream_anchor = AsyncMock()  # type: ignore[method-assign]

    chunks = [
        chunk
        async for chunk in service._run_overdrive_turn(
            user_id="user",
            session_id="session",
            user_content=(
                "我要对 TP53 敲除的 10 个小鼠样本做单细胞差异表达分析；"
                "已有 count 表达矩阵，请用代码实现。"
            ),
            manager_ctx=_manager_ctx(),
            deep_thinking=True,
        )
    ]

    thought_deltas = [
        chunk
        for chunk in chunks
        if chunk.type == "room_speech_delta"
        and chunk.metadata.get("worker_key") == "manager-plan"
    ]
    assert [chunk.content for chunk in thought_deltas] == ["思考中:需要先明确分组。"]
    assert thought_deltas[0].metadata["is_reasoning"] is True
    assert thought_deltas[0].metadata["sender"]["role"] == "manager"

    plan_speech = next(
        chunk
        for chunk in chunks
        if chunk.type == "room_speech" and chunk.metadata.get("worker_key") == "manager-plan"
    )
    assert plan_speech.content == "按依赖顺序执行。"
    assert plan_speech.metadata["thought"] == "思考中:需要先明确分组。"
    assert "思考中" not in plan_speech.content
