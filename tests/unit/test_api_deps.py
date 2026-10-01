"""数据库依赖在请求取消时必须清理事务。"""

from __future__ import annotations

import asyncio

import pytest

from cygnusx.api import deps


class _Session:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _SessionContext:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> _Session:
        return self.session

    async def __aexit__(self, *_args: object) -> bool:
        return False


@pytest.mark.asyncio
async def test_get_db_rolls_back_cancelled_request(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    monkeypatch.setattr(
        deps,
        "get_session_factory",
        lambda: lambda: _SessionContext(session),
    )

    generator = deps.get_db()
    assert await generator.__anext__() is session
    with pytest.raises(asyncio.CancelledError):
        await generator.athrow(asyncio.CancelledError())

    assert session.commits == 0
    assert session.rollbacks == 1
