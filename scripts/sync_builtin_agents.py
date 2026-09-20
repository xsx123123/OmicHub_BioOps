#!/usr/bin/env python3
"""Synchronize YAML-managed built-in Agent declarations into the database."""

from __future__ import annotations

import asyncio

from cygnusx.application.services.agent_service import AgentService
from cygnusx.infrastructure.database.session import get_session_factory


async def sync_builtin_agents() -> None:
    async with get_session_factory()() as db:
        await AgentService(db).ensure_builtin_agents()
        await db.commit()


if __name__ == "__main__":
    asyncio.run(sync_builtin_agents())
