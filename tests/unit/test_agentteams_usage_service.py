"""AgentTeams 协作室用量落库与饼干扣费单元测试。"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from omichub.application.services import agentteams_usage_service as usage_service
from omichub.application.services.agentteams_usage_service import record_consultation_usage
from omichub.application.services.cookie_service import CookieService
from omichub.domain.cookie.entities import CookieAccount
from omichub.domain.cookie.value_objects import TransactionType
from omichub.infrastructure.database.models.chat import ChatMessageModel, ChatSessionModel


class _FakeNested:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeDB:
    """捕获 add/commit 的伪 AsyncSession；execute 只服务会话重查。"""

    def __init__(self, session_row: ChatSessionModel | None = None) -> None:
        self.added: list[object] = []
        self.commits = 0
        self._session_row = session_row

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.commits += 1

    def begin_nested(self) -> _FakeNested:
        return _FakeNested()

    async def execute(self, _stmt: object) -> SimpleNamespace:
        return SimpleNamespace(scalar_one_or_none=lambda: self._session_row)


def _model_config() -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), name="doubao 配置", model="doubao-pro")


def _usage(total: int = 150) -> dict[str, int]:
    return {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": total}


def _stub_cookie_service(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    stub = SimpleNamespace(spend_ai_tokens=AsyncMock(return_value=Decimal("0.15")))
    monkeypatch.setattr(usage_service, "CookieService", lambda db: stub)
    return stub


@pytest.mark.asyncio
async def test_records_session_and_message_and_spends_cookies(monkeypatch) -> None:
    stub = _stub_cookie_service(monkeypatch)
    db = _FakeDB()
    user_id = str(uuid4())
    agentteams = SimpleNamespace(
        get_case=AsyncMock(return_value={"intent": "RNA-seq 差异表达分析方案评审"})
    )

    message_id = await record_consultation_usage(
        db,
        case_id="case-1",
        agent_id="agent-rnaseq",
        requester_ref=user_id,
        usage=_usage(150),
        conclusion="会诊结论正文",
        model_config=_model_config(),
        agentteams_service=agentteams,
    )

    assert message_id is not None and message_id.startswith("at:")
    session = next(obj for obj in db.added if isinstance(obj, ChatSessionModel))
    message = next(obj for obj in db.added if isinstance(obj, ChatMessageModel))
    assert session.session_id == "agentteams:case-1"
    assert session.user_id == user_id
    assert session.status == "system"
    assert session.mode == "agentteams"
    assert session.title == "协作室 · RNA-seq 差异表达分析方案评审"
    assert session.total_tokens == 150
    assert session.message_count == 1
    assert session.last_message_at is not None
    assert message.session_id == session.session_id
    assert message.message_id == message_id
    assert message.role == "assistant"
    assert message.status == "complete"
    assert message.content == "会诊结论正文"
    assert message.metadata_json["usage"] == {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
    }
    assert message.metadata_json["source"] == "agentteams"
    assert message.metadata_json["case_id"] == "case-1"
    assert message.metadata_json["agent_id"] == "agent-rnaseq"
    assert message.metadata_json["provider"] == "doubao 配置"
    assert message.metadata_json["model"] == "doubao-pro"
    assert db.commits == 1
    stub.spend_ai_tokens.assert_awaited_once()
    kwargs = stub.spend_ai_tokens.await_args.kwargs
    assert kwargs["user_id"] == UUID(user_id)
    assert kwargs["tokens"] == 150
    assert kwargs["source_id"] == message_id


@pytest.mark.asyncio
async def test_title_falls_back_when_case_lookup_fails(monkeypatch) -> None:
    _stub_cookie_service(monkeypatch)
    db = _FakeDB()
    agentteams = SimpleNamespace(get_case=AsyncMock(side_effect=RuntimeError("bridge down")))

    await record_consultation_usage(
        db,
        case_id="case-2",
        agent_id="agent-rnaseq",
        requester_ref=str(uuid4()),
        usage=_usage(10),
        conclusion="结论",
        model_config=_model_config(),
        agentteams_service=agentteams,
    )

    session = next(obj for obj in db.added if isinstance(obj, ChatSessionModel))
    assert session.title == "协作室会话"


@pytest.mark.asyncio
async def test_existing_session_reused_and_counters_accumulate(monkeypatch) -> None:
    _stub_cookie_service(monkeypatch)
    existing = ChatSessionModel(
        session_id="agentteams:case-3",
        user_id=str(uuid4()),
        title="协作室 · 既有",
        status="system",
        mode="agentteams",
        model_id=uuid4(),
        message_count=2,
        total_tokens=300,
    )
    db = _FakeDB(session_row=existing)

    await record_consultation_usage(
        db,
        case_id="case-3",
        agent_id="agent-atac",
        requester_ref=existing.user_id,
        usage=_usage(150),
        conclusion="新一轮结论",
        model_config=_model_config(),
    )

    assert not [obj for obj in db.added if isinstance(obj, ChatSessionModel)]
    assert existing.total_tokens == 450
    assert existing.message_count == 3


@pytest.mark.asyncio
async def test_same_message_id_not_double_charged(monkeypatch) -> None:
    """同一 message_id 重复记录：spend_ai_tokens 幂等键命中，只扣一次。"""
    account = CookieAccount(id=1, user_id=uuid4(), balance=Decimal("100"))
    svc = CookieService(session=MagicMock())
    svc.get_or_create_account = AsyncMock(return_value=account)
    svc._record_transaction = AsyncMock()
    svc.resolve_ai_token_rate = AsyncMock(
        return_value=(Decimal("1"), Decimal("1"), None)
    )
    svc._txn_repo.list_by_source = AsyncMock(
        side_effect=[[], [MagicMock(txn_type=TransactionType.SPEND)]]
    )
    monkeypatch.setattr(usage_service, "CookieService", lambda db: svc)
    model_config = _model_config()
    kwargs = dict(
        case_id="case-4",
        agent_id="agent-rnaseq",
        requester_ref=str(account.user_id),
        usage=_usage(150),
        conclusion="结论",
        model_config=model_config,
        message_id="at:fixed",
    )

    await record_consultation_usage(_FakeDB(), **kwargs)
    existing = ChatSessionModel(
        session_id="agentteams:case-4",
        user_id=str(account.user_id),
        title="协作室会话",
        status="system",
        mode="agentteams",
        model_id=model_config.id,
    )
    await record_consultation_usage(_FakeDB(session_row=existing), **kwargs)

    svc._record_transaction.assert_awaited_once()


@pytest.mark.asyncio
async def test_skips_when_total_non_positive_or_requester_invalid(monkeypatch) -> None:
    stub = _stub_cookie_service(monkeypatch)

    db_zero = _FakeDB()
    assert (
        await record_consultation_usage(
            db_zero,
            case_id="case-5",
            agent_id="agent-rnaseq",
            requester_ref=str(uuid4()),
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            conclusion="结论",
            model_config=_model_config(),
        )
        is None
    )
    assert await record_consultation_usage(
        _FakeDB(),
        case_id="case-5",
        agent_id="agent-rnaseq",
        requester_ref=str(uuid4()),
        usage=None,
        conclusion="结论",
        model_config=_model_config(),
    ) is None
    assert db_zero.added == [] and db_zero.commits == 0

    assert (
        await record_consultation_usage(
            _FakeDB(),
            case_id="case-5",
            agent_id="agent-rnaseq",
            requester_ref="not-a-uuid",
            usage=_usage(150),
            conclusion="结论",
            model_config=_model_config(),
        )
        is None
    )
    stub.spend_ai_tokens.assert_not_awaited()


@pytest.mark.asyncio
async def test_records_but_skips_spending_when_cookie_system_disabled(monkeypatch) -> None:
    stub = _stub_cookie_service(monkeypatch)
    settings = usage_service.get_settings()
    monkeypatch.setattr(settings, "enable_cookie_system", False)

    message_id = await record_consultation_usage(
        _FakeDB(),
        case_id="case-6",
        agent_id="agent-rnaseq",
        requester_ref=str(uuid4()),
        usage=_usage(150),
        conclusion="结论",
        model_config=_model_config(),
    )

    assert message_id is not None
    stub.spend_ai_tokens.assert_not_awaited()
