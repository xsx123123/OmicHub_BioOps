"""管理端模块权限接口单元测试 — PUT /admin/users/{user_id}/modules 校验逻辑。

防自锁（管理员目标 403）/ 非法 key（400）/ 正常保存。
直接调用端点函数，用假 DbSession 与假注册表隔离数据库。
"""

import uuid
from types import SimpleNamespace

import pytest

from omichub.api.v1.admin import users as admin_users
from omichub.application.schemas.user import UserModulesUpdateRequest
from omichub.core.exceptions import AuthorizationError, BusinessError, NotFoundError
from omichub.infrastructure.config.module_registry import ModuleEntry, ModuleRegistry


def _registry() -> ModuleRegistry:
    return ModuleRegistry(
        modules=(
            ModuleEntry(
                key="ai-assistant",
                name="AI 助手",
                route_prefix=["/ai"],
                api_prefix=["/api/v1/chat"],
                lockable=True,
                default_locked=False,
                ai=True,
            ),
            ModuleEntry(
                key="admin",
                name="系统管理",
                route_prefix=["/admin"],
                api_prefix=["/api/v1/admin"],
                lockable=False,
                default_locked=False,
                ai=False,
            ),
        )
    )


class _FakeDB:
    def __init__(self, user):
        self._user = user

    async def get(self, model, key):
        return self._user

    async def flush(self):
        return None


@pytest.fixture(autouse=True)
def fake_registry(monkeypatch: pytest.MonkeyPatch):
    # 端点内局部 import get_module_registry，patch 源模块即可生效
    import omichub.infrastructure.config.module_registry as registry_mod

    monkeypatch.setattr(registry_mod, "get_module_registry", _registry)


async def test_update_modules_success():
    """普通用户合法 key 保存成功，返回契约结构。"""
    user = SimpleNamespace(id=uuid.uuid4(), role="user", disabled_modules=[])
    req = UserModulesUpdateRequest(disabled_modules=["ai-assistant"])
    result = await admin_users.update_user_modules(user.id, req, _admin="admin-id", db=_FakeDB(user))
    assert result == {"id": str(user.id), "disabled_modules": ["ai-assistant"]}
    assert user.disabled_modules == ["ai-assistant"]


async def test_update_modules_dedupes_keys():
    """重复 key 去重且保持请求顺序。"""
    user = SimpleNamespace(id=uuid.uuid4(), role="user", disabled_modules=["ai-assistant"])
    req = UserModulesUpdateRequest(disabled_modules=["ai-assistant", "ai-assistant"])
    result = await admin_users.update_user_modules(user.id, req, _admin="admin-id", db=_FakeDB(user))
    assert result["disabled_modules"] == ["ai-assistant"]


async def test_update_modules_rejects_admin_target():
    """目标用户是管理员时 403（防自锁，含管理员改自己）。"""
    user = SimpleNamespace(id=uuid.uuid4(), role="admin", disabled_modules=[])
    req = UserModulesUpdateRequest(disabled_modules=["ai-assistant"])
    with pytest.raises(AuthorizationError, match="管理员默认拥有全部模块权限，不可取消"):
        await admin_users.update_user_modules(user.id, req, _admin="admin-id", db=_FakeDB(user))


async def test_update_modules_rejects_invalid_key():
    """未知模块 key → 400。"""
    user = SimpleNamespace(id=uuid.uuid4(), role="user", disabled_modules=[])
    req = UserModulesUpdateRequest(disabled_modules=["not-a-module"])
    with pytest.raises(BusinessError, match="无效的模块 key"):
        await admin_users.update_user_modules(user.id, req, _admin="admin-id", db=_FakeDB(user))


async def test_update_modules_rejects_non_lockable_key():
    """lockable=false 的模块（系统管理）不允许写入 → 400。"""
    user = SimpleNamespace(id=uuid.uuid4(), role="user", disabled_modules=[])
    req = UserModulesUpdateRequest(disabled_modules=["admin"])
    with pytest.raises(BusinessError, match="无效的模块 key"):
        await admin_users.update_user_modules(user.id, req, _admin="admin-id", db=_FakeDB(user))


async def test_update_modules_user_not_found():
    """目标用户不存在 → 404。"""
    req = UserModulesUpdateRequest(disabled_modules=[])
    with pytest.raises(NotFoundError):
        await admin_users.update_user_modules(uuid.uuid4(), req, _admin="admin-id", db=_FakeDB(None))
