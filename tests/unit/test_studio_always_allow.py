"""会话级"总是允许"（always-allow）、动态审批名单、决议落库与聊天沙盒入闸测试。

覆盖：
- always_allow_set / needs_approval 纯函数（含 chat_sandbox_execute 入闸与放行降级）；
- approval_required_tools() 动态 ∪ 硬编码名单及 schema 读取失败回退；
- resolve(always=True) 决议载荷携带 always 标记；
- record_approval_audit 落 audit_logs（best-effort，异常不抛出）；
- REST 端点：approve 支持 always、计划审批忽略 always、切换权限模式清空 always_allow。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from cygnusx.api.v1 import studio as studio_api
from cygnusx.application.schemas.studio import (
    StudioApprovalApproveRequest,
    UpdateStudioPermissionsRequest,
)
from cygnusx.application.services import studio_approval_service as approval_module
from cygnusx.application.services.studio_approval_service import (
    APPROVAL_REQUIRED_TOOLS,
    StudioApprovalService,
    always_allow_set,
    approval_required_tools,
    needs_approval,
    record_approval_audit,
)

# ---------------------------------------------------------------------------
# always_allow_set：sandbox_meta.permissions.always_allow 解析
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_always_allow_set_parses_permissions() -> None:
    meta = {"permissions": {"mode": "supervised", "always_allow": ["sandbox_execute"]}}
    assert always_allow_set(meta) == {"sandbox_execute"}


@pytest.mark.unit
def test_always_allow_set_degrades_to_empty_on_missing_or_malformed() -> None:
    assert always_allow_set(None) == set()
    assert always_allow_set({}) == set()
    assert always_allow_set({"permissions": None}) == set()
    assert always_allow_set({"permissions": {"always_allow": "sandbox_execute"}}) == set()
    assert always_allow_set({"permissions": {"always_allow": None}}) == set()


# ---------------------------------------------------------------------------
# needs_approval：supervised 闸 + always 放行 + 模式缺失降级
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_needs_approval_supervised_controlled_tool() -> None:
    assert needs_approval("supervised", "sandbox_execute", set()) is True
    # 普通聊天的代码执行同闸
    assert needs_approval("supervised", "chat_sandbox_execute", set()) is True
    # 只读工具不受控
    assert needs_approval("supervised", "workspace_read", set()) is False


@pytest.mark.unit
def test_needs_approval_always_allow_bypasses() -> None:
    always = {"sandbox_execute", "chat_sandbox_execute"}
    assert needs_approval("supervised", "sandbox_execute", always) is False
    assert needs_approval("supervised", "chat_sandbox_execute", always) is False
    # 其他受控工具仍逐次审批
    assert needs_approval("supervised", "workspace_write", always) is True


@pytest.mark.unit
def test_needs_approval_non_supervised_or_missing_mode_allows() -> None:
    assert needs_approval("auto", "sandbox_execute", set()) is False
    assert needs_approval("plan", "sandbox_execute", set()) is False
    # 会话未声明权限模式（普通聊天现状）→ 保持现状放行
    assert needs_approval(None, "chat_sandbox_execute", set()) is False
    assert needs_approval("", "chat_sandbox_execute", set()) is False


@pytest.mark.unit
def test_network_request_requires_approval_outside_supervised_and_can_be_allowed_for_session() -> None:
    # 出网是跨越平台边界的副作用，普通聊天也必须先由前端确认。
    assert needs_approval(None, "network_request", set()) is True
    assert needs_approval("auto", "network_request", set()) is True
    assert needs_approval("auto", "network_request", {"network_request"}) is False


# ---------------------------------------------------------------------------
# approval_required_tools：硬编码 ∪ schema requires_confirm，失败回退
# ---------------------------------------------------------------------------


class _FakeSchemaLoader:
    def __init__(self, tools: list[Any] | None = None, exc: Exception | None = None) -> None:
        self._tools = tools or []
        self._exc = exc

    def get_config(self) -> Any:
        if self._exc is not None:
            raise self._exc
        return SimpleNamespace(tools=self._tools)


def _patch_schema_loader(monkeypatch: pytest.MonkeyPatch, loader: Any) -> None:
    import cygnusx.tools.schema_loader as schema_loader_module

    monkeypatch.setattr(schema_loader_module, "schema_loader", loader)


@pytest.mark.unit
def test_approval_required_tools_unions_schema_requires_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_schema_loader(
        monkeypatch,
        _FakeSchemaLoader(
            tools=[
                SimpleNamespace(name="cygnusx_open_terminal", requires_confirm=True),
                SimpleNamespace(name="web_search", requires_confirm=False),
            ]
        ),
    )

    tools = approval_required_tools()

    assert "cygnusx_open_terminal" in tools
    assert "web_search" not in tools
    # 硬编码集合仍在
    assert tools >= APPROVAL_REQUIRED_TOOLS


@pytest.mark.unit
def test_approval_required_tools_falls_back_to_hardcoded_on_schema_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_schema_loader(monkeypatch, _FakeSchemaLoader(exc=RuntimeError("yaml missing")))

    assert approval_required_tools() == APPROVAL_REQUIRED_TOOLS
    # 回退后闸仍拦截已知危险工具
    assert needs_approval("supervised", "sandbox_execute", set()) is True


@pytest.mark.unit
def test_needs_approval_covers_schema_marked_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """schema 中 requires_confirm: true 的非硬编码工具同样受 supervised 闸控制。"""
    _patch_schema_loader(
        monkeypatch,
        _FakeSchemaLoader(
            tools=[SimpleNamespace(name="some_dangerous_tool", requires_confirm=True)]
        ),
    )

    assert needs_approval("supervised", "some_dangerous_tool", set()) is True
    assert needs_approval("auto", "some_dangerous_tool", set()) is False


# ---------------------------------------------------------------------------
# resolve(always=True)：决议载荷携带 always 标记
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_always_marks_resolution_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    pushed: list[str] = []

    class FakeRedis:
        async def eval(self, *_args: object) -> str:
            pushed.append(str(_args[6]))  # ARGV[3] = 决议 JSON
            return json.dumps({"approval_id": "a-1", "user_id": "u-1", "status": "approved"})

    monkeypatch.setattr(approval_module, "get_redis", lambda: FakeRedis())

    resolved = await StudioApprovalService().resolve("a-1", "u-1", "approved", always=True)

    assert resolved is not None
    assert json.loads(pushed[0]) == {"action": "approved", "always": True}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_without_always_keeps_payload_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    pushed: list[str] = []

    class FakeRedis:
        async def eval(self, *_args: object) -> str:
            pushed.append(str(_args[6]))
            return json.dumps({"approval_id": "a-1", "user_id": "u-1", "status": "approved"})

    monkeypatch.setattr(approval_module, "get_redis", lambda: FakeRedis())

    await StudioApprovalService().resolve("a-1", "u-1", "approved")

    assert json.loads(pushed[0]) == {"action": "approved"}


# ---------------------------------------------------------------------------
# record_approval_audit：落 audit_logs，best-effort
# ---------------------------------------------------------------------------


class _FakeAuditSession:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.committed = False

    async def __aenter__(self) -> _FakeAuditSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def add(self, entry: Any) -> None:
        self.added.append(entry)

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_record_approval_audit_writes_audit_log(monkeypatch: pytest.MonkeyPatch) -> None:
    import cygnusx.infrastructure.database.session as session_module

    fake_session = _FakeAuditSession()
    monkeypatch.setattr(session_module, "get_session_factory", lambda: lambda: fake_session)

    await record_approval_audit(
        user_id="00000000-0000-0000-0000-000000000001",
        approval_id="a-1",
        session_id="sess-1",
        tool_name="sandbox_execute",
        action="approved",
        resolver="user",
        always=True,
        arguments={"language": "python", "code": "print(1)"},
    )

    assert len(fake_session.added) == 1
    assert fake_session.committed is True
    entry = fake_session.added[0]
    assert entry.resource_type == "studio_approval"
    assert entry.resource_id == "a-1"
    assert entry.detail["event"] == "approval_decision"
    assert entry.detail["action"] == "approved"
    assert entry.detail["resolver"] == "user"
    assert entry.detail["always"] is True
    assert entry.detail["tool_name"] == "sandbox_execute"
    assert "print(1)" in entry.detail["args_summary"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_record_approval_audit_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import cygnusx.infrastructure.database.session as session_module

    def _boom() -> Any:
        raise RuntimeError("db down")

    monkeypatch.setattr(session_module, "get_session_factory", _boom)

    # best-effort：DB 异常仅告警，不向审批主流程抛出
    await record_approval_audit(
        user_id="u-1",
        approval_id="a-1",
        session_id="sess-1",
        tool_name="sandbox_execute",
        action="timeout",
        resolver="timeout",
        method="EVENT",
    )


# ---------------------------------------------------------------------------
# REST 端点：approve always / 计划审批忽略 always / 模式切换清空
# ---------------------------------------------------------------------------


class _FakeDb:
    def __init__(self, merged_permissions: dict[str, Any] | None = None) -> None:
        self.executed: list[tuple[str, dict[str, Any] | None]] = []
        self._merged_permissions = merged_permissions or {}

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> None:
        self.executed.append((str(stmt), params))

    async def flush(self) -> None:
        return None

    async def refresh(self, session: Any) -> None:
        session.sandbox_meta = {"permissions": self._merged_permissions}


class _FakeChatService:
    def __init__(self, session: Any) -> None:
        self._session = session

    async def get_session(self, session_id: str, user_id: str) -> Any:
        return self._session


class _FakeApprovalService:
    def __init__(self, record: dict[str, Any]) -> None:
        self._record = record
        self.resolve_calls: list[dict[str, Any]] = []

    async def get(self, approval_id: str) -> dict[str, Any] | None:
        return self._record if approval_id == self._record["approval_id"] else None

    async def resolve(self, approval_id: str, user_id: str, action: str, **kwargs: Any) -> Any:
        self.resolve_calls.append({"action": action, **kwargs})
        if user_id != self._record["user_id"]:
            return None
        return {**self._record, "status": action}


def _approval_record(kind: str = "tool") -> dict[str, Any]:
    return {
        "approval_id": "a-1",
        "user_id": "u-1",
        "session_id": "sess-1",
        "tool_call_id": "tc-1",
        "tool_name": "sandbox_execute",
        "arguments": {"language": "python", "code": "print(1)"},
        "approval_kind": kind,
        "status": "pending",
    }


class _AuditCapture:
    """record_approval_audit 替身：记录调用 kwargs，保持 async 签名。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_approve_with_always_persists_allow_and_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeApprovalService(_approval_record())
    audits = _AuditCapture()
    monkeypatch.setattr(studio_api, "get_studio_approval_service", lambda: service)
    monkeypatch.setattr(studio_api, "record_approval_audit", audits)
    db = _FakeDb()

    result = await studio_api.approve_studio_tool(
        current_user_id="u-1",
        db=db,
        approval_id="a-1",
        req=StudioApprovalApproveRequest(always=True),
    )

    assert result == {"success": True, "status": "approved", "always": True}
    assert service.resolve_calls[0]["always"] is True
    # always_allow 经 jsonb 原子合并追加工具名
    assert len(db.executed) == 1
    _, params = db.executed[0]
    assert params is not None
    assert json.loads(params["tool"]) == "sandbox_execute"
    assert params["sid"] == "sess-1"
    # 决议落审计
    assert len(audits.calls) == 1
    assert audits.calls[0]["action"] == "approved"
    assert audits.calls[0]["always"] is True
    assert audits.calls[0]["resolver"] == "user"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_approve_without_always_skips_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeApprovalService(_approval_record())
    audits = _AuditCapture()
    monkeypatch.setattr(studio_api, "get_studio_approval_service", lambda: service)
    monkeypatch.setattr(studio_api, "record_approval_audit", audits)
    db = _FakeDb()

    result = await studio_api.approve_studio_tool(
        current_user_id="u-1",
        db=db,
        approval_id="a-1",
        req=StudioApprovalApproveRequest(),
    )

    assert result == {"success": True, "status": "approved", "always": False}
    assert service.resolve_calls[0]["always"] is False
    assert db.executed == []
    assert len(audits.calls) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_approve_plan_kind_ignores_always(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _FakeApprovalService(_approval_record(kind="plan"))
    monkeypatch.setattr(studio_api, "get_studio_approval_service", lambda: service)
    monkeypatch.setattr(studio_api, "record_approval_audit", _AuditCapture())
    db = _FakeDb()

    result = await studio_api.approve_studio_tool(
        current_user_id="u-1",
        db=db,
        approval_id="a-1",
        req=StudioApprovalApproveRequest(always=True),
    )

    # 计划审批无"同工具复用"语义，always 不生效也不落 always_allow
    assert result["always"] is False
    assert service.resolve_calls[0]["always"] is False
    assert db.executed == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_permissions_clears_always_allow() -> None:
    session = SimpleNamespace(mode="studio", sandbox_meta={})
    service = _FakeChatService(session)
    db = _FakeDb(merged_permissions={"mode": "auto", "always_allow": []})

    result = await studio_api.update_studio_permissions(
        current_user_id="u-1",
        service=service,
        db=db,
        session_id="sess-1",
        req=UpdateStudioPermissionsRequest(mode="auto"),
    )

    assert len(db.executed) == 1
    _, params = db.executed[0]
    assert params is not None
    patch = json.loads(params["patch"])
    # 模式切换（含切回）清空"本会话总是允许"集合，避免残留放行
    assert patch == {"mode": "auto", "always_allow": []}
    assert result == {"permissions": {"mode": "auto", "always_allow": []}}
