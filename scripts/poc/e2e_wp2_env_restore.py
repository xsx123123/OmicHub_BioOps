"""WP2 任务 3 e2e 验收脚本：声明式环境还原（替代容器快照）。

真实层次：
- 真实容器：经 StudioSandboxManager 懒启动 dev 沙盒镜像（cygnusx-analysis:core），
  还原钩子容器内一次性执行 micromamba 安装（真实进程、真实安装）；
- 真实 DB：audit_logs 走平台 get_session_factory 落库（异步 ORM 真写真实 Postgres）；
- 真实审计查询：missing_env_snapshot 联动从真实 audit_logs 读。

唯一与生产的偏差（脚本开头显式声明）：read_only_rootfs=false。生产基线为只读
根文件系统，micromamba 无法写 /opt/conda（已在镜像上实测 EROFS），此时还原会
走「失败→降级基础环境→前端 warning」路径（场景 B 同链路验证）；本脚本为验证
「还原成功」主链路需要可写根文件系统。两态共用同一份钩子代码。

前置：Docker 可用、cygnusx-studio-egress-proxy 容器运行中（whitelist 出站）、
本地 Postgres 127.0.0.1:5432 可达。

用法：
    .venv/bin/python scripts/poc/e2e_wp2_env_restore.py
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://omichub:omichub_dev_password@127.0.0.1:5432/omichub",
)

import asyncpg

RUN_ID = uuid.uuid4().hex[:8]
SESSION_OK = f"e2e-wp2-env-ok-{RUN_ID}"
SESSION_BAD = f"e2e-wp2-env-bad-{RUN_ID}"
SESSION_SKIP = f"e2e-wp2-env-skip-{RUN_ID}"
SESSION_MANIFEST = f"e2e-wp2-env-mani-{RUN_ID}"
PG_DSN = "postgresql://omichub:omichub_dev_password@127.0.0.1:5432/omichub"
IMAGE = "cygnusx-analysis:core-v0.0.2dev"

PASS = "[PASS]"
FAIL = "[FAIL]"


def _ok(step: str, detail: str = "") -> None:
    print(f"{PASS} {step}" + (f" — {detail}" if detail else ""))


async def _exec_python(manager, session_id: str, code: str) -> tuple[int, str]:
    """经 sandbox-agent 在容器内执行 python，返回 (exit_code, 合并输出)。"""
    exit_code = -1
    output: list[str] = []
    async for event in manager.exec(session_id, "python", code):
        etype = event.get("type")
        if etype in ("stdout", "stderr"):
            output.append(str(event.get("data", "")))
        elif etype == "result":
            exit_code = int(event.get("exit_code", -1))
    return exit_code, "".join(output)


async def _restore_audit_rows(conn, session_id: str) -> list[asyncpg.Record]:
    return await conn.fetch(
        "select status_code, detail, created_at from audit_logs "
        "where resource_type='workspace_env_restore' and resource_id=$1 "
        "order by created_at",
        session_id,
    )


async def main() -> None:
    import docker
    from cygnusx.infrastructure.config.studio_loader import StudioConfigManager
    from cygnusx.infrastructure.studio.manager import StudioSandboxManager

    client = docker.from_env()
    proxy = client.containers.get("cygnusx-studio-egress-proxy")
    assert proxy.status == "running", "cygnusx-studio-egress-proxy 未运行，whitelist 出站不可用"

    work_root = Path(f"/tmp/e2e-wp2-env-restore-{RUN_ID}")
    work_root.mkdir(parents=True, exist_ok=True)
    # 与 data/ai/studio.yaml 同源约定；唯一偏差 read_only_rootfs=false（见模块 docstring）
    studio_yaml = work_root / "studio.yaml"
    studio_yaml.write_text(
        f"""studio:
  enabled: true
  default_image: {IMAGE}
  mounts:
    workspace: "{work_root}/ws"
  session:
    idle_ttl_minutes: 10
  sandbox:
    cpu: 2
    memory: 4g
    exec_timeout_seconds: 600
    pids_limit: 512
    read_only_rootfs: false
    tmpfs_size: 512m
    container_user: 10001:10001
    network:
      mode: whitelist
      docker_network: cygnusx-studio-egress
      proxy_container: cygnusx-studio-egress-proxy
      proxy_host: studio-egress-proxy
      proxy_port: 3128
      # ustc anaconda 镜像把 menpo 频道 302 重定向到 mirrors.nju.edu.cn（实测），
      # 不放行则整个事务失败 —— 这是部署级白名单缺口，POC 先放行验证主链路
      allow: [conda.anaconda.org, pypi.org, files.pythonhosted.org, mirrors.aliyun.com, mirrors.ustc.edu.cn, mirrors.nju.edu.cn, pypi.mirrors.ustc.edu.cn]
""",
        encoding="utf-8",
    )
    manager = StudioSandboxManager(_config_manager=StudioConfigManager(config_path=studio_yaml))

    conn = await asyncpg.connect(PG_DSN)
    sessions = [SESSION_OK, SESSION_BAD, SESSION_SKIP, SESSION_MANIFEST]
    try:
        # ===== 场景 A：environment.yml（tqdm）→ 还原成功，包真实可见 =====
        print(f"\n== 场景 A：还原成功主链路（session={SESSION_OK}） ==")
        ws_ok = manager.workspace_dir(SESSION_OK)
        manager.ensure_workspace_dirs(ws_ok)
        (ws_ok / "environment.yml").write_text(
            "name: e2e-restore\n"
            "channels:\n  - conda-forge\n"
            "dependencies:\n  - tqdm\n",
            encoding="utf-8",
        )
        handle = await manager.ensure_running(SESSION_OK)
        _ok("懒启动 + 还原钩子执行", f"container={handle.container_name}")
        state = manager.env_restore_status(SESSION_OK)
        assert state and state["status"] == "restored", f"还原未成功: {state}"
        _ok("还原状态 restored", f"file={state['file']} duration_ms={state['duration_ms']}")

        exit_code, output = await _exec_python(
            manager, SESSION_OK, "import tqdm; print('tqdm', tqdm.__version__)"
        )
        assert exit_code == 0 and "tqdm" in output, f"容器内 import tqdm 失败: {output[-500:]}"
        _ok("容器内可见还原安装的包", output.strip().splitlines()[-1])

        rows = await _restore_audit_rows(conn, SESSION_OK)
        assert len(rows) == 1, f"audit 行数异常: {len(rows)}"
        detail = json.loads(rows[0]["detail"]) if isinstance(rows[0]["detail"], str) else rows[0]["detail"]
        assert rows[0]["status_code"] == 200 and detail["success"] is True
        assert detail["duration_ms"] > 0 and detail["file"] == "environment.yml"
        _ok("audit_logs 成功记录（含耗时）", json.dumps(detail, ensure_ascii=False))

        # 重复激活（同容器生命周期）不重复还原
        await manager.ensure_running(SESSION_OK)
        rows = await _restore_audit_rows(conn, SESSION_OK)
        assert len(rows) == 1, f"重复激活产生了重复还原: {len(rows)} 行"
        _ok("重复激活不重复还原", "audit 行数仍为 1")

        # ===== 场景 B：不存在的包 → 还原失败但会话可执行，审计记失败 =====
        print(f"\n== 场景 B：还原失败降级（session={SESSION_BAD}） ==")
        ws_bad = manager.workspace_dir(SESSION_BAD)
        manager.ensure_workspace_dirs(ws_bad)
        (ws_bad / "environment.yml").write_text(
            "channels:\n  - conda-forge\n"
            "dependencies:\n  - definitely-not-a-real-pkg-xyz-12345\n",
            encoding="utf-8",
        )
        handle = await manager.ensure_running(SESSION_BAD)  # 不得抛异常
        _ok("还原失败未阻断会话启动", f"container={handle.container_name}")
        exit_code, _ = await _exec_python(manager, SESSION_BAD, "print('base env alive')")
        assert exit_code == 0, "基础环境执行失败"
        _ok("基础环境可继续执行代码")
        state = manager.env_restore_status(SESSION_BAD)
        assert state and state["status"] == "failed" and state["reason"], f"失败状态缺失: {state}"
        _ok("失败状态可见（前端 warning toast 数据源）", state["reason"][:120])
        rows = await _restore_audit_rows(conn, SESSION_BAD)
        assert len(rows) == 1 and rows[0]["status_code"] == 500
        detail = json.loads(rows[0]["detail"]) if isinstance(rows[0]["detail"], str) else rows[0]["detail"]
        assert detail["success"] is False and detail["reason"]
        _ok("audit_logs 失败记录", detail["reason"][:120])

        # ===== 场景 C：无声明文件 → 跳过并记日志/审计 =====
        print(f"\n== 场景 C：无声明文件跳过（session={SESSION_SKIP}） ==")
        ws_skip = manager.workspace_dir(SESSION_SKIP)
        manager.ensure_workspace_dirs(ws_skip)
        await manager.ensure_running(SESSION_SKIP)
        state = manager.env_restore_status(SESSION_SKIP)
        assert state and state["status"] == "skipped" and "跳过" in (state["reason"] or "")
        _ok("跳过状态 + 原因", state["reason"])
        rows = await _restore_audit_rows(conn, SESSION_SKIP)
        assert len(rows) == 1 and rows[0]["status_code"] == 204
        _ok("audit_logs 跳过记录（204）")

        # ===== 场景 D：WP1 manifest missing_env_snapshot 联动 =====
        print(f"\n== 场景 D：missing_env_snapshot 联动（session={SESSION_MANIFEST}） ==")
        ws_mani = manager.workspace_dir(SESSION_MANIFEST)
        manager.ensure_workspace_dirs(ws_mani)
        # 模拟 WP1 打包审计：manifest 标记缺失四件套中的 environment.yml
        await conn.execute(
            "insert into audit_logs (id, user_id, username, method, path, resource_type, "
            "resource_id, status_code, detail) "
            "values ($1, null, 'e2e', 'POST', '/e2e', 'workspace_archive', $2, 200, $3)",
            uuid.uuid4(),
            SESSION_MANIFEST,
            json.dumps(
                {
                    "event": "workspace_archive_packed",
                    "session_id": SESSION_MANIFEST,
                    "missing_env_snapshot": ["conda-explicit.txt", "environment.yml"],
                }
            ),
        )
        await manager.ensure_running(SESSION_MANIFEST)
        state = manager.env_restore_status(SESSION_MANIFEST)
        assert state and state["status"] == "skipped"
        assert "缺失环境四件套" in (state["reason"] or ""), f"跳过原因未引用 manifest: {state}"
        _ok("跳过原因引用 WP1 manifest 缺失清单", state["reason"])
        rows = await _restore_audit_rows(conn, SESSION_MANIFEST)
        assert len(rows) == 1 and rows[0]["status_code"] == 204
        _ok("audit_logs 跳过记录（含 manifest 联动）")

        print(f"\n全部场景通过 ✅（run={RUN_ID}）")
    finally:
        for sid in sessions:
            with __import__("contextlib").suppress(Exception):
                await manager.stop(sid)
            with __import__("contextlib").suppress(Exception):
                rows = await conn.execute(
                    "delete from audit_logs where resource_type in ('workspace_env_restore','workspace_archive') "
                    "and resource_id=$1",
                    sid,
                )
        await conn.close()
        with __import__("contextlib").suppress(Exception):
            import shutil

            shutil.rmtree(work_root, ignore_errors=True)
        print(f"清理完成（容器已回收、审计行已删、{work_root} 已删）")


if __name__ == "__main__":
    asyncio.run(main())
