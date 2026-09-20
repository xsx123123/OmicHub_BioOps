"""ProjectOverviewService 单元测试（mock DB + tmp 磁盘目录）。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from cygnusx.application.services.project_overview_service import ProjectOverviewService
from cygnusx.core.exceptions import NotFoundError


class _FakeResult:
    """按调用形态分发的假 SQLAlchemy Result。"""

    def __init__(self, *, scalar_one_or_none=None, scalar_one=0, scalars=()):  # noqa: ANN001, ANN204
        self._scalar_one_or_none = scalar_one_or_none
        self._scalar_one = scalar_one
        self._scalars = list(scalars)

    def scalar_one_or_none(self):  # noqa: ANN202
        return self._scalar_one_or_none

    def scalar_one(self):  # noqa: ANN202
        return self._scalar_one

    def scalars(self):  # noqa: ANN202
        return SimpleNamespace(all=lambda: list(self._scalars))


class _FakeFactory:
    """只实现 overview 扫描用到的 project_dir。"""

    def __init__(self, root: Path):
        self._root = root

    def project_dir(self, user_id: str, project_slug: str) -> Path:
        return self._root / "users" / user_id / "projects" / project_slug


def _project(user_id):  # noqa: ANN001, ANN202
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        name="COP1-HY5 示例分析",
        slug="cop1-hy5-demo",
        description="示例项目",
        created_at=now,
        updated_at=now,
    )


def _chat_session(project_id):  # noqa: ANN001, ANN202
    now = datetime.now(UTC)
    return SimpleNamespace(
        session_id="sess-abc",
        title="差异表达分析",
        agent_id="rna-expert",
        status="active",
        mode="chat",
        message_count=12,
        last_message_at=now,
        project_id=str(project_id),
        created_at=now,
        updated_at=now,
    )


def _room(project_id, *, room_id="room-1", status="active", case_id=None, updated_at=None):  # noqa: ANN001, ANN202
    now = updated_at or datetime.now(UTC)
    return SimpleNamespace(
        room_id=room_id,
        owner_id="owner-1",
        title="协作室：单细胞分析",
        status=status,
        case_id=case_id,
        project_id=str(project_id),
        created_at=now,
        updated_at=now,
    )


def _make_service(project, sessions, runs_root: Path, rooms=()) -> ProjectOverviewService:  # noqa: ANN001
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _FakeResult(scalar_one_or_none=project),  # _load_project
            _FakeResult(scalar_one=len(sessions)),  # chat sessions total
            _FakeResult(scalars=sessions),  # chat sessions items
            _FakeResult(scalars=rooms),  # agentteams rooms
        ]
    )
    return ProjectOverviewService(session, factory=_FakeFactory(runs_root))  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_overview_aggregates_project_sessions_and_runs(tmp_path: Path) -> None:
    user_id = uuid4()
    project = _project(user_id)
    session_row = _chat_session(project.id)

    runs_dir = tmp_path / "users" / str(user_id) / "projects" / project.slug / "runs"
    run = runs_dir / "rna-seq-20260901-101530"
    (run / "output").mkdir(parents=True)
    (run / "AGENTS.md").write_text("# run", encoding="utf-8")
    (run / "README.md").write_text("readme", encoding="utf-8")
    (run / "environment.json").write_text("{}", encoding="utf-8")
    (run / "output" / "result.tsv").write_text("a\tb\n", encoding="utf-8")
    legacy = runs_dir / "atac-20260801-000000"
    legacy.mkdir()

    service = _make_service(project, [session_row], tmp_path)
    overview = await service.get_overview(user_id, project.id, session_limit=20, session_offset=0)

    assert overview["project"]["id"] == str(project.id)
    assert overview["project"]["slug"] == "cop1-hy5-demo"
    # ProjectModel 尚无 customer 字段时兜底为 None
    assert overview["project"]["customer"] is None

    sessions = overview["sessions"]
    assert sessions["total"] == 1
    assert sessions["limit"] == 20
    assert sessions["offset"] == 0
    assert sessions["items"][0]["id"] == "sess-abc"
    assert sessions["items"][0]["agent_id"] == "rna-expert"
    assert sessions["items"][0]["message_count"] == 12
    assert sessions["items"][0]["last_message_at"] is not None
    assert sessions["items"][0]["room_id"] is None
    assert sessions["items"][0]["case_id"] is None

    runs = overview["runs"]
    assert [r["name"] for r in runs] == ["rna-seq-20260901-101530", "atac-20260801-000000"]
    first = runs[0]
    assert first["timestamp"] == "2026-09-01T10:15:30+00:00"
    assert first["has_agents_md"] and first["has_readme"] and first["has_environment"]
    assert first["file_count"] == 4
    assert first["total_size_bytes"] > 0
    second = runs[1]
    assert not (second["has_agents_md"] or second["has_readme"] or second["has_environment"])
    assert second["file_count"] == 0


@pytest.mark.asyncio
async def test_overview_missing_runs_dir_returns_empty(tmp_path: Path) -> None:
    user_id = uuid4()
    project = _project(user_id)
    service = _make_service(project, [], tmp_path)

    overview = await service.get_overview(user_id, project.id)

    assert overview["runs"] == []
    assert overview["sessions"]["total"] == 0
    assert overview["sessions"]["items"] == []


@pytest.mark.asyncio
async def test_overview_project_not_found(tmp_path: Path) -> None:
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=None))
    service = ProjectOverviewService(session, factory=_FakeFactory(tmp_path))  # type: ignore[arg-type]

    with pytest.raises(NotFoundError):
        await service.get_overview(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_overview_merges_agentteams_rooms_sorted_and_paginated(tmp_path: Path) -> None:
    """agentteams 房间作为 mode=agentteams 条目并入 sessions 段，统一按更新时间倒序分页。"""
    user_id = uuid4()
    project = _project(user_id)
    older = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    newer = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
    chat_row = _chat_session(project.id)
    chat_row.updated_at = older
    room = _room(project.id, room_id="room-xyz", case_id="case-9", updated_at=newer)

    service = _make_service(project, [chat_row], tmp_path, rooms=[room])
    overview = await service.get_overview(user_id, project.id, session_limit=10, session_offset=0)

    sessions = overview["sessions"]
    assert sessions["total"] == 2
    assert [item["id"] for item in sessions["items"]] == ["room-xyz", "sess-abc"]
    room_item = sessions["items"][0]
    assert room_item["mode"] == "agentteams"
    assert room_item["status"] == "active"
    assert room_item["agent_id"] is None
    assert room_item["message_count"] == 0
    assert room_item["room_id"] == "room-xyz"
    assert room_item["case_id"] == "case-9"
    assert room_item["last_message_at"] == newer.isoformat()


@pytest.mark.asyncio
async def test_overview_agentteams_rooms_participate_in_status_views(tmp_path: Path) -> None:
    """session_status=archived 时仅保留映射为 archived 的房间（非 active/deleted 的其余状态）。"""
    user_id = uuid4()
    project = _project(user_id)
    rooms = [
        _room(project.id, room_id="room-active", status="active"),
        _room(project.id, room_id="room-closed", status="closed"),
        _room(project.id, room_id="room-deleted", status="deleted"),
    ]

    service = _make_service(project, [], tmp_path, rooms=rooms)
    overview = await service.get_overview(user_id, project.id, session_status="archived")

    sessions = overview["sessions"]
    assert sessions["total"] == 1
    assert sessions["items"][0]["room_id"] == "room-closed"
    assert sessions["items"][0]["status"] == "archived"


@pytest.mark.asyncio
async def test_overview_active_view_excludes_non_active_rooms(tmp_path: Path) -> None:
    user_id = uuid4()
    project = _project(user_id)
    rooms = [
        _room(project.id, room_id="room-active", status="active"),
        _room(project.id, room_id="room-closed", status="closed"),
    ]

    service = _make_service(project, [], tmp_path, rooms=rooms)
    overview = await service.get_overview(user_id, project.id)

    assert [item["room_id"] for item in overview["sessions"]["items"]] == ["room-active"]
    assert overview["sessions"]["total"] == 1
