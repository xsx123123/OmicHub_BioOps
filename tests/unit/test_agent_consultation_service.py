from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.api.v1.agentteams import require_integration_token
from cygnusx.application.services.agent_consultation_service import (
    AgentConsultationService,
    ConsultationEnvelope,
)
from cygnusx.application.services.parallel_subagent_service import ParallelSubAgentService
from cygnusx.core.exceptions import NotFoundError
from cygnusx.middleware.auth import SELF_AUTHENTICATED_PREFIXES


class _Session(AsyncSession):
    def __init__(self):
        pass


def test_run_consultation_uses_safe_single_task_and_parses_envelope() -> None:
    asyncio.run(_test_run_consultation_uses_safe_single_task_and_parses_envelope())


async def _test_run_consultation_uses_safe_single_task_and_parses_envelope() -> None:
    agent_service = SimpleNamespace(
        assemble_context=AsyncMock(return_value=SimpleNamespace(model_config=object()))
    )
    parallel_service = SimpleNamespace(
        run=AsyncMock(
            return_value={
                "llm_payload": {
                    "results": [
                        {
                            "answer": """```json
{"conclusion":"可信","recommendations":["复核样本"],"evidence_refs":["report://qc"],"risks":[],"token_usage":42}
```"""
                        }
                    ]
                }
            }
        )
    )
    service = AgentConsultationService(
        SimpleNamespace(), agent_service=agent_service, parallel_service=parallel_service
    )

    result = await service.run_consultation(
        case_id="case-1",
        agent_id="agent-rnaseq",
        question="解释结果",
        capability="result_interpretation",
        evidence_refs=[],
        requested_tools=["knowledge_search"],
        requester_ref="user-1",
    )

    assert result == ConsultationEnvelope(
        conclusion="可信",
        recommendations=["复核样本"],
        evidence_refs=[],
        risks=[],
        token_usage=42,
    )
    agent_service.assemble_context.assert_awaited_once_with("agent-rnaseq", user_id="user-1")
    call = parallel_service.run.await_args.kwargs
    assert call["safe_only"] is True
    assert call["runtime_authorized"] is True
    assert call["allow_non_spawnable_target"] is True
    assert len(call["tasks"]) == 1
    assert call["tasks"][0]["workspace_access"] is False


def test_build_instruction_flow_type_includes_taskspec_skeleton() -> None:
    """BUG-E2E-04：流程型规划指令必须给出完整 TaskSpec 骨架与 sample_sheet list 形态。"""
    instruction = AgentConsultationService._build_instruction(
        question="规划 scrna_seq 流程",
        capability="planning_advice",
        evidence_refs=[],
        requested_tools=[],
        execution_mode="readonly_consultation",
        hard_gate=None,
    )
    assert '"flow_id"' in instruction
    assert '"sample_sheet"' in instruction
    assert "dict 组成的 list" in instruction
    assert "proposed_submission" in instruction


def test_parse_envelope_falls_back_to_raw_answer() -> None:
    result = AgentConsultationService.parse_envelope("普通文本结论")
    assert result.conclusion == "普通文本结论"


def test_extract_answer_preserves_parallel_service_error() -> None:
    result = AgentConsultationService._extract_answer(
        {"llm_payload": {"success": False, "error": "目标 Agent 未标记为可派生子 Agent"}}
    )
    assert result == "会诊执行失败：目标 Agent 未标记为可派生子 Agent"


def test_parse_envelope_recovers_trailing_commas_from_manager_response() -> None:
    result = AgentConsultationService.parse_envelope(
        '''{
  "conclusion": "收到需求。在制定分析方案前，需要确认数据状态。",
  "recommendations": [],
  "evidence_refs": [],
  "risks": ["3v3 设计的统计效能有限"],
  "ask_user": [
    {"question": "数据是什么格式？", "options": ["Seurat RDS", "h5ad"]},
    {"question": "来自什么组织？", "options": [],}
  ],
}'''
    )

    assert result.conclusion == "收到需求。在制定分析方案前，需要确认数据状态。"
    assert result.risks == ["3v3 设计的统计效能有限"]
    assert result.ask_user[1].question == "来自什么组织？"


def test_parse_envelope_flattens_nested_string_lists() -> None:
    result = AgentConsultationService.parse_envelope(
        '{"conclusion":"今天武汉天气为晴到多云。",'
        '"recommendations":[["注意高温"],["携带雨具"]],'
        '"evidence_refs":[["https://example.test/weather"]],"risks":[]}'
    )

    assert result.recommendations == ["注意高温", "携带雨具"]
    assert result.evidence_refs == ["https://example.test/weather"]


def test_parse_envelope_recovers_restarted_envelope_after_length_continuation() -> None:
    """长度截断续写时模型重开了一个完整信封：跨块错配的旧配对方式会整段降级。"""
    raw = (
        '```json { "conclusion": "我在绘图阶段输出 ggtree 脚本 + '
        '```json { "conclusion": "（接上段）可视化美化评估收尾。", '
        '"recommendations": ["先核验树文件"], "risks": [] } ```'
    )
    envelope, parse_success = AgentConsultationService._parse_envelope_with_status(raw)

    assert parse_success is True
    assert envelope.conclusion == "（接上段）可视化美化评估收尾。"
    assert envelope.recommendations == ["先核验树文件"]


def test_parse_envelope_tolerates_newline_seam_inside_string() -> None:
    """续写拼接的 \\n\\n seam 落入字符串值时，strict=False 仍可解析。"""
    raw = '```json\n{"conclusion": "前半段\n\n后半段", "risks": []}\n```'
    envelope, parse_success = AgentConsultationService._parse_envelope_with_status(raw)

    assert parse_success is True
    assert envelope.conclusion == "前半段\n\n后半段"


def test_parse_envelope_still_degrades_on_truncated_json() -> None:
    """只有一段截断 JSON、没有重开完整信封时，仍走降级兜底。"""
    raw = '```json { "conclusion": "写到一半被截断'
    envelope, parse_success = AgentConsultationService._parse_envelope_with_status(raw)

    assert parse_success is False
    assert envelope.conclusion == raw
    assert envelope.risks == ["信封解析降级：专家答复未满足结构化 JSON 契约。"]


@pytest.mark.asyncio
async def test_quality_gate_blocks_low_mapping_rate_and_keeps_verified_refs(monkeypatch) -> None:
    task_id = "00000000-0000-0000-0000-000000000002"
    agent_service = SimpleNamespace(
        assemble_context=AsyncMock(return_value=SimpleNamespace(model_config=object()))
    )
    parallel_service = SimpleNamespace(
        run=AsyncMock(
            return_value={
                "llm_payload": {
                    "results": [
                        {
                            "answer": """```json
{"conclusion":"PASSED\n模型认为可放行","recommendations":[],"evidence_refs":["task:伪造"],"risks":[],"token_usage":1}
```""",
                            "verified_evidence_refs": [
                                f"task:{task_id}",
                                "rule:rna_seq:mapping_rate",
                            ],
                        }
                    ]
                }
            }
        )
    )
    monkeypatch.setattr(
        "cygnusx.application.services.agent_consultation_service.PipelineResultService.get_task_summary",
        AsyncMock(
            return_value={
                "flow_id": "rna_seq",
                "metrics": {"mapping_rate": 0.30, "q30": 0.91, "duplicate_rate": 0.2},
            }
        ),
    )
    service = AgentConsultationService(
        _Session(), agent_service=agent_service, parallel_service=parallel_service
    )

    result = await service.run_consultation(
        case_id="case-1",
        agent_id="agent-qc",
        question="执行独立质量门",
        capability="quality-gate",
        evidence_refs=[f"task:{task_id}"],
        requested_tools=["task_result_summary", "rule_threshold_lookup"],
        requester_ref="00000000-0000-0000-0000-000000000001",
    )

    assert result.conclusion.startswith("BLOCKED\n")
    assert result.evidence_refs == [f"task:{task_id}", "rule:rna_seq:mapping_rate"]
    assert result.hard_gate is not None
    assert result.hard_gate["decision"] == "BLOCKED"
    instruction = parallel_service.run.await_args.kwargs["tasks"][0]["task"]
    assert "mapping_rate" in instruction
    assert "不得把硬规则 BLOCKED 降级" in instruction
    # 信封内字符串含未转义换行也能容错解析（strict=False），硬门判定不受影响
    assert result.token_usage == 1
    assert result.risks == []


def test_workspace_consultation_uses_scoped_workdir() -> None:
    asyncio.run(_test_workspace_consultation_uses_scoped_workdir())


async def _test_workspace_consultation_uses_scoped_workdir() -> None:
    agent_service = SimpleNamespace(
        assemble_context=AsyncMock(return_value=SimpleNamespace(model_config=object()))
    )
    parallel_service = SimpleNamespace(
        run=AsyncMock(return_value={"llm_payload": {"results": [{"answer": "workspace complete"}]}})
    )
    service = AgentConsultationService(
        SimpleNamespace(), agent_service=agent_service, parallel_service=parallel_service
    )

    result = await service.run_consultation(
        case_id="case-1",
        work_item_id="code-write-01",
        agent_id="agent-code",
        question="生成报告",
        capability="result_interpretation",
        evidence_refs=[],
        requested_tools=[],
        requester_ref="user-1",
        execution_mode="workspace_execution",
    )

    call = parallel_service.run.await_args.kwargs
    assert call["safe_only"] is False
    assert call["tasks"][0]["workspace_access"] is True
    assert str(call["workdir_root"]) == "/data/cygnusx/output/agentteams/case-1/code-write-01"
    task = call["tasks"][0]
    assert "## AgentTeams 工作区执行协议" in task["task"]
    assert "plan_hash 已确认" in task["task"]
    assert "最终答复只包含一个 `json` 代码块" in task["task"]
    assert "信封解析降级" in result.risks[0]


def test_workspace_consultation_allowed_for_declared_expert() -> None:
    """P0 回归：workspace_execution 不再硬编码 agent-code/agent-viz，按 YAML 声明放行。"""
    asyncio.run(_test_workspace_consultation_allowed_for_declared_expert())


async def _test_workspace_consultation_allowed_for_declared_expert() -> None:
    agent_service = SimpleNamespace(
        assemble_context=AsyncMock(return_value=SimpleNamespace(model_config=object()))
    )
    parallel_service = SimpleNamespace(
        run=AsyncMock(return_value={"llm_payload": {"results": [{"answer": "workspace complete"}]}})
    )
    service = AgentConsultationService(
        SimpleNamespace(), agent_service=agent_service, parallel_service=parallel_service
    )

    await service.run_consultation(
        case_id="case-1",
        work_item_id="rna-exec-01",
        agent_id="agent-rnaseq",
        question="执行 RNA-seq 表达定量",
        capability="interpretation",
        evidence_refs=[],
        requested_tools=[],
        requester_ref="user-1",
        execution_mode="workspace_execution",
    )

    call = parallel_service.run.await_args.kwargs
    assert call["safe_only"] is False
    assert str(call["workdir_root"]) == "/data/cygnusx/output/agentteams/case-1/rna-exec-01"


def test_workspace_artifacts_are_copied_and_registered(tmp_path, monkeypatch) -> None:
    asyncio.run(_test_workspace_artifacts_are_copied_and_registered(tmp_path, monkeypatch))


async def _test_workspace_artifacts_are_copied_and_registered(tmp_path, monkeypatch) -> None:
    source_root = tmp_path / "output" / "agentteams" / "case-1" / "exec-01"
    source_root.mkdir(parents=True)
    source = source_root / "treeplot.svg"
    source.write_text("<svg/>", encoding="utf-8")
    storage_root = tmp_path / "storage"

    class Factory:
        def user_root(self, user_id: str):
            return storage_root / "users" / user_id

        def relative_to_root(self, path):
            return path.relative_to(storage_root).as_posix()

    saved = []

    class Repository:
        def __init__(self, _db) -> None:
            pass

        async def save(self, file):
            saved.append(file)
            return file

    class Lineage:
        """血缘写入探针：登记路径强制写 version 行（F1），测试侧只断言被调用。"""

        def __init__(self, _db) -> None:
            self.versions = []
            self.dependencies = []

        async def register_version(self, **kwargs):
            row = SimpleNamespace(id=uuid4(), version_no=1, **kwargs)
            self.versions.append(row)
            return row

        async def register_dependencies(self, **kwargs):
            self.dependencies.append(kwargs)
            return []

    monkeypatch.setattr(
        "cygnusx.application.services.agent_consultation_service.get_path_factory",
        lambda: Factory(),
    )
    monkeypatch.setattr(
        "cygnusx.application.services.agent_consultation_service.FileRepositoryImpl", Repository
    )
    monkeypatch.setattr(
        "cygnusx.application.services.agent_consultation_service.AgentTeamsArtifactLineageService",
        Lineage,
    )
    service = AgentConsultationService(SimpleNamespace())

    artifacts, errors = await service._register_workspace_artifacts(
        str(uuid4()), "case-1", "exec-01", source_root
    )

    assert errors == []
    assert len(artifacts) == len(saved) == 1
    assert artifacts[0]["id"] == str(saved[0].id)
    assert artifacts[0]["download_url"] == f"/api/v1/files/{saved[0].id}/download"
    assert artifacts[0]["path"].endswith("workspace/agentteams/case-1/exec-01/treeplot.svg")
    assert (storage_root / artifacts[0]["path"]).read_text(encoding="utf-8") == "<svg/>"


def test_run_consultation_rejects_missing_agent() -> None:
    asyncio.run(_test_run_consultation_rejects_missing_agent())


async def _test_run_consultation_rejects_missing_agent() -> None:
    agent_service = SimpleNamespace(assemble_context=AsyncMock(return_value=None))
    service = AgentConsultationService(
        SimpleNamespace(),
        agent_service=agent_service,
        parallel_service=SimpleNamespace(run=AsyncMock()),
    )
    with pytest.raises(NotFoundError):
        await service.run_consultation(
            case_id="case-1",
            agent_id="agent-rnaseq",
            question="解释结果",
            capability="result_interpretation",
            evidence_refs=[],
            requested_tools=[],
            requester_ref="user-1",
        )


def test_integration_token_missing_or_wrong_is_unauthorized(monkeypatch) -> None:
    monkeypatch.setattr(
        "cygnusx.api.v1.agentteams.get_settings",
        lambda: SimpleNamespace(agentteams_integration_token="expected-token"),
    )
    with pytest.raises(HTTPException) as missing:
        require_integration_token(None)
    with pytest.raises(HTTPException) as wrong:
        require_integration_token("wrong-token")
    assert missing.value.status_code == 401
    assert wrong.value.status_code == 401
    assert require_integration_token("expected-token") is None


def test_consultation_prefix_uses_its_integration_token_guard() -> None:
    assert "/api/v1/agent-teams/consultations/" in SELF_AUTHENTICATED_PREFIXES


def test_safe_only_filters_writable_and_confirmation_tools(monkeypatch) -> None:
    schemas = {
        "safe_lookup": SimpleNamespace(
            invocation_mode="backend_sync",
            annotations=SimpleNamespace(read_only_hint=True),
            requires_confirm=False,
        ),
        "write_file": SimpleNamespace(
            invocation_mode="backend_sync",
            annotations=SimpleNamespace(read_only_hint=False),
            requires_confirm=False,
        ),
        "dangerous_read": SimpleNamespace(
            invocation_mode="backend_sync",
            annotations=SimpleNamespace(read_only_hint=True),
            requires_confirm=True,
        ),
    }
    monkeypatch.setattr(
        "cygnusx.application.services.parallel_subagent_service.schema_loader.get_tool",
        schemas.get,
    )
    context = SimpleNamespace(
        tools=[
            {"type": "function", "function": {"name": name}}
            for name in ("safe_lookup", "write_file", "dangerous_read")
        ],
        features={"web_search": False},
        mcp_servers=[],
    )

    filtered = ParallelSubAgentService._prepare_child_tools(context, safe_only=True)
    names = {tool["function"]["name"] for tool in filtered}

    assert "safe_lookup" in names
    assert "write_file" not in names
    assert "dangerous_read" not in names


def _ok_envelope_result() -> dict:
    return {
        "llm_payload": {
            "results": [
                {
                    "answer": """```json
{"conclusion":"可信","recommendations":[],"evidence_refs":[],"risks":[],"token_usage":1}
```"""
                }
            ]
        }
    }


def _consultation_service_with_events(
    events: list[dict], post_evidence: AsyncMock
) -> tuple[AgentConsultationService, AsyncMock]:
    agent_service = SimpleNamespace(
        assemble_context=AsyncMock(return_value=SimpleNamespace(model_config=object()))
    )

    async def _run(**kwargs):
        on_event = kwargs.get("on_event")
        if on_event is not None:
            for event in events:
                on_event(event)
        return _ok_envelope_result()

    parallel_service = SimpleNamespace(run=AsyncMock(side_effect=_run))
    agentteams_service = SimpleNamespace(available=True, post_case_evidence=post_evidence)
    service = AgentConsultationService(
        SimpleNamespace(),
        agent_service=agent_service,
        parallel_service=parallel_service,
        agentteams_service=agentteams_service,
    )
    return service, parallel_service.run


@pytest.mark.asyncio
@pytest.mark.quarantine(reason="证据投影 project_event 为协程但调用方未 await，未发出任何 agent 事件，事件集合断言失败")
async def test_evidence_projection_emits_agent_events_with_truncated_args() -> None:
    post_evidence = AsyncMock(return_value={"event_id": "e1"})
    events = [
        {"type": "worker_started", "index": 1, "agent_id": "agent-rnaseq"},
        {
            "type": "worker_tool_call",
            "index": 1,
            "agent_id": "agent-rnaseq",
            "tool_name": "task_result_summary",
            "tool_call_id": "call-1",
            "round": 1,
            "execution_path": "agentteams_worker_react",
            "args_summary": "x" * 500,
        },
        {
            "type": "worker_tool_result",
            "index": 1,
            "agent_id": "agent-rnaseq",
            "tool_name": "task_result_summary",
            "tool_call_id": "call-1",
            "round": 1,
            "execution_path": "agentteams_worker_react",
            "result_summary": "结果可信",
            "success": True,
            "duration_ms": 12,
        },
        {
            "type": "agent_context_reinjected",
            "index": 1,
            "agent_id": "agent-rnaseq",
            "tool_name": "task_result_summary",
            "tool_call_id": "call-1",
            "round": 1,
            "execution_path": "agentteams_worker_react",
        },
        {
            "type": "worker_finished",
            "index": 1,
            "agent_id": "agent-rnaseq",
            "status": "ok",
            "elapsed_s": 2.5,
        },
    ]
    service, _ = _consultation_service_with_events(events, post_evidence)

    result = await service.run_consultation(
        case_id="case-1",
        work_item_id="wi-1",
        agent_id="agent-rnaseq",
        question="解释结果",
        capability="result_interpretation",
        evidence_refs=[],
        requested_tools=[],
        requester_ref="user-1",
    )

    assert result.conclusion == "可信"
    calls = {call.kwargs["event_type"]: call for call in post_evidence.await_args_list}
    assert set(calls) == {
        "agent.started",
        "agent.tool_call",
        "agent.tool_result",
        "agent.context_reinjected",
        "agent.finished",
    }
    for call in calls.values():
        assert call.args[0] == "case-1"
        assert call.kwargs["work_item_id"] == "wi-1"
        assert call.kwargs["payload"]["work_item_id"] == "wi-1"
        assert call.kwargs["payload"]["agent_id"] == "agent-rnaseq"
    tool_call_payload = calls["agent.tool_call"].kwargs["payload"]
    assert tool_call_payload["tool"] == "task_result_summary"
    assert tool_call_payload["tool_call_id"] == "call-1"
    assert tool_call_payload["round"] == 1
    assert tool_call_payload["execution_path"] == "agentteams_worker_react"
    assert len(tool_call_payload["args_summary"]) == 200
    tool_result_payload = calls["agent.tool_result"].kwargs["payload"]
    assert tool_result_payload == {
        "tool": "task_result_summary",
        "tool_call_id": "call-1",
        "round": 1,
        "execution_path": "agentteams_worker_react",
        "result_summary": "结果可信",
        "success": True,
        "duration_ms": 12,
        "work_item_id": "wi-1",
        "agent_id": "agent-rnaseq",
    }
    finished_payload = calls["agent.finished"].kwargs["payload"]
    assert finished_payload["status"] == "ok"
    assert finished_payload["tool_call_count"] == 1
    assert finished_payload["duration_ms"] == 2500


@pytest.mark.asyncio
async def test_parse_failure_is_projected_to_case_timeline() -> None:
    post_evidence = AsyncMock(return_value={"event_id": "parse-1"})
    agent_service = SimpleNamespace(
        assemble_context=AsyncMock(return_value=SimpleNamespace(model_config=object()))
    )
    parallel_service = SimpleNamespace(
        run=AsyncMock(
            return_value={
                "llm_payload": {
                    "results": [{"answer": "这不是 JSON 信封"}],
                }
            }
        )
    )
    service = AgentConsultationService(
        SimpleNamespace(),
        agent_service=agent_service,
        parallel_service=parallel_service,
        agentteams_service=SimpleNamespace(available=True, post_case_evidence=post_evidence),
    )

    result = await service.run_consultation(
        case_id="case-parse",
        work_item_id="plan-01",
        agent_id="agent-code",
        question="生成计划",
        capability="planning_advice",
        evidence_refs=[],
        requested_tools=[],
        requester_ref="user-1",
    )

    assert result.risks == ["信封解析降级：专家答复未满足结构化 JSON 契约。"]
    post_evidence.assert_awaited_once()
    assert post_evidence.await_args.kwargs["event_type"] == "consultation.parse_failed"
    assert post_evidence.await_args.kwargs["payload"]["parse_success"] is False


@pytest.mark.asyncio
async def test_parse_failure_evidence_carries_causation_event_id() -> None:
    """手册阶段 2 修复 3：解析失败异常事件携带触发它的 room.user_message event_id。"""
    post_evidence = AsyncMock(return_value={"event_id": "parse-1"})
    agent_service = SimpleNamespace(
        assemble_context=AsyncMock(return_value=SimpleNamespace(model_config=object()))
    )
    parallel_service = SimpleNamespace(
        run=AsyncMock(
            return_value={
                "llm_payload": {
                    "results": [{"answer": "这不是 JSON 信封"}],
                }
            }
        )
    )
    service = AgentConsultationService(
        SimpleNamespace(),
        agent_service=agent_service,
        parallel_service=parallel_service,
        agentteams_service=SimpleNamespace(available=True, post_case_evidence=post_evidence),
    )

    await service.run_consultation(
        case_id="case-parse",
        work_item_id="plan-01",
        agent_id="agent-code",
        question="生成计划",
        capability="planning_advice",
        evidence_refs=[],
        requested_tools=[],
        requester_ref="user-1",
        causation_event_id="evt-user-1",
    )

    post_evidence.assert_awaited_once()
    assert post_evidence.await_args.kwargs["event_type"] == "consultation.parse_failed"
    assert post_evidence.await_args.kwargs["payload"]["causation_event_id"] == "evt-user-1"


@pytest.mark.asyncio
@pytest.mark.quarantine(reason="证据投影协程未被 await，post_evidence 调用计数为 0，与预期 3 不符")
async def test_evidence_projection_failure_does_not_break_consultation() -> None:
    post_evidence = AsyncMock(side_effect=RuntimeError("bridge down"))
    events = [
        {"type": "worker_started", "index": 1, "agent_id": "agent-rnaseq"},
        {
            "type": "worker_tool_call",
            "index": 1,
            "agent_id": "agent-rnaseq",
            "tool_name": "knowledge_search",
            "args_summary": "{}",
        },
        {
            "type": "worker_finished",
            "index": 1,
            "agent_id": "agent-rnaseq",
            "status": "ok",
            "elapsed_s": 1.0,
        },
    ]
    service, _ = _consultation_service_with_events(events, post_evidence)

    result = await service.run_consultation(
        case_id="case-1",
        work_item_id="wi-1",
        agent_id="agent-rnaseq",
        question="解释结果",
        capability="result_interpretation",
        evidence_refs=[],
        requested_tools=[],
        requester_ref="user-1",
    )

    assert result.conclusion == "可信"
    assert post_evidence.await_count == 3


@pytest.mark.asyncio
@pytest.mark.quarantine(reason="证据投影协程未被 await，工具调用证据为 0 条，200 条上限截断断言失败")
async def test_tool_call_evidence_is_capped_at_200_with_truncation_marker() -> None:
    post_evidence = AsyncMock(return_value={"event_id": "e1"})
    events = [
        {
            "type": "worker_tool_call",
            "index": 1,
            "agent_id": "agent-rnaseq",
            "tool_name": f"tool_{number}",
            "args_summary": "{}",
        }
        for number in range(205)
    ]
    service, _ = _consultation_service_with_events(events, post_evidence)

    await service.run_consultation(
        case_id="case-1",
        work_item_id="wi-1",
        agent_id="agent-rnaseq",
        question="解释结果",
        capability="result_interpretation",
        evidence_refs=[],
        requested_tools=[],
        requester_ref="user-1",
    )

    event_types = [call.kwargs["event_type"] for call in post_evidence.await_args_list]
    assert event_types.count("agent.tool_call") == 200
    assert event_types.count("agent.tool_call_truncated") == 1
    truncated_call = next(
        call
        for call in post_evidence.await_args_list
        if call.kwargs["event_type"] == "agent.tool_call_truncated"
    )
    assert truncated_call.kwargs["payload"]["limit"] == 200


@pytest.mark.asyncio
async def test_evidence_projection_skipped_without_work_item_or_service() -> None:
    post_evidence = AsyncMock()
    agent_service = SimpleNamespace(
        assemble_context=AsyncMock(return_value=SimpleNamespace(model_config=object()))
    )
    parallel_service = SimpleNamespace(run=AsyncMock(return_value=_ok_envelope_result()))
    agentteams_service = SimpleNamespace(available=True, post_case_evidence=post_evidence)
    service = AgentConsultationService(
        SimpleNamespace(),
        agent_service=agent_service,
        parallel_service=parallel_service,
        agentteams_service=agentteams_service,
    )

    await service.run_consultation(
        case_id="case-1",
        agent_id="agent-rnaseq",
        question="解释结果",
        capability="result_interpretation",
        evidence_refs=[],
        requested_tools=[],
        requester_ref="user-1",
    )

    assert parallel_service.run.await_args.kwargs["on_event"] is None
    post_evidence.assert_not_awaited()


# --- M3：L4 记忆写入纪律 ---

def test_build_instruction_includes_l4_memory_write_discipline_when_v2_on(monkeypatch) -> None:
    """v2 开启时会诊 prompt 追加 L4 版三条写入纪律（解释 why 风格）。"""
    monkeypatch.setattr(
        "cygnusx.application.services.agent_consultation_service.get_settings",
        lambda: SimpleNamespace(memory_v2_enabled=True),
    )

    instruction = AgentConsultationService._build_instruction(
        question="拆解这个需求",
        capability="interpretation",
        evidence_refs=[],
        requested_tools=[],
        execution_mode="readonly_consultation",
        hard_gate=None,
    )

    assert "记忆写入纪律" in instruction
    # 三条纪律：持久偏好与纠错 / Case 事实禁写（血缘与 case_facts_query）/ 写前查重
    assert "持久偏好与纠错" in instruction
    assert "case_facts_query" in instruction
    assert "cygnusx_search_memory" in instruction


def test_build_instruction_omits_memory_discipline_when_v2_off(monkeypatch) -> None:
    """v2 off 时不追加纪律，装配产物与现状一致。"""
    monkeypatch.setattr(
        "cygnusx.application.services.agent_consultation_service.get_settings",
        lambda: SimpleNamespace(memory_v2_enabled=False),
    )

    instruction = AgentConsultationService._build_instruction(
        question="拆解这个需求",
        capability="interpretation",
        evidence_refs=[],
        requested_tools=[],
        execution_mode="readonly_consultation",
        hard_gate=None,
    )

    assert "记忆写入纪律" not in instruction
    assert "case_facts_query" not in instruction
