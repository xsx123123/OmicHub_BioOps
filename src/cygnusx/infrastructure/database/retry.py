"""Small retry helpers for transient database connection failures."""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession


def _is_connection_closed(error: BaseException) -> bool:
    """Recognize driver/pool disconnects without retrying arbitrary SQL errors."""
    if isinstance(error, DBAPIError) and error.connection_invalidated:
        return True
    driver_error = getattr(error, "orig", error)
    name = type(driver_error).__name__.lower()
    message = str(driver_error).lower()
    return "interfaceerror" in name or "connection is closed" in message


async def execute_read_with_retry(
    session: AsyncSession,
    statement: Any,
    *,
    attempts: int = 2,
) -> Any:
    """Execute a read query once more after a transient closed connection.

    The rollback is intentional: an async SQLAlchemy session may still be in the
    failed transaction that held the dead connection. Writes are excluded from
    this helper because replaying them could duplicate side effects.
    """
    for attempt in range(max(1, attempts)):
        try:
            return await session.execute(statement)
        except Exception as exc:  # noqa: BLE001 - driver errors vary by asyncpg version
            if attempt + 1 >= attempts or not _is_connection_closed(exc):
                raise
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001 - the connection is already dead
                pass
    raise RuntimeError("unreachable")
