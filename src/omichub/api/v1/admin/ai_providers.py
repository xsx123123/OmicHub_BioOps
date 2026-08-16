"""AI Provider 配置管理 — 管理端路由"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from omichub.api.deps import DbSession
from omichub.api.v1.admin.users import AdminRequired
from omichub.application.schemas.ai_provider import (
    AIProviderConfigCreateDTO,
    AIProviderConfigDTO,
    AIProviderConfigTestRequest,
    AIProviderConfigTestResponse,
    AIProviderConfigUpdateDTO,
    AIProviderDiscoverResponse,
    AIProviderTemplate,
)
from omichub.application.services.ai_provider_service import AIProviderConfigService

router = APIRouter()


def get_service(db: DbSession) -> AIProviderConfigService:
    return AIProviderConfigService(db)


ServiceDep = Annotated[AIProviderConfigService, Depends(get_service)]


@router.get("/templates", response_model=list[AIProviderTemplate], summary="内置 Provider 模板列表")
async def list_templates(
    _admin: AdminRequired,
    service: ServiceDep,
) -> list[AIProviderTemplate]:
    return await service.list_templates()


@router.get("", response_model=list[AIProviderConfigDTO], summary="AI Provider 配置列表")
async def list_configs(
    _admin: AdminRequired,
    service: ServiceDep,
) -> list[AIProviderConfigDTO]:
    return await service.list_configs()


@router.post(
    "",
    response_model=AIProviderConfigDTO,
    status_code=201,
    summary="创建 AI Provider 配置",
)
async def create_config(
    _admin: AdminRequired,
    service: ServiceDep,
    req: AIProviderConfigCreateDTO,
) -> AIProviderConfigDTO:
    return await service.create_config(req)


@router.get("/{config_id}", response_model=AIProviderConfigDTO, summary="AI Provider 配置详情")
async def get_config(
    _admin: AdminRequired,
    service: ServiceDep,
    config_id: UUID,
) -> AIProviderConfigDTO:
    return await service.get_config(config_id)


@router.put("/{config_id}", response_model=AIProviderConfigDTO, summary="更新 AI Provider 配置")
async def update_config(
    _admin: AdminRequired,
    service: ServiceDep,
    config_id: UUID,
    req: AIProviderConfigUpdateDTO,
) -> AIProviderConfigDTO:
    return await service.update_config(config_id, req)


@router.delete("/{config_id}", summary="删除 AI Provider 配置")
async def delete_config(
    _admin: AdminRequired,
    service: ServiceDep,
    config_id: UUID,
) -> dict[str, Any]:
    # 被会话/Agent 引用时降级为软删除（is_active=False），避免外键违例 500
    result = await service.delete_config(config_id)
    if result.get("soft_deleted"):
        result["message"] = "该模型已被会话或 Agent 引用，已改为停用（保留历史数据）"
    elif result.get("deleted"):
        result["message"] = "已删除"
    else:
        result["message"] = "配置不存在"
    return result


@router.post(
    "/{config_id}/set-default",
    response_model=AIProviderConfigDTO,
    summary="设为默认 AI Provider",
)
async def set_default_config(
    _admin: AdminRequired,
    service: ServiceDep,
    config_id: UUID,
) -> AIProviderConfigDTO:
    return await service.set_default(config_id)


@router.post(
    "/{config_id}/discover-models",
    response_model=AIProviderDiscoverResponse,
    summary="自动发现该 Provider 下的可用模型",
)
async def discover_models(
    _admin: AdminRequired,
    service: ServiceDep,
    config_id: UUID,
) -> AIProviderDiscoverResponse:
    return await service.discover_models(config_id)


@router.post(
    "/{config_id}/test",
    response_model=AIProviderConfigTestResponse,
    summary="测试 AI Provider 连接",
)
async def test_config(
    _admin: AdminRequired,
    service: ServiceDep,
    config_id: UUID,
    req: AIProviderConfigTestRequest | None = None,
) -> AIProviderConfigTestResponse:
    return await service.test_config(config_id, req.message if req else "")
