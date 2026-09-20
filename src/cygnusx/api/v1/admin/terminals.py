"""终端会话管理 — 管理端路由

管理员可查看全量活跃沙盒终端，包括：
- 所属用户、会话 ID、容器 ID/名称
- 已使用时长、配置资源
- 实时 CPU / 内存占用（可选）
- 手动销毁按钮
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from cygnusx.api.deps import DbSession
from cygnusx.application.schemas.terminal import AdminTerminalSessionDTO
from cygnusx.application.services.terminal_service import TerminalService
from cygnusx.middleware.rbac import AdminRequired

router = APIRouter()


def _get_service(db: DbSession) -> TerminalService:
    return TerminalService(db)


TerminalServiceDep = Annotated[TerminalService, Depends(_get_service)]


@router.get("", response_model=list[AdminTerminalSessionDTO], summary="终端会话列表")
async def list_terminal_sessions(
    _admin: AdminRequired,
    service: TerminalServiceDep,
    include_stats: Annotated[bool, Query(description="是否包含实时 Docker 资源占用")] = False,
) -> list[AdminTerminalSessionDTO]:
    """列出所有活跃终端会话（管理员）。"""
    return await service.list_all_sessions(include_stats=include_stats)


@router.delete("/{session_id}", summary="强制销毁终端会话")
async def destroy_terminal_session(
    session_id: str,
    _admin: AdminRequired,
    service: TerminalServiceDep,
) -> dict[str, bool]:
    """管理员强制销毁指定终端会话及其 Docker 容器。"""
    ok = await service.admin_delete_session(session_id)
    return {"deleted": ok}
