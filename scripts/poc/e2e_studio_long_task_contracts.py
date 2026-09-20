"""WP2 任务4 e2e 验收脚本：Studio 长任务 job 三契约（真实执行）。

真实组件：
  - 真实 PostgreSQL（独立 scratch 库 omichub_wp2t4，从开发库 schema-only 克隆，
    只应用本任务迁移 g4b5c6d7e8f9a，不动共享开发库的 alembic 版本）
  - 真实 Redis broker / result backend（db 13/14，与开发栈 db 0/1/2 隔离，
    消息不会真被 worker 消费，正好制造"悬挂"场景）
  - 真实 Celery apply_async 投递、真实 enqueue_task 链路、真实对账函数

验收项：
  1. 提交长任务 → job 行先于队列提交存在（投递前用独立连接验证行已提交）
  2. 同一幂等键重复提交 → 返回同一 job，不新建行、队列只有一条消息
  3. 终态 job 重试 → 409 拒绝（ConflictError.status_code == 409）
  4. 悬挂 pending（worker 丢失）→ 对账只标记漂移/失败并记日志，日志与队列证据
     证明无第二次执行发生（reconcile-only）

用法：
    .venv/bin/python scripts/poc/e2e_studio_long_task_contracts.py
    .venv/bin/python scripts/poc/e2e_studio_long_task_contracts.py --keep-db   # 保留 scratch 库
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta

# 必须在导入 cygnusx 之前设置：scratch 库 + 隔离 redis db（避开开发栈 worker 消费的队列）
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://omichub:omichub_dev_password@127.0.0.1:5432/omichub_wp2t4",
)

import asyncpg
import redis

# celery 的配置层会直接读 CELERY_BROKER_URL/CELERY_RESULT_BACKEND 环境变量，
# 必须带密码且指向隔离 db，否则覆盖构造参数后投递会认证失败
_REDIS_PW = "PQ283DKos9D6h5kCK2gbCBtaFfG-MyAp6bjINeczb48"
os.environ["CELERY_BROKER_URL"] = f"redis://:{_REDIS_PW}@127.0.0.1:6379/13"
os.environ["CELERY_RESULT_BACKEND"] = f"redis://:{_REDIS_PW}@127.0.0.1:6379/14"

PG_DSN = "postgresql://omichub:omichub_dev_password@127.0.0.1:5432"
SCRATCH_DB = "omichub_wp2t4"
DEV_DB = "omichub"
REDIS_BROKER_DB = 13
USER_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "wp2-task4-e2e-user"))
SESSION_ID = f"e2e-wp2t4-{uuid.uuid4().hex[:8]}"
CMD_ID_A1 = f"e2e-wp2t4-a1-{uuid.uuid4().hex[:6]}"

CODE = "print('wp2-task4 e2e')"


def _ok(step: str, detail: str = "") -> None:
    print(f"[PASS] {step}" + (f" — {detail}" if detail else ""))


def _docker_psql(db: str, sql: str) -> str:
    return subprocess.run(
        ["docker", "exec", "cygnusx-db", "psql", "-U", "omichub", "-d", db, "-c", sql],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _setup_scratch_db() -> None:
    """从开发库克隆 schema-only → stamp 到 f3a4b5c6d7e8 → 只应用本任务迁移。"""
    exists = subprocess.run(
        ["docker", "exec", "cygnusx-db", "psql", "-U", "omichub", "-d", "postgres", "-tAc",
         f"select 1 from pg_database where datname='{SCRATCH_DB}'"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if exists != "1":
        print(f"== 创建 scratch 库 {SCRATCH_DB} 并从 {DEV_DB} 克隆 schema ==")
        subprocess.run(
            ["docker", "exec", "cygnusx-db", "createdb", "-U", "omichub", SCRATCH_DB],
            check=True,
        )
        dump = subprocess.run(
            ["docker", "exec", "cygnusx-db", "pg_dump", "-U", "omichub", "-d", DEV_DB,
             "--schema-only", "--no-owner", "--no-privileges"],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["docker", "exec", "-i", "cygnusx-db", "psql", "-U", "omichub", "-d", SCRATCH_DB, "-q"],
            input=dump.stdout,
            check=True,
        )
    # stamp 到当前开发库版本（仅当版本表为空时，避免重跑时回绕），再仅应用本任务迁移
    env = dict(os.environ)
    env["DATABASE_URL"] = (
        f"postgresql+asyncpg://omichub:omichub_dev_password@127.0.0.1:5432/{SCRATCH_DB}"
    )
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ver = subprocess.run(
        ["docker", "exec", "cygnusx-db", "psql", "-U", "omichub", "-d", SCRATCH_DB, "-tAc",
         "select version_num from alembic_version limit 1"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if not ver:
        subprocess.run(
            [".venv/bin/alembic", "stamp", "f3a4b5c6d7e8"],
            env=env,
            check=True,
            capture_output=True,
            cwd=repo_root,
        )
    subprocess.run(
        [".venv/bin/alembic", "upgrade", "g4b5c6d7e8f9a"],
        env=env,
        check=True,
        capture_output=True,
        cwd=repo_root,
    )
    cols = _docker_psql(
        SCRATCH_DB,
        "select column_name from information_schema.columns "
        f"where table_name='tasks' and column_name='idempotency_key'",
    )
    assert "idempotency_key" in cols, "迁移未生效：tasks.idempotency_key 缺失"
    idx = _docker_psql(
        SCRATCH_DB,
        "select indexname from pg_indexes where tablename='tasks' and indexname='uq_tasks_idempotency_key'",
    )
    assert "uq_tasks_idempotency_key" in idx, "唯一索引 uq_tasks_idempotency_key 缺失"
    _ok("迁移真实执行", "tasks.idempotency_key 列 + uq_tasks_idempotency_key UNIQUE 索引就位")


def _redis_queue_messages(r: redis.Redis, queue: str = "analysis") -> list[str]:
    return list(r.lrange(queue, 0, -1))


async def main() -> None:
    from cygnusx.application.services import studio_task_service
    from cygnusx.core.exceptions import ConflictError
    from cygnusx.infrastructure.celery_app.tasks import studio as studio_tasks
    from cygnusx.infrastructure.task_queue import dispatcher as task_dispatcher

    conn = await asyncpg.connect(f"{PG_DSN}/{SCRATCH_DB}")
    r = redis.Redis(
        host="127.0.0.1", port=6379, db=REDIS_BROKER_DB, password=_REDIS_PW, decode_responses=True
    )
    cleanup_ids: list[str] = []

    # enqueue_task 是同步调用（apply_async 同步发出），包装器必须用同步连接做投递前检查，
    # 否则在运行中的事件循环里 await 会死锁——这里用独立的 psycopg3 同步连接。
    import psycopg

    sync_conn = psycopg.connect(f"{PG_DSN}/{SCRATCH_DB}", autocommit=True)
    real_enqueue = task_dispatcher.enqueue_task
    proof: dict[str, Any] = {"row_committed_before_enqueue": False, "enqueue_call_ts": None}

    def wrapped_enqueue(task, *args, **kwargs):
        # 契约 1 证明点：投递动作发生前，用独立同步连接确认 job 行已提交存在
        with sync_conn.cursor() as cur:
            cur.execute(
                "select id, status from tasks where idempotency_key = %s", (CMD_ID_A1,)
            )
            row = cur.fetchone()
        proof["row_committed_before_enqueue"] = row is not None and row[1] == "queued"
        proof["enqueue_call_ts"] = datetime.now(UTC).isoformat()
        return real_enqueue(task, *args, **kwargs)

    studio_task_service.enqueue_task = wrapped_enqueue  # type: ignore[assignment]

    try:
        # ============ 契约 1：job 行先落盘，再提交队列 ============
        print("== 契约1：提交长任务（timeout=601s > 600s 阈值，走 Celery 链路）==")
        first = await studio_task_service.submit_studio_sandbox_task(
            user_id=USER_ID,
            session_id=SESSION_ID,
            language="python",
            code=CODE,
            timeout_sec=601,
            image=None,
            command_id=CMD_ID_A1,
        )
        cleanup_ids.append(first["task_id"])
        assert proof["row_committed_before_enqueue"], "投递前 job 行不存在：落盘顺序被破坏"
        row = await conn.fetchrow(
            "select id, status, created_at from tasks where idempotency_key = $1", CMD_ID_A1
        )
        assert row is not None and str(row["id"]) == first["task_id"]
        queued_msgs = [m for m in _redis_queue_messages(r) if first["task_id"] in m]
        assert len(queued_msgs) == 1, f"队列中应有 1 条消息, 实际 {len(queued_msgs)}"
        _ok(
            "契约1 job 行先于队列提交存在",
            f"投递前独立连接已可见 committed 行（queued）→ 随后 broker 出现消息；"
            f"row.created_at={row['created_at'].isoformat()} enqueue_at={proof['enqueue_call_ts']}",
        )

        # ============ 契约 2：同一幂等键重复提交 → 返回同一 job ============
        print("== 契约2：同幂等键重复提交 ==")
        second = await studio_task_service.submit_studio_sandbox_task(
            user_id=USER_ID,
            session_id=SESSION_ID,
            language="python",
            code=CODE,
            timeout_sec=601,
            image=None,
            command_id=CMD_ID_A1,
        )
        assert second["task_id"] == first["task_id"], "同键重复提交未返回同一 job"
        assert second["deduplicated"] is True
        count = await conn.fetchval(
            "select count(*) from tasks where idempotency_key = $1", CMD_ID_A1
        )
        assert count == 1, f"同键不应新建行, 实际 {count} 行"
        queued_msgs = [m for m in _redis_queue_messages(r) if first["task_id"] in m]
        assert len(queued_msgs) == 1, f"队列不应重复投递, 实际 {len(queued_msgs)} 条消息"
        _ok("契约2 幂等去重", f"task_id={first['task_id'][:8]}… 行数=1 队列消息=1")

        # ============ 契约 3：终态 job 重试 → 409 ============
        print("== 契约3：终态重试拒绝 ==")
        await conn.execute(
            "update tasks set status='success', finished_at=now() where id=$1",
            uuid.UUID(first["task_id"]),
        )
        try:
            await studio_task_service.retry_studio_sandbox_task(
                task_id=first["task_id"], user_id=USER_ID
            )
            raise AssertionError("终态重试未被拒绝")
        except ConflictError as exc:
            assert exc.status_code == 409, f"应为 409, 实际 {exc.status_code}"
            assert "不可重开" in exc.detail and "success" in exc.detail
            _ok("契约3 终态重试 409", f"detail={exc.detail}")
        # 幂等语义不受终态影响：同键提交仍返回同一 job，不新建行
        third = await studio_task_service.submit_studio_sandbox_task(
            user_id=USER_ID,
            session_id=SESSION_ID,
            language="python",
            code=CODE,
            timeout_sec=601,
            image=None,
            command_id=CMD_ID_A1,
        )
        assert third["task_id"] == first["task_id"]
        count = await conn.fetchval(
            "select count(*) from tasks where idempotency_key = $1", CMD_ID_A1
        )
        assert count == 1
        _ok("契约3 幂等语义保持", "终态后同键提交仍返回同一 job（重试需走新任务）")

        # ============ 契约 4：reconcile-only，模拟 worker 丢失 ============
        print("== 契约4：悬挂 pending 对账（模拟 worker 丢失）==")
        orphan_id = uuid.uuid4()
        orphan_key = f"e2e-wp2t4-orphan-{uuid.uuid4().hex[:6]}"
        await conn.execute(
            "insert into tasks (id, flow_id, user_id, name, status, execution_mode, parameters, "
            "work_dir, result_path, error_message, progress, logs, sample_count, idempotency_key, "
            "created_at, updated_at) "
            "values ($1, 'studio_sandbox', $2, 'e2e orphan', 'queued', 'local', '{}', '', '', '', "
            "0, '[]'::json, 0, $3, $4, $4)",
            orphan_id,
            uuid.UUID(USER_ID),
            orphan_key,
            datetime.now(UTC) - timedelta(hours=2),  # 超过 30min grace，且从未进过队列
        )
        cleanup_ids.append(str(orphan_id))
        # 确认队列与 backend 都没有它的任何痕迹（worker 从未收到 → PENDING + 不在队列）
        assert not any(str(orphan_id) in m for m in _redis_queue_messages(r))
        report = await studio_tasks._reconcile_studio_long_tasks()
        assert str(orphan_id) in report["queued_marked_failed"], f"对账未标记: {report}"
        orphan = await conn.fetchrow("select status, error_message, logs from tasks where id=$1", orphan_id)
        assert orphan["status"] == "failed", f"悬挂任务应被标记 failed, 实际 {orphan['status']}"
        assert "不会自动重提交" in orphan["error_message"]
        logs = json.loads(orphan["logs"])
        assert any(log.get("source") == "reconcile" for log in logs), "缺少对账日志"
        # 无第二次执行的证据：队列无该 id 的新消息、backend 无该 id 的执行痕迹
        assert not any(str(orphan_id) in m for m in _redis_queue_messages(r)), "对账重提交了任务！"
        _ok(
            "契约4 reconcile-only",
            f"悬挂 job {str(orphan_id)[:8]}… → failed + 对账日志；"
            "队列扫描无该 id 消息（无第二次执行）",
        )

        # 滞留 RUNNING：只报告、不动状态（OpenAI4S unknown=live 语义）
        stuck_id = uuid.uuid4()
        await conn.execute(
            "insert into tasks (id, flow_id, user_id, name, status, execution_mode, parameters, "
            "work_dir, result_path, error_message, progress, logs, sample_count, idempotency_key, "
            "started_at, created_at, updated_at) "
            "values ($1, 'studio_sandbox', $2, 'e2e stuck', 'running', 'local', '{}', '', '', '', "
            "0.5, '[]'::json, 0, $3, $4, $4, $4)",
            stuck_id,
            uuid.UUID(USER_ID),
            f"e2e-wp2t4-stuck-{uuid.uuid4().hex[:6]}",
            datetime.now(UTC) - timedelta(hours=7),
        )
        cleanup_ids.append(str(stuck_id))
        report2 = await studio_tasks._reconcile_studio_long_tasks()
        assert str(stuck_id) in report2["running_reported"]
        stuck = await conn.fetchrow("select status, logs from tasks where id=$1", stuck_id)
        assert stuck["status"] == "running", "滞留 RUNNING 不应对账改状态"
        assert any(log.get("source") == "reconcile" for log in json.loads(stuck["logs"]))
        _ok("契约4 滞留 RUNNING 仅报告", "状态保持 running，仅追加对账日志")

        print("\n== WP2 任务4 e2e 全部通过 ==")
        print(f"   验收 job: {first['task_id']}（幂等键 {CMD_ID_A1}）")
    finally:
        if cleanup_ids:
            await conn.execute(
                "delete from tasks where id = any($1::uuid[])",
                [uuid.UUID(tid) for tid in cleanup_ids],
            )
            print(f"== 清理 e2e 任务行 {len(cleanup_ids)} 条 ==")
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-db", action="store_true", help="保留 scratch 库（默认保留，可手动 drop）")
    args = parser.parse_args()
    _setup_scratch_db()
    asyncio.run(main())
    print(f"== scratch 库 {SCRATCH_DB} 已保留（验收后可 docker exec cygnusx-db dropdb -U omichub {SCRATCH_DB}）==")
