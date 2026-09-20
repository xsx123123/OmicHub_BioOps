"""首次部署初始化管理员账号

用法:
  python scripts/init_admin.py
  uv run python scripts/init_admin.py
  docker exec cygnusx-web python scripts/init_admin.py

环境变量:
  OMICHBUB_INIT_ADMIN_USERNAME   管理员用户名 (默认: admin)
  OMICHBUB_INIT_ADMIN_EMAIL      管理员邮箱 (默认: admin@example.com)
  OMICHBUB_INIT_ADMIN_PASSWORD   管理员密码

安全说明:
  - 生产环境必须设置 OMICHBUB_INIT_ADMIN_PASSWORD，否则脚本会拒绝执行。
  - 开发环境未设置密码时，会使用弱默认密码并打印警告，请在首次登录后立即修改。
  - 脚本具有幂等性：如果目标用户名已存在，则跳过创建。
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

    username = os.getenv("OMICHBUB_INIT_ADMIN_USERNAME", "admin").strip()
    email = os.getenv("OMICHBUB_INIT_ADMIN_EMAIL", "admin@example.com").strip()
    password = os.getenv("OMICHBUB_INIT_ADMIN_PASSWORD", "").strip()

    if not username or not email:
        print("错误: 管理员用户名和邮箱不能为空")
        sys.exit(1)

    if not password:
        if settings.is_production:
            print("错误: 生产环境必须设置 OMICHBUB_INIT_ADMIN_PASSWORD 环境变量")
            sys.exit(1)
        password = "admin123"
        print("⚠️  警告: 未设置 OMICHBUB_INIT_ADMIN_PASSWORD，使用默认开发密码 'admin123'")
        print("    请在首次登录后立即修改密码。\n")

    factory = get_session_factory()
    async with factory() as session:
        user_repo = SqlAlchemyUserRepository(session)

        # 幂等检查：按用户名
        existing = await user_repo.get_by_username(username)
        if existing is not None:
            print(f"管理员用户 '{username}' 已存在，跳过创建")
            return

        # 额外检查邮箱冲突
        existing_email = await user_repo.get_by_email(email)
        if existing_email is not None:
            print(f"错误: 邮箱 '{email}' 已被其他用户注册")
            sys.exit(1)

        # 创建管理员账号
        admin = User(
            username=username,
            email=email,
            hashed_password=hash_password(password),
            role=Role.ADMIN,
            status=UserStatus.ACTIVE,
        )
        created = await user_repo.save(admin)

        # 如果启用饼干系统，自动创建饼干账户
        if settings.enable_cookie_system:
            from cygnusx.application.services.cookie_service import CookieService

            cookie_service = CookieService(session)
            await cookie_service.get_or_create_account(created.id)
            print(f"🥫 已为管理员创建饼干账户 (初始余额: {settings.initial_cookie_balance})")

    print("✅ 管理员账号创建成功")
    print(f"   用户名: {created.username}")
    print(f"   邮箱:   {created.email}")
    print(f"   角色:   {created.role.value}")
    print(f"   状态:   {created.status.value}")


if __name__ == "__main__":
    asyncio.run(main())
