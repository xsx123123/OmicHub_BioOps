"""AI 对话饼干计费单元测试 — spend_ai_tokens 扣减 / 封顶 + 对话准入闸门。"""

from datetime import UTC, date, datetime, time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from omichub.application.services.cookie_service import CookieService
from omichub.domain.cookie.entities import CookieAccount
from omichub.domain.cookie.value_objects import TransactionType
from omichub.infrastructure.database.models.cookie import CookieDiscountModel


def _service_with_account(balance: str) -> tuple[CookieService, CookieAccount]:
    svc = CookieService(session=MagicMock())
    account = CookieAccount(id=1, user_id=uuid4(), balance=Decimal(balance))
    svc.get_or_create_account = AsyncMock(return_value=account)
    svc._record_transaction = AsyncMock()
    svc._txn_repo.list_by_source = AsyncMock(return_value=[])
    svc.resolve_ai_token_rate = AsyncMock(
        return_value=(Decimal("1"), Decimal("1"), None)
    )
    return svc, account


@pytest.mark.asyncio
async def test_spend_ai_tokens_deducts_by_rate():
    svc, account = _service_with_account("100.00")

    cost = await svc.spend_ai_tokens(account.user_id, tokens=1500, source_id="msg-1")

    assert cost == Decimal("1.50")  # 1500 / 1000 * 1 🥫
    svc._record_transaction.assert_awaited_once()
    kwargs = svc._record_transaction.call_args
    assert kwargs.args[2] == Decimal("-1.50")
    assert kwargs.kwargs["source_type"] == "ai_chat"


@pytest.mark.asyncio
async def test_spend_ai_tokens_caps_at_available_balance():
    svc, account = _service_with_account("1.00")

    cost = await svc.spend_ai_tokens(account.user_id, tokens=1500, source_id="msg-1")

    assert cost == Decimal("1.00")
    assert svc._record_transaction.call_args.args[2] == Decimal("-1.00")


@pytest.mark.asyncio
async def test_spend_ai_tokens_skips_when_broke_or_invalid():
    svc, account = _service_with_account("0.00")
    assert await svc.spend_ai_tokens(account.user_id, tokens=1500, source_id="m") == Decimal("0")
    assert await svc.spend_ai_tokens(account.user_id, tokens=0, source_id="m") == Decimal("0")
    svc._record_transaction.assert_not_awaited()


@pytest.mark.asyncio
async def test_spend_ai_tokens_is_idempotent_per_message():
    svc, account = _service_with_account("100.00")
    svc._txn_repo.list_by_source = AsyncMock(
        return_value=[MagicMock(txn_type=TransactionType.SPEND)]
    )

    cost = await svc.spend_ai_tokens(account.user_id, tokens=1500, source_id="msg-1")

    assert cost == Decimal("0")
    svc._record_transaction.assert_not_awaited()


@pytest.mark.asyncio
async def test_spend_ai_tokens_applies_active_discount_rate():
    svc, account = _service_with_account("100.00")
    discount = MagicMock(name="夜间优惠")
    discount.name = "夜间优惠"
    svc.resolve_ai_token_rate = AsyncMock(
        return_value=(Decimal("1"), Decimal("0.01"), discount)
    )

    cost = await svc.spend_ai_tokens(account.user_id, tokens=1500, source_id="msg-2")

    assert cost == Decimal("0.02")
    assert svc._record_transaction.call_args.args[2] == Decimal("-0.02")
    assert "夜间优惠" in svc._record_transaction.call_args.kwargs["description"]


def test_discount_window_supports_overnight_period():
    discount = CookieDiscountModel(
        name="夜间优惠",
        discount_multiplier=Decimal("0.01"),
        date_start=date(2026, 7, 23),
        date_end=date(2026, 7, 24),
        daily_start=time(22, 0),
        daily_end=time(2, 0),
        timezone="Asia/Shanghai",
        banner_title="夜间优惠",
        banner_description="测试",
    )

    assert CookieService._discount_matches(
        discount, datetime(2026, 7, 23, 15, 0, tzinfo=UTC)
    )
    assert CookieService._discount_matches(
        discount, datetime(2026, 7, 23, 17, 0, tzinfo=UTC)
    )
    assert not CookieService._discount_matches(
        discount, datetime(2026, 7, 23, 8, 0, tzinfo=UTC)
    )


@pytest.mark.asyncio
async def test_chat_gate_blocks_when_balance_empty():
    from omichub.application.services.chat_service import ChatService

    svc = ChatService(db=MagicMock())
    with patch(
        "omichub.application.services.cookie_service.CookieService.check_balance",
        AsyncMock(return_value=Decimal("0")),
    ):
        message = await svc._ensure_cookie_balance(str(uuid4()))

    assert message is not None
    assert "饼干余额不足" in message


@pytest.mark.asyncio
async def test_chat_gate_passes_with_balance():
    from omichub.application.services.chat_service import ChatService

    svc = ChatService(db=MagicMock())
    with patch(
        "omichub.application.services.cookie_service.CookieService.check_balance",
        AsyncMock(return_value=Decimal("3.5")),
    ):
        assert await svc._ensure_cookie_balance(str(uuid4())) is None
