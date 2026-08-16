"""MCP Server 版本控制单元测试（更新快照 / 版本列表 / 回滚）"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

import omichub.application.services.mcp_service as mcp_service
from omichub.application.schemas.mcp import CreateMCPServerDTO, UpdateMCPServerDTO
from omichub.application.services.mcp_service import MCPService
from omichub.core.exceptions import NotFoundError
from omichub.domain.mcp.entities import MCPServer, MCPToolRegistry
from omichub.domain.mcp.value_objects import ServerStatus, Transport
from omichub.infrastructure.database.models.mcp_builder import MCPVersionModel


class _FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self._rows

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


class _FakeSession:
    """最小内存版 AsyncSession：仅覆盖版本表查询（execute）与写入（add/flush）"""

    def __init__(self, versions=()):
        self.versions = list(versions)
        self.added = []

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, MCPVersionModel):
            self.versions.append(obj)

    async def flush(self):
        # 模拟真实 DB 在 flush 时为新行生成主键
        for obj in self.added:
            if isinstance(obj, MCPVersionModel) and getattr(obj, "id", None) is None:
                obj.id = uuid4()

    async def execute(self, stmt):
        if stmt.column_descriptions[0]["name"] == "version":  # select(MCPVersionModel.version)
            return _FakeResult([v.version for v in self.versions])
        rows = list(self.versions)
        wanted = _version_filter(stmt)
        if wanted is not None:
            rows = [v for v in rows if v.version == wanted]
        else:
            rows.sort(key=lambda v: v.created_at or datetime.min, reverse=True)
        return _FakeResult(rows)


def _server(**overrides) -> MCPServer:
    server_id = uuid4()
    server = MCPServer(
        id=server_id,
        name="demo-server",
        description="old desc",
        transport=Transport.BUILTIN,
        status=ServerStatus.ONLINE,
        current_version="1.0.0",
        tools=[
            MCPToolRegistry(
                tool_name="tool_a", description="a", input_schema={}, server_id=server_id
            ),
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
        source="admin",
        changelog="",
        created_at=datetime.now(),
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _make_service(server: MCPServer, versions=()) -> tuple[MCPService, _FakeSession]:
    db = _FakeSession(versions)
    service = MCPService(MagicMock())
    service._db = db
    service._repo = AsyncMock()
    service._repo.get_by_id.return_value = server
    service._repo.save.side_effect = lambda s: s
    return service, db


@pytest.mark.unit
async def test_register_creates_initial_version_snapshot():
    """注册 MCP Server 时写入 source=register 的 v1.0.0 初始快照，版本历史不为空"""
    db = _FakeSession()
    service = MCPService(MagicMock())
    service._db = db
    service._repo = AsyncMock()
    service._repo.get_by_name.return_value = None
    captured: list[MCPServer] = []
    service._repo.get_by_id.side_effect = lambda _id: captured[0]
    service._repo.save.side_effect = lambda s: s
    service._domain = MagicMock()

    async def _register(s):
        captured.append(s)
        return s

    service._domain.register_server = AsyncMock(side_effect=_register)
    service._autodiscover_tools = AsyncMock()

    dto = await service.register_server(
        CreateMCPServerDTO(name="go-server", transport="stdio", command="python")
    )

    assert dto.current_version == "1.0.0"
    rows = [v for v in db.versions if isinstance(v, MCPVersionModel)]
    assert len(rows) == 1
    row = rows[0]
    assert row.version == "1.0.0"
    assert row.source == "register"
    assert row.changelog == "注册 MCP Server（初始配置）"
    assert row.config_snapshot["name"] == "go-server"


@pytest.mark.unit
async def test_list_server_versions_backfills_initial_snapshot():
    """存量 server 无任何版本行时，按当前配置懒回填一条初始快照"""
    server = _server(name="go-server", current_version="1.0.0")
    service, db = _make_service(server, versions=[])

    result = await service.list_server_versions(server.id)

    assert len(result) == 1
    assert result[0].version == "1.0.0"
    assert result[0].source == "register"
    assert result[0].has_config_snapshot is True
    rows = [v for v in db.versions if isinstance(v, MCPVersionModel)]
    assert len(rows) == 1
    assert rows[0].config_snapshot["name"] == "go-server"


@pytest.mark.unit
async def test_builtin_preset_sync_creates_upgrade_snapshot(monkeypatch):
    """内置工具变化：保留 v1.0.0 初始快照并升级到 v1.0.1。"""
    server = _server(name="omichub-platform")
    service, db = _make_service(server)
    preset = {
        "name": "omichub-platform",
        "description": "平台操作 MCP",
        "tools": [
            {
                "name": "platform_get_current_time",
                "description": "获取当前时间",
                "inputSchema": {"type": "object", "properties": {}},
            }
        ],
    }
    monkeypatch.setattr(mcp_service, "PRESET_SERVERS", [preset])
    monkeypatch.setattr(
        mcp_service,
        "_build_omichub_tools_preset",
        lambda: {"name": "omichub-tools", "description": "tools", "tools": []},
    )
    service._repo.list_all.return_value = [server]
    service._repo.get_by_name.return_value = server
    service._repo.get_by_id.return_value = server

    await service.ensure_presets()

    assert server.current_version == "1.0.1"
    assert [tool.tool_name for tool in server.tools] == ["platform_get_current_time"]
    versions = {row.version: row for row in db.versions}
    assert versions["1.0.0"].source == "register"
    assert versions["1.0.0"].changelog == "注册 MCP Server（初始配置）"
    assert versions["1.0.1"].source == "preset"
    assert versions["1.0.1"].changelog == "内置 MCP 预设升级：同步最新工具清单"


@pytest.mark.unit
async def test_builtin_preset_sync_keeps_user_selected_version(monkeypatch):
    """回滚选择的内置版本在普通刷新中保持，不被最新代码工具清单覆盖。"""
    server = _server(
        name="omichub-platform",
        current_version="1.0.0",
        generation_meta={"preset_version_pinned": True},
    )
    service, db = _make_service(server)
    preset = {
        "name": "omichub-platform",
        "description": "平台操作 MCP",
        "tools": [
            {
                "name": "platform_get_current_time",
                "description": "获取当前时间",
                "inputSchema": {"type": "object", "properties": {}},
            }
        ],
    }
    monkeypatch.setattr(mcp_service, "PRESET_SERVERS", [preset])
    monkeypatch.setattr(
        mcp_service,
        "_build_omichub_tools_preset",
        lambda: {"name": "omichub-tools", "description": "tools", "tools": []},
    )
    service._repo.list_all.return_value = [server]
    service._repo.get_by_name.return_value = server
    service._repo.get_by_id.return_value = server

    await service.ensure_presets()

    assert server.current_version == "1.0.0"
    assert [tool.tool_name for tool in server.tools] == ["tool_a"]
    assert db.versions == []


@pytest.mark.unit
async def test_update_transport_string_converted_to_enum():
    """DTO 的 transport 字符串转换为枚举，避免仓储 save 取 .value 报 AttributeError"""
    server = _server()
    service, _db = _make_service(server)

    await service.update_server(
        server.id,
        UpdateMCPServerDTO(transport="sse", url="https://example.com/sse"),
    )

    assert server.transport is Transport.SSE


@pytest.mark.unit
async def test_update_invalid_transport_raises_validation():
    """非法 transport 值抛 ValidationError，不写版本快照"""
    from omichub.core.exceptions import ValidationError

    server = _server()
    service, db = _make_service(server)

    with pytest.raises(ValidationError, match="不支持的传输方式"):
        await service.update_server(server.id, UpdateMCPServerDTO(transport="bogus"))

    assert server.transport is Transport.BUILTIN
    assert db.versions == []


@pytest.mark.unit
async def test_update_triggers_snapshot_and_version_bump():
    """配置类变更：bump patch 版本并写入 source=admin 的全量配置快照"""
    server = _server()
    service, db = _make_service(server)
    actor_id = uuid4()

    dto = await service.update_server(
        server.id,
        UpdateMCPServerDTO(description="new desc", env={"A": "1"}),
        actor_id=actor_id,
    )

    assert server.current_version == "1.0.1"
    assert dto.description == "new desc"
    service._repo.save.assert_awaited_once()

    assert len(db.versions) == 1
    row = db.versions[0]
    assert row.version == "1.0.1"
    assert row.source == "admin"
    assert row.changelog == "管理员更新配置：description, env"
    assert row.created_by == actor_id
    assert row.config_snapshot["description"] == "new desc"
    assert row.config_snapshot["env"] == {"A": "1"}
    assert row.config_snapshot["transport"] == "builtin"
    assert row.config_snapshot["name"] == "demo-server"
    assert row.tools_snapshot == [
        {"name": "tool_a", "description": "a", "inputSchema": {}}
    ]


@pytest.mark.unit
async def test_update_is_enabled_only_skips_snapshot():
    """仅 is_enabled 等噪音字段变更时不打快照、不 bump 版本"""
    server = _server()
    service, db = _make_service(server)

    await service.update_server(server.id, UpdateMCPServerDTO(is_enabled=False))

    assert server.is_enabled is False
    assert server.current_version == "1.0.0"
    assert db.versions == []


@pytest.mark.unit
async def test_list_server_versions_desc():
    """版本列表按 created_at 倒序，含 source/changelog/has_config_snapshot"""
    server = _server()
    now = datetime.now()
    older = _version_row(server.id, "1.0.0", source="builder",
                         config_snapshot=None, created_at=now - timedelta(hours=1))
    newer = _version_row(server.id, "1.0.1", source="admin", changelog="管理员更新配置：env",
                         config_snapshot={"env": {}}, created_at=now)
    service, _db = _make_service(server, versions=[newer, older])

    result = await service.list_server_versions(server.id)

    assert [v.version for v in result] == ["1.0.1", "1.0.0"]
    assert result[0].source == "admin"
    assert result[0].changelog == "管理员更新配置：env"
    assert result[0].has_config_snapshot is True
    assert result[1].has_config_snapshot is False


@pytest.mark.unit
async def test_rollback_restores_config_and_creates_rollback_row():
    """回滚：还原配置/工具快照，current_version 指向目标版本，并新增 rollback 版本行"""
    server = _server(description="new desc", env={"B": "2"}, current_version="1.0.2")
    target = _version_row(
        server.id,
        "1.0.1",
        config_snapshot={"description": "old desc", "env": {"A": "1"}},
        tools_snapshot=[{"name": "tool_old", "description": "o", "inputSchema": {}}],
    )
    newer = _version_row(server.id, "1.0.2", config_snapshot={"description": "new desc"})
    service, db = _make_service(server, versions=[target, newer])
    actor_id = uuid4()

    dto = await service.rollback_server(server.id, "1.0.1", actor_id=actor_id)

    assert server.description == "old desc"
    assert server.env == {"A": "1"}
    assert dto.description == "old desc"
    assert server.current_version == "1.0.1"
    assert [t.tool_name for t in server.tools] == ["tool_old"]

    rollback_rows = [v for v in db.versions if v.source == "rollback"]
    assert len(rollback_rows) == 1
    row = rollback_rows[0]
    # 在当前最大版本 1.0.2 上 bump patch，保证 (server, version) 唯一
    assert row.version == "1.0.3"
    assert row.changelog == "回滚到 v1.0.1"
    assert row.created_by == actor_id
    assert row.config_snapshot["description"] == "old desc"
    assert row.tools_snapshot == [
        {"name": "tool_old", "description": "o", "inputSchema": {}}
    ]


@pytest.mark.unit
async def test_rollback_missing_version_raises_not_found():
    """目标版本不存在时抛 NotFoundError"""
    server = _server()
    service, _db = _make_service(server)

    with pytest.raises(NotFoundError, match="版本 9.9.9 不存在"):
        await service.rollback_server(server.id, "9.9.9", actor_id=uuid4())

    service._repo.save.assert_not_awaited()


@pytest.mark.unit
async def test_update_syncs_legacy_version_field():
    """bump 版本时同步遗留 version 字段，且 DTO 暴露 current_version"""
    server = _server()
    service, _db = _make_service(server)

    dto = await service.update_server(server.id, UpdateMCPServerDTO(description="d2"))

    assert server.version == "1.0.1"
    assert server.current_version == "1.0.1"
    assert dto.version == "1.0.1"
    assert dto.current_version == "1.0.1"
    assert dto.pool == "production"


@pytest.mark.unit
async def test_rollback_syncs_legacy_version_field():
    """回滚后遗留 version 字段跟随 current_version 指向目标版本"""
    server = _server(current_version="1.0.2", version="1.0.2")
    target = _version_row(server.id, "1.0.1", config_snapshot={"description": "old"})
    service, _db = _make_service(server, versions=[target, _version_row(server.id, "1.0.2")])

    dto = await service.rollback_server(server.id, "1.0.1")

    assert server.version == "1.0.1"
    assert server.current_version == "1.0.1"
    assert dto.version == "1.0.1"
    assert dto.current_version == "1.0.1"
