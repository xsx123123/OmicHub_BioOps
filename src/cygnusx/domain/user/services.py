"""用户域服务 - 跨实体业务逻辑"""

from cygnusx.domain.user.entities import User
from cygnusx.domain.user.repositories import IUserRepository
from cygnusx.domain.user.value_objects import Role, UserStatus


class UserDomainService:
    """用户域服务"""

    def __init__(self, repo: IUserRepository):
        self._repo = repo

    async def activate_user(self, user: User) -> User:
        """激活用户"""
        user.status = UserStatus.ACTIVE
        return await self._repo.save(user)

    async def set_role(self, user: User, role: Role) -> User:
        """设置用户角色"""
        user.role = role
        return await self._repo.save(user)
