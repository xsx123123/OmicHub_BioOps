"""用户仓储的 SQLAlchemy 实现"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.domain.user.entities import User
from omichub.domain.user.repositories import IUserRepository
from omichub.domain.user.value_objects import Role, UserStatus
from omichub.infrastructure.database.models.user import UserModel


class SqlAlchemyUserRepository(IUserRepository):
    """用户仓储的 SQLAlchemy 实现"""

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _to_domain(db_user: UserModel) -> User:
        """ORM 模型 → 领域实体"""
        return User(
            id=db_user.id,
            username=db_user.username,
            email=db_user.email,
            hashed_password=db_user.hashed_password,
            role=Role(db_user.role),
            status=UserStatus(db_user.status),
            workspace_id=db_user.workspace_id,
            avatar_url=db_user.avatar_url,
            nickname=db_user.nickname,
            preferences=db_user.preferences or {},
            last_login_at=db_user.last_login_at,
            storage_quota=db_user.storage_quota,
            used_storage=db_user.used_storage,
            admin_note=db_user.admin_note,
            lab_group=db_user.lab_group,
            totp_secret=db_user.totp_secret,
            is_2fa_enabled=db_user.is_2fa_enabled,
            disabled_modules=list(db_user.disabled_modules or []),
            token_version=db_user.token_version,
            created_at=db_user.created_at,
            updated_at=db_user.updated_at,
        )

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """根据 ID 获取用户"""
        stmt = select(UserModel).where(UserModel.id == user_id)
        result = await self.session.execute(stmt)
        db_user = result.scalar_one_or_none()
        return self._to_domain(db_user) if db_user else None

    async def get_by_username(self, username: str) -> User | None:
        """根据用户名获取用户"""
        stmt = select(UserModel).where(UserModel.username == username)
        result = await self.session.execute(stmt)
        db_user = result.scalar_one_or_none()
        return self._to_domain(db_user) if db_user else None

    async def get_by_email(self, email: str) -> User | None:
        """根据邮箱获取用户"""
        stmt = select(UserModel).where(UserModel.email == email)
        result = await self.session.execute(stmt)
        db_user = result.scalar_one_or_none()
        return self._to_domain(db_user) if db_user else None

    async def has_any_admin(self) -> bool:
        """检查是否已存在管理员账号"""
        stmt = select(UserModel).where(UserModel.role == Role.ADMIN.value).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def count_total(self) -> int:
        """全平台注册用户总数"""
        stmt = select(func.count(UserModel.id))
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def save(self, user: User) -> User:
        """保存用户（新建或更新）"""
        if user.id is not None:
            # 尝试更新已有用户
            stmt = select(UserModel).where(UserModel.id == user.id)
            result = await self.session.execute(stmt)
            db_user = result.scalar_one_or_none()
        else:
            db_user = None

        if db_user:
            # 更新现有用户
            db_user.username = user.username
            db_user.email = user.email
            db_user.hashed_password = user.hashed_password
            db_user.role = user.role.value if isinstance(user.role, Role) else user.role
            db_user.status = (
                user.status.value if isinstance(user.status, UserStatus) else user.status
            )
            db_user.workspace_id = user.workspace_id
            db_user.avatar_url = user.avatar_url
            db_user.nickname = user.nickname
            db_user.preferences = user.preferences
            db_user.last_login_at = user.last_login_at
            db_user.storage_quota = user.storage_quota
            db_user.used_storage = user.used_storage
            db_user.admin_note = user.admin_note
            db_user.lab_group = user.lab_group
            db_user.totp_secret = user.totp_secret
            db_user.is_2fa_enabled = user.is_2fa_enabled
            db_user.disabled_modules = list(user.disabled_modules)
            db_user.token_version = user.token_version
        else:
            # 创建新用户
            db_user = UserModel(
                id=user.id,
                username=user.username,
                email=user.email,
                hashed_password=user.hashed_password,
                role=user.role.value if isinstance(user.role, Role) else user.role,
                status=user.status.value if isinstance(user.status, UserStatus) else user.status,
                token_version=user.token_version,
                workspace_id=user.workspace_id,
                avatar_url=user.avatar_url,
                nickname=user.nickname,
                preferences=user.preferences,
                last_login_at=user.last_login_at,
                storage_quota=user.storage_quota,
                used_storage=user.used_storage,
                admin_note=user.admin_note,
                lab_group=user.lab_group,
                totp_secret=user.totp_secret,
                is_2fa_enabled=user.is_2fa_enabled,
                disabled_modules=list(user.disabled_modules),
            )
            self.session.add(db_user)

        await self.session.commit()
        await self.session.refresh(db_user)
        return self._to_domain(db_user)

    async def add_used_storage(self, user_id: uuid.UUID, delta: int) -> int:
        """原子累加用户已用空间（并发安全，防双计/漏计）。

        delta 为正表示增加（上传完成），为负表示扣减（删除文件）。
        返回累加后的 used_storage 值。
        """
        from sqlalchemy import update

        stmt = (
            update(UserModel)
            .where(UserModel.id == user_id)
            .values(used_storage=UserModel.used_storage + delta)
            .returning(UserModel.used_storage)
        )
        result = await self.session.execute(stmt)
        new_value = int(result.scalar_one())
        await self.session.commit()
        return new_value

    async def recompute_used_storage(self, user_id: uuid.UUID) -> int:
        """按 file_records(active) 重算 used_storage，修正配额漂移。

        下载登记/同步后调用，亦可作配额自愈。返回重算后的值。
        """
        from sqlalchemy import func, update

        from omichub.infrastructure.database.models.file import FileRecordModel

        sum_stmt = (
            select(func.coalesce(func.sum(FileRecordModel.size), 0))
            .where(
                FileRecordModel.user_id == user_id,
                FileRecordModel.status == "active",
            )
            .scalar_subquery()
        )
        stmt = (
            update(UserModel)
            .where(UserModel.id == user_id)
            .values(used_storage=sum_stmt)
            .returning(UserModel.used_storage)
        )
        result = await self.session.execute(stmt)
        new_value = int(result.scalar_one())
        await self.session.commit()
        return new_value

    async def delete(self, user_id: uuid.UUID) -> bool:
        """删除用户"""
        stmt = select(UserModel).where(UserModel.id == user_id)
        result = await self.session.execute(stmt)
        db_user = result.scalar_one_or_none()

        if db_user:
            await self.session.delete(db_user)
            await self.session.commit()
            return True
        return False
