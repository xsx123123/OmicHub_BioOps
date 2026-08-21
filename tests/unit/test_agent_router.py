"""智能路由（ChatService._route_to_agent / _extract_route_json）单元测试"""

import json
from types import SimpleNamespace
from typing import Any

import pytest

import omichub.application.services.chat_service as chat_service_module
from omichub.application.schemas.agent import AgentTemplateDTO
from omichub.application.services.chat_service import (
    ChatService,
    _extract_route_json,
    _is_route_execution_confirmation,
    _should_show_route_transition,
)


def test_route_transition_only_shows_for_initial_or_changed_target() -> None:
    assert _should_show_route_transition(None, "agent-general") is True
    assert _should_show_route_transition("agent-general", "agent-general") is False
    assert _should_show_route_transition("agent-general", "agent-rnaseq") is True
    assert (
        _should_show_route_transition(
            "agent-rnaseq", "agent-rnaseq", execution_confirmed=True
        )
        is True
    )


def _candidate(agent_id: str, category: str, name: str = "") -> AgentTemplateDTO:
    return AgentTemplateDTO(
        agent_id=agent_id,
        name=name or agent_id,
        description=f"{agent_id} 描述",
        avatar="🧬",
        color="#123456",
        category=category,
        features={},
    )


CANDIDATES = [
    _candidate("agent-general", "general", "通用助手"),
    _candidate("agent-rnaseq", "analysis", "RNA-seq 分析师"),
    _candidate("agent-router", "general", "智能助手"),  # features.router 应被排除
]
CANDIDATES[2].features = {"router": True}


def _catalog_entry(dto: AgentTemplateDTO) -> dict[str, Any]:
    """模拟注册表 chat_router_catalog 条目(双注册表统一后 chat 候选的唯一来源)。"""
    return {
        "agent_id": dto.agent_id,
        "name": dto.name,
        "description": dto.description,
        "category": dto.category,
        "chat_entry": True,
        "capabilities": [],
        "not_suitable_for": [],
        "handoff_when": [],
        "preferred_inputs": [],
        "routing_hints": [],
        "capability_tags": [],
        "routing_notes": "",
        "avatar": dto.avatar,
        "color": dto.color,
    }


class _FakeCapabilityRegistry:
    """快照桩:与真实注册表一样过滤 features.router 候选。"""

    def snapshot(self) -> dict[str, Any]:
        return {
            "chat_router_catalog": [
                _catalog_entry(c) for c in CANDIDATES if not c.features.get("router")
            ],
            "flow_router_catalog": [],
        }


class _FakeAgentService:
    """按 agent_id 返回上下文的最小桩"""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def list_agents(self, active_only: bool = False) -> list[AgentTemplateDTO]:
        return CANDIDATES

    async def assemble_context(self, agent_id: str) -> Any:
        if agent_id not in {c.agent_id for c in CANDIDATES}:
            return None
        return SimpleNamespace(
            agent_id=agent_id,
            model_config=SimpleNamespace(name="qwen3.7-max", api_key="k"),
        )


def _fake_chat_stream(text: str):
    async def _stream(**kwargs: Any):
        yield SimpleNamespace(type="text", content=text, metadata={})
        yield SimpleNamespace(type="done", content="", metadata={"usage": {}})

    return _stream


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> ChatService:
    monkeypatch.setattr(
        "omichub.application.services.agent_service.AgentService", _FakeAgentService
    )
    monkeypatch.setattr(
        "omichub.application.services.agentteams_capability_registry"
        ".get_agentteams_capability_registry",
        lambda: _FakeCapabilityRegistry(),
    )
    return ChatService(db=SimpleNamespace())


@pytest.fixture
def router_ctx() -> Any:
    return SimpleNamespace(model_config=SimpleNamespace(name="qwen3.7-max", api_key="k"))


@pytest.mark.unit
def test_extract_route_json_pure():
    data = _extract_route_json('{"agent_id": "agent-rnaseq", "reason": "r"}')
    assert data == {"agent_id": "agent-rnaseq", "reason": "r"}


@pytest.mark.unit
def test_extract_route_json_with_chatter():
    data = _extract_route_json('好的，选择：{"agent_id": "agent-rnaseq", "reason": "r"} 以上')
    assert data is not None
    assert data["agent_id"] == "agent-rnaseq"


@pytest.mark.unit
def test_extract_route_json_invalid():
    assert _extract_route_json("完全无法解析的输出") is None
    assert _extract_route_json("{broken json") is None


@pytest.mark.unit
@pytest.mark.parametrize(
    ("user_text", "expected"),
    [
        ("确认开始分析", True),
        ("按上述方案执行", True),
        ("现在开始", True),
        ("先不执行，想调整参数", False),
        ("暂不开始分析", False),
        ("我想知道 RNA-seq 怎么开始", False),
    ],
)
def test_route_execution_confirmation_requires_explicit_opt_in(
    user_text: str, expected: bool
) -> None:
    assert _is_route_execution_confirmation(user_text) is expected


@pytest.mark.unit
def test_extract_route_json_reasoning_then_duplicated_json():
    """模型先输出思考过程、再重复输出两次 JSON：取最后一个可解析且含 agent_id 的"""
    text = (
        '用户请求："帮我进行单细胞分析"\n匹配专家：agent-scrna\n\n构建 JSON 输出：\n'
        '{"agent_id": "agent-scrna", "reason": "单细胞需求"}'
        '{"agent_id": "agent-scrna", "reason": "单细胞需求"}'
    )
    data = _extract_route_json(text)
    assert data is not None
    assert data["agent_id"] == "agent-scrna"


@pytest.mark.unit
async def test_route_pure_json(service: ChatService, router_ctx: Any, monkeypatch):
    monkeypatch.setattr(
        chat_service_module.provider_manager,
        "chat_stream",
        _fake_chat_stream(json.dumps({"agent_id": "agent-rnaseq", "reason": "转录组问题"})),
    )
    ctx, info = await service._route_to_agent(router_ctx, "帮我做 RNA-seq 差异分析")
    assert ctx is not None and ctx.agent_id == "agent-rnaseq"
    assert info is not None
    assert info["agent_id"] == "agent-rnaseq"
    assert info["name"] == "RNA-seq 分析师"
    assert info["reason"] == "转录组问题"
    assert {"agent_id", "name", "avatar", "color", "reason"} <= set(info)
    assert info["transition"]["visible"] is True
    assert info["transition"]["stage"] == "specialist_intake"
    assert info["transition"]["requires_execution_confirmation"] is True
    assert info["transition"]["auto_start"] is False


@pytest.mark.unit
async def test_route_normalizes_legacy_delivery_case_to_case(
    service: ChatService, router_ctx: Any, monkeypatch
):
    monkeypatch.setattr(
        chat_service_module.provider_manager,
        "chat_stream",
        _fake_chat_stream(
            json.dumps(
                {
                    "agent_id": "agent-rnaseq",
                    "reason": "需要完整 RNA-seq 交付",
                    "intent": "delivery_case",
                    "confidence": 0.91,
                }
            )
        ),
    )

    _ctx, info = await service._route_to_agent(router_ctx, "帮我跑完 RNA-seq 并出报告")

    assert info is not None
    assert info["intent"] == "case"
    assert info["confidence"] == 0.91


@pytest.mark.unit
async def test_route_normalizes_low_confidence_legacy_delivery_case_to_case(
    service: ChatService, router_ctx: Any, monkeypatch
):
    monkeypatch.setattr(
        chat_service_module.provider_manager,
        "chat_stream",
        _fake_chat_stream(
            json.dumps(
                {
                    "agent_id": "agent-rnaseq",
                    "reason": "不确定",
                    "intent": "delivery_case",
                    "confidence": 0.4,
                }
            )
        ),
    )

    _ctx, info = await service._route_to_agent(router_ctx, "RNA-seq 怎么做")

    assert info is not None
    assert info["intent"] == "case"


@pytest.mark.unit
async def test_route_json_with_chatter(service: ChatService, router_ctx: Any, monkeypatch):
    monkeypatch.setattr(
        chat_service_module.provider_manager,
        "chat_stream",
        _fake_chat_stream('我认为应选 {"agent_id": "agent-rnaseq", "reason": "x"}，谢谢'),
    )
    ctx, info = await service._route_to_agent(router_ctx, "差异表达")
    assert ctx is not None and ctx.agent_id == "agent-rnaseq"
    assert info is not None and info["agent_id"] == "agent-rnaseq"


@pytest.mark.unit
async def test_route_unparseable_falls_back_general(
    service: ChatService, router_ctx: Any, monkeypatch
):
    monkeypatch.setattr(
        chat_service_module.provider_manager,
        "chat_stream",
        _fake_chat_stream("我不知道该选谁"),
    )
    ctx, info = await service._route_to_agent(router_ctx, "你好")
    assert ctx is not None and ctx.agent_id == "agent-general"
    assert info is not None
    assert info["agent_id"] == "agent-general"
    assert info["reason"]  # 兜底理由非空


@pytest.mark.unit
async def test_route_unknown_agent_falls_back_general(
    service: ChatService, router_ctx: Any, monkeypatch
):
    monkeypatch.setattr(
        chat_service_module.provider_manager,
        "chat_stream",
        _fake_chat_stream('{"agent_id": "agent-not-exist", "reason": "幻觉"}'),
    )
    ctx, info = await service._route_to_agent(router_ctx, "随便聊聊")
    assert ctx is not None and ctx.agent_id == "agent-general"
    assert info is not None and info["agent_id"] == "agent-general"
    assert info["reason"] == "幻觉"  # 保留模型给出的理由


@pytest.mark.unit
async def test_route_model_error_falls_back_none(
    service: ChatService, router_ctx: Any, monkeypatch
):
    async def _boom(**kwargs: Any):
        raise RuntimeError("模型超时")
        yield  # pragma: no cover

    monkeypatch.setattr(chat_service_module.provider_manager, "chat_stream", _boom)
    ctx, info = await service._route_to_agent(router_ctx, "你好")
    assert ctx is None and info is None
