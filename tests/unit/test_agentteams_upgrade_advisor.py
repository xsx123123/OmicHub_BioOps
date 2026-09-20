"""L2→L4 升级规则（愿景 Phase D / 协作室升级方案 Part 3.2）单元测试。

覆盖：触发规则（显式要求必出 / Flow 步骤≥3 / requires_formal_delivery /
咨询否决 / 未命中）、会话状态抑制（suggested/dismissed/upgraded/已有 Case）、
建议卡 schema、上下文摘要（context_refs 协议路径可解析、已澄清结论）、
接受升级全链路（房间创建+摘要系统消息+双向标记+幂等）、拒绝降级路径。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cygnusx.application.services.agentteams_context_refs import check_context_refs
from cygnusx.application.services.agentteams_room_service import AgentTeamsRoomService
from cygnusx.application.services.agentteams_service import room_namespace_case_id
from cygnusx.application.services.agentteams_upgrade_advisor import (
    ROOM_ORIGIN_L2_UPGRADE,
    ROOM_UPGRADE_CONTEXT_EVENT_TYPE,
    RULE_EXPLICIT_REQUEST,
    RULE_FLOW_STEPS_GTE_3,
    RULE_REQUIRES_FORMAL_DELIVERY,
    UPGRADE_SESSION_META_KEY,
    AgentTeamsUpgradeService,
    build_upgrade_context_summary,
    build_upgrade_suggestion,
    evaluate_upgrade_trigger,
    session_upgrade_state,
    suggestion_message_text,
    upgrade_suggestion_allowed,
)
from cygnusx.core.exceptions import BusinessError
from cygnusx.infrastructure.database.models.chat import (
    AgentTeamsRoomModel,
    ChatMessageModel,
    ChatSessionModel,
)

# ---------------------------------------------------------------------------
# 触发规则
# ---------------------------------------------------------------------------

_FLOWS = [
    {
        "flow_id": "rnaseq",
        "display_name": "bulk RNA-seq 差异分析",
        "trigger_hints": ["RNA-seq", "bulk RNA"],
        "stage_count": 2,
        "actor": "agent-rnaseq",
    },
    {
        "flow_id": "scrna",
        "display_name": "单细胞转录组分析",
        "trigger_hints": ["单细胞", "scRNA"],
        "stage_count": 3,
        "actor": "agent-scrna",
    },
]


class _FakeAbilityCatalog:
    def __init__(self, marked: set[str]) -> None:
        self._marked = marked

    def get(self, agent_id: str) -> dict:
        return {"requires_formal_delivery": agent_id in self._marked}


def _evaluate(content: str, marked: set[str] | None = None):
    return evaluate_upgrade_trigger(
        content, flows=_FLOWS, ability_catalog=_FakeAbilityCatalog(marked or set())
    )


def test_explicit_request_always_suggests() -> None:
    decision = _evaluate("请开协作室帮我做这批样本的正式交付")
    assert decision is not None
    assert decision.matched_rules == (RULE_EXPLICIT_REQUEST,)
    assert "协作室" in decision.reason


def test_explicit_request_not_confused_with_consultation() -> None:
    # “协作室是什么”是功能咨询而非升级请求，不应命中显式要求规则。
    assert _evaluate("协作室是什么？") is None


def test_flow_steps_gte_3_suggests() -> None:
    decision = _evaluate("我有 6 个单细胞样本，帮我跑完整分析流程")
    assert decision is not None
    assert RULE_FLOW_STEPS_GTE_3 in decision.matched_rules
    assert decision.flow_id == "scrna"
    assert decision.stage_count == 3


def test_requires_formal_delivery_suggests_below_step_threshold() -> None:
    decision = _evaluate("我的 RNA-seq 数据要做差异分析", marked={"agent-rnaseq"})
    assert decision is not None
    assert decision.matched_rules == (RULE_REQUIRES_FORMAL_DELIVERY,)
    assert decision.flow_id == "rnaseq"


def test_short_flow_without_marker_stays_in_l2() -> None:
    # rnaseq 仅 2 个阶段且未标记正式交付 → 留在 L2。
    assert _evaluate("我的 RNA-seq 数据要做差异分析") is None


def test_consultation_veto_blocks_flow_rules() -> None:
    assert _evaluate("单细胞测序有哪些常用方法？") is None
    assert _evaluate("RNA-seq 是什么") is None


def test_unrelated_content_stays_in_l2() -> None:
    assert _evaluate("今天天气怎么样") is None
    assert _evaluate("") is None
    assert _evaluate("   ") is None


# ---------------------------------------------------------------------------
# 会话状态抑制
# ---------------------------------------------------------------------------


def test_suggestion_allowed_only_without_marker_or_active_case() -> None:
    assert upgrade_suggestion_allowed({}) is True
    assert upgrade_suggestion_allowed(None) is True
    for status in ("suggested", "dismissed", "upgraded"):
        meta = {UPGRADE_SESSION_META_KEY: {"status": status}}
        assert upgrade_suggestion_allowed(meta) is False
    active_case = {
        "agentteams_case_ids": ["bioops_x"],
        "agentteams_case_status": {"bioops_x": "running"},
    }
    assert upgrade_suggestion_allowed(active_case) is False
    closed_case = {
        "agentteams_case_ids": ["bioops_x"],
        "agentteams_case_status": {"bioops_x": "closed"},
    }
    assert upgrade_suggestion_allowed(closed_case) is True


def test_session_upgrade_state_defaults() -> None:
    assert session_upgrade_state(None) == {}
    assert session_upgrade_state({"other": 1}) == {}


# ---------------------------------------------------------------------------
# 建议卡 schema
# ---------------------------------------------------------------------------


def test_suggestion_card_schema() -> None:
    decision = _evaluate("我有 6 个单细胞样本，帮我跑完整分析流程")
    assert decision is not None
    card = build_upgrade_suggestion(decision, session_id="sess-1")

    assert card["kind"] == "agentteams_upgrade_suggestion"
    assert card["suggestion_id"]
    assert card["source_session_id"] == "sess-1"
    assert card["matched_rules"] == [RULE_FLOW_STEPS_GTE_3]
    assert card["reason"] == decision.reason
    assert card["flow_id"] == "scrna"
    assert card["actions"] == ["accept", "dismiss"]
    assert card["takeover"]
    text = suggestion_message_text(card)
    assert decision.reason in text
    assert "拒绝" in text


# ---------------------------------------------------------------------------
# 上下文摘要与 context_refs 协议路径
# ---------------------------------------------------------------------------


def _message(
    role: str,
    content: str = "",
    metadata: dict | None = None,
    message_id: str | None = None,
) -> ChatMessageModel:
    return ChatMessageModel(
        message_id=message_id or f"m-{role}-{abs(hash(content)) % 100000}",
        session_id="sess-1",
        role=role,
        content=content,
        metadata_json=metadata or {},
    )


def _session(**overrides) -> ChatSessionModel:
    values = {
        "session_id": "sess-1",
        "user_id": "user-a",
        "title": "小鼠单细胞分析",
        "mode": "chat",
        "project_id": None,
        "sandbox_meta": {},
    }
    values.update(overrides)
    return ChatSessionModel(**values)


def test_summary_collects_protocol_context_refs_and_clarified_pairs() -> None:
    messages = [
        _message("user", "我想分析这批数据"),
        _message("assistant", "请问样本分组是怎样的？"),
        _message(
            "user",
            "3vs3，对照和处理",
            metadata={
                "attachments": [
                    {
                        "file_id": "f1",
                        "name": "matrix.csv",
                        "url": "/api/v1/files/chat-upload/user-a/f1.ssess-1.csv",
                    },
                    # 无 url 的附件无法还原协议路径，必须跳过（不生成不可解析引用）。
                    {"file_id": "f2", "name": "nofile.csv"},
                ]
            },
        ),
    ]
    summary = build_upgrade_context_summary(_session(), messages, matched_rules=["r1"])

    assert summary["objective"] == "3vs3，对照和处理"
    assert summary["source_session_id"] == "sess-1"
    assert summary["matched_rules"] == ["r1"]
    assert summary["clarified_conclusions"] == [
        {"question": "请问样本分组是怎样的？", "answer": "3vs3，对照和处理"}
    ]
    refs = summary["context_refs"]
    assert len(refs) == 1
    assert refs[0]["location"] == "workspace/chat-uploads/f1.ssess-1.csv"
    assert refs[0]["kind"] == "file"
    # 可解析性：移交的引用必须全部通过 context_refs 协议预检。
    checks = check_context_refs(refs)
    assert all(item.readable for item in checks)


def test_summary_falls_back_to_title_and_includes_project() -> None:
    summary = build_upgrade_context_summary(
        _session(project_id="proj-1"), [], matched_rules=[]
    )
    assert summary["objective"] == "小鼠单细胞分析"
    assert summary["confirmed_parameters"]["project_id"] == "proj-1"
    assert summary["context_refs"] == []
    assert summary["clarified_conclusions"] == []


# ---------------------------------------------------------------------------
# 接受升级全链路 / 拒绝降级路径
# ---------------------------------------------------------------------------


def _make_db(messages: list[ChatMessageModel]) -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()  # Session.add 是同步方法
    result = SimpleNamespace(scalars=MagicMock(return_value=SimpleNamespace(all=lambda: messages)))
    db.execute = AsyncMock(return_value=result)
    return db


def _make_agentteams() -> SimpleNamespace:
    return SimpleNamespace(
        available=True,
        create_room_namespace=AsyncMock(return_value={"case_id": "room-stub"}),
        provision_case_room=AsyncMock(return_value={"room_id": "!room:test"}),
        post_case_evidence=AsyncMock(return_value={"event_id": "evt-new"}),
    )


@pytest.mark.asyncio
async def test_accept_creates_room_posts_summary_and_marks_session() -> None:
    messages = [
        _message("user", "我想分析这批单细胞数据"),
        _message("assistant", "请问分组？"),
        _message(
            "user",
            "3vs3",
            metadata={
                "attachments": [
                    {
                        "file_id": "f1",
                        "name": "matrix.csv",
                        "url": "/api/v1/files/chat-upload/user-a/f1.ssess-1.csv",
                    }
                ]
            },
        ),
    ]
    session = _session(
        sandbox_meta={
            UPGRADE_SESSION_META_KEY: {
                "status": "suggested",
                "suggestion_id": "sug-1",
                "matched_rules": [RULE_FLOW_STEPS_GTE_3],
            }
        }
    )
    db = _make_db(messages)
    agentteams = _make_agentteams()
    service = AgentTeamsUpgradeService(db, agentteams)

    result = await service.accept(session, "user-a")

    assert result["status"] == "upgraded"
    room_id = result["room_id"]
    # 房间创建走 Case 解耦后的房间实体：origin=l2_upgrade，不创建 Case。
    agentteams.create_room_namespace.assert_awaited_once()
    # 反向链接：房间记录来源 L2 会话 id。
    added_room = db.add.call_args.args[0]
    assert isinstance(added_room, AgentTeamsRoomModel)
    assert added_room.origin == ROOM_ORIGIN_L2_UPGRADE
    assert added_room.origin_ref == "sess-1"
    # L2 会话只读标记。
    marker = session.sandbox_meta[UPGRADE_SESSION_META_KEY]
    assert marker["status"] == "upgraded"
    assert marker["room_id"] == room_id
    assert marker["matched_rules"] == [RULE_FLOW_STEPS_GTE_3]
    # 首条系统消息：房间命名空间流上的结构化上下文摘要。
    agentteams.post_case_evidence.assert_awaited_once()
    call = agentteams.post_case_evidence.await_args
    assert call.args[0] == room_namespace_case_id(room_id)
    assert call.kwargs["event_type"] == ROOM_UPGRADE_CONTEXT_EVENT_TYPE
    payload = call.kwargs["payload"]
    assert payload["objective"] == "3vs3"
    assert payload["source_session_id"] == "sess-1"
    assert payload["context_refs"][0]["location"] == "workspace/chat-uploads/f1.ssess-1.csv"
    assert payload["clarified_conclusions"][0]["answer"] == "3vs3"
    assert result["context_summary"]["objective"] == "3vs3"


@pytest.mark.asyncio
async def test_accept_is_idempotent_after_upgrade() -> None:
    session = _session(
        sandbox_meta={
            UPGRADE_SESSION_META_KEY: {"status": "upgraded", "room_id": "room-existing"}
        }
    )
    agentteams = _make_agentteams()
    service = AgentTeamsUpgradeService(_make_db([]), agentteams)

    result = await service.accept(session, "user-a")

    assert result == {
        "status": "upgraded",
        "room_id": "room-existing",
        "idempotent_replay": True,
    }
    agentteams.create_room_namespace.assert_not_called()


@pytest.mark.asyncio
async def test_accept_works_after_dismissal() -> None:
    session = _session(
        sandbox_meta={
            UPGRADE_SESSION_META_KEY: {"status": "dismissed", "matched_rules": []}
        }
    )
    db = _make_db([_message("user", "帮我分析单细胞数据")])
    agentteams = _make_agentteams()
    service = AgentTeamsUpgradeService(db, agentteams)

    result = await service.accept(session, "user-a")

    assert result["status"] == "upgraded"
    assert session.sandbox_meta[UPGRADE_SESSION_META_KEY]["status"] == "upgraded"


@pytest.mark.asyncio
async def test_dismiss_marks_session_and_suppresses_future_cards() -> None:
    session = _session(
        sandbox_meta={
            UPGRADE_SESSION_META_KEY: {
                "status": "suggested",
                "suggestion_id": "sug-1",
                "matched_rules": [RULE_EXPLICIT_REQUEST],
            }
        }
    )
    db = _make_db([])
    service = AgentTeamsUpgradeService(db, agentteams=None)

    result = await service.dismiss(session)

    assert result == {"status": "dismissed"}
    marker = session.sandbox_meta[UPGRADE_SESSION_META_KEY]
    assert marker["status"] == "dismissed"
    assert upgrade_suggestion_allowed(session.sandbox_meta) is False
    db.flush.assert_awaited()


@pytest.mark.asyncio
async def test_dismiss_requires_pending_suggestion() -> None:
    service = AgentTeamsUpgradeService(_make_db([]), agentteams=None)
    with pytest.raises(BusinessError, match="没有待处理的升级建议"):
        await service.dismiss(_session())
    upgraded = _session(
        sandbox_meta={UPGRADE_SESSION_META_KEY: {"status": "upgraded", "room_id": "r1"}}
    )
    with pytest.raises(BusinessError, match="已升级至协作室"):
        await service.dismiss(upgraded)


@pytest.mark.asyncio
async def test_accept_uses_real_room_service_contract() -> None:
    # 与真实 AgentTeamsRoomService 对齐：create_room(origin=...) + post_system_message。
    session = _session()
    db = _make_db([_message("user", "分析单细胞数据")])
    agentteams = _make_agentteams()
    service = AgentTeamsUpgradeService(
        db,
        agentteams,
        room_service_factory=lambda d, a: AgentTeamsRoomService(d, a),
    )

    result = await service.accept(session, "user-a")

    assert result["status"] == "upgraded"
    assert agentteams.post_case_evidence.await_args.kwargs["event_type"] == (
        ROOM_UPGRADE_CONTEXT_EVENT_TYPE
    )


# ---------------------------------------------------------------------------
# C2：veto 可审计 + "介绍"词表收窄
# ---------------------------------------------------------------------------


def test_consultation_veto_records_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    """否决命中不再静默：记录 vetoed 事件，detail 含命中词/消息摘要/会话 id。"""
    recorded: list[tuple[str, tuple[str, ...], str]] = []
    monkeypatch.setattr(
        "cygnusx.application.services.agentteams_upgrade_advisor.record_upgrade_event",
        lambda event, *, matched_rules=(), detail="": recorded.append(
            (event, tuple(matched_rules), detail)
        ),
    )

    decision = evaluate_upgrade_trigger(
        "RNA-seq 是什么", flows=_FLOWS, ability_catalog=_FakeAbilityCatalog(set()),
        session_id="sess-1",
    )

    assert decision is None
    assert recorded == [("vetoed", ("consultation_veto",), recorded[0][2])]
    detail = recorded[0][2]
    assert "matched=是什么" in detail
    assert "RNA-seq 是什么" in detail
    assert "session=sess-1" in detail


def test_veto_telemetry_does_not_fire_without_veto(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        "cygnusx.application.services.agentteams_upgrade_advisor.record_upgrade_event",
        lambda event, *, matched_rules=(), detail="": recorded.append((event,)),
    )

    decision = _evaluate("我有 6 个单细胞样本，帮我跑完整分析流程")

    assert decision is not None
    assert recorded == []


def test_intro_wording_narrowed_to_request_forms() -> None:
    # 收窄后："介绍一下/详细介绍"仍是咨询否决；陈述性的"介绍给导师"不再误判。
    assert _evaluate("介绍一下单细胞测序", marked={"agent-scrna"}) is None
    assert _evaluate("详细介绍一下单细胞测序流程", marked={"agent-scrna"}) is None
    decision = _evaluate("帮我把单细胞分析结果介绍给导师", marked={"agent-scrna"})
    assert decision is not None
    assert RULE_REQUIRES_FORMAL_DELIVERY in decision.matched_rules
