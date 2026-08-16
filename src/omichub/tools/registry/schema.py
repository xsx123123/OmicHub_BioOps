"""工具箱注册表 Schema —— 前端工具卡片 DTO。

字段命名与前端 `frontend/src/types/tools.ts` 对齐：
ToolItemDTO 直接对应前端 ToolItem，外层用 { data: [...] } 包络（与 SpeciesListResponse 一致）。
"""

from __future__ import annotations

from omichub.application.schemas.base import OmicsHubBaseSchema


class ToolItemDTO(OmicsHubBaseSchema):
    """单个工具卡片（前端 ToolItem）。

    仅暴露前端渲染所需字段；config_dir 是文档性字段，前端可据其跳转工具配置目录，
    但不参与渲染。
    """

    key: str
    title: str
    description: str = ""
    icon: str
    gradient: str
    route: str
    group: str = ""
    order: int = 0
    config_dir: str = ""


class ToolListResponse(OmicsHubBaseSchema):
    """GET /tools 响应包络（前端解 { data: [...] }）。"""

    data: list[ToolItemDTO] = []


class ToolReloadResponse(OmicsHubBaseSchema):
    """POST /tools/reload 响应。"""

    message: str = "工具箱注册表已重载"
    tools_count: int
