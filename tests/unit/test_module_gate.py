"""模块权限拦截中间件单元测试 — 前缀匹配规则 / admin 跳过 / 命中禁用。"""

import json
from types import SimpleNamespace

import pytest
from starlette.requests import Request
from starlette.responses import Response

from cygnusx.infrastructure.config.module_registry import ModuleEntry, ModuleRegistry
from cygnusx.middleware import module_gate
from cygnusx.middleware.module_gate import ModuleGateMiddleware, match_module_by_path


def _module(key: str, api_prefix: list[str], lockable: bool = True) -> ModuleEntry:
    return ModuleEntry(
        key=key,
        name=key,
        route_prefix=[f"/{key}"],
        api_prefix=api_prefix,
        lockable=lockable,
        default_locked=False,
        ai=False,
    )


_MODULES = [
    _module("cookies", ["/api/v1/cookies"]),
    _module("ai-assistant", ["/api/v1/chat", "/api/v1/ai"]),
    _module("tools", ["/api/v1/deg", "/api/v1/tools"]),
    _module("about", []),
    _module("admin", ["/api/v1/admin"], lockable=False),
]


def test_match_exact_prefix():
    assert match_module_by_path("/api/v1/cookies", _MODULES).key == "cookies"


def test_match_prefix_with_subpath():
    assert match_module_by_path("/api/v1/chat/sessions/abc", _MODULES).key == "ai-assistant"


def test_match_does_not_hit_sibling_prefix():
    """精确规则：/api/v1/admin/cookies 不被 /api/v1/cookies 误伤。

    中间件只对 lockable_modules() 做匹配，admin 模块（lockable=false）不在其中。
    """
    lockable_only = [m for m in _MODULES if m.lockable]
    assert match_module_by_path("/api/v1/admin/cookies", lockable_only) is None
    # /api/v1/downloads 不被 /api/v1/deg 误伤
    assert match_module_by_path("/api/v1/downloads", lockable_only) is None


def test_match_skips_empty_and_lockable_false():
    """api_prefix 为空的模块永不命中；lockable=false 由 lockable_modules() 过滤。"""
    assert match_module_by_path("/api/v1/anything", _MODULES) is None
    lockable_only = [m for m in _MODULES if m.lockable]
    assert match_module_by_path("/api/v1/admin", lockable_only) is None


# ------------------------------------------------------------------
# dispatch 级测试（mock 注册表与用户查询）
# ------------------------------------------------------------------
def _make_request(path: str, user_id: str | None = "u-1") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "scheme": "http",
        "server": ("test", 80),
        "path": path,
        "query_string": b"",
        "headers": [],
        "state": {},
    }
    if user_id is not None:
        scope["state"]["user_id"] = user_id
    return Request(scope)


async def _ok_call_next(request: Request) -> Response:
    return Response(status_code=200, content="ok", media_type="text/plain")


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> ModuleRegistry:
    reg = ModuleRegistry(modules=tuple(_MODULES))
    monkeypatch.setattr(module_gate, "get_module_registry", lambda: reg)
    return reg


@pytest.fixture
def gate() -> ModuleGateMiddleware:
    return ModuleGateMiddleware(app=lambda scope, receive, send: None)


async def test_dispatch_blocks_disabled_module(
    gate: ModuleGateMiddleware, registry: ModuleRegistry, monkeypatch: pytest.MonkeyPatch
):
    """用户 disabled_modules 含命中模块时返回 403 + MODULE_LOCKED。"""
    async def _blocked(user_id: str, module_key: str) -> bool:
        return True

    monkeypatch.setattr(ModuleGateMiddleware, "_is_module_blocked", staticmethod(_blocked))
    response = await gate.dispatch(_make_request("/api/v1/chat/sessions"), _ok_call_next)
    assert response.status_code == 403
    body = json.loads(response.body)
    assert body["detail"] == "该模块未开通，请联系管理员解锁"
    assert body["code"] == "MODULE_LOCKED"


async def test_dispatch_passes_when_module_not_disabled(
    gate: ModuleGateMiddleware, registry: ModuleRegistry, monkeypatch: pytest.MonkeyPatch
):
    """模块未被禁用时放行。"""

    async def _allowed(user_id: str, module_key: str) -> bool:
        return False

    monkeypatch.setattr(ModuleGateMiddleware, "_is_module_blocked", staticmethod(_allowed))
    response = await gate.dispatch(_make_request("/api/v1/chat/sessions"), _ok_call_next)
    assert response.status_code == 200


async def test_dispatch_passes_unmanaged_path(
    gate: ModuleGateMiddleware, registry: ModuleRegistry, monkeypatch: pytest.MonkeyPatch
):
    """未命中注册表的路径不触发用户查询，直接放行。"""
    called = False

    async def _spy(user_id: str, module_key: str) -> bool:
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(ModuleGateMiddleware, "_is_module_blocked", staticmethod(_spy))
    response = await gate.dispatch(_make_request("/api/v1/auth/me"), _ok_call_next)
    assert response.status_code == 200
    assert called is False


async def test_dispatch_passes_anonymous(
    gate: ModuleGateMiddleware, registry: ModuleRegistry, monkeypatch: pytest.MonkeyPatch
):
    """未认证请求放行，由下游依赖处理 401。"""
    async def _blocked(user_id: str, module_key: str) -> bool:
        return True

    monkeypatch.setattr(ModuleGateMiddleware, "_is_module_blocked", staticmethod(_blocked))
    response = await gate.dispatch(_make_request("/api/v1/chat/sessions", user_id=None), _ok_call_next)
    assert response.status_code == 200


# ------------------------------------------------------------------
# _is_module_blocked：admin 跳过 / 命中禁用 / 异常降级
# ------------------------------------------------------------------
def _fake_user(role: str = "user", disabled: list[str] | None = None):
    return SimpleNamespace(role=role, disabled_modules=disabled or [])


class _FakeSession:
    def __init__(self, user):
        self._user = user

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, model, key):
        if isinstance(self._user, Exception):
            raise self._user
        return self._user


def _patch_session_factory(monkeypatch: pytest.MonkeyPatch, user):
    from cygnusx.infrastructure.database import session as db_session

    monkeypatch.setattr(db_session, "get_session_factory", lambda: (lambda: _FakeSession(user)))


async def test_is_module_blocked_admin_skipped(monkeypatch: pytest.MonkeyPatch):
    """管理员角色即使 disabled_modules 非空也不拦截。"""
    _patch_session_factory(monkeypatch, _fake_user(role="admin", disabled=["ai-assistant"]))
    assert await ModuleGateMiddleware._is_module_blocked("6f5e61f0-0000-0000-0000-000000000001", "ai-assistant") is False


async def test_is_module_blocked_hit_disabled(monkeypatch: pytest.MonkeyPatch):
    """普通用户 disabled_modules 含该模块时拦截。"""
    _patch_session_factory(monkeypatch, _fake_user(disabled=["ai-assistant"]))
    uid = "6f5e61f0-0000-0000-0000-000000000001"
    assert await ModuleGateMiddleware._is_module_blocked(uid, "ai-assistant") is True
    assert await ModuleGateMiddleware._is_module_blocked(uid, "tools") is False


async def test_is_module_blocked_degrades_on_error(monkeypatch: pytest.MonkeyPatch):
    """数据库异常时降级放行（不阻断正常业务）。"""
    _patch_session_factory(monkeypatch, RuntimeError("db down"))
    assert await ModuleGateMiddleware._is_module_blocked("6f5e61f0-0000-0000-0000-000000000001", "ai-assistant") is False
