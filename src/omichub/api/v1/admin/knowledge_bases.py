"""知识库资源管理接口（AI 配置中心）。"""

from typing import Annotated

from fastapi import APIRouter, Depends

from omichub.api.deps import DbSession
from omichub.api.v1.admin.users import AdminRequired
from omichub.application.schemas.knowledge_base import (
    KnowledgeBaseCreateDTO,
    KnowledgeBaseDocDTO,
    KnowledgeBaseDTO,
    KnowledgeBaseUpdateDTO,
)
from omichub.application.services.knowledge_base_service import KnowledgeBaseService

router = APIRouter()


def get_service(db: DbSession) -> KnowledgeBaseService:
    return KnowledgeBaseService(db)


ServiceDep = Annotated[KnowledgeBaseService, Depends(get_service)]


@router.get("", response_model=list[KnowledgeBaseDTO])
async def list_knowledge_bases(_admin: AdminRequired, service: ServiceDep) -> list[KnowledgeBaseDTO]:
    return await service.list_bases()


@router.post("", response_model=KnowledgeBaseDTO)
async def create_knowledge_base(
    dto: KnowledgeBaseCreateDTO, _admin: AdminRequired, service: ServiceDep
) -> KnowledgeBaseDTO:
    return await service.create_base(dto)


@router.put("/{kb_id}", response_model=KnowledgeBaseDTO)
async def update_knowledge_base(
    kb_id: str, dto: KnowledgeBaseUpdateDTO, _admin: AdminRequired, service: ServiceDep
) -> KnowledgeBaseDTO:
    return await service.update_base(kb_id, dto)


@router.delete("/{kb_id}")
async def delete_knowledge_base(kb_id: str, _admin: AdminRequired, service: ServiceDep) -> dict[str, bool]:
    await service.delete_base(kb_id)
    return {"ok": True}


@router.get("/{kb_id}/docs", response_model=list[KnowledgeBaseDocDTO])
async def list_knowledge_base_docs(
    kb_id: str, _admin: AdminRequired, service: ServiceDep
) -> list[KnowledgeBaseDocDTO]:
    return await service.list_docs(kb_id)
