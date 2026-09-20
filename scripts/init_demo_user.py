"""Demo 模式初始化演示账号

用法:
  python scripts/init_demo_user.py
  uv run python scripts/init_demo_user.py
  docker exec cygnusx-web python scripts/init_demo_user.py

环境变量:
  CYGNUSX_INIT_DEMO_USERNAME   演示用户名 (默认: demo)
  CYGNUSX_INIT_DEMO_EMAIL      演示邮箱 (默认: demo@example.com)
  CYGNUSX_INIT_DEMO_PASSWORD   演示密码 (默认: demo_cygnusx)

说明:
  - 仅供 demo 模式使用；生产环境请勿运行（账号密码公开在登录页）。
  - 脚本具有幂等性：如果目标用户名已存在，则跳过创建。
  - 演示账号为普通用户角色，状态直接置为 ACTIVE，无需管理员激活。
"""

import asyncio
import os
import sys


async def main() -> None:
    from cygnusx.core.config import get_settings
    from cygnusx.core.security import hash_password
    from cygnusx.domain.user.entities import User
    from cygnusx.domain.user.value_objects import Role, UserStatus
    from cygnusx.infrastructure.database.repositories.user_repository import (
        SqlAlchemyUserRepository,
    )
    from cygnusx.infrastructure.database.session import get_session_factory

    settings = get_settings()

    if settings.is_production:
        print("错误: 生产环境禁止创建公开密码的演示账号")
        sys.exit(1)

    username = os.getenv("CYGNUSX_INIT_DEMO_USERNAME", "demo").strip()
    email = os.getenv("CYGNUSX_INIT_DEMO_EMAIL", "demo@example.com").strip()
    password = os.getenv("CYGNUSX_INIT_DEMO_PASSWORD", "demo_cygnusx").strip()

    factory = get_session_factory()
    async with factory() as session:
        user_repo = SqlAlchemyUserRepository(session)

        # 幂等检查：按用户名
        existing = await user_repo.get_by_username(username)
        if existing is not None:
            print(f"演示用户 '{username}' 已存在，跳过创建")
            return

        # 额外检查邮箱冲突
        existing_email = await user_repo.get_by_email(email)
        if existing_email is not None:
            print(f"错误: 邮箱 '{email}' 已被其他用户注册")
            sys.exit(1)

        demo = User(
            username=username,
            email=email,
            hashed_password=hash_password(password),
            role=Role.USER,
            status=UserStatus.ACTIVE,
        )
        created = await user_repo.save(demo)

        # 如果启用饼干系统，自动创建饼干账户
        if settings.enable_cookie_system:
            from cygnusx.application.services.cookie_service import CookieService

            cookie_service = CookieService(session)
            await cookie_service.get_or_create_account(created.id)
            print(f"🥫 已为演示账号创建饼干账户 (初始余额: {settings.initial_cookie_balance})")

    print("✅ 演示账号创建成功")
    print(f"   用户名: {created.username}")
    print(f"   邮箱:   {created.email}")
    print(f"   角色:   {created.role.value}")
    print(f"   状态:   {created.status.value}")


if __name__ == "__main__":
    asyncio.run(main())
