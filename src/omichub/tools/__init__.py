"""生信工具箱模块包 —— 每个工具自成子包（registry / jbrowse / enrichments / ...）。

设计目标：让工具像「插件模块」一样自包含。每个工具子包把该工具的全部代码
（api 路由 / service / schema / config / tasks / runner）收口在一个目录里，
仓库根的 ``tool_configs/`` 只放 YAML 配置，配置与代码职责分离。

新增工具（带后端逻辑）：
  1. 本包下建子包 ``<工具名>/``，内含 ``api.py``（声明 ``router`` / ``prefix`` / ``tags``）
     及 service / schema / config 等；
  2. 在仓库根 ``tool_configs/tools_setting.yaml`` 登记前端展示元数据；
  3. 功能配置放仓库根 ``tool_configs/<工具名>/*.yaml``，由子包内 config 加载器读取。
  无需改 ``api/v1/router.py`` —— ``register_tool_routers`` 会自动发现并挂载子包路由。

自动发现约定：子包若有 ``api`` 模块且带 ``router`` 属性，即被视为可挂载工具；
``prefix`` / ``tags`` 缺省时按子包名推导。子包无 ``api`` 模块（纯配置工具）会被跳过。
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from types import ModuleType
from typing import Any

logger = logging.getLogger(__name__)

#: 子包 ``api`` 模块上识别路由的属性名
ROUTER_ATTR = "router"
#: 路由前缀属性名（缺省取子包名，如 ``jbrowse`` → ``/jbrowse``）
PREFIX_ATTR = "prefix"
#: OpenAPI tags 属性名（缺省取子包名）
TAGS_ATTR = "tags"


def discover_tool_api_modules() -> list[ModuleType]:
    """自动发现 ``omichub.tools`` 下所有子包的 ``api`` 模块。

    无 ``api`` 模块的子包（纯配置 / 尚未落地后端的工具）静默跳过。
    子包按名称升序处理，保证路由挂载顺序确定。
    """
    modules: list[ModuleType] = []
    for mod_info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        dotted = f"{__name__}.{mod_info.name}.api"
        try:
            mod = importlib.import_module(dotted)
        except ModuleNotFoundError:
            # 子包无 api.py —— 纯配置工具，跳过
            continue
        if hasattr(mod, ROUTER_ATTR):
            modules.append(mod)
    return modules


def register_tool_routers(api_router: Any) -> list[str]:
    """把所有工具子包的路由自动挂载到 ``api_router``。

    供 ``api/v1/router.py`` 调用，替代逐工具手写 ``include_router``。
    返回已挂载的工具名列表（便于启动日志 / 排障）。
    """
    mounted: list[str] = []
    for mod in discover_tool_api_modules():
        tool_name = mod.__name__.rsplit(".", 2)[-2]  # omichub.tools.<name>.api → <name>
        prefix = getattr(mod, PREFIX_ATTR, f"/{tool_name}")
        tags = getattr(mod, TAGS_ATTR, [tool_name])
        api_router.include_router(mod.router, prefix=prefix, tags=tags)
        mounted.append(tool_name)
    logger.info("已自动挂载工具路由: %s", mounted)
    return mounted


__all__ = ["discover_tool_api_modules", "register_tool_routers"]
