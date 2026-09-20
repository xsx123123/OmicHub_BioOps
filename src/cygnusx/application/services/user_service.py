"""用户管理应用服务"""

import logging
import uuid

from sqlalchemy.exc import SQLAlchemyError

from cygnusx.application.schemas.user import UserUpdateRequest
from cygnusx.core.exceptions import AuthenticationError, ConflictError, NotFoundError
from cygnusx.core.security import hash_password, verify_password
from cygnusx.domain.user.entities import User
from cygnusx.domain.user.repositories import IUserRepository
from cygnusx.infrastructure.storage import get_path_factory

logger = logging.getLogger(__name__)


class UserService:
    """用户管理应用服务"""

    def __init__(self, user_repository: IUserRepository):
        self.user_repo = user_repository

    async def get_user_list(
        self,
        page: int = 1,
        page_size: int = 20,
        q: str | None = None,
        role: str | None = None,
        status: str | None = None,
    ) -> tuple[list[User], int]:
        """获取用户列表"""
        # 这里可以添加数据库查询逻辑，支持筛选和分页
        # 目前返回空列表和0计数
        return [], 0

    async def get_user_by_id(self, user_id: str) -> User:
        """根据ID获取用户"""
        user = await self.user_repo.get_by_id(uuid.UUID(user_id))
        if not user:
            raise NotFoundError("用户不存在")

        return user

    async def get_user_by_username(self, username: str) -> User:
        """根据用户名获取用户"""
        user = await self.user_repo.get_by_username(username)
        if not user:
            raise NotFoundError("用户不存在")

        return user

    async def update_user(self, user_id: str, req: UserUpdateRequest) -> User:
        """更新用户信息"""
        try:
            uid = uuid.UUID(user_id)
        except ValueError as exc:
            raise NotFoundError("用户 ID 格式不正确") from exc
        try:
            user = await self.user_repo.get_by_id(uid)
            if not user:
                raise NotFoundError("用户不存在")

            # 检查用户名变更
            if req.username and req.username != user.username:
                existing_user = await self.user_repo.get_by_username(req.username)
                if existing_user:
                    raise ConflictError(f"用户名 {req.username} 已存在")
                user.username = req.username

            # 检查邮箱变更
            if req.email and req.email != user.email:
                existing_email = await self.user_repo.get_by_email(req.email)
                if existing_email:
                    raise ConflictError(f"邮箱 {req.email} 已被注册")
                user.email = req.email

            # 更新其他字段
            if req.avatar_url is not None:
                user.avatar_url = req.avatar_url
            if req.nickname is not None:
                user.nickname = req.nickname
            if req.preferences is not None:
                user.preferences = req.preferences
            if req.status is not None:
                user.status = req.status

            return await self.user_repo.save(user)
        except SQLAlchemyError as exc:
            logger.exception(f"更新用户 {user_id} 数据库错误: {exc}")
            raise ConflictError("保存用户信息失败，请稍后重试") from exc

    async def delete_user(self, user_id: str) -> bool:
        """删除用户"""
        try:
            uid = uuid.UUID(user_id)
            deleted = await self.user_repo.delete(uid)
            if deleted:
                get_path_factory().remove_user_root(str(uid))
            return deleted
        except ValueError as exc:
            raise NotFoundError("用户 ID 格式不正确") from exc

    async def change_password(self, user_id: str, old_password: str, new_password: str) -> None:
        """修改密码 — 校验旧密码后设置新密码"""
        try:
            uid = uuid.UUID(user_id)
        except ValueError as exc:
            raise NotFoundError("用户 ID 格式不正确") from exc
        try:
            user = await self.user_repo.get_by_id(uid)
            if not user:
                raise NotFoundError("用户不存在")

            if not verify_password(old_password, user.hashed_password):
                raise AuthenticationError("当前密码不正确")

            if old_password == new_password:
                raise AuthenticationError("新密码不能与旧密码相同")

            user.hashed_password = hash_password(new_password)
            user.token_version += 1
            await self.user_repo.save(user)
        except SQLAlchemyError as exc:
            logger.exception(f"修改密码 {user_id} 数据库错误: {exc}")
            raise ConflictError("修改密码失败，请稍后重试") from exc
