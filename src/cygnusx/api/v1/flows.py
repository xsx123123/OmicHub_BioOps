"""流程定义路由 — YAML 配置中心 API。

- GET    /flows                  列表（支持 ?category= 过滤）
- GET    /flows/{flow_id}        流程详情（完整 FlowConfig）
- GET    /flows/{flow_id}/schema 流程参数 JSON Schema（前端动态表单用）
- GET    /flows/schema           顶层 FlowConfig JSON Schema（类型生成用）
- POST   /flows/reload           热重载所有 YAML 配置
"""

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from cygnusx.application.schemas.flow import (
    FlowDetailDTO,
    FlowListResponse,
    FlowReloadResponse,
)
from cygnusx.application.services.flow_service import FlowService

router = APIRouter()


@lru_cache(maxsize=1)
def get_flow_service() -> FlowService:
    """获取 FlowService 实例（单例，缓存 repository）"""
    return FlowService()


FlowServiceDep = Annotated[FlowService, Depends(get_flow_service)]


@router.get("", response_model=FlowListResponse, summary="获取流程列表")
async def list_flows(
    service: FlowServiceDep,
    category: Annotated[str | None, Query(description="按分类过滤")] = None,
) -> FlowListResponse:
    """获取所有可用流程的列表"""
    return service.list_flows(category=category)


@router.get(
    "/schema",
    response_model=dict,
    summary="获取 FlowConfig 顶层 JSON Schema",
    description="返回 FlowConfig 的完整 JSON Schema (Draft 2020-12)，供前端类型生成使用",
)
async def get_top_schema(service: FlowServiceDep) -> dict:
    """获取顶层 FlowConfig JSON Schema"""
    return service.get_flow_json_schema(flow_id=None)


@router.post(
    "/reload",
    response_model=FlowReloadResponse,
    summary="热重载所有流程配置",
)
async def reload_flows(service: FlowServiceDep) -> FlowReloadResponse:
    """重新扫描 YAML 目录并加载所有流程配置"""
    return service.reload()


@router.get(
    "/{flow_id}",
    response_model=FlowDetailDTO,
    summary="获取流程详情",
)
async def get_flow(flow_id: str, service: FlowServiceDep) -> FlowDetailDTO:
    """获取指定流程的完整配置"""
    return service.get_flow(flow_id)


@router.get(
    "/{flow_id}/schema",
    response_model=dict,
    summary="获取流程参数 JSON Schema",
    description="返回该流程参数定义的 JSON Schema，供前端动态表单渲染与校验",
)
async def get_flow_schema(flow_id: str, service: FlowServiceDep) -> dict:
    """获取流程的参数 JSON Schema"""
    return service.get_flow_json_schema(flow_id=flow_id)
