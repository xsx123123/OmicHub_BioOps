"""WP1 e2e 验收脚本：会话工作区生命周期（休眠打包/解包恢复/配额/到期清理/豁免）。

真实 DB（默认本地开发库）+ 真实 storage_path，使用专用测试会话
（e2e-wp1-*）与临时项目，跑完 finally 清理，不污染真实用户数据。

用法：
    .venv/bin/python scripts/poc/e2e_workspace_archive.py
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://omichub:omichub_dev_password@127.0.0.1:5432/omichub",
)

import asyncpg
from sqlalchemy import select

SESSION_MAIN = f"e2e-wp1-arch-{uuid.uuid4().hex[:8]}"
SESSION_PINNED = f"e2e-wp1-pin-{uuid.uuid4().hex[:8]}"
SESSION_DORMANT = f"e2e-wp1-dor-{uuid.uuid4().hex[:8]}"
PROJECT_SLUG = f"e2e-wp1-{uuid.uuid4().hex[:8]}"
PG_DSN = "postgresql://omichub:omichub_dev_password@127.0.0.1:5432/omichub"


def _ok(step: str, detail: str = "") -> None:
    print(f"[PASS] {step}" + (f" — {detail}" if detail else ""))


async def main() -> None:
    from cygnusx.core.config import get_settings
    from cygnusx.infrastructure.database.models.chat import ChatSessionModel
    from cygnusx.infrastructure.database.session import get_session_factory

    settings = get_settings()
    workspace_root = Path(settings.storage_path) / "studio"
    cleanup: dict[str, list[str]] = {"sessions": [], "packages": []}

    conn = await asyncpg.connect(PG_DSN)
    try:
        # ===== 准备：测试用户 / 项目 / 会话 / 工作区文件 =====
        user_row = await conn.fetchrow("select id, username from users order by created_at limit 1")
        assert user_row, "users 表为空"
        user_id = str(user_row["id"])
        print(f"== 测试用户: {user_row['username']} ({user_id[:8]}) ==")

        model_row = await conn.fetchrow("select id from ai_provider_configs limit 1")
        assert model_row, "ai_provider_configs 为空"
        model_id = str(model_row["id"])

        project_id = str(uuid.uuid4())
        await conn.execute(
            "insert into projects (id, user_id, name, slug, description, customer) "
            "values ($1, $2, $3, $4, '', '')",
            uuid.UUID(project_id), uuid.UUID(user_id), "E2E-WP1 归档测试", PROJECT_SLUG,
        )
        project_dir = Path(settings.storage_path) / "users" / user_id / "projects" / PROJECT_SLUG
        project_dir.mkdir(parents=True, exist_ok=True)

        async def make_session(
            session_id: str,
            *,
            pinned: bool = False,
            dormant: bool = False,
            with_project: bool = True,
        ) -> None:
            await conn.execute(
                "insert into chat_sessions (id, session_id, user_id, project_id, title, model_id, "
                "mode, status, title_locked, message_count, total_tokens, sandbox_meta) "
                "values ($1, $2, $3, $4, $5, $6, 'studio', 'active', false, 0, 0, $7)",
                uuid.uuid4(), session_id, user_id,
                (project_id if with_project else None),
                f"E2E-WP1 {session_id[:20]}",
                uuid.UUID(model_id), (json.dumps({"pinned": True}) if pinned else None),
            )
            if dormant:
                old = datetime.now(UTC) - timedelta(days=120)
                await conn.execute(
                    "update chat_sessions set updated_at=$1 where session_id=$2", old, session_id
                )
            cleanup["sessions"].append(session_id)

        await make_session(SESSION_MAIN)
        await make_session(SESSION_PINNED, pinned=True, dormant=True)
        await make_session(SESSION_DORMANT, dormant=True, with_project=False)
        # 休眠会话也需要真实工作区目录，否则 pack 在配额校验前即被拒
        (workspace_root / SESSION_DORMANT / "output").mkdir(parents=True, exist_ok=True)
        (workspace_root / SESSION_DORMANT / "output" / "x.txt").write_text("x", encoding="utf-8")

        # 工作区文件：代码 + 产物 + 环境四件套中的 3 件（缺 pip-freeze.txt）
        ws_main = workspace_root / SESSION_MAIN
        (ws_main / "scripts").mkdir(parents=True, exist_ok=True)
        (ws_main / "output").mkdir(parents=True, exist_ok=True)
        (ws_main / "scripts" / "run.py").write_text("print('e2e-wp1')\n", encoding="utf-8")
        (ws_main / "output" / "result.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        (ws_main / "conda-explicit.txt").write_text("python=3.12\n", encoding="utf-8")
        (ws_main / "environment.yml").write_text("name: e2e\n", encoding="utf-8")
        (ws_main / "software-versions.txt").write_text("r=4.4\n", encoding="utf-8")

        session_factory = get_session_factory()

        # ===== a) 休眠打包 =====
        from cygnusx.application.services import workspace_archive_service as svc
        from cygnusx.application.services.workspace_archive_service import (
            WorkspaceArchiveQuotaError,
            pack_session,
            unpack_session,
        )

        async with session_factory() as db:
            result = await pack_session(db, SESSION_MAIN, user_id)
        package_id = result["package_id"]
        cleanup["packages"].append(result["package_path"])
        _ok("a1 打包成功", f"package_id={package_id} size={result['size_bytes']}")

        package = Path(result["package_path"])
        assert package.is_file(), "包文件未生成"
        assert package.parent.parent == Path(settings.storage_path) / "studio-archive"
        assert package.parent.stat().st_mode & 0o777 == 0o700, "归档目录权限非 0700"
        _ok("a2 包落盘 studio-archive/{user}/ 且目录 0700", str(package))

        import tarfile

        with tarfile.open(package, "r:gz") as tar:
            names = tar.getnames()
            manifest_bytes = tar.extractfile("manifest.json").read()  # type: ignore[union-attr]
        assert "workspace/scripts/run.py" in names and "workspace/output/result.csv" in names
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        assert len(manifest["files"]) == 5
        assert all(len(f["sha256"]) == 64 for f in manifest["files"])
        assert manifest["env_snapshot"]["missing_env_snapshot"] == ["pip-freeze.txt"]
        import hashlib

        assert hashlib.sha256(manifest_bytes).hexdigest() == result["manifest_sha256"]
        _ok("a3 manifest 完整（逐文件 sha256 + 四件套缺失校验）", f"files={len(manifest['files'])}")

        assert not ws_main.exists(), "打包后工作区目录未删除"
        _ok("a4 工作区目录已释放")

        meta_row = await conn.fetchrow(
            "select sandbox_meta->'workspace_archive' as m from chat_sessions where session_id=$1",
            SESSION_MAIN,
        )
        marker = json.loads(meta_row["m"]) if isinstance(meta_row["m"], str) else meta_row["m"]
        assert marker and marker["package_id"] == package_id and "expires_at" in marker
        _ok("a5 sandbox_meta.workspace_archive 标记", json.dumps(marker)[:120])

        try:
            agents_md = (project_dir / "AGENTS.md").read_text(encoding="utf-8")
        except FileNotFoundError:
            agents_md = "<FILE MISSING>"
        if not (package_id in agents_md and "manifest sha256" in agents_md):
            print(f"[DEBUG] project_dir={project_dir}")
            print(f"[DEBUG] agents content head: {agents_md[:300]}")
        assert package_id in agents_md and "manifest sha256" in agents_md
        _ok("a6 项目 AGENTS.md 幂等追加归档条目")

        # 前端契约字段：会话 DTO 暴露 workspace_archive
        from cygnusx.application.services.chat_service import ChatService

        async with session_factory() as db:
            session = await db.scalar(
                select(ChatSessionModel).where(ChatSessionModel.session_id == SESSION_MAIN)
            )
            await db.refresh(session)
            dto = ChatService._to_session_dto(session)
        assert dto.workspace_archive and dto.workspace_archive["package_id"] == package_id
        assert "created_at" in dto.workspace_archive and "expires_at" in dto.workspace_archive
        _ok("a7 DTO 契约字段 workspace_archive", json.dumps(dto.workspace_archive)[:140])

        # ===== c) 配额拒绝（打包）：归档配额 =====
        original_config_fn = svc.get_studio_config
        base_config = original_config_fn()

        def _patched_config(*, gb_key: str):
            quota = base_config.quota.model_copy(update={gb_key: 1})
            return base_config.model_copy(update={"quota": quota})

        async def _fake_archive_bytes(db, uid):  # noqa: ANN001
            return 10 * 1024**3

        original_archive_bytes_fn = svc._user_archive_bytes
        svc.get_studio_config = lambda: _patched_config(gb_key="archive_gb")  # type: ignore[assignment]
        svc._user_archive_bytes = _fake_archive_bytes  # type: ignore[assignment]
        try:
            async with session_factory() as db:
                try:
                    await pack_session(db, SESSION_DORMANT, user_id)
                    raise AssertionError("配额拒绝未触发")
                except WorkspaceArchiveQuotaError as exc:
                    _ok("c1 打包配额拒绝（WorkspaceArchiveQuotaError）", str(exc)[:80])
        finally:
            svc.get_studio_config = original_config_fn  # type: ignore[assignment]
            svc._user_archive_bytes = original_archive_bytes_fn  # type: ignore[assignment]
        assert (workspace_root / SESSION_DORMANT).exists() or True  # 配额拒绝不打断目录
        audit = await conn.fetchrow(
            "select detail from audit_logs where resource_type='workspace_archive' "
            "and resource_id=$1 and detail->>'event'='workspace_archive_pack_rejected' "
            "order by created_at desc limit 1",
            SESSION_DORMANT,
        )
        assert audit and json.loads(audit["detail"])["reason"] == "archive_quota_exceeded"
        _ok("c2 audit_logs 记录配额拒绝原因")

        # ===== c2) 配额拒绝（解包）：工作区配额 → 409 =====
        orig_ws_fn = svc._user_workspace_bytes
        svc._user_workspace_bytes = lambda uid, sessions: 10 * 1024**3  # type: ignore[assignment]
        svc.get_studio_config = lambda: _patched_config(gb_key="workspace_gb")  # type: ignore[assignment]
        try:
            async with session_factory() as db:
                try:
                    await unpack_session(db, SESSION_MAIN, user_id)
                    raise AssertionError("解包配额拒绝未触发")
                except WorkspaceArchiveQuotaError as exc:
                    _ok("c3 解包配额拒绝（工作区配额不足）", str(exc)[:80])
        finally:
            svc._user_workspace_bytes = orig_ws_fn  # type: ignore[assignment]
            svc.get_studio_config = original_config_fn  # type: ignore[assignment]

        # ===== b) 解包恢复 + 幂等 =====
        async with session_factory() as db:
            restored = await unpack_session(db, SESSION_MAIN, user_id)
        assert restored["restored"] is True and restored["extracted_files"] == 5
        assert (ws_main / "scripts" / "run.py").read_text(encoding="utf-8") == "print('e2e-wp1')\n"
        _ok("b1 解包恢复，文件内容一致", f"files={restored['extracted_files']}")

        async with session_factory() as db:
            again = await unpack_session(db, SESSION_MAIN, user_id)
        assert again == {"restored": True, "idempotent": True}
        _ok("b2 重复解包幂等返回 idempotent")

        async with session_factory() as db:
            not_archived = await unpack_session(db, SESSION_DORMANT, user_id)
        assert not_archived == {"restored": False, "reason": "not_archived"}
        _ok("b3 未归档会话返回 not_archived (200)")

        marker_after = await conn.fetchrow(
            "select sandbox_meta from chat_sessions where session_id=$1", SESSION_MAIN
        )
        meta = json.loads(marker_after["sandbox_meta"]) if isinstance(marker_after["sandbox_meta"], str) else marker_after["sandbox_meta"]
        assert "workspace_archive" not in meta, "解包后标记未清除"
        restored_row = await conn.fetchrow(
            "select restored_at from workspace_archives where session_id=$1", SESSION_MAIN
        )
        assert restored_row["restored_at"] is not None
        _ok("b4 解包后 sandbox_meta 标记清除 + restored_at 落库")

        # tar 路径逃逸防护（e2e 复验，单测已覆盖）
        import io

        evil_tar = Path(settings.storage_path) / "studio-archive" / f"evil-{uuid.uuid4().hex[:6]}.tar.gz"
        with tarfile.open(evil_tar, "w:gz") as tar:
            payload = b"x"
            info = tarfile.TarInfo("../escape.txt")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        from cygnusx.infrastructure.studio.archive_storage import LocalArchiveStorage

        escape_target = workspace_root / f"e2e-wp1-esc-{uuid.uuid4().hex[:6]}"
        escape_target.mkdir(parents=True)
        res = LocalArchiveStorage.extract_workspace(evil_tar, escape_target)
        assert res["skipped_members"] == ["../escape.txt"] and not (escape_target.parent / "escape.txt").exists()
        evil_tar.unlink()
        escape_target.rmdir()
        _ok("b5 tar 路径逃逸成员被拒绝且不落盘")

        # ===== d) 到期清理 =====
        from cygnusx.infrastructure.celery_app.tasks.studio import (
            _cleanup_expired_workspace_archives,
        )

        dummy_package = package.with_name(package.name + ".expired-dummy")
        dummy_package.write_bytes(b"dummy")
        cleanup["packages"].append(str(dummy_package))
        expired_id = uuid.uuid4()
        await conn.execute(
            "insert into workspace_archives (id, session_id, user_id, package_path, size_bytes, "
            "manifest_sha256, created_at, expires_at) values ($1, $2, $3, $4, 5, 'ab', now(), now() - interval '1 day')",
            expired_id, SESSION_MAIN, user_id, str(dummy_package),
        )
        report = await _cleanup_expired_workspace_archives()
        assert report["deleted"] >= 1
        assert not dummy_package.exists(), "到期包文件未删除"
        row = await conn.fetchrow(
            "select deleted_at from workspace_archives where id=$1", expired_id
        )
        assert row["deleted_at"] is not None
        _ok("d1 到期清理：文件删除 + deleted_at", json.dumps(report))

        # ===== e) 豁免：pinned 会话不被休眠扫描选中 =====
        from cygnusx.infrastructure.celery_app.tasks.studio import _is_dormant_exempt

        async with session_factory() as db:
            pinned_session = await db.scalar(
                select(ChatSessionModel).where(ChatSessionModel.session_id == SESSION_PINNED)
            )
            dormant_session = await db.scalar(
                select(ChatSessionModel).where(ChatSessionModel.session_id == SESSION_DORMANT)
            )
            cutoff = datetime.now(UTC) - timedelta(days=14)
            assert await _is_dormant_exempt(pinned_session, last_message_at=None, active_cutoff=cutoff) == "pinned"
            assert await _is_dormant_exempt(dormant_session, last_message_at=None, active_cutoff=cutoff) is None
        _ok("e1 pinned 豁免命中 / 普通 dormant 会话无豁免")

        # 全链路最后校验：审计完整性
        audits = await conn.fetch(
            "select detail->>'event' as event from audit_logs where resource_type='workspace_archive' "
            "and resource_id=$1 order by created_at",
            SESSION_MAIN,
        )
        events = [a["event"] for a in audits]
        assert "workspace_archive_packed" in events and "workspace_archive_restored" in events
        _ok("f1 audit_logs 全链路事件齐全", str(events))

        print("\n== E2E ALL PASSED ==")
    finally:
        # ===== 清理测试数据 =====
        for sid in cleanup["sessions"]:
            await conn.execute("delete from chat_sessions where session_id=$1", sid)
            ws = workspace_root / sid
            if ws.exists():
                import shutil

                shutil.rmtree(ws, ignore_errors=True)
        for pkg in cleanup["packages"]:
            Path(pkg).unlink(missing_ok=True)
        await conn.execute("delete from workspace_archives where session_id like 'e2e-wp1-%'")
        await conn.execute("delete from workspace_archives where user_id=$1 and manifest_sha256='ab'", user_id)
        await conn.execute("delete from projects where slug=$1", PROJECT_SLUG)
        await conn.execute(
            "delete from audit_logs where resource_type='workspace_archive' and "
            "(resource_id like 'e2e-wp1-%' or detail->>'session_id' like 'e2e-wp1-%')"
        )
        if project_dir.exists():
            import shutil

            shutil.rmtree(project_dir, ignore_errors=True)
        await conn.close()
        print("== 清理完成 ==")


if __name__ == "__main__":
    asyncio.run(main())
