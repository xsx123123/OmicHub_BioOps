"""MCP Builder 架构缺陷修复回归测试.

覆盖两组缺陷：

A. 审批链断裂 —— builder 实验池 MCP 未经人工审核（review_status != APPROVED）
   不得被 Agent 挂载执行；注册 stdio args 改为「相对脚本路径 + working_dir」
   并在注册处显式复用 client.py 的 validate_stdio_args / validate_working_dir；
   审核通过路径把 review_status 置为 APPROVED。
B. AST 门禁加固 —— 别名调用（``f = eval; f(...)``）、白名单模块危险属性
   （os.remove/unlink/rename/environ/spawn*、shutil.rmtree、subprocess 直调）、
   字符串拼接常量折叠（``"/et" + "c/passwd"``）、生成标记按行精确匹配。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql

from cygnusx.application.schemas.mcp_builder import SubmitBuildRequest
from cygnusx.application.services.agent_service import (
    AgentService,
    _mcp_mount_allowed_for_agent,
)
from cygnusx.application.services.mcp_builder_service import MCPBuilderService
from cygnusx.core.exceptions import BusinessError, ValidationError
from cygnusx.domain.mcp.entities import MCPServer
from cygnusx.domain.mcp.value_objects import (
    ReviewStatus,
    ServerPool,
    ServerStatus,
    Transport,
)
from cygnusx.infrastructure.database.models.mcp_builder import (
    MCPBuildModel,
    MCPVersionModel,
)
from cygnusx.infrastructure.mcp.builder.safety import (
    GENERATED_MARKER,
    StaticSafetyChecker,
)
from cygnusx.infrastructure.mcp.client import validate_stdio_args, validate_working_dir

SAMPLE_MCP_CODE = '''"""echo MCP server"""

__exp_mcp_generated__ = True


async def list_tools():
    return [{"name": "echo", "description": "回显文本", "inputSchema": {"type": "object"}}]


async def call_tool(name, arguments):
    if name == "echo":
        return {"content": [{"type": "text", "text": str(arguments.get("text", ""))}]}
    raise ValueError("unknown tool")
'''


def _wrap(body: str) -> str:
    """把业务代码包成符合结构要求的完整 MCP Server 模板（同 test_builder_safety 风格）."""
    return f'''#!/usr/bin/env python3
"""MCP Server: test"""

{GENERATED_MARKER} = True

from mcp.server import Server
import json

server = Server("test")

@server.list_tools()
async def list_tools() -> list:
    return []

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
{body}
'''


def _report(body: str):
    return StaticSafetyChecker().analyze(_wrap(body))


# ======================================================================
# B1. 别名调用绕过：f = eval; f(...)
# ======================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    "body, alias, original",
    [
        ("    f = eval\n    return f('1+1')", "f", "eval"),
        ("    runner = exec\n    runner('x=1')\n    return []", "runner", "exec"),
        ("    h = open\n    h('/tmp/x', 'w')\n    return []", "h", "open"),
        ("    r, keep = eval, 1\n    return r('1')", "r", "eval"),
        ("    (g := exec)\n    g('x=1')\n    return []", "g", "exec"),
        ("    for fn in (eval, compile):\n        pass\n    return fn('1')", "fn", "eval"),
        ("    evil: callable = eval\n    return evil('1')", "evil", "eval"),
    ],
)
def test_forbidden_call_via_alias_is_violation(body: str, alias: str, original: str):
    report = _report(body)
    assert report.passed is False
    assert any(
        "别名" in v and alias in v and original in v for v in report.violations
    ), report.violations


@pytest.mark.unit
def test_benign_function_alias_still_passes():
    """普通函数/方法别名不受影响：只追踪危险内置名的别名。"""
    body = (
        "    nums = [1, 2]\n"
        "    nums.remove(1)\n"
        "    g = max\n"
        "    return [g(nums)]"
    )
    report = _report(body)
    assert report.passed is True, report.violations


# ======================================================================
# B2. 白名单模块的危险属性：os.remove/unlink/rename/environ/spawn* 等
# ======================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    "body, needle",
    [
        ("    import os\n    os.remove(path)\n    return []", "os.remove"),
        ("    import os\n    os.unlink(path)\n    return []", ".unlink()"),
        ("    import os\n    os.rename(a, b)\n    return []", "os.rename"),
        ("    import os\n    return [os.environ['PATH']]", "os.environ"),
        ("    import os\n    env = os.environ\n    return [env]", "os.environ"),
        ("    import os\n    fn = os.remove\n    return [fn]", "os.remove"),
        ("    import os\n    os.spawnlpe(os.P_NOWAIT, 'ls')\n    return []", "spawn"),
        ("    import os\n    return [os.pathsep]", None),  # 安全属性不拦（单独断言）
        ("    shutil.rmtree(d)\n    return []", "rmtree"),
        ("    subprocess.run(['ls'])\n    return []", "subprocess"),
    ],
)
def test_dangerous_module_attribute_calls(body: str, needle: str | None):
    report = _report(body)
    if needle is None:
        assert report.passed is True, report.violations
        return
    assert report.passed is False, body
    assert any(needle in v for v in report.violations), report.violations


@pytest.mark.unit
def test_non_os_receivers_not_false_positive():
    """模块限定属性只在接收者为 os/posix/nt/shutil/subprocess 时拦截：
    pandas 的 df.rename、字符串的 s.replace、Path 对象的 .unlink() 调用名
    在非常规接收者上不误伤。"""
    body = (
        "    renamed = df.rename(columns={'a': 'b'})\n"
        "    fixed = text.replace('x', 'y')\n"
        "    merged = target.merge(other)\n"
        "    return [renamed, fixed, merged]"
    )
    report = _report(body)
    assert report.passed is True, report.violations


# ======================================================================
# B3. 字符串拼接常量折叠："/et" + "c/passwd"
# ======================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    "body",
    [
        '    target = "/et" + "c/passwd"\n    return [target]',
        '    target = "/" + "etc" + "/passwd"\n    return [target]',
        '    return ["/et" + "c/passwd" + user_input]',
        '    return [prefix + "/proc/" + suffix]',  # 单片段命中（既有行为保持）
        '    return [f"/etc/{name}"]',
    ],
)
def test_split_path_concatenation_detected(body: str):
    report = _report(body)
    assert report.passed is False, body
    assert any("受保护路径" in v for v in report.violations), report.violations


@pytest.mark.unit
def test_benign_concat_and_fold_positive():
    body = (
        '    out_dir = "/data" + "/results"\n'
        '    code = f"mcp-builds/{build_id}/server.py"\n'
        "    return [out_dir, code]"
    )
    report = _report(body)
    assert report.passed is True, report.violations


# ======================================================================
# B4. 生成标记按行精确匹配（防伪造注释/字符串）
# ======================================================================


@pytest.mark.unit
def test_forged_marker_comment_is_violation():
    """旧版子串匹配可被注释/字符串里的标记文本绕过，按行精确匹配后必须拦截。"""
    code = f'''#!/usr/bin/env python3
# 规范要求：__exp_mcp_generated__ = True  # 伪造注释
NOTE = "__exp_mcp_generated__ = True"

from mcp.server import Server

server = Server("test")

@server.list_tools()
async def list_tools() -> list:
    return []

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    return []
'''
    report = StaticSafetyChecker().analyze(code)
    assert report.passed is False
    assert any("生成标记" in v for v in report.violations), report.violations


@pytest.mark.unit
def test_real_marker_assignment_line_passes():
    """合法的 ``__exp_mcp_generated__ = True`` 赋值行（含带缩进块内形态）仍放行。"""
    assert _report("    return []").passed is True


# ======================================================================
# A. 注册形态与审批链
# ======================================================================


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


class _FakeBuilderSession:
    """内存版 AsyncSession：与 test_mcp_builder_version_control 的夹具同构."""

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

    async def delete(self, obj):
        pass

    async def get(self, _model, pk):
        return self.builds.get(pk)

    async def execute(self, stmt):
        name = stmt.column_descriptions[0]["name"]
        if "count" in name:
            return _FakeResult([0])
        if name == "version":
            return _FakeResult([v.version for v in self.versions])
        rows = list(self.versions)
        where = stmt.whereclause
        clauses = getattr(where, "clauses", [where] if where is not None else [])
        wanted = None
        for clause in clauses:
            left, right = getattr(clause, "left", None), getattr(clause, "right", None)
            if left is not None and str(left) == "mcp_versions.version":
                wanted = getattr(right, "value", None)
        if wanted is not None:
            rows = [v for v in rows if v.version == wanted]
        return _FakeResult(rows)


def _settings(**overrides) -> SimpleNamespace:
    base = dict(
        mcp_builder_enabled=True,
        mcp_builder_requires_review=True,
        mcp_builder_max_per_user=10,
        mcp_builder_default_ttl_hours=24,
        mcp_default_timeout=30,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_service(versions=(), builds=(), **settings_overrides):
    db = _FakeBuilderSession(versions, builds)
    service = MCPBuilderService(MagicMock())
    service._db = db
    service._repo = AsyncMock()
    service._repo.save.side_effect = lambda s: s
    service._repo.get_by_name.return_value = None
    service._settings = _settings(**settings_overrides)
    return service, db


def _experimental_server(**overrides) -> MCPServer:
    server_id = uuid4()
    server = MCPServer(
        id=server_id,
        name="exp-demo",
        description="desc",
        transport=Transport.STDIO,
        command="python",
        args=["mcp-builds/demo/server.py"],
        working_dir="/workspace",
        status=ServerStatus.ONLINE,
        is_enabled=True,
        pool=ServerPool.EXPERIMENTAL,
        created_by=uuid4(),
        current_version="1.0.0",
        version="1.0.0",
        generation_meta={"build_id": str(uuid4()), "code_path": "mcp-builds/demo/server.py"},
        review_status=ReviewStatus.PENDING,
    )
    for key, value in overrides.items():
        setattr(server, key, value)
    return server


@pytest.mark.unit
async def test_submit_build_registers_validated_relative_stdio_shape():
    """注册形态：相对脚本路径 + working_dir，且通过平台 stdio 校验器."""
    service, _db = _make_service()
    uid = uuid4()

    dto = await service.submit_build(
        str(uid),
        SubmitBuildRequest(requirement="echo 工具", code=SAMPLE_MCP_CODE, mcp_name="smoke"),
    )

    server = service._repo.save.call_args.args[0]
    assert server.args == ["mcp-builds/smoke/server.py"]
    assert server.working_dir == "/workspace"
    # 显式复用 client.py 的校验器：注册形态在宿主 stdio 链上同样合法
    validate_stdio_args(server.args)
    validate_working_dir(server.working_dir)
    # 开启审核时：注册即 PENDING，不能以「已启用 + 已通过」形态进入挂载面
    assert server.review_status == ReviewStatus.PENDING
    assert dto.status == "reviewing"


@pytest.mark.unit
async def test_submit_build_without_review_requirement_is_approved():
    service, _db = _make_service(mcp_builder_requires_review=False)
    await service.submit_build(
        str(uuid4()),
        SubmitBuildRequest(requirement="echo 工具", code=SAMPLE_MCP_CODE, mcp_name="free"),
    )
    server = service._repo.save.call_args.args[0]
    assert server.review_status == ReviewStatus.APPROVED


@pytest.mark.unit
@pytest.mark.parametrize("bad_name", ["../../etc", "a;rm -rf /tmp/x", "x$(id)"])
async def test_submit_build_rejects_unsafe_mcp_name(bad_name: str):
    """mcp_name 直拼进 code_path：注册处显式走 validate_stdio_args 拦截恶意形态."""
    service, _db = _make_service()
    with pytest.raises(ValidationError):
        await service.submit_build(
            str(uuid4()),
            SubmitBuildRequest(requirement="echo 工具", code=SAMPLE_MCP_CODE, mcp_name=bad_name),
        )


@pytest.mark.unit
async def test_review_approve_flips_server_to_approved():
    """确认审核通过路径把 review_status 置 APPROVED（挂载链的唯一放行口）."""
    server = _experimental_server()
    build = MCPBuildModel(
        id=uuid4(), user_id=uuid4(), requirement="echo", generated_code=SAMPLE_MCP_CODE,
        mcp_server_id=server.id, version="1.0.0", status="reviewing",
    )
    service, db = _make_service(builds=[build])
    service._repo.get_by_id.return_value = server

    dto = await service.review_build(str(build.id), str(uuid4()), "approved")

    assert server.review_status == ReviewStatus.APPROVED
    assert dto.status == "published"
    assert any(isinstance(o, MCPVersionModel) for o in db.added)


@pytest.mark.unit
async def test_review_reject_disables_server():
    server = _experimental_server(review_status=ReviewStatus.APPROVED)
    build = MCPBuildModel(
        id=uuid4(), user_id=uuid4(), requirement="echo", generated_code=SAMPLE_MCP_CODE,
        mcp_server_id=server.id, version="1.0.0", status="reviewing",
    )
    service, _db = _make_service(builds=[build])
    service._repo.get_by_id.return_value = server

    await service.review_build(str(build.id), str(uuid4()), "rejected")

    assert server.review_status == ReviewStatus.REJECTED
    assert server.is_enabled is False


def _fake_studio(monkeypatch, tools=None):
    fake = SimpleNamespace(
        write_file=AsyncMock(),
        start_mcp_server=AsyncMock(
            return_value={"server_id": "s1", "tools": tools if tools is not None else [{"name": "echo"}]}
        ),
        mcp_call_tool=AsyncMock(return_value={"content": [{"text": "ok"}], "is_error": False}),
        stop_mcp_server=AsyncMock(),
    )
    monkeypatch.setattr("cygnusx.infrastructure.studio.manager.studio_sandbox_manager", fake)
    return fake


@pytest.mark.unit
async def test_sandbox_test_with_review_required_keeps_server_pending(monkeypatch):
    """审核开启时沙箱测试全通过也只是进入 REVIEWING，review_status 保持 PENDING，
    挂载链（依赖 APPROVED）不会放行。"""
    server = _experimental_server(status=ServerStatus.OFFLINE)
    build = MCPBuildModel(
        id=uuid4(), user_id=uuid4(), requirement="echo", generated_code=SAMPLE_MCP_CODE,
        mcp_server_id=server.id, version="1.0.0", status="testing",
    )
    service, _db = _make_service(builds=[build])
    service._repo.get_by_id.return_value = server
    _fake_studio(monkeypatch)

    dto = await service.test_in_sandbox(str(build.id), "sess-1", user_id=str(build.user_id))

    assert dto.status == "reviewing"
    assert server.review_status == ReviewStatus.PENDING


@pytest.mark.unit
async def test_sandbox_test_without_review_approves_server(monkeypatch):
    server = _experimental_server(status=ServerStatus.OFFLINE)
    build = MCPBuildModel(
        id=uuid4(), user_id=uuid4(), requirement="echo", generated_code=SAMPLE_MCP_CODE,
        mcp_server_id=server.id, version="1.0.0", status="testing",
    )
    service, _db = _make_service(builds=[build], mcp_builder_requires_review=False)
    service._repo.get_by_id.return_value = server
    _fake_studio(monkeypatch)

    dto = await service.test_in_sandbox(str(build.id), "sess-1", user_id=str(build.user_id))

    assert dto.status == "published"
    assert server.review_status == ReviewStatus.APPROVED


# ======================================================================
# A. 挂载侧过滤
# ======================================================================


@pytest.mark.unit
def test_mount_gate_blocks_unapproved_experimental_only():
    blocked = _experimental_server(review_status=ReviewStatus.PENDING, is_enabled=True)
    approved = _experimental_server(review_status=ReviewStatus.APPROVED)
    rejected = _experimental_server(review_status=ReviewStatus.REJECTED)
    # preset / 手工注册：production 池，默认 APPROVED —— 不受门禁影响
    manual = MCPServer(id=uuid4(), name="manual-mcp")
    promoted = _experimental_server(pool=ServerPool.PRODUCTION)
    # 理论上 production 池 + 非 APPROVED 也不误伤（门禁仅针对 builder 实验池）
    production_pending = MCPServer(
        id=uuid4(), name="prod-pending",
        pool=ServerPool.PRODUCTION, review_status=ReviewStatus.PENDING,
    )

    assert _mcp_mount_allowed_for_agent(blocked) is False
    assert _mcp_mount_allowed_for_agent(rejected) is False
    assert _mcp_mount_allowed_for_agent(approved) is True
    assert _mcp_mount_allowed_for_agent(manual) is True
    assert _mcp_mount_allowed_for_agent(promoted) is True
    assert _mcp_mount_allowed_for_agent(production_pending) is True


class _RecordingSession:
    """捕获 SQL 的伪 AsyncSession，用于断言能力校验查询的过滤条件."""

    def __init__(self, rows=()):
        self.rows = list(rows)
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _FakeResult(self.rows)


@pytest.mark.unit
async def test_capability_validation_query_requires_approval():
    """:502 校验查询须带上实验池审核条件，且未通过审核的实验 MCP 被过滤后报错."""
    mcp_id = uuid4()
    db = _RecordingSession(rows=[])  # 模拟：SQL 过滤后查不到该 server
    service = AgentService(db)

    with pytest.raises(BusinessError, match="不存在或未启用"):
        await service._validate_user_capability_assets(None, [str(mcp_id)], [])

    sql = str(db.statements[0].compile(dialect=postgresql.dialect()))
    assert "mcp_servers.is_enabled" in sql
    assert "mcp_servers.pool" in sql
    assert "mcp_servers.review_status" in sql
