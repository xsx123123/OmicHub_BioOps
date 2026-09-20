"""Gateway → CygnusX 会诊端点契约与聊天 Case Flow 绑定门槛测试。

回归背景（2026-08-20 事故）：
1. ``ScientificInterpretationRequest`` 缺少 ``requester_ref`` 等字段，Gateway 转发
   的字段被 pydantic 静默丢弃，``run_consultation(**dump)`` 抛 TypeError，端点
   一律 500，所有 Worker 会诊退化为 manual_review（房间内出现
   "No automated scientific conclusion is available." 人工复核卡片）。
2. ``_resolve_chat_flow_id`` 把建 Case 时自动注入的 project 运行目录当作
   "明确执行对象"，导致"如何进行"一类尚无数据的请求在 Manager 澄清完成前
   就绑定领域 Flow 并向领域 Agent 派出 plan-01。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from cygnusx.api.v1.agentteams import (
    AgentTeamsRoomMessageRequest,
    ScientificInterpretationRequest,
    post_case_message,
    scientific_interpretation,
)
from cygnusx.application.services.agent_consultation_service import (
    AgentConsultationService,
    ConsultationEnvelope,
)
from cygnusx.application.services.agentteams_service import AgentTeamsService


def test_scientific_interpretation_request_accepts_gateway_payload() -> None:
    """Gateway 转发的完整载荷必须可用：requester_ref 等被保留，额外字段被容忍。"""
    request = ScientificInterpretationRequest.model_validate(
        {
            "case_id": "bioops_1",
            "agent_id": "agent-scrna",
            "question": "形成可执行计划、参数快照、任务依赖与风险说明。",
            "capability": "planning_advice",
            "evidence_refs": [],
            "requested_tools": [],
            "requester_ref": "user-1",
            "work_item_id": "plan-01",
            "execution_mode": "readonly_consultation",
            # Gateway client.py 附带的安全标志位：模型必须忽略而不是报错。
            "read_only": True,
            "allow_task_actions": False,
            "allow_file_write": False,
            "allow_database_access": False,
            "allow_shell": False,
        }
    )

    assert request.requester_ref == "user-1"
    assert request.work_item_id == "plan-01"
    assert request.execution_mode == "readonly_consultation"


def test_room_message_request_accepts_model_override() -> None:
    model_id = uuid4()
    request = AgentTeamsRoomMessageRequest(content="切换模型后继续", model_id=model_id)

    assert request.model_id == model_id


@pytest.mark.asyncio
async def test_scientific_interpretation_endpoint_passes_requester_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """端点必须把 requester_ref / work_item_id / execution_mode 传给会诊服务。"""
    captured: dict = {}

    async def fake_run(self, **kwargs):  # noqa: ANN001, ANN202 - 测试替身
        captured.update(kwargs)
        return ConsultationEnvelope(conclusion="ok")

    monkeypatch.setattr(AgentConsultationService, "run_consultation", fake_run)

    request = ScientificInterpretationRequest(
        case_id="bioops_1",
        agent_id="agent-scrna",
        question="形成可执行计划",
        capability="interpretation",
        requester_ref="user-1",
        work_item_id="plan-01",
    )
    result = await scientific_interpretation(
        request, None, SimpleNamespace(), SimpleNamespace()
    )

    assert result.conclusion == "ok"
    assert captured["requester_ref"] == "user-1"
    assert captured["work_item_id"] == "plan-01"
    assert captured["execution_mode"] == "readonly_consultation"


_NO_DATA_INTENT = (
    "我想进行小鼠肺部6个样本 3v3 TP53mutation vs TP53 WT 单细胞分析，"
    "你帮我看一下我要如何进行呀"
)


def test_chat_flow_binding_ignores_auto_injected_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """project 运行目录与 workspace 默认引用不算执行对象：无数据时不绑定 Flow。"""
    route_calls: list[str] = []

    def fake_route(text: str):  # noqa: ANN202 - 测试替身
        route_calls.append(text)
        return SimpleNamespace(flow_id="scrna", lead_planner="agent-scrna")

    monkeypatch.setattr(
        "cygnusx.application.services.agentteams_service.infer_intent_route", fake_route
    )

    assert (
        AgentTeamsService._resolve_chat_flow_id(
            _NO_DATA_INTENT, [{"kind": "project", "id": "proj-1"}]
        )
        is None
    )
    assert (
        AgentTeamsService._resolve_chat_flow_id(
            _NO_DATA_INTENT, [{"kind": "workspace", "id": "user-1"}]
        )
        is None
    )
    assert AgentTeamsService._resolve_chat_flow_id(_NO_DATA_INTENT, []) is None
    assert route_calls == []


def test_chat_flow_binding_allows_real_data_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实文件引用或文本内明确数据产物仍允许在创建时绑定领域 Flow。"""
    monkeypatch.setattr(
        "cygnusx.application.services.agentteams_service.infer_intent_route",
        lambda text: SimpleNamespace(flow_id="scrna", lead_planner="agent-scrna"),
    )

    assert (
        AgentTeamsService._resolve_chat_flow_id(
            _NO_DATA_INTENT, [{"kind": "file", "id": "file-1"}]
        )
        == "scrna"
    )
    assert (
        AgentTeamsService._resolve_chat_flow_id(
            "请用 Cell Ranger 输出进行单细胞分析", []
        )
        == "scrna"
    )


@pytest.mark.asyncio
async def test_duplicate_room_message_does_not_dispatch_manager_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """服务已按 client_message_id 去重时，API 不应再次投递 Celery 回复任务。"""
    from cygnusx.infrastructure.celery_app.tasks import agentteams as task_module

    delay = Mock()
    monkeypatch.setattr(task_module.respond_to_room_message, "delay", delay)
    service = SimpleNamespace(
        post_room_message=AsyncMock(
            return_value={"event_id": "evt-1", "deduplicated": True}
        )
    )

    result = await post_case_message(
        "bioops_1",
        AgentTeamsRoomMessageRequest(content="重复的澄清回复", client_message_id="msg-1"),
        "user-1",
        service,
    )

    assert result["response_dispatch"] == "deduplicated"
    delay.assert_not_called()


@pytest.mark.asyncio
async def test_room_message_dispatches_selected_model_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cygnusx.infrastructure.celery_app.tasks import agentteams as task_module

    delay = Mock()
    monkeypatch.setattr(task_module.respond_to_room_message, "delay", delay)
    service = SimpleNamespace(
        post_room_message=AsyncMock(return_value={"event_id": "evt-1"})
    )
    model_id = uuid4()

    result = await post_case_message(
        "bioops_1",
        AgentTeamsRoomMessageRequest(content="使用备用模型继续", model_id=model_id),
        "user-1",
        service,
    )

    assert result["response_dispatch"] == "queued"
    delay.assert_called_once_with("bioops_1", "user-1", "使用备用模型继续", None, str(model_id))
