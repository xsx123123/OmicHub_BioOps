"""Skill 管理 API — 管理员 CRUD + SKILL.md 标准导入（五入口 + 预览确认）"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from cygnusx.api.deps import CurrentUserId, DbSession
from cygnusx.api.v1.admin.users import AdminRequired
from cygnusx.application.schemas.skill import (
    AliyunMarketplaceStatusDTO,
    CreateSkillDTO,
    GithubImportRequest,
    JsonImportRequest,
    SkillDTO,
    SkillImportConfirmDTO,
    SkillImportPreviewDTO,
    SkillInvocationDTO,
    SkillInvocationStatDTO,
    SkillMarketplaceItemDTO,
    SkillReferenceDTO,
    SkillRollbackRequest,
    SkillUpdateCheckDTO,
    SkillVersionDetailDTO,
    SkillVersionDTO,
    UpdateSkillDTO,
)
from cygnusx.application.services.skill_import_service import SkillImportService
from cygnusx.application.services.skill_service import SkillService
from cygnusx.core.exceptions import BusinessError
from cygnusx.infrastructure.skills.skillmd import SkillParseError

router = APIRouter()

MAX_SKILL_UPLOAD_BYTES = 6 * 1024 * 1024


def get_skill_service(db: DbSession) -> SkillService:
    return SkillService(db)


def get_skill_import_service(db: DbSession) -> SkillImportService:
    return SkillImportService(db)


SkillServiceDep = Annotated[SkillService, Depends(get_skill_service)]
SkillImportServiceDep = Annotated[SkillImportService, Depends(get_skill_import_service)]


def _wrap_parse_error(exc: SkillParseError) -> BusinessError:
    return BusinessError(f"技能解析失败：{exc}")


@router.get("", response_model=list[SkillDTO], summary="技能列表")
async def list_skills(
    _admin: AdminRequired,
    service: SkillServiceDep,
    active_only: bool = False,
) -> list[SkillDTO]:
    return await service.list_skills(active_only=active_only)


@router.post("", response_model=SkillDTO, status_code=201, summary="创建技能")
async def create_skill(
    _admin: AdminRequired,
    current_user_id: CurrentUserId,
    service: SkillServiceDep,
    req: CreateSkillDTO,
) -> SkillDTO:
    return await service.create_skill(req, actor_id=uuid.UUID(current_user_id))


# ---------- 技能市场（内置可安装技能） ----------


@router.get(
    "/marketplace",
    response_model=list[SkillMarketplaceItemDTO],
    summary="技能市场列表",
)
async def list_marketplace(
    _admin: AdminRequired,
    service: SkillImportServiceDep,
) -> list[SkillMarketplaceItemDTO]:
    return await service.list_marketplace()


@router.post(
    "/marketplace/{skill_id}/install",
    response_model=SkillDTO,
    summary="安装市场技能",
)
async def install_marketplace(
    _admin: AdminRequired,
    service: SkillImportServiceDep,
    skill_id: str,
    overwrite: bool = False,
) -> SkillDTO:
    return await service.install_marketplace(skill_id, overwrite=overwrite)


# ---------- 阿里云官方技能源（市场第二分组） ----------


@router.get(
    "/marketplace/aliyun/status",
    response_model=AliyunMarketplaceStatusDTO,
    summary="阿里云官方技能源同步状态",
)
async def aliyun_marketplace_status(
    _admin: AdminRequired,
    service: SkillImportServiceDep,
) -> AliyunMarketplaceStatusDTO:
    return await service.aliyun_status()


@router.post(
    "/marketplace/aliyun/sync",
    response_model=AliyunMarketplaceStatusDTO,
    summary="同步阿里云官方技能源",
)
async def sync_aliyun_marketplace(
    _admin: AdminRequired,
    service: SkillImportServiceDep,
    force: bool = False,
) -> AliyunMarketplaceStatusDTO:
    return await service.sync_aliyun_marketplace(force=force)


@router.post(
    "/marketplace/aliyun/{skill_id}/install",
    response_model=SkillDTO,
    summary="安装阿里云官方技能",
)
async def install_aliyun_marketplace(
    _admin: AdminRequired,
    service: SkillImportServiceDep,
    skill_id: str,
    overwrite: bool = False,
) -> SkillDTO:
    return await service.install_aliyun(skill_id, overwrite=overwrite)


# ---------- 调用记录（Skill 调用可视化） ----------


@router.get(
    "/invocation-stats",
    response_model=list[SkillInvocationStatDTO],
    summary="技能调用聚合统计",
)
async def skill_invocation_stats(
    _admin: AdminRequired,
    service: SkillServiceDep,
) -> list[SkillInvocationStatDTO]:
    return await service.invocation_stats()


# ---------- 导入：四入口统一先预览、确认后入库 ----------


@router.post(
    "/import/github",
    response_model=SkillImportPreviewDTO,
    summary="从 GitHub 仓库/子目录解析技能（预览）",
)
async def import_from_github(
    _admin: AdminRequired,
    service: SkillImportServiceDep,
    req: GithubImportRequest,
) -> SkillImportPreviewDTO:
    try:
        return await service.parse_from_github(req.url)
    except SkillParseError as exc:
        raise _wrap_parse_error(exc) from exc


@router.post(
    "/import/zip",
    response_model=SkillImportPreviewDTO,
    summary="上传 zip 技能包（预览）",
)
async def import_from_zip(
    _admin: AdminRequired,
    service: SkillImportServiceDep,
    file: UploadFile = File(...),
) -> SkillImportPreviewDTO:
    data = await file.read()
    if len(data) > MAX_SKILL_UPLOAD_BYTES:
        raise BusinessError(f"上传文件超过 {MAX_SKILL_UPLOAD_BYTES // 1024 // 1024}MB 上限")
    try:
        return await service.parse_from_zip(data)
    except SkillParseError as exc:
        raise _wrap_parse_error(exc) from exc


@router.post(
    "/import/markdown",
    response_model=SkillImportPreviewDTO,
    summary="上传 Markdown 指令文件（预览）",
)
async def import_from_markdown(
    _admin: AdminRequired,
    service: SkillImportServiceDep,
    file: UploadFile = File(...),
) -> SkillImportPreviewDTO:
    filename = file.filename or "skill.md"
    if not filename.lower().endswith(".md"):
        raise BusinessError("仅支持上传 .md 格式的技能指令文件")
    data = await file.read()
    if len(data) > MAX_SKILL_UPLOAD_BYTES:
        raise BusinessError(f"上传文件超过 {MAX_SKILL_UPLOAD_BYTES // 1024 // 1024}MB 上限")
    try:
        return await service.parse_from_markdown(data, filename)
    except SkillParseError as exc:
        raise _wrap_parse_error(exc) from exc


@router.post(
    "/import/json",
    response_model=SkillImportPreviewDTO,
    summary="JSON 粘贴导入（兼容旧格式，预览）",
)
async def import_from_json(
    _admin: AdminRequired,
    service: SkillImportServiceDep,
    req: JsonImportRequest,
) -> SkillImportPreviewDTO:
    try:
        return await service.parse_from_json(req.text)
    except SkillParseError as exc:
        raise _wrap_parse_error(exc) from exc


@router.post(
    "/import/confirm",
    response_model=SkillDTO,
    summary="确认导入（预览通过后入库）",
)
async def confirm_import(
    _admin: AdminRequired,
    service: SkillImportServiceDep,
    req: SkillImportConfirmDTO,
) -> SkillDTO:
    try:
        return await service.confirm_import(req.preview, overwrite=req.overwrite)
    except SkillParseError as exc:
        raise _wrap_parse_error(exc) from exc


@router.get("/{skill_id}", response_model=SkillDTO, summary="技能详情")
async def get_skill(
    _admin: AdminRequired,
    service: SkillServiceDep,
    skill_id: str,
) -> SkillDTO:
    return await service.get_skill(skill_id)


@router.put("/{skill_id}", response_model=SkillDTO, summary="更新技能")
async def update_skill(
    _admin: AdminRequired,
    current_user_id: CurrentUserId,
    service: SkillServiceDep,
    skill_id: str,
    req: UpdateSkillDTO,
) -> SkillDTO:
    return await service.update_skill(skill_id, req, actor_id=uuid.UUID(current_user_id))


@router.get(
    "/{skill_id}/references",
    response_model=list[SkillReferenceDTO],
    summary="查询引用该技能的助手",
)
async def skill_references(
    _admin: AdminRequired,
    service: SkillServiceDep,
    skill_id: str,
) -> list[SkillReferenceDTO]:
    return await service.skill_references(skill_id)


@router.delete("/{skill_id}", summary="删除技能")
async def delete_skill(
    _admin: AdminRequired,
    service: SkillServiceDep,
    skill_id: str,
    force: bool = False,
) -> dict[str, bool]:
    """被助手引用时需 force=true 二次确认；版本快照保留（软删除主档）"""
    await service.delete_skill(skill_id, force=force)
    return {"deleted": True}


@router.post("/{skill_id}/toggle", response_model=SkillDTO, summary="启用/停用技能")
async def toggle_skill(
    _admin: AdminRequired,
    service: SkillServiceDep,
    skill_id: str,
) -> SkillDTO:
    return await service.toggle_skill(skill_id)


# ---------- 版本控制（快照 + 回滚） ----------


@router.get(
    "/{skill_id}/versions",
    response_model=list[SkillVersionDTO],
    summary="技能版本历史",
)
async def list_skill_versions(
    _admin: AdminRequired,
    service: SkillServiceDep,
    skill_id: str,
) -> list[SkillVersionDTO]:
    return await service.list_skill_versions(skill_id)


@router.post("/{skill_id}/rollback", response_model=SkillDTO, summary="回滚技能到指定版本")
async def rollback_skill(
    _admin: AdminRequired,
    current_user_id: CurrentUserId,
    service: SkillServiceDep,
    skill_id: str,
    req: SkillRollbackRequest,
) -> SkillDTO:
    return await service.rollback_skill(
        skill_id, req.revision, actor_id=uuid.UUID(current_user_id)
    )


@router.get(
    "/{skill_id}/versions/{revision}",
    response_model=SkillVersionDetailDTO,
    summary="版本快照详情（含正文，供 diff）",
)
async def get_skill_version_detail(
    _admin: AdminRequired,
    service: SkillServiceDep,
    skill_id: str,
    revision: int,
) -> SkillVersionDetailDTO:
    return await service.get_skill_version(skill_id, revision)


@router.post(
    "/{skill_id}/check-update",
    response_model=SkillUpdateCheckDTO,
    summary="检查上游更新",
)
async def check_update(
    _admin: AdminRequired,
    service: SkillImportServiceDep,
    skill_id: str,
) -> SkillUpdateCheckDTO:
    return await service.check_update(skill_id)


@router.get(
    "/{skill_id}/invocations",
    response_model=list[SkillInvocationDTO],
    summary="技能调用记录",
)
async def list_skill_invocations(
    _admin: AdminRequired,
    service: SkillServiceDep,
    skill_id: str,
    limit: int = 20,
) -> list[SkillInvocationDTO]:
    return await service.list_invocations(skill_id, limit=limit)
