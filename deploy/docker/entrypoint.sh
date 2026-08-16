#!/bin/sh
# OmicHub 容器启动入口
#
# 在启动主进程前，按需自动应用数据库迁移，保证 schema 与代码同步：
#   - 仅当 RUN_MIGRATIONS=1 时执行（只赋给 web 容器，避免多容器并发迁移竞争）；
#   - 先检测 Alembic 是否存在多分支 (Multiple Heads)，若有则自动合并；
#   - 最后执行 `alembic upgrade head`，幂等（已在 head 则 no-op）；
#   - 迁移后跑一次 schema 漂移对账（ORM metadata ↔ 实际库），
#     版本戳与实际 DDL 不一致（手工 DDL / create_all / 备份恢复）时 fail-fast；
#   - 迁移失败则容器不启动（fail-fast，避免带病运行）。
set -e

if [ "$RUN_MIGRATIONS" = "1" ]; then
  # ── 多分支检测 & 自愈 ──
  HEAD_COUNT=$(alembic heads 2>/dev/null | grep -c '(head)' || echo 0)
  if [ "$HEAD_COUNT" -gt 1 ]; then
    echo "[entrypoint] ⚠️  检测到 $HEAD_COUNT 个 Alembic heads，正在自动合并..."
    alembic merge heads -m "auto-merge parallel branches"
    echo "[entrypoint] ✅ 多分支合并完成。"
  fi

  echo "[entrypoint] Applying database migrations: alembic upgrade head"
  alembic upgrade head

  echo "[entrypoint] Checking schema drift (ORM metadata vs database)"
  python /app/scripts/check_schema_drift.py
fi

exec "$@"
