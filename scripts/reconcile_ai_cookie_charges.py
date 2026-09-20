"""为已落库但尚未产生饼干流水的 AI 消息补账。"""

from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import text

from cygnusx.application.services.cookie_service import CookieService
from cygnusx.core.config import get_settings
from cygnusx.infrastructure.database.session import get_session_factory


def _total_tokens(metadata: dict | None) -> int:
    usage = (metadata or {}).get("usage") or {}
    prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    return int(usage.get("total_tokens") or usage.get("total") or prompt + completion)


async def reconcile(apply: bool) -> int:
    settings = get_settings()
    factory = get_session_factory()
    async with factory() as db:
        result = await db.execute(
            text(
                "SELECT m.message_id, m.metadata_json, s.user_id "
                "FROM chat_messages AS m "
                "JOIN chat_sessions AS s ON s.session_id = m.session_id "
                "WHERE m.role = 'assistant' "
                "ORDER BY m.created_at"
            )
        )
        rows = result.all()
        total_tokens = 0
        total_cost = Decimal("0")
        billed = 0
        service = CookieService(db)
        for message_id, metadata_json, user_id in rows:
            tokens = _total_tokens(metadata_json)
            if tokens <= 0:
                continue
            rate = Decimal(str(settings.ai_token_cookie_rate))
            expected = (Decimal(tokens) / Decimal(1000) * rate).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            existing = await service._txn_repo.list_by_source("ai_chat", message_id)
            if any(txn.txn_type.value == "spend" for txn in existing):
                continue
            total_tokens += tokens
            total_cost += expected
            billed += 1
            if apply:
                await service.spend_ai_tokens(
                    user_id=user_id,
                    tokens=tokens,
                    source_id=message_id,
                )
        if apply:
            await db.commit()
        print(
            f"messages={billed} tokens={total_tokens} "
            f"estimated_cookie_cost={total_cost.quantize(Decimal('0.01'))} apply={apply}"
        )
        return billed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="实际写入 AI 饼干扣费流水")
    args = parser.parse_args()
    asyncio.run(reconcile(args.apply))


if __name__ == "__main__":
    main()
