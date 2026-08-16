"""技能版本控制单元测试：快照 / 版本列表 / 回滚（FakeSession 不落真实 DB）"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList

from omichub.application.schemas.skill import CreateSkillDTO, UpdateSkillDTO
from omichub.application.services.skill_service import SkillService
from omichub.core.exceptions import NotFoundError
from omichub.infrastructure.database.models.skill import SkillModel, SkillVersionModel

# ---------- 内存版 AsyncSession：按 statement 实体 + where 条件分发 ----------


class _Result:
    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows

    def scalar_one_or_none(self):
        return self._scalar

    def scalar(self):
        return self._scalar

    def scalars(self):
        rows = list(self._rows or [])
        return type("Scalars", (), {"all": staticmethod(lambda: rows)})()


def _where_filters(stmt) -> dict:
    filters: dict = {}

    def walk(clause):
        if isinstance(clause, BooleanClauseList):
            for sub in clause.clauses:
                walk(sub)
        elif isinstance(clause, BinaryExpression):
            name = getattr(clause.left, "name", None)
            if name:
                filters[name] = getattr(clause.right, "value", None)

    if stmt.whereclause is not None:
        walk(stmt.whereclause)
    return filters


class FakeSession:
    def __init__(self):
        self.skill: SkillModel | None = None
        self.versions: list[SkillVersionModel] = []

    def add(self, obj):
        now = datetime.now(UTC)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now
        if isinstance(obj, SkillModel):
            self.skill = obj
        elif isinstance(obj, SkillVersionModel):
            self.versions.append(obj)

    async def flush(self):
        # 模拟列级 default（真实会话由 INSERT 时填充）
        if self.skill is not None:
            if self.skill.source_type is None:
                self.skill.source_type = "json"
            if self.skill.has_scripts is None:
                self.skill.has_scripts = False

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0].get("entity")
        filters = _where_filters(stmt)
        if entity is SkillModel:
            hit = (
                self.skill
                if self.skill and self.skill.skill_id == filters.get("skill_id")
                else None
            )
            return _Result(scalar=hit)
        if entity is SkillVersionModel:
            rows = [v for v in self.versions if v.skill_id == filters.get("skill_id")]
            if stmt.column_descriptions[0].get("expr") is not SkillVersionModel:
                # func.max(SkillVersionModel.revision) 聚合查询
                revs = [v.revision for v in rows]
                return _Result(scalar=max(revs) if revs else None)
            if "revision" in filters:
                hit = next((v for v in rows if v.revision == filters["revision"]), None)
                return _Result(scalar=hit)
            rows.sort(key=lambda v: v.revision, reverse=True)
            return _Result(rows=rows)
        raise AssertionError(f"FakeSession 未处理的查询: {stmt}")


@pytest.fixture
def env(monkeypatch):
    db = FakeSession()
    disk_calls: list = []
    monkeypatch.setattr(
        "omichub.application.services.skill_service.rewrite_skill_md",
        lambda parsed: disk_calls.append(parsed) or True,
    )
    return SkillService(db), db, disk_calls


def _create_dto(**overrides) -> CreateSkillDTO:
    base = dict(
        skill_id="demo-skill",
        name="示例技能",
        description="初版描述",
        prompt="初版正文",
        icon="🧬",
        category="general",
    )
    base.update(overrides)
    return CreateSkillDTO(**base)


# ---------- 快照 ----------


@pytest.mark.asyncio
async def test_create_skill_snapshots_revision_1(env):
    service, db, _ = env
    actor = uuid.uuid4()
    await service.create_skill(_create_dto(), actor_id=actor)

    assert len(db.versions) == 1
    snap = db.versions[0]
    assert snap.revision == 1
    assert snap.source == "admin"
    assert snap.changelog == "创建技能"
    assert snap.created_by == actor
    assert snap.prompt == "初版正文"
    assert snap.name == "示例技能"


@pytest.mark.asyncio
async def test_update_skill_creates_new_revision_and_rewrites_disk(env):
    service, db, disk_calls = env
    await service.create_skill(_create_dto())
    await service.update_skill(
        "demo-skill", UpdateSkillDTO(prompt="第二版正文", description="第二版描述")
    )

    assert len(db.versions) == 2
    snap = db.versions[-1]
    assert snap.revision == 2
    assert snap.source == "admin"
    assert "prompt" in snap.changelog and "description" in snap.changelog
    assert snap.prompt == "第二版正文"  # 快照记录更新后的最终值
    # 内容字段变更 → 磁盘 SKILL.md 同步重写
    assert len(disk_calls) == 1
    assert disk_calls[0].body == "第二版正文"


@pytest.mark.asyncio
async def test_toggle_skill_does_not_snapshot(env):
    service, db, disk_calls = env
    await service.create_skill(_create_dto())
    dto = await service.toggle_skill("demo-skill")

    assert dto.is_active is False
    assert len(db.versions) == 1  # 启停是操作不是内容变更
    assert disk_calls == []


# ---------- 版本列表 ----------


@pytest.mark.asyncio
async def test_list_versions_desc(env):
    service, db, _ = env
    await service.create_skill(_create_dto())
    await service.update_skill("demo-skill", UpdateSkillDTO(prompt="v2"))

    versions = await service.list_skill_versions("demo-skill")
    assert [v.revision for v in versions] == [2, 1]
    assert versions[0].source == "admin"


@pytest.mark.asyncio
async def test_list_versions_unknown_skill(env):
    service, _, _ = env
    with pytest.raises(NotFoundError):
        await service.list_skill_versions("nope")


# ---------- 回滚 ----------


@pytest.mark.asyncio
async def test_rollback_restores_fields_and_snapshots(env):
    service, db, disk_calls = env
    await service.create_skill(_create_dto())
    await service.update_skill(
        "demo-skill", UpdateSkillDTO(prompt="第二版正文", description="第二版描述")
    )

    dto = await service.rollback_skill("demo-skill", 1)

    assert dto.prompt == "初版正文"
    assert dto.description == "初版描述"
    # 回滚后新增一行 rollback 快照
    assert len(db.versions) == 3
    snap = db.versions[-1]
    assert snap.revision == 3
    assert snap.source == "rollback"
    assert snap.changelog == "回滚到 revision 1"
    assert snap.prompt == "初版正文"
    # 磁盘同步重写（正文还原）
    assert disk_calls[-1].body == "初版正文"


@pytest.mark.asyncio
async def test_rollback_missing_revision_raises(env):
    service, _, _ = env
    await service.create_skill(_create_dto())

    with pytest.raises(NotFoundError, match="revision 99"):
        await service.rollback_skill("demo-skill", 99)
