"""用户管理 — 管理端路由 (审批/列表)"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import desc, func, select

from cygnusx.api.deps import AdminTotpRequired, CurrentUserId, DbSession
from cygnusx.application.schemas.agent_memory import AgentMemoryDTO, MemoryOverviewDTO
from cygnusx.application.schemas.auth import UserRegisterRequest
from cygnusx.application.schemas.user import UserModulesUpdateRequest
from cygnusx.application.services.agent_memory_service import AgentMemoryService
from cygnusx.core.exceptions import AuthorizationError, BusinessError, ConflictError, NotFoundError
from cygnusx.core.security import hash_password
from cygnusx.domain.user.entities import User
from cygnusx.domain.user.value_objects import Role, UserStatus
from cygnusx.middleware.rbac import (
    AdminRequired as AdminRequired,  # 统一 RBAC 实现，re-export 供下游导入
)

router = APIRouter()


@router.get("", summary="所有用户列表")
async def list_users(
    _admin: AdminRequired,
    db: DbSession,
    status: Annotated[str | None, Query()] = None,
    offset: int = 0,
    limit: int = 100,
):
    from cygnusx.infrastructure.database.models.cookie import CookieAccountModel
    from cygnusx.infrastructure.database.models.user import UserModel

    query = select(
        UserModel.id,
        UserModel.username,
        UserModel.nickname,
        UserModel.email,
        UserModel.role,
        UserModel.status,
        UserModel.created_at,
        UserModel.last_login_at,
        UserModel.storage_quota,
        UserModel.used_storage,
        UserModel.admin_note,
        UserModel.lab_group,
        UserModel.disabled_modules,
        CookieAccountModel.balance.label("cookie_balance"),
        CookieAccountModel.status.label("cookie_status"),
    ).outerjoin(CookieAccountModel, CookieAccountModel.user_id == UserModel.id)
    if status:
        query = query.where(UserModel.status == status)
    query = query.order_by(desc(UserModel.created_at)).offset(offset).limit(limit)
    result = await db.execute(query)
    return [
        {
            "id": str(row.id),
            "username": row.username,
            "nickname": row.nickname,
            "email": row.email,
            "role": row.role,
            "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "last_login_at": row.last_login_at.isoformat() if row.last_login_at else None,
            "storage_quota": row.storage_quota,
            "used_storage": row.used_storage,
            "admin_note": row.admin_note or "",
            "lab_group": row.lab_group or "",
            "disabled_modules": row.disabled_modules or [],
            # 资产穿透：饼干余额与账户状态（无账户视为未发放，余额 0）
            "cookie_balance": float(row.cookie_balance) if row.cookie_balance is not None else 0.0,
            "cookie_status": row.cookie_status or None,
        }
        for row in result.all()
    ]


@router.get("/{user_id}/memories", response_model=list[AgentMemoryDTO], summary="查看用户 Agent 记忆")
async def list_user_memories(
    user_id: UUID,
    _admin: AdminRequired,
    db: DbSession,
    agent_id: str | None = Query(None, max_length=50),
    scope: str | None = Query(None, pattern="^(profile|project|preference|summary)$"),
) -> list[AgentMemoryDTO]:
    """管理员只读查看用户长期记忆，含归档记录以支持审计。"""
    memories = await AgentMemoryService(db).list_memories(
        str(user_id),
        agent_id=agent_id,
        scope=scope,
        include_archived=True,
    )
    return [AgentMemoryDTO(**AgentMemoryService._serialize(memory)) for memory in memories]


@router.get("/{user_id}/memory-overview", response_model=MemoryOverviewDTO, summary="查看用户 v2 Agent 记忆")
async def get_user_memory_overview(
    user_id: UUID,
    _admin: AdminRequired,
    db: DbSession,
    agent_id: str | None = Query(None, max_length=50),
    scope: str | None = Query(None, pattern="^(profile|project|preference|summary)$"),
    include_archived: bool = Query(True),
) -> MemoryOverviewDTO:
    from cygnusx.infrastructure.database.models.user import UserModel

    if await db.get(UserModel, user_id) is None:
        raise NotFoundError("用户不存在")
    overview = await AgentMemoryService(db).get_memory_overview(
        str(user_id),
        agent_id=agent_id,
        scope=scope,
        include_archived=include_archived,
    )
    return MemoryOverviewDTO(**overview)


@router.post("", summary="管理员添加用户")
async def create_user(
    req: UserRegisterRequest,
    current_user_id: CurrentUserId,
    _admin: AdminRequired,
    db: DbSession,
):
    """管理员直接添加用户（无需自助注册审批）。

    - 复用 UserRegisterRequest 的字段与密码强度校验；
    - 创建即为 active 状态，可直接登录；
    - 可选角色 user/admin（默认 user）。
    """
    from cygnusx.infrastructure.database.models.user import UserModel

    # 用户名/邮箱唯一性校验
    if await db.scalar(select(UserModel).where(UserModel.username == req.username)):
        raise ConflictError(f"用户名 {req.username} 已存在")
    if await db.scalar(select(UserModel).where(UserModel.email == req.email)):
        raise ConflictError(f"邮箱 {req.email} 已被注册")

    # 注册表 default_locked: true 的模块，新用户默认锁定
    from cygnusx.infrastructure.config.module_registry import get_module_registry

    user = User(
        username=req.username,
        email=req.email,
        hashed_password=hash_password(req.password),
        role=Role.USER,
        status=UserStatus.ACTIVE,
        lab_group=req.lab_group,
        disabled_modules=get_module_registry().default_locked_keys(),
    )
    # 领域实体落库
    from cygnusx.infrastructure.database.repositories import SqlAlchemyUserRepository

    saved = await SqlAlchemyUserRepository(db).save(user)

    # 集成点：启用饼干系统时自动创建饼干账户
    from cygnusx.core.config import get_settings

    if get_settings().enable_cookie_system:
        from cygnusx.application.services.cookie_service import CookieService

        await CookieService(db).get_or_create_account(saved.id)

    # 初始化用户默认目录（raw_data/workspace/temp），使新用户进数据管理页即见
    from cygnusx.application.services.file_service import FileService

    await FileService(db).ensure_default_directories(saved.id)

    return {
        "id": str(saved.id),
        "username": saved.username,
        "email": saved.email,
        "role": saved.role.value,
        "status": saved.status.value,
        "created_at": saved.created_at.isoformat() if saved.created_at else None,
    }


@router.put("/{user_id}/approve", summary="审批通过用户")
async def approve_user(
    user_id: UUID,
    _admin: AdminRequired,
    db: DbSession,
):
    from cygnusx.infrastructure.database.models.user import UserModel

    user = await db.get(UserModel, user_id)
    if user is None:
        raise NotFoundError("用户不存在")
    # 审批通过：允许 pending（首次审批）与 rejected（重新捞回误拒用户）→ active。
    # active/inactive 已是正常在用账号，不再走审批路径。
    if user.status not in ("pending", "rejected"):
        return {"message": f"用户当前状态为 {user.status}，无需审批"}
    user.status = "active"
    user.token_version += 1
    await db.flush()

    # 账号初始化钩子：审批通过时自动创建饼干钱包并发放新人初始额度。
    # get_or_create_account 幂等——重复审批不会重复发放。
    from cygnusx.core.config import get_settings

    if get_settings().enable_cookie_system:
        from cygnusx.application.services.cookie_service import CookieService

        await CookieService(db).get_or_create_account(user.id)
        await db.flush()

    # 初始化用户默认目录（raw_data/workspace/temp），使新用户进数据管理页即见
    from cygnusx.application.services.file_service import FileService

    await FileService(db).ensure_default_directories(user.id)

    return {"id": str(user.id), "username": user.username, "status": user.status}


@router.put("/{user_id}/reject", summary="拒绝用户注册")
async def reject_user(
    user_id: UUID,
    _admin: AdminRequired,
    db: DbSession,
    reason: str = "",
):
    from cygnusx.infrastructure.database.models.user import UserModel

    user = await db.get(UserModel, user_id)
    if user is None:
        raise NotFoundError("用户不存在")
    user.status = "rejected"
    user.token_version += 1
    await db.flush()
    return {"id": str(user.id), "username": user.username, "status": "rejected", "reason": reason}


@router.put("/{user_id}/role", summary="修改用户角色")
async def update_user_role(
    user_id: UUID,
    _admin: AdminRequired,
    db: DbSession,
    role: str = "user",
):
    from cygnusx.infrastructure.database.models.user import UserModel

    if role not in ("admin", "user"):
        raise AuthorizationError("角色只能是 admin 或 user")
    user = await db.get(UserModel, user_id)
    if user is None:
        raise NotFoundError("用户不存在")
    user.role = role
    user.token_version += 1
    await db.flush()
    return {"id": str(user.id), "username": user.username, "role": user.role}


@router.put("/{user_id}/quota", summary="调整用户存储配额")
async def update_user_quota(
    user_id: UUID,
    _admin: AdminRequired,
    db: DbSession,
    storage_quota_gb: float = 500.0,
):
    """动态调整用户存储配额（应对 WGS 等超大数据项目临时扩容）。

    - storage_quota_gb 单位 GiB，需 > 0，上限 5 TiB（5120 GiB）；
    - 不可低于当前已用空间（避免负配额）。
    """
    from cygnusx.infrastructure.database.models.user import UserModel

    if storage_quota_gb <= 0:
        raise AuthorizationError("配额必须大于 0")
    if storage_quota_gb > 5120:
        raise AuthorizationError("单用户配额上限 5 TiB")

    user = await db.get(UserModel, user_id)
    if user is None:
        raise NotFoundError("用户不存在")

    new_quota = int(storage_quota_gb * 1024 * 1024 * 1024)
    if new_quota < user.used_storage:
        raise AuthorizationError(
            f"新配额 {storage_quota_gb} GiB 低于该用户已用空间"
            f"（{user.used_storage / 1024 / 1024 / 1024:.2f} GiB）"
        )

    user.storage_quota = new_quota
    await db.flush()
    return {
        "id": str(user.id),
        "username": user.username,
        "storage_quota": user.storage_quota,
        "used_storage": user.used_storage,
    }


@router.put("/{user_id}/note", summary="编辑管理员备注")
async def update_user_note(
    user_id: UUID,
    _admin: AdminRequired,
    db: DbSession,
    note: str = "",
):
    """编辑用户的管理员备注（如"客户要求延期""测试账号"等辅助信息）。

    - 备注仅管理员可见，不对外暴露给用户；
    - 空字符串视为清除备注；
    - 长度上限 1000 字符。
    """
    from cygnusx.infrastructure.database.models.user import UserModel

    note = (note or "").strip()
    if len(note) > 1000:
        raise AuthorizationError("备注长度不能超过 1000 字符")

    user = await db.get(UserModel, user_id)
    if user is None:
        raise NotFoundError("用户不存在")

    user.admin_note = note or None
    await db.flush()
    return {
        "id": str(user.id),
        "username": user.username,
        "admin_note": user.admin_note or "",
    }


@router.put("/{user_id}/modules", summary="配置用户模块权限")
async def update_user_modules(
    user_id: UUID,
    req: UserModulesUpdateRequest,
    _admin: AdminRequired,
    db: DbSession,
):
    """按用户配置被禁用的模块列表（勾选矩阵保存入口）。

    安全护栏：
    - 目标用户是管理员时拒绝修改（管理员默认拥有全部模块权限，防自锁）；
    - disabled_modules 中的 key 必须是注册表中 lockable=true 的模块，否则 400；
    - 不做 token_version 变更（权限变更用户侧下次拉取用户信息即生效）。
    """
    from cygnusx.infrastructure.config.module_registry import get_module_registry
    from cygnusx.infrastructure.database.models.user import UserModel

    user = await db.get(UserModel, user_id)
    if user is None:
        raise NotFoundError("用户不存在")

    # 管理员默认拥有全部模块权限，接口层强制不可取消（防自锁）
    if user.role == "admin":
        raise AuthorizationError("管理员默认拥有全部模块权限，不可取消")

    lockable_keys = get_module_registry().lockable_keys()
    invalid_keys = [key for key in req.disabled_modules if key not in lockable_keys]
    if invalid_keys:
        raise BusinessError(f"无效的模块 key（不存在或不可锁定）: {', '.join(invalid_keys)}")

    # 去重并保持请求顺序
    user.disabled_modules = list(dict.fromkeys(req.disabled_modules))
    await db.flush()
    return {"id": str(user.id), "disabled_modules": user.disabled_modules}


@router.put("/{user_id}/status", summary="启用/禁用账号")
async def update_user_status(
    user_id: UUID,
    current_user_id: CurrentUserId,
    _admin: AdminRequired,
    db: DbSession,
    status: str = "active",
):
    """切换账号状态（active 启用 / inactive 禁用）。

    安全护栏：
    - 禁止禁用当前登录账号自己；
    - 禁止禁用最后一个管理员（避免平台失去管理入口）。
    禁用后用户登录会被拒（login 校验 status != active）。
    """
    from cygnusx.infrastructure.database.models.user import UserModel

    if status not in ("active", "inactive"):
        raise AuthorizationError("状态只能是 active 或 inactive")

    # 不能禁用自己
    if status == "inactive" and str(user_id) == current_user_id:
        raise AuthorizationError("不能禁用当前登录的管理员账号")

    user = await db.get(UserModel, user_id)
    if user is None:
        raise NotFoundError("用户不存在")

    # 禁用管理员时，确保仍至少保留一个可用管理员
    if status == "inactive" and user.role == "admin":
        active_admin_count = await db.scalar(
            select(func.count(UserModel.id)).where(
                UserModel.role == "admin", UserModel.status == "active"
            )
        )
        if active_admin_count is not None and active_admin_count <= 1:
            raise AuthorizationError("系统至少需要保留一个可用管理员账号，无法禁用")

    user.status = status
    user.token_version += 1
    await db.flush()
    return {"id": str(user.id), "username": user.username, "status": user.status}


@router.delete("/{user_id}", summary="删除用户")
async def delete_user(
    user_id: UUID,
    current_user_id: CurrentUserId,
    _admin: AdminRequired,
    _totp: AdminTotpRequired,  # 敏感操作：强制 X-TOTP-Code 二次校验
    db: DbSession,
):
    """彻底删除用户（不可恢复）。

    安全护栏：
    - 禁止删除当前登录账号自己；
    - 禁止删除最后一个管理员（避免平台失去管理入口）。
    前端已做二次确认（逐字输入确认文案），此处为后端兜底。

    关联数据清理：CASCADE 的表（ai_conversations / cookie_accounts /
    sandbox_sessions）由数据库自动级联删除；NO ACTION 的表在此显式处理：
    - 交易流水/消费日志/账本（user_id NOT NULL）：删除该用户记录；
    - 交易流水的 admin_id、饼干定价 created_by/updated_by（可空）：置 NULL 保留审计；
    - 通知：删除该用户创建的及定向发给该用户的通知。
    """
    from cygnusx.infrastructure.database.models.agent_memory import AgentMemoryModel
    from cygnusx.infrastructure.database.models.cookie import (
        ConsumptionLogModel,
        CookiePricingModel,
        CookieTransactionModel,
        LedgerEntryModel,
    )
    from cygnusx.infrastructure.database.models.notification import NotificationModel
    from cygnusx.infrastructure.database.models.user import UserModel

    # 不能删除自己
    if str(user_id) == current_user_id:
        raise AuthorizationError("不能删除当前登录的管理员账号")

    user = await db.get(UserModel, user_id)
    if user is None:
        raise NotFoundError("用户不存在")

    # 删除的是管理员时，确保仍至少保留一个管理员
    if user.role == "admin":
        admin_count = await db.scalar(
            select(func.count(UserModel.id)).where(UserModel.role == "admin")
        )
        if admin_count is not None and admin_count <= 1:
            raise AuthorizationError("系统至少需要保留一个管理员账号，无法删除")

    username = user.username

    # 1) 可空外键置 NULL（保留审计流水，仅断开用户关联）
    await db.execute(
        CookieTransactionModel.__table__.update()
        .where(CookieTransactionModel.admin_id == user_id)
        .values(admin_id=None)
    )
    await db.execute(
        CookiePricingModel.__table__.update()
        .where(CookiePricingModel.created_by == user_id)
        .values(created_by=None)
    )
    await db.execute(
        CookiePricingModel.__table__.update()
        .where(CookiePricingModel.updated_by == user_id)
        .values(updated_by=None)
    )

    # 2) NOT NULL 外键的关联记录：删除该用户的数据
    await db.execute(
        CookieTransactionModel.__table__.delete().where(CookieTransactionModel.user_id == user_id)
    )
    await db.execute(
        ConsumptionLogModel.__table__.delete().where(ConsumptionLogModel.user_id == user_id)
    )
    await db.execute(LedgerEntryModel.__table__.delete().where(LedgerEntryModel.user_id == user_id))

    # 3) 通知：删除该用户创建的 + 定向发给该用户的
    await db.execute(
        NotificationModel.__table__.delete().where(
            (NotificationModel.created_by == user_id)
            | (NotificationModel.target_user_id == user_id)
        )
    )
    await db.execute(AgentMemoryModel.__table__.delete().where(AgentMemoryModel.user_id == str(user_id)))
    # 4) 最后删除用户本体（CASCADE 表由数据库自动清理）
    await db.delete(user)
    await db.commit()
    from cygnusx.infrastructure.storage import get_path_factory

    get_path_factory().remove_user_root(str(user_id))
    return {"id": str(user_id), "username": username, "deleted": True}
