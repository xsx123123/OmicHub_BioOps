"""WP2 任务 2 e2e 验收：产物 sha256 实测对账（挂登记点）。

真实 DB（默认本地开发库）+ 真实 storage_path，走生产代码路径：
 场景1 声明 2 个产物且都真实存在 → 执行结果 manifest 含 path/size/sha256，
        与系统 sha256sum 一致；新建 file_records 记录 checksum 列 = 实测 sha256；
 场景2 声明 1 个产物但文件不存在 → llm_payload/ui_payload 带 missing_artifacts，
        登记流程不中断，日志有 warn；
 场景3 归档 README 同时含 MD5 与 sha256，run 目录 manifest.json 落盘且 sha256 与实测一致。

沙盒容器侧用假 pool 模拟"容器→宿主机"复制（文件真实落盘到 storage_path），
sha256 实测/对账/登记全部由被测生产代码执行。专用 e2e-wp2-* 目录，
跑完 finally 清理（file_records 行 + 宿主机文件 + 项目归档目录），不污染真实数据。

用法：
    .venv/bin/python scripts/poc/e2e_wp2_artifact_manifest.py
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
import subprocess
import uuid
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://omichub:omichub_dev_password@127.0.0.1:5432/omichub",
)

import asyncpg

HEX = uuid.uuid4().hex[:8]
PG_DSN = "postgresql://omichub:omichub_dev_password@127.0.0.1:5432/omichub"
CHAT_SESSION_1 = f"e2e-wp2-chat-a-{HEX}"
CHAT_SESSION_2 = f"e2e-wp2-chat-b-{HEX}"
PROJECT_NAME = f"E2E-WP2-{HEX}"


def _ok(step: str, detail: str = "") -> None:
    print(f"[PASS] {step}" + (f" — {detail}" if detail else ""))


def _sha256sum(path: Path) -> str:
    """系统 sha256sum 的输出（hex），与平台实测值对账。"""
    out = subprocess.run(
        ["sha256sum", str(path)], capture_output=True, text=True, check=True
    ).stdout
    return out.split()[0]


class _FakePool:
    """模拟沙盒池 copy_dir_out：把"容器产物"真实写到宿主机目录并返回条目。"""

    def __init__(self, files: dict[str, bytes]):
        self._files = files

    async def copy_dir_out(self, _container_id: str, container_dir: str, host_dest: Path):
        if container_dir != "/tmp/chat_output":
            return []
        items = []
        for rel, content in self._files.items():
            target = host_dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            stat = target.stat()
            items.append({"path": rel, "size": stat.st_size, "mtime": stat.st_mtime})
        return items


def _install_fakes(files: dict[str, bytes]) -> None:
    """把 execute_chat_sandbox 的容器侧依赖替换为假实现（沙盒池/会话服务）。"""
    from cygnusx.application.services import sandbox_service
    from cygnusx.infrastructure import sandbox as sandbox_module
    from cygnusx.infrastructure.database import session as session_module

    counter = {"n": 0}

    class FakeService:
        def __init__(self, db: object) -> None:
            pass

        async def create_session(self, user_id, language):
            counter["n"] += 1
            return SimpleNamespace(
                id=f"e2e-wp2-sbx-{HEX}-{counter['n']}",
                container_id=f"e2e-wp2-ctr-{HEX}-{counter['n']}",
            )

        async def execute_code(self, user_id, session_id, code, timeout_sec=0, language="bash"):
            yield {"type": "done"}

    sandbox_service.SandboxService = FakeService
    real_factory = session_module.get_session_factory()
    session_module.get_session_factory = lambda: real_factory
    sandbox_module.get_sandbox_pool = lambda: _FakePool(files)


async def main() -> None:
    from cygnusx.application.services.chat_sandbox_tools import execute_chat_sandbox
    from cygnusx.core.config import get_settings
    from loguru import logger

    settings = get_settings()
    conn = await asyncpg.connect(PG_DSN)
    log_sink = io.StringIO()
    sink_id = logger.add(log_sink, level="WARNING")
    try:
        user_row = await conn.fetchrow("select id, username from users order by created_at limit 1")
        assert user_row, "users 表为空"
        user_id = str(user_row["id"])
        print(f"== 测试用户: {user_row['username']} ({user_id[:8]}) ==")

        # ===== 场景 1：声明 2 个产物且都真实存在 =====
        f_summary = b"gene,log2fc\nA,1.2\nB,-0.5\n"
        f_plot = b"png-bytes-e2e-wp2"
        _install_fakes({"results/summary.csv": f_summary, "figures/plot.png": f_plot})

        result = await execute_chat_sandbox(
            {
                "language": "python",
                "code": "（e2e：容器侧由假 pool 模拟产物落盘）",
                "artifacts": ["results/summary.csv", "figures/*.png"],
            },
            user_id,
            session_id=CHAT_SESSION_1,
        )
        assert result["success"], result
        llm = result["result"]["llm_payload"]
        assert "missing_artifacts" not in llm, f"不应有缺失告警: {llm.get('missing_artifacts')}"
        manifest = {e["path"]: e for e in llm["artifact_manifest"]}
        assert set(manifest) == {"results/summary.csv", "figures/plot.png"}, manifest

        host_dir = (
            Path(settings.storage_path)
            / "users"
            / user_id
            / "workspace"
            / "chat-output"
        )
        sbx_dirs = sorted(host_dir.glob(f"e2e-wp2-sbx-{HEX}-1/output"))
        assert len(sbx_dirs) == 1, f"宿主产物目录未找到: {host_dir}"
        out_dir = sbx_dirs[0]
        for rel, content in (
            ("results/summary.csv", f_summary),
            ("figures/plot.png", f_plot),
        ):
            entry = manifest[rel]
            measured = _sha256sum(out_dir / rel)
            assert entry["sha256"] == measured == sha256(content).hexdigest(), rel
            assert entry["size"] == len(content), rel
        _ok("1a manifest path/size/sha256 与系统 sha256sum 一致", str(sorted(manifest)))

        rows = await conn.fetch(
            "select storage_path, checksum from file_records "
            "where storage_path like $1 order by storage_path",
            f"users/{user_id}/workspace/chat-output/e2e-wp2-sbx-{HEX}-1/%",
        )
        assert len(rows) == 2, f"file_records 应有 2 条新记录: {rows}"
        for row in rows:
            rel = Path(row["storage_path"]).name
            content = dict(summary=f_summary, plot=f_plot)[
                "summary" if rel.endswith(".csv") else "plot"
            ]
            assert row["checksum"] == sha256(content).hexdigest(), row
        _ok("1b 新建 file_records 记录 checksum 列 = 实测 sha256", f"{len(rows)} rows")

        # ===== 场景 2：声明 1 个产物但文件不存在 → missing_artifacts 告警 =====
        log_sink.seek(0)
        log_sink.truncate()
        _install_fakes({"only_real.txt": b"real"})

        result2 = await execute_chat_sandbox(
            {
                "language": "python",
                "code": "（e2e：只产出 1 个文件，但声明 2 个）",
                "artifacts": ["only_real.txt", "results/ghost.csv"],
            },
            user_id,
            session_id=CHAT_SESSION_2,
        )
        assert result2["success"], "登记流程被缺失声明中断"
        llm2 = result2["result"]["llm_payload"]
        ui2 = result2["result"]["ui_payload"]
        assert llm2["missing_artifacts"] == ["results/ghost.csv"], llm2
        assert ui2["missing_artifacts"] == ["results/ghost.csv"], ui2
        # 存在的文件照常出 manifest，主流程不中断
        assert [e["path"] for e in llm2["artifact_manifest"]] == ["only_real.txt"]
        warns = log_sink.getvalue()
        assert "missing_artifacts" in warns and "results/ghost.csv" in warns, warns
        _ok("2a missing_artifacts 进 llm/ui 信封（含声明路径），流程不中断")
        _ok("2b 日志 warn 已打出", warns.strip().splitlines()[-1][:110])

        # ===== 场景 3：归档 README 同时含 MD5 与 sha256，manifest.json 落盘 =====
        from cygnusx.application.services.project_archive_service import archive_studio_run
        from cygnusx.infrastructure.storage import get_path_factory, get_storage_backend

        factory = get_path_factory()
        backend = get_storage_backend()
        run_dir = factory.create_project_run_dir(user_id, PROJECT_NAME, "studio")
        artifact_path = run_dir / "output" / "de.csv"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_bytes(b"gene,log2fc\nA,1.2\n")

        await archive_studio_run(
            user_id=user_id,
            session=SimpleNamespace(title=PROJECT_NAME, sandbox_meta={"image": ""}),
            run_dir=run_dir,
            report=SimpleNamespace(title="E2E 图 v1", status="completed", description=""),
            artifact=SimpleNamespace(name="de.csv", size=artifact_path.stat().st_size),
            factory=factory,
            backend=backend,
            db=None,
        )
        readme = (run_dir / "README.md").read_text(encoding="utf-8")
        expected_md5 = __import__("hashlib").md5(b"gene,log2fc\nA,1.2\n").hexdigest()
        expected_sha = _sha256sum(artifact_path)
        assert expected_md5 in readme, "README 缺 MD5"
        assert expected_sha in readme, "README 缺 sha256"
        _ok("3a 归档 README MD5 与 sha256 并存")

        archive_manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        assert archive_manifest["files"] == [
            {
                "path": "output/de.csv",
                "size": artifact_path.stat().st_size,
                "sha256": expected_sha,
            }
        ], archive_manifest
        snapshot = json.loads((run_dir / "environment.json").read_text(encoding="utf-8"))
        assert snapshot["artifacts"][0]["sha256"] == expected_sha
        assert snapshot["artifacts"][0]["md5"] == expected_md5
        _ok("3b manifest.json（path/size/sha256）落盘且与 sha256sum 一致")

        print("\n== E2E ALL PASSED ==")
    finally:
        logger.remove(sink_id)
        # ===== 清理测试数据 =====
        await conn.execute(
            "delete from file_records where storage_path like $1",
            f"users/%/workspace/chat-output/e2e-wp2-sbx-{HEX}-%",
        )
        users_root = Path(settings.storage_path) / "users"
        for p in users_root.glob(f"*/workspace/chat-output/e2e-wp2-sbx-{HEX}-*"):
            shutil.rmtree(p, ignore_errors=True)
        for p in users_root.glob(f"*/projects/e2e-wp2-{HEX.lower()}"):
            shutil.rmtree(p, ignore_errors=True)
        await conn.close()
        print("== 清理完成 ==")


if __name__ == "__main__":
    asyncio.run(main())
