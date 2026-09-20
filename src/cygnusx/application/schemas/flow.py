"""流程相关 DTO 模型"""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

from cygnusx.application.schemas.base import CygnusXBaseSchema
from cygnusx.domain.flow.entities import FlowConfig, Parameter


class FlowMetaDTO(CygnusXBaseSchema):
    """流程元信息 DTO"""

    id: str
    name: str
    category: str
    version: str
    description: str
    author: str | None = None
    tags: list[str] = []
    icon: str | None = None
    color: str | None = None
    docs_url: str | None = None
    github_url: str | None = None


class FlowListItemDTO(CygnusXBaseSchema):
    """流程列表项 DTO — 用于列表展示"""

    id: str
    name: str
    category: str
    version: str
    description: str
    author: str | None = None
    tags: list[str] = []
    icon: str | None = None
    color: str | None = None
    docs_url: str | None = None
    github_url: str | None = None
    parameter_count: int = 0
    has_sample_sheet: bool = False


class FlowDetailDTO(CygnusXBaseSchema):
    """流程详情 DTO — 完整 FlowConfig"""

    meta: FlowMetaDTO
    parameters: list[Parameter]
    execution: dict[str, Any]
    groups: list[dict[str, Any]] | None = None
    sample_sheet: dict[str, Any] | None = None
    pipeline_mapping: dict[str, Any] | None = None


class FlowListResponse(CygnusXBaseSchema):
    """流程列表响应"""

    items: list[FlowListItemDTO]
    total: int


class FlowReloadResponse(CygnusXBaseSchema):
    """流程热重载响应"""

    loaded: int
    message: str


def flow_config_to_list_item(config: FlowConfig) -> FlowListItemDTO:
    """FlowConfig → FlowListItemDTO"""
    return FlowListItemDTO(
        id=config.meta.id,
        name=config.meta.name,
        category=config.meta.category,
        version=config.meta.version,
        description=config.meta.description,
        author=config.meta.author,
        tags=config.meta.tags,
        icon=config.meta.icon,
        color=config.meta.color,
        docs_url=config.meta.docs_url,
        github_url=config.meta.github_url,
        parameter_count=len(config.parameters),
        has_sample_sheet=config.sample_sheet is not None,
    )


def flow_config_to_detail(config: FlowConfig) -> FlowDetailDTO:
    """FlowConfig → FlowDetailDTO"""
    return FlowDetailDTO(
        meta=FlowMetaDTO(
            id=config.meta.id,
            name=config.meta.name,
            category=config.meta.category,
            version=config.meta.version,
            description=config.meta.description,
            author=config.meta.author,
            tags=config.meta.tags,
            icon=config.meta.icon,
            color=config.meta.color,
            docs_url=config.meta.docs_url,
            github_url=config.meta.github_url,
        ),
        parameters=config.parameters,
        execution=config.execution.model_dump(),
        groups=[g.model_dump() for g in config.groups] if config.groups else None,
        sample_sheet=config.sample_sheet.model_dump(by_alias=True) if config.sample_sheet else None,
        pipeline_mapping=config.pipeline_mapping.model_dump() if config.pipeline_mapping else None,
    )


def export_flow_json_schema() -> dict[str, Any]:
    """导出 FlowConfig 的 JSON Schema (Draft 2020-12) — 供前端使用"""
    adapter = TypeAdapter(FlowConfig)
    return adapter.json_schema()


def export_parameter_json_schema() -> dict[str, Any]:
    """导出 Parameter 的独立 JSON Schema — 供前端动态表单校验"""
    adapter = TypeAdapter(Parameter)
    return adapter.json_schema()
