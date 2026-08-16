"""MCP Builder 版本控制单元测试.

覆盖 builder 路径的版本管理闭环：
- 提交构建即落版本行（code + config 快照，source=builder）
- 同版本行在测试/审核阶段增量补齐（tools_snapshot）
- 回滚还原配置/工具/代码指针，并新增 source=rollback 版本行
- 沙箱调用按 current_version 写回代码（回滚后运行旧代码）
- 实验 MCP 转正生产池（source=publish 版本行）
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from omichub.application.schemas.mcp_builder import SubmitBuildRequest
from omichub.application.services.mcp_builder_service import MCPBuilderService
from omichub.core.exceptions import NotFoundError, ValidationError
from omichub.domain.mcp.entities import MCPServer, MCPToolRegistry
from omichub.domain.mcp.value_objects import (
    ReviewStatus,
    ServerPool,
    ServerStatus,
    Transport,
)
from omichub.infrastructure.database.models.mcp_builder import (
    MCPBuildModel,
    MCPVersionModel,
)

SAMPLE_MCP_CODE = '''"""echo MCP server"""

__exp_mcp_generated__ = True


async def list_tools():
    return [{"name": "echo", "description": "回显文本", "inputSchema": {"type": "object"}}]


async def call_tool(name, arguments):
    if name == "echo":
        return {"content": [{"type": "text", "text": str(arguments.get("text", ""))}]}
    raise ValueError("unknown tool")
'''


class _FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one(self):
        return self._rows[0]

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


def _version_filter(stmt):
    """从 where 子句中提取 MCPVersionModel.version 的等值过滤值"""
    where = stmt.whereclause
    clauses = getattr(where, "clauses", [where] if where is not None else [])
    for clause in clauses:
        left, right = getattr(clause, "left", None), getattr(clause, "right", None)
        if left is not None and str(left) == "mcp_versions.version":
            return getattr(right, "value", None)
    return None


class _FakeBuilderSession:
    """内存版 AsyncSession：覆盖版本表查询、计数、主键 get 与写入"""

    def __init__(self, versions=(), builds=()):
        self.versions = list(versions)
        self.builds = {b.id: b for b in builds}
        self.added = []

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, MCPVersionModel):
            self.versions.append(obj)
        if isinstance(obj, MCPBuildModel):
            self.builds[obj.id] = obj

    async def flush(self):
        pass

    async def refresh(self, _obj):
        pass

    async def get(self, _model, pk):
        return self.builds.get(pk)

    async def execute(self, stmt):
        name = stmt.column_descriptions[0]["name"]
        if "count" in name:  # _check_quota
            return _FakeResult([0])
        if name == "version":  # select(MCPVersionModel.version)
            return _FakeResult([v.version for v in self.versions])
        rows = list(self.versions)
        wanted = _version_filter(stmt)
        if wanted is not None:
            rows = [v for v in rows if v.version == wanted]
        return _FakeResult(rows)


def _settings(**overrides) -> SimpleNamespace:
    base = dict(
        mcp_builder_enabled=True,
        mcp_builder_requires_review=False,
        mcp_builder_max_per_user=10,
        mcp_builder_default_ttl_hours=24,
        mcp_default_timeout=30,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_service(versions=(), builds=(), **settings_overrides) -> tuple[MCPBuilderService, _FakeBuilderSession, MCPServer | None]:
    db = _FakeBuilderSession(versions, builds)
    service = MCPBuilderService(MagicMock())
    service._db = db
    service._repo = AsyncMock()
    service._repo.save.side_effect = lambda s: s
    service._repo.get_by_name.return_value = None
    service._settings = _settings(**settings_overrides)
    return service, db, None


def _server(**overrides) -> MCPServer:
    server_id = uuid4()
    server = MCPServer(
        id=server_id,
        name="exp-demo",
        description="desc",
        transport=Transport.STDIO,
        command="python",
        args=["/workspace/mcp-builds/demo/server.py"],
        status=ServerStatus.ONLINE,
        pool=ServerPool.EXPERIMENTAL,
        created_by=uuid4(),
        current_version="1.0.0",
        version="1.0.0",
        generation_meta={"build_id": str(uuid4()), "code_path": "mcp-builds/demo/server.py"},
        tools=[
            MCPToolRegistry(tool_name="tool_a", description="a", input_schema={}, server_id=server_id),
        ],
    )
    for key, value in overrides.items():
        setattr(server, key, value)
    return server


def _version_row(server_id: UUID, version: str, **overrides) -> MCPVersionModel:
    row = MCPVersionModel(
        id=uuid4(),
        mcp_server_id=server_id,
        version=version,
        is_major=False,
        source="builder",
        changelog="",
        created_at=datetime.now(),
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


# ----------------------------------------------------------------------
# 提交即落版本
# ----------------------------------------------------------------------
@pytest.mark.unit
async def test_submit_build_creates_full_version_snapshot():
    """提交构建：注册实验 MCP 并立即写入带 code + config 快照的 builder 版本行"""
    service, db, _ = _make_service()
    uid = uuid4()

    dto = await service.submit_build(
        str(uid),
        SubmitBuildRequest(requirement="echo 工具", code=SAMPLE_MCP_CODE, mcp_name="smoke"),
    )

    assert dto.version == "1.0.0"
    assert dto.status == "testing"  # 无审核流程 → 直接进入测试阶段

    # 注册的 server：实验池 + 双版本字段同步
    saved_server = service._repo.save.call_args.args[0]
    assert saved_server.pool == ServerPool.EXPERIMENTAL
    assert saved_server.current_version == "1.0.0"
    assert saved_server.version == "1.0.0"

    rows = [o for o in db.added if isinstance(o, MCPVersionModel)]
    assert len(rows) == 1
    row = rows[0]
    assert row.version == "1.0.0"
    assert row.source == "builder"
    assert row.code_snapshot == SAMPLE_MCP_CODE.strip()
    assert row.config_snapshot is not None
    assert row.config_snapshot["name"] == "exp-smoke"
    assert row.config_snapshot["transport"] == "stdio"
    assert row.changelog.startswith("初始构建：")
    assert row.build_id == dto.id


@pytest.mark.unit
async def test_snapshot_enriches_existing_row():
    """同版本行已存在（submit 创建）时，测试阶段发现工具后增量补齐而非跳过"""
    server = _server()
    build_id = uuid4()
    existing = _version_row(
        server.id, "1.0.0",
        code_snapshot=SAMPLE_MCP_CODE, tools_snapshot=[], config_snapshot=None,
    )
    service, db, _ = _make_service(versions=[existing])
    build = MCPBuildModel(id=build_id, user_id=uuid4(), requirement="echo", generated_code=SAMPLE_MCP_CODE)

    server.tools = [
        MCPToolRegistry(tool_name="echo", description="回显", input_schema={"type": "object"}, server_id=server.id),
    ]
    await service._snapshot_version(server, build)

    # 未新增行，原行被补齐
    assert len(db.versions) == 1
    assert existing.tools_snapshot == [
        {"name": "echo", "description": "回显", "inputSchema": {"type": "object"}}
    ]
    assert existing.config_snapshot is not None
    assert existing.config_snapshot["name"] == "exp-demo"
    assert existing.code_snapshot == SAMPLE_MCP_CODE


# ----------------------------------------------------------------------
# 回滚
# ----------------------------------------------------------------------
@pytest.mark.unit
async def test_rollback_restores_config_tools_and_code_pointer():
    """回滚：还原配置/工具快照 + 切换代码指针 + 新增 rollback 版本行"""
    owner = uuid4()
    orig_build_id = uuid4()
    server = _server(
        created_by=owner,
        current_version="1.0.1",
        version="1.0.1",
        description="new desc",
        generation_meta={"build_id": str(uuid4()), "code_path": "mcp-builds/demo/server.py"},
    )
    server.tools = [
        MCPToolRegistry(tool_name="tool_new", description="n", input_schema={}, server_id=server.id),
    ]
    target = _version_row(
        server.id, "1.0.0",
        build_id=orig_build_id,
        code_snapshot="OLD CODE",
        config_snapshot={"description": "old desc", "name": "exp-demo", "transport": "stdio"},
        tools_snapshot=[{"name": "tool_old", "description": "o", "inputSchema": {}}],
    )
    newer = _version_row(server.id, "1.0.1", source="admin",
                         config_snapshot={"description": "new desc"})
    service, db, _ = _make_service(versions=[target, newer])
    service._repo.get_by_id.return_value = server

    result = await service.rollback(str(server.id), "1.0.0", str(owner))

    # 配置/工具/版本指针还原
    assert server.description == "old desc"
    assert [t.tool_name for t in server.tools] == ["tool_old"]
    assert server.current_version == "1.0.0"
    assert server.version == "1.0.0"
    # 代码指针切到目标版本的构建（下次沙箱调用据此写回旧代码）
    assert server.generation_meta["build_id"] == str(orig_build_id)
    assert server.generation_meta["rolled_back_to"] == "1.0.0"

    # 回滚本身记一条新版本行
    rollback_rows = [v for v in db.versions if v.source == "rollback"]
    assert len(rollback_rows) == 1
    row = rollback_rows[0]
    assert row.version == "1.0.2"  # 在最大版本 1.0.1 上 bump patch
    assert row.changelog == "回滚到 v1.0.0"
    assert row.code_snapshot == "OLD CODE"
    assert row.config_snapshot["description"] == "old desc"
    assert row.created_by == owner

    assert result == {
        "id": str(server.id),
        "current_version": "1.0.0",
        "rollback_version": "1.0.2",
    }


@pytest.mark.unit
async def test_rollback_missing_version_raises():
    server = _server()
    service, _db, _ = _make_service()
    service._repo.get_by_id.return_value = server

    with pytest.raises(NotFoundError, match="版本 9.9.9 不存在"):
        await service.rollback(str(server.id), "9.9.9", str(server.created_by))


@pytest.mark.unit
async def test_rollback_requires_owner_or_admin():
    server = _server()
    service, _db, _ = _make_service()
    service._repo.get_by_id.return_value = server

    from omichub.core.exceptions import AuthorizationError

    with pytest.raises(AuthorizationError):
        await service.rollback(str(server.id), "1.0.0", str(uuid4()))


# ----------------------------------------------------------------------
# 沙箱调用按当前版本写回代码
# ----------------------------------------------------------------------
@pytest.mark.unit
async def test_call_experimental_tool_writes_current_version_code(monkeypatch):
    """调用前按 current_version 的 code_snapshot 写回沙箱，回滚后运行旧代码"""
    owner = uuid4()
    server = _server(
        created_by=owner,
        current_version="1.0.0",
        expires_at=None,
        generation_meta={"build_id": str(uuid4()), "code_path": "mcp-builds/demo/server.py"},
    )
    row = _version_row(server.id, "1.0.0", code_snapshot="ROLLED BACK CODE")
    service, _db, _ = _make_service(versions=[row])
    service._repo.get_by_id.return_value = server

    fake = SimpleNamespace(
        write_file=AsyncMock(),
        start_mcp_server=AsyncMock(return_value={"server_id": "s1", "tools": []}),
        mcp_call_tool=AsyncMock(return_value={"content": [{"text": "ok"}], "is_error": False}),
        stop_mcp_server=AsyncMock(),
    )
    monkeypatch.setattr("omichub.infrastructure.studio.manager.studio_sandbox_manager", fake)

    result = await service.call_experimental_tool(
        str(server.id), "echo", {"text": "hi"}, "sess-1", str(owner)
    )

    fake.write_file.assert_awaited_once_with("sess-1", "mcp-builds/demo/server.py", "ROLLED BACK CODE")
    fake.start_mcp_server.assert_awaited_once()
    assert result == {"content": [{"text": "ok"}], "is_error": False}


@pytest.mark.unit
async def test_call_experimental_tool_falls_back_to_build_record(monkeypatch):
    """版本行无 code_snapshot 时回退到 generation_meta.build_id 指向的构建记录"""
    owner = uuid4()
    build_id = uuid4()
    build = MCPBuildModel(id=build_id, user_id=owner, requirement="echo", generated_code="BUILD CODE")
    server = _server(
        created_by=owner,
        current_version="1.0.0",
        expires_at=None,
        generation_meta={"build_id": str(build_id), "code_path": "mcp-builds/demo/server.py"},
    )
    row = _version_row(server.id, "1.0.0", code_snapshot="", build_id=build_id)
    service, _db, _ = _make_service(versions=[row], builds=[build])
    service._repo.get_by_id.return_value = server

    fake = SimpleNamespace(
        write_file=AsyncMock(),
        start_mcp_server=AsyncMock(return_value={"server_id": "s1", "tools": []}),
        mcp_call_tool=AsyncMock(return_value={"content": [], "is_error": False}),
        stop_mcp_server=AsyncMock(),
    )
    monkeypatch.setattr("omichub.infrastructure.studio.manager.studio_sandbox_manager", fake)

    await service.call_experimental_tool(str(server.id), "echo", {}, "sess-1", str(owner))

    fake.write_file.assert_awaited_once_with("sess-1", "mcp-builds/demo/server.py", "BUILD CODE")


# ----------------------------------------------------------------------
# 转正
# ----------------------------------------------------------------------
@pytest.mark.unit
async def test_promote_moves_pool_and_writes_publish_row():
    """转正：池切换 production、清 TTL、bump 版本并写 source=publish 行"""
    admin_id = uuid4()
    server = _server(
        current_version="1.0.0",
        version="1.0.0",
        expires_at=datetime(2030, 1, 1),
        review_status=ReviewStatus.APPROVED,
    )
    row = _version_row(server.id, "1.0.0", code_snapshot="CODE")
    service, db, _ = _make_service(versions=[row], mcp_builder_requires_review=True)
    service._repo.get_by_id.return_value = server

    result = await service.promote_server(str(server.id), str(admin_id))

    assert server.pool == ServerPool.PRODUCTION
    assert server.expires_at is None
    assert server.is_enabled is True
    assert server.current_version == "1.0.1"
    assert server.version == "1.0.1"

    publish_rows = [v for v in db.versions if v.source == "publish"]
    assert len(publish_rows) == 1
    pub = publish_rows[0]
    assert pub.version == "1.0.1"
    assert pub.code_snapshot == "CODE"  # 归档转正时生效版本的代码
    assert pub.config_snapshot is not None
    assert "转正发布" in pub.changelog
    assert pub.created_by == admin_id

    assert result == {
        "id": str(server.id),
        "name": server.name,
        "pool": "production",
        "current_version": "1.0.1",
    }


@pytest.mark.unit
async def test_promote_rejects_non_experimental():
    server = _server(pool=ServerPool.PRODUCTION)
    service, _db, _ = _make_service()
    service._repo.get_by_id.return_value = server

    with pytest.raises(ValidationError, match="仅实验池 MCP 可转正"):
        await service.promote_server(str(server.id), str(uuid4()))


@pytest.mark.unit
async def test_promote_blocks_unreviewed_when_review_required():
    server = _server(review_status=ReviewStatus.PENDING)
    service, _db, _ = _make_service(mcp_builder_requires_review=True)
    service._repo.get_by_id.return_value = server

    with pytest.raises(ValidationError, match="须通过审核"):
        await service.promote_server(str(server.id), str(uuid4()))
