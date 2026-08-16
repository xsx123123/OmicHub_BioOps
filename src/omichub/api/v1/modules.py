"""模块注册表下发 API — 把 data/MODULE_LOCKED.yaml 的模块清单下发给前端

权限对话框、路由守卫、侧边栏锁定态全部从本接口取模块清单，
前端任何位置禁止写死模块名。共享基础设施接口，永不拦截。
"""

from typing import Any

from fastapi import APIRouter

from omichub.api.deps import CurrentUserId
from omichub.infrastructure.config.module_registry import get_module_registry

router = APIRouter()


@router.get("/registry", summary="模块注册表")
async def get_modules_registry(_user_id: CurrentUserId) -> dict[str, Any]:
    """下发平台模块注册表（含 lockable=false 条目，供前端区分管理员专属模块）。

    需登录即可访问；返回条目含 key / name / route_prefix / api_prefix /
    lockable / default_locked / ai。
    """
    return get_module_registry().to_dict()
