"""用户管理路由"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from omichub.api.deps import CurrentUserId, DbSession
from omichub.application.schemas.agent_memory import (
    AgentMemoryClearResponse,
    AgentMemoryDTO,
    MemoryBlockDTO,
    MemoryBlockUpdateRequest,
    MemoryOverviewDTO,
)
from omichub.application.schemas.user import (
    ChangePasswordRequest,
    UserListItem,
    UserResponse,
    UserUpdateRequest,
)
from omichub.application.services import UserService
from omichub.application.services.agent_memory_service import AgentMemoryService
from omichub.core.config import get_settings
from omichub.core.exceptions import AuthorizationError
from omichub.infrastructure.database.models.audit_log import AuditLogModel
from omichub.infrastructure.database.models.chat import ChatSessionModel
from omichub.infrastructure.database.repositories import SqlAlchemyUserRepository
from omichub.infrastructure.task_queue.dispatcher import enqueue_task
from omichub.middleware.rbac import require_roles

router = APIRouter()


def get_user_service(db: DbSession) -> UserService:
    """获取用户服务实例"""
    return UserService(SqlAlchemyUserRepository(db))


@router.get("/me/memories", response_model=list[AgentMemoryDTO])
async def list_my_memories(
    current_user_id: CurrentUserId,
    db: DbSession,
    agent_id: str | None = Query(None, max_length=50),
    scope: str | None = Query(None, pattern="^(profile|project|preference|summary)$"),
    project_id: str | None = Query(None, max_length=64),
) -> list[AgentMemoryDTO]:
    """列出当前用户可管理的跨会话 Agent 记忆。"""
    memories = await AgentMemoryService(db).list_memories(
        current_user_id, agent_id=agent_id, scope=scope, project_id=project_id
    )
    return [AgentMemoryDTO(**AgentMemoryService._serialize(memory)) for memory in memories]


@router.get("/me/memory-overview", response_model=MemoryOverviewDTO)
async def get_my_memory_overview(
    current_user_id: CurrentUserId,
    db: DbSession,
    agent_id: str | None = Query(None, max_length=50),
    scope: str | None = Query(None, pattern="^(profile|project|preference|summary)$"),
    include_archived: bool = Query(False),
) -> MemoryOverviewDTO:
    overview = await AgentMemoryService(db).get_memory_overview(
        current_user_id,
        agent_id=agent_id,
        scope=scope,
        include_archived=include_archived,
    )
    return MemoryOverviewDTO(**overview)


@router.patch("/me/memory-blocks/{block_name}", response_model=MemoryBlockDTO)
async def update_my_memory_block(
    block_name: str,
    req: MemoryBlockUpdateRequest,
    current_user_id: CurrentUserId,
    db: DbSession,
    agent_id: str = Query(..., min_length=1, max_length=50),
) -> MemoryBlockDTO:
    block = await AgentMemoryService(db).update_memory_block(
        current_user_id,
        agent_id,
        block_name,
        req.content,
        req.expected_version,
    )
    return MemoryBlockDTO(**block)


@router.post("/me/memories/rebuild")
async def rebuild_my_memories(
    current_user_id: CurrentUserId,
    db: DbSession,
) -> dict[str, int | str]:
    """为历史上尚未触发沉淀的长会话补投记忆任务。"""
    settings = get_settings()
    if not settings.memory_v2_enabled:
        return {"status": "disabled", "queued": 0}

    minimum_messages = max(
        2,
        settings.memory_settle_min_new_messages,
    )
    sessions = list(
        (
            await db.scalars(
                select(ChatSessionModel).where(
                    ChatSessionModel.user_id == current_user_id,
                    ChatSessionModel.status != "deleted",
                    ChatSessionModel.message_count >= minimum_messages,
                )
            )
        ).all()
    )
    from omichub.infrastructure.celery_app.tasks.memory import settle_session_memory

    for session in sessions:
        enqueue_task(settle_session_memory, session.session_id, countdown=5)
    return {"status": "queued", "queued": len(sessions)}


@router.delete("/me/memories/{memory_id}", status_code=204)
async def delete_my_memory(
    memory_id: str,
    current_user_id: CurrentUserId,
    db: DbSession,
) -> None:
    """永久删除当前用户的一条记忆。"""
    await AgentMemoryService(db).delete_memory(current_user_id, memory_id)


@router.delete("/me/memories", response_model=AgentMemoryClearResponse)
async def clear_my_memories(
    current_user_id: CurrentUserId,
    db: DbSession,
    agent_id: str | None = Query(None, max_length=50),
) -> AgentMemoryClearResponse:
    """归档清空当前用户全部或指定 Agent 的记忆。"""
    cleared_count = await AgentMemoryService(db).clear_memories(
        current_user_id, agent_id=agent_id
    )
    return AgentMemoryClearResponse(cleared_count=cleared_count)


@router.get("/me/audit-logs")
async def get_my_audit_logs(
    current_user_id: CurrentUserId,
    db: DbSession,
    limit: int = Query(5, ge=1, le=50),
) -> list[dict[str, str]]:
    """返回当前用户最近的真实写操作审计记录。"""
    rows = await db.scalars(
        select(AuditLogModel)
        .where(AuditLogModel.user_id == uuid.UUID(current_user_id))
        .order_by(AuditLogModel.created_at.desc())
        .limit(limit)
    )

    def category(path: str) -> tuple[str, str]:
        if "/password" in path:
            return "password", "密码"
        if "/2fa" in path:
            return "security", "安全"
        if "delete" in path or path.endswith("/account"):
            return "delete", "删除"
        if "/users" in path:
            return "email", "资料"
        return "security", "操作"

    return [
        {
            "type": category(row.path)[0],
            "type_label": category(row.path)[1],
            "description": f"{row.method} {row.path}",
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.get(
    "/",
    dependencies=[Depends(require_roles("admin"))],
    response_model=list[UserListItem],
)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    q: str | None = Query(None, description="搜索关键词（用户名/邮箱）"),
    role: str | None = Query(None),
    status: str | None = Query(None),
    user_service: Annotated[UserService, Depends(get_user_service)] = None,
):
    """获取用户列表（仅管理员）"""
    users, _total = await user_service.get_user_list(page, page_size, q, role, status)
    return [UserListItem.model_validate(u) for u in users]


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    current_user_id: CurrentUserId,
    user_service: Annotated[UserService, Depends(get_user_service)] = None,
):
    """获取用户详情（普通用户只能查看自己，管理员可查看所有）"""
    # 普通用户只能查看自己
    if user_id != current_user_id:
        # 检查是否为管理员 - 通过 require_roles 依赖已校验
        # 此处简化处理：非自己的请求需要管理员权限
        # TODO: 完整 RBAC 检查需要查询用户角色
        raise AuthorizationError("无权查看其他用户信息")

    user = await user_service.get_user_by_id(user_id)
    return UserResponse.model_validate(user)


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    req: UserUpdateRequest,
    current_user_id: CurrentUserId,
    user_service: Annotated[UserService, Depends(get_user_service)] = None,
):
    """更新用户信息（普通用户只能更新自己）"""
    if user_id != current_user_id:
        raise AuthorizationError("无权修改其他用户信息")

    user = await user_service.update_user(user_id, req)
    return UserResponse.model_validate(user)


@router.delete("/{user_id}", dependencies=[Depends(require_roles("admin"))])
async def delete_user(
    user_id: str,
    user_service: Annotated[UserService, Depends(get_user_service)] = None,
):
    """删除用户（仅管理员）"""
    await user_service.delete_user(user_id)
    return {"message": "用户删除成功"}


@router.put("/{user_id}/password")
async def change_password(
    user_id: str,
    req: ChangePasswordRequest,
    current_user_id: CurrentUserId,
    user_service: Annotated[UserService, Depends(get_user_service)] = None,
):
    """修改密码（只能修改自己的密码）"""
    if user_id != current_user_id:
        raise AuthorizationError("无权修改其他用户密码")

    await user_service.change_password(user_id, req.old_password, req.new_password)
    return {"message": "密码修改成功"}
