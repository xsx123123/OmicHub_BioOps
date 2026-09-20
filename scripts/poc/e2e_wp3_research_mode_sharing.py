"""WP3 任务 3 + 任务 4 e2e 验收：科研模式三开关门控 + 分享快照修复（R4）。

真实层次：
- 真实 DB（dev Postgres 127.0.0.1:5432/omichub）：会话/项目/消息/审计/file_records
  全部经平台 ORM 真写真读；PUT research-mode 端点函数真调用（jsonb_set 原子写入
  + audit_logs 落库）。
- 真实容器：默认会话（开关全关）有 environment.yml 时激活不触发还原；
  开启 research 协议后激活真实执行 micromamba 还原（真实进程、真实安装）。
- 真实编排子进程：run_orchestration 派生受限子进程跑 call_tool('llm_query')，
  软失败/放行均走真实 RPC 白名单判定（放行场景注入 recorder executor，不真调模型）。
- 真实分享链路：create_share → get_shared_session(token) → build_shared_snapshot
  → render_printable_report，工作区文件落真实存储后端。

前置：Docker 可用、cygnusx-studio-egress-proxy 运行中、本地 Postgres 可达。

用法：
    .venv/bin/python scripts/poc/e2e_wp3_research_mode_sharing.py
"""

from __future__ import annotations

import asyncio
import hashlib
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
SESSION_DEFAULT = f"e2e-wp3-default-{RUN_ID}"  # 开关全关（research_mode=null）
SESSION_ON = f"e2e-wp3-on-{RUN_ID}"  # 三开关全开
SESSION_OFF_MIN = f"e2e-wp3-offmin-{RUN_ID}"  # enabled=False 最小对象
SESSION_SHARE = f"e2e-wp3-share-{RUN_ID}"  # 分享 R4
PROJECT_SLUG = f"e2e-wp3-proj-{RUN_ID}"
PG_DSN = "postgresql://omichub:omichub_dev_password@127.0.0.1:5432/omichub"
IMAGE = "cygnusx-analysis:core-v0.0.2dev"
USER_NAME = "demo"  # 既有 dev 用户（避免造用户行）

PASS = "[PASS]"
FAIL = "[FAIL]"


def _ok(step: str, detail: str = "") -> None:
    print(f"{PASS} {step}" + (f" — {detail}" if detail else ""))


def _fail(step: str, detail: str = "") -> None:
    print(f"{FAIL} {step}" + (f" — {detail}" if detail else ""))


async def main() -> None:
    import docker
    from cygnusx.api.v1.chat import update_research_mode
    from cygnusx.application.schemas.chat import ResearchModeUpdateRequest
    from cygnusx.application.services.chat_service import ChatService
    from cygnusx.application.services.project_service import ProjectService
    from cygnusx.application.services.ptc_orchestrator import (
        PTC_ALLOWED_TOOLS,
        PTC_STATIC_ALLOWED_TOOLS,
        run_orchestration,
    )
    from cygnusx.application.services.studio_approval_service import (
        approval_required_tools,
    )
    from cygnusx.application.services.studio_sharing import (
        build_shared_snapshot,
        create_share,
        get_shared_session,
        render_printable_report,
    )
    from cygnusx.application.services.workspace_env_restore_service import (
        RESTORE_SKIP_RESEARCH_MODE_OFF,
        research_restore_gate_enabled,
    )
    from cygnusx.infrastructure.config.studio_loader import StudioConfigManager
    from cygnusx.infrastructure.database.models.chat import (
        ChatMessageModel,
        ChatSessionModel,
    )
    from cygnusx.infrastructure.database.models.file import FileRecordModel
    from cygnusx.infrastructure.database.models.project import ProjectModel
    from cygnusx.infrastructure.database.session import get_session_factory
    from cygnusx.infrastructure.studio.manager import StudioSandboxManager
    from sqlalchemy import select

    client = docker.from_env()
    proxy = client.containers.get("cygnusx-studio-egress-proxy")
    assert proxy.status == "running", "cygnusx-studio-egress-proxy 未运行"

    conn = await asyncpg.connect(PG_DSN)
    cleanup_sids = [SESSION_DEFAULT, SESSION_ON, SESSION_OFF_MIN, SESSION_SHARE]
    cleanup = {"png_sha256": None}  # finally 清理用（在 try 内赋值）

    # ---- 前置数据：dev 用户与模型配置（只读查询，不新建用户） ----
    user_id = await conn.fetchval("select id::text from users where username=$1", USER_NAME)
    model_id = await conn.fetchval(
        "select id::text from ai_provider_configs where is_active limit 1"
    )
    assert user_id and model_id, "dev 库缺少 demo 用户或可用模型配置"
    factory = get_session_factory()

    # ---- 容器管理器（/tmp 工作区，read_only_rootfs=false，同 WP2 poc 声明的偏差） ----
    work_root = Path(f"/tmp/e2e-wp3-research-{RUN_ID}")
    work_root.mkdir(parents=True, exist_ok=True)
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
      allow: [conda.anaconda.org, pypi.org, files.pythonhosted.org, mirrors.aliyun.com, mirrors.ustc.edu.cn, mirrors.nju.edu.cn, pypi.mirrors.ustc.edu.cn]
""",
        encoding="utf-8",
    )
    manager = StudioSandboxManager(_config_manager=StudioConfigManager(config_path=studio_yaml))

    try:
        async with factory() as db:
            # ============ 准备：插入测试会话行（真实 ORM） ============
            for sid in cleanup_sids:
                db.add(
                    ChatSessionModel(
                        id=uuid.uuid4(),
                        session_id=sid,
                        user_id=user_id,
                        model_id=uuid.UUID(model_id),
                        title=f"e2e wp3 {sid}",
                        status="active",
                        mode="studio",
                        sandbox_meta={},
                    )
                )
            await db.commit()

            # ============ 场景 1：默认会话（research_mode=null）全关门 ============
            print(f"\n== 场景 1：默认会话开关全关（session={SESSION_DEFAULT}） ==")
            gate_on, reason = await research_restore_gate_enabled(SESSION_DEFAULT)
            assert gate_on is False, f"默认会话门控应关闭: {gate_on}"
            _ok("restore 门控判定=关闭", reason or "")

            # llm_query：真实子进程 RPC，白名单软失败
            calls: list[str] = []

            async def _recorder(name, args):
                calls.append(name)
                return {"success": True, "result": {"llm_payload": {"answer": "ok"}, "ui_payload": {}}}

            code = (
                "try:\n"
                "    call_tool('llm_query', prompt='hi')\n"
                "except RuntimeError as exc:\n"
                "    print('blocked:', exc)\n"
            )
            result = await run_orchestration(code, SESSION_DEFAULT, db=db, tool_executor=_recorder)
            summary = result["result"]["llm_payload"]["summary"]
            assert result["success"] is True and "当前会话未开启 llm_query" in summary
            assert calls == [], f"被拦截的 llm_query 不应到达分发器: {calls}"
            _ok("llm_query 软失败且不在白名单", summary.strip().split("blocked: ", 1)[-1][:60])

            # restore：有 environment.yml 也不还原（真实容器激活）
            ws_default = manager.workspace_dir(SESSION_DEFAULT)
            manager.ensure_workspace_dirs(ws_default)
            (ws_default / "environment.yml").write_text(
                "channels:\n  - conda-forge\ndependencies:\n  - tqdm\n", encoding="utf-8"
            )
            handle = await manager.ensure_running(SESSION_DEFAULT)
            state = manager.env_restore_status(SESSION_DEFAULT)
            assert state and state["status"] == "skipped", f"默认会话不应还原: {state}"
            assert state["reason"] == RESTORE_SKIP_RESEARCH_MODE_OFF
            _ok("声明文件存在但激活不触发还原", f"container={handle.container_name}")
            audit_rows = await conn.fetch(
                "select 1 from audit_logs where resource_type='workspace_env_restore' "
                "and resource_id=$1",
                SESSION_DEFAULT,
            )
            assert not audit_rows, f"门控跳过不应落审计: {len(audit_rows)} 行"
            _ok("门控跳过未落审计（无 204 噪音）")

            # ============ 场景 2：PUT research-mode 开启三开关 ============
            print(f"\n== 场景 2：PUT research-mode 三开关全开（session={SESSION_ON}） ==")
            applied = await update_research_mode(
                current_user_id=user_id,
                db=db,
                session_id=SESSION_ON,
                req=ResearchModeUpdateRequest(
                    enabled=True,
                    render_mode="cell_timeline",
                    workspace_protocol="research",
                    ptc_llm_query=True,
                ),
            )
            await db.commit()
            assert applied == {
                "enabled": True,
                "render_mode": "cell_timeline",
                "workspace_protocol": "research",
                "ptc_llm_query": True,
            }, f"回显契约不符: {applied}"
            _ok("PUT 端点回显裸对象（前端契约）", json.dumps(applied, ensure_ascii=False))

            stored = await conn.fetchval(
                "select sandbox_meta->'research_mode' from chat_sessions where session_id=$1",
                SESSION_ON,
            )
            # asyncpg 将 jsonb 以文本返回，需解析后比较
            assert json.loads(stored) == applied, f"jsonb_set 落库值不符: {stored}"
            _ok("sandbox_meta.research_mode 原子落库")

            audit = await conn.fetchrow(
                "select status_code, detail from audit_logs where resource_type="
                "'research_mode_change' and resource_id=$1 order by created_at desc limit 1",
                SESSION_ON,
            )
            assert audit and audit["status_code"] == 200
            detail = audit["detail"] if isinstance(audit["detail"], dict) else json.loads(audit["detail"])
            assert detail["old"] is None and detail["new"] == applied
            _ok("audit_logs research_mode_change（含旧值新值）", json.dumps(detail["new"]))

            # enabled=False → 最小对象
            applied_off = await update_research_mode(
                current_user_id=user_id,
                db=db,
                session_id=SESSION_OFF_MIN,
                req=ResearchModeUpdateRequest(
                    enabled=False,
                    render_mode="cell_timeline",  # 应被忽略
                    workspace_protocol="research",
                    ptc_llm_query=True,
                ),
            )
            await db.commit()
            assert applied_off == {"enabled": False}, f"enabled=False 应存储最小对象: {applied_off}"
            _ok("enabled=False 存储最小对象并忽略子项", json.dumps(applied_off))

            # DTO 透出（列表/详情同构，走 ChatService._to_session_dto）
            session_on = await ChatService(db).get_session(SESSION_ON, user_id)
            dto = ChatService._to_session_dto(session_on)
            assert dto.research_mode and dto.research_mode.ptc_llm_query is True
            session_default = await ChatService(db).get_session(SESSION_DEFAULT, user_id)
            assert ChatService._to_session_dto(session_default).research_mode is None
            _ok("DTO 透出 research_mode（开/关两态）")

            # llm_query 进白名单（recorder 验证判定，不真调模型）
            calls.clear()
            result = await run_orchestration(
                "print(call_tool('llm_query', prompt='hi')['answer'])\n",
                SESSION_ON,
                db=db,
                tool_executor=_recorder,
            )
            assert result["success"] is True and calls == ["llm_query"]
            _ok("llm_query 进白名单并可调用", f"summary={result['result']['llm_payload']['summary'].strip()}")

            # restore 门控判定=执行 + 真实容器还原
            gate_on, _ = await research_restore_gate_enabled(SESSION_ON)
            assert gate_on is True, "开启后会话 restore 门控应放行"
            _ok("restore 门控判定=执行")
            ws_on = manager.workspace_dir(SESSION_ON)
            manager.ensure_workspace_dirs(ws_on)
            (ws_on / "environment.yml").write_text(
                "channels:\n  - conda-forge\ndependencies:\n  - tqdm\n", encoding="utf-8"
            )
            handle = await manager.ensure_running(SESSION_ON)
            state = manager.env_restore_status(SESSION_ON)
            assert state and state["status"] == "restored", f"科研会话应真实还原: {state}"
            _ok("真实容器还原执行", f"file={state['file']} duration_ms={state['duration_ms']}")
            audit_rows = await conn.fetch(
                "select status_code, detail from audit_logs where resource_type="
                "'workspace_env_restore' and resource_id=$1",
                SESSION_ON,
            )
            assert len(audit_rows) == 1 and audit_rows[0]["status_code"] == 200
            _ok("audit_logs 还原成功记录（200）")

            # ============ 场景 3：项目 settings.research_mode 继承 ============
            print("\n== 场景 3：项目级 settings 继承 ==")
            project = ProjectModel(
                id=uuid.uuid4(),
                user_id=uuid.UUID(user_id),
                name=f"e2e-wp3-{RUN_ID}",
                slug=PROJECT_SLUG,
                description="",
            )
            db.add(project)
            await db.flush()
            inherited_cfg = {
                "enabled": True,
                "render_mode": "cell_timeline",
                "workspace_protocol": "research",
                "ptc_llm_query": True,
            }
            updated = await ProjectService(db).update_project_settings(
                uuid.UUID(user_id), project.id, {"research_mode": inherited_cfg}
            )
            assert updated["settings"] == {"research_mode": inherited_cfg}
            _ok("PATCH settings 落库并回显", json.dumps(updated["settings"], ensure_ascii=False))

            dto = await ChatService(db).create_session(
                user_id,
                uuid.UUID(model_id),
                "wp3 继承测试",
                project_id=str(project.id),
            )
            assert dto.research_mode is not None
            assert dto.research_mode.model_dump() == inherited_cfg, dto.research_mode
            _ok("新建会话继承项目 research_mode", json.dumps(dto.research_mode.model_dump()))
            cleanup_sids.append(dto.session_id)

            # 调用方显式传入的 research_mode 优先于项目继承
            explicit_cfg = {"enabled": False}
            dto2 = await ChatService(db).create_session(
                user_id,
                uuid.UUID(model_id),
                "wp3 覆盖测试",
                sandbox_meta={"research_mode": dict(explicit_cfg)},
                project_id=str(project.id),
            )
            assert dto2.research_mode is not None and dto2.research_mode.enabled is False
            _ok("显式 research_mode 优先于项目继承")
            cleanup_sids.append(dto2.session_id)

            # 无 settings 的项目 → 不继承
            plain_project = ProjectModel(
                id=uuid.uuid4(),
                user_id=uuid.UUID(user_id),
                name=f"e2e-wp3-plain-{RUN_ID}",
                slug=f"{PROJECT_SLUG}-plain",
                description="",
            )
            db.add(plain_project)
            await db.flush()
            dto3 = await ChatService(db).create_session(
                user_id,
                uuid.UUID(model_id),
                "wp3 无继承测试",
                project_id=str(plain_project.id),
            )
            assert dto3.research_mode is None
            _ok("无 settings 项目不继承（research_mode=null）")
            cleanup_sids.append(dto3.session_id)
            await db.commit()

            # ============ 场景 4：分享快照 R4 ============
            print(f"\n== 场景 4：分享快照补执行历史与产物 sha256（session={SESSION_SHARE}） ==")
            big_timeline = [{"seq": i, "event": "tool_output", "data": "x" * 200} for i in range(3000)]
            invocations = [
                {
                    "tool_call_id": "tc-1",
                    "tool_name": "sandbox_execute",
                    "arguments": {"language": "python", "code": "print('volcano')"},
                    "success": True,
                    "result": {"exit_code": 0, "artifacts": ["output/volcano.png"]},
                    "payload_hash": "a" * 64,
                },
                {
                    "tool_call_id": "tc-2",
                    "tool_name": "workspace_write",
                    "arguments": {"path": "scripts/plot.py", "content": "import matplotlib"},
                    "success": True,
                    "result": {"path": "scripts/plot.py", "size": 16},
                    "payload_hash": "b" * 64,
                },
            ]
            db.add(
                ChatMessageModel(
                    id=uuid.uuid4(),
                    message_id=f"msg-u-{RUN_ID}",
                    session_id=SESSION_SHARE,
                    role="user",
                    content="画一张火山图",
                    status="complete",
                    metadata_json={},
                )
            )
            db.add(
                ChatMessageModel(
                    id=uuid.uuid4(),
                    message_id=f"msg-a-{RUN_ID}",
                    session_id=SESSION_SHARE,
                    role="assistant",
                    content="已完成火山图绘制。",
                    status="complete",
                    metadata_json={
                        "tool_invocations": invocations,
                        "timeline": big_timeline,  # 超 200KB → 快照层二次截断
                        "usage": {"input": 11, "output": 22, "total": 33},
                        "model": "internal-only",  # 非白名单键不外泄
                    },
                )
            )
            session_share = (
                await db.execute(
                    select(ChatSessionModel).where(
                        ChatSessionModel.session_id == SESSION_SHARE
                    )
                )
            ).scalar_one()

            # 工作区产物（真实存储后端可读）+ file_records 登记（WP2 checksum 列）
            from cygnusx.infrastructure.studio.manager import studio_sandbox_manager

            ws_share = studio_sandbox_manager.workspace_dir(SESSION_SHARE)
            manager.ensure_workspace_dirs(ws_share)
            png_bytes = b"\x89PNG-fake-volcano"
            (ws_share / "output" / "volcano.png").write_bytes(png_bytes)
            (ws_share / "output" / "notes.txt").write_text("no checksum", encoding="utf-8")
            png_sha256 = hashlib.sha256(png_bytes).hexdigest()
            cleanup["png_sha256"] = png_sha256
            db.add(
                FileRecordModel(
                    id=uuid.uuid4(),
                    user_id=uuid.UUID(user_id),
                    original_name="volcano.png",
                    storage_path=f"users/{user_id}/projects/p/runs/r/output/volcano.png",
                    size=len(png_bytes),
                    checksum=png_sha256,
                    file_type="png",
                    source="studio",
                )
            )
            await db.commit()

            token, _expires = create_share(session_share, 24)
            shared_session = await get_shared_session(db, token)
            snapshot = await build_shared_snapshot(db, shared_session)

            assistant_msg = [m for m in snapshot.messages if m.role == "assistant"][0]
            meta = assistant_msg.metadata_json or {}
            assert "model" not in meta, "非白名单键不得外泄"
            assert meta["tool_invocations"] == invocations, "工具卡（含 code arguments）应原样透出"
            assert meta["usage"] == {"input": 11, "output": 22, "total": 33}
            assert meta["timeline"] == {"_cygnusx_payload_truncated": True}
            assert meta["timeline_truncation"]["payload_truncated"] is True
            _ok("metadata_json 含 tool_invocations/usage，timeline 超 200KB 带截断标记")

            artifacts = {a["path"]: a for a in snapshot.artifacts}
            assert artifacts["output/volcano.png"]["sha256"] == png_sha256
            assert artifacts["output/notes.txt"]["sha256"] is None
            _ok("产物清单补 sha256（登记命中/未命中两态）")

            report = render_printable_report(snapshot)
            assert "sandbox_execute" in report and "volcano" in report
            assert "workspace_write" in report and "scripts/plot.py" in report
            assert f"sha256:{png_sha256[:16]}…" in report
            _ok("render_printable_report 含工具卡摘要（代码+输出）与 sha256")

            # ============ 场景 5：审批语义不变 ============
            print("\n== 场景 5：审批语义回归 ==")
            approvals = approval_required_tools()
            assert "tool_orchestrate" in approvals and "llm_query" not in approvals
            assert "llm_query" in PTC_ALLOWED_TOOLS and "llm_query" not in PTC_STATIC_ALLOWED_TOOLS
            _ok("tool_orchestrate ∈ 审批名单；llm_query ∉（整段一次审批不变）")

            print(f"\n全部场景通过 ✅（run={RUN_ID}）")
    finally:
        # ---- 清理：容器 / 工作区 / DB 行 ----
        for sid in set(cleanup_sids):
            with __import__("contextlib").suppress(Exception):
                await manager.stop(sid)
        with __import__("contextlib").suppress(Exception):
            import shutil

            shutil.rmtree(work_root, ignore_errors=True)
            shutil.rmtree(
                studio_sandbox_manager.workspace_dir(SESSION_SHARE), ignore_errors=True
            )
        await conn.execute(
            "delete from audit_logs where resource_type in "
            "('research_mode_change','workspace_env_restore') and resource_id = any($1::text[])",
            list(set(cleanup_sids)),
        )
        await conn.execute(
            "delete from chat_sessions where session_id = any($1::text[])",
            list(set(cleanup_sids)),
        )
        await conn.execute("delete from projects where slug like $1", f"e2e-wp3-%{RUN_ID}%")
        if cleanup["png_sha256"]:
            await conn.execute(
                "delete from file_records where source='studio' and checksum=$1",
                cleanup["png_sha256"],
            )
        await conn.close()
        print("清理完成（容器/工作区/DB 测试行已回收）")


if __name__ == "__main__":
    asyncio.run(main())
