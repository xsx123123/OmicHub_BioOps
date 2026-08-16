"""联网搜索服务商管理接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends

from omichub.api.deps import DbSession
from omichub.api.v1.admin.users import AdminRequired
from omichub.application.schemas.search_provider import (
    SearchProviderAvailabilityDTO,
    SearchProviderDTO,
    SearchProviderTestResponse,
    SearchProviderUpdateDTO,
)
from omichub.application.services.search_provider_service import SearchProviderService

router = APIRouter()


def get_service(db: DbSession) -> SearchProviderService:
    return SearchProviderService(db)


ServiceDep = Annotated[SearchProviderService, Depends(get_service)]


@router.get("", response_model=list[SearchProviderDTO])
async def list_search_providers(_admin: AdminRequired, service: ServiceDep) -> list[SearchProviderDTO]:
    return await service.list_providers()


@router.get("/availability", response_model=SearchProviderAvailabilityDTO)
async def search_provider_availability(_admin: AdminRequired, service: ServiceDep) -> SearchProviderAvailabilityDTO:
    return await service.availability()


@router.put("/{provider_id}", response_model=SearchProviderDTO)
async def update_search_provider(provider_id: str, _admin: AdminRequired, service: ServiceDep, dto: SearchProviderUpdateDTO) -> SearchProviderDTO:
    return await service.update_provider(provider_id, dto)


@router.put("/{provider_id}/default", response_model=SearchProviderDTO)
async def set_default_search_provider(provider_id: str, _admin: AdminRequired, service: ServiceDep) -> SearchProviderDTO:
    return await service.set_default(provider_id)


@router.post("/{provider_id}/test", response_model=SearchProviderTestResponse)
async def test_search_provider(provider_id: str, _admin: AdminRequired, service: ServiceDep) -> SearchProviderTestResponse:
    return await service.test_provider(provider_id)
