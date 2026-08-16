"""Redis Pub/Sub — 饼干余额实时推送

交易完成后发布余额变更事件，WebSocket 端点订阅推送给前端。
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import UUID

from omichub.infrastructure.cache.redis_client import get_redis

COOKIE_BALANCE_CHANNEL_PREFIX = "omichub:cookie_balance:"


def get_cookie_balance_channel(user_id: UUID | str) -> str:
    """获取用户饼干余额频道名（带应用级前缀，避免多应用共享 Redis 时冲突）"""
    return f"{COOKIE_BALANCE_CHANNEL_PREFIX}{user_id}"


async def publish_cookie_balance(
    user_id: UUID,
    balance: Decimal,
    frozen_balance: Decimal,
    txn_type: str = "",
    amount: Decimal = Decimal("0"),
    description: str = "",
) -> None:
    """发布余额变更事件到 Redis Pub/Sub"""
    redis_client = get_redis()
    payload: dict[str, Any] = {
        "user_id": str(user_id),
        "balance": float(balance),
        "frozen_balance": float(frozen_balance),
        "available_balance": float(balance - frozen_balance),
        "txn_type": txn_type,
        "amount": float(amount),
        "description": description,
    }
    await redis_client.publish(get_cookie_balance_channel(user_id), json.dumps(payload))


async def subscribe_cookie_balance(user_id: UUID | str):
    """订阅用户余额变更频道，返回 pubsub 对象"""
    redis_client = get_redis()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(get_cookie_balance_channel(user_id))
    return pubsub
