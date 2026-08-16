"""Studio Context Packager 与产物登记服务单元测试（§7.2，fake db）"""

import contextlib
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from omichub.application.services import studio_context_service
from omichub.application.services.agent_service import AgentService
from omichub.application.services.studio_context_service import (
    create_session_from_report,
    import_datahub_file,
    register_artifact_report,
    render_context_pack_hint,
)
from omichub.core.config import get_settings
from omichub.core.exceptions import BusinessError, NotFoundError
from omichub.domain.file.value_objects import FileSource
from omichub.infrastructure.config.storage_config import StorageConfig
from omichub.infrastructure.database.models.chat import ChatSessionModel
from omichub.infrastructure.database.models.report import ReportFileModel, ReportModel
from omichub.infrastructure.database.models.task import TaskModel
from omichub.infrastructure.storage.path_factory import StoragePathFactory
from omichub.infrastructure.storage import reset_storage_backend
from omichub.infrastructure.storage import backend as _storage_backend_module
from omichub.infrastructure.storage import path_factory as _path_factory_module


def _lexists(path: Path) -> bool:
    """同步断言辅助：宿主侧软链悬空时也可见（避免在 async 测试中直接调 os.path）"""
    return os.path.lexists(path)


def _readlink(path: Path) -> str:
    """同步断言辅助：读软链目标（避免在 async 测试中直接调 os）"""
    return os.readlink(path)


class _FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeDb:
    """按 select 实体路由：报告查询返回固定报告，会话查询返回最近 add 的会话。"""

    def __init__(self, *, report: Any = None, task: Any = None, parent: Any = None) -> None:
        self.report = report
        self.task = task
        self.parent = parent
        self.added: list[Any] = []
        self.commits = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        # 真实 flush 会应用列默认值 / server_default，此处手动补齐新会话的默认字段
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        for obj in self.added:
            if isinstance(obj, ChatSessionModel):
                if obj.message_count is None:
                    obj.message_count = 0
                if obj.total_tokens is None:
                    obj.total_tokens = 0
                if obj.title_locked is None:
                    obj.title_locked = False
                if obj.created_at is None:
                    obj.created_at = now
                if obj.updated_at is None:
                    obj.updated_at = now

    async def commit(self) -> None:
        self.commits += 1

    async def execute(self, stmt: Any) -> _FakeResult:
        entity = None
        with contextlib.suppress(Exception):
            entity = stmt.column_descriptions[0].get("entity")
        if entity is ReportModel:
            return _FakeResult(self.report)
        if entity is ChatSessionModel:
            sess = next((o for o in reversed(self.added) if isinstance(o, ChatSessionModel)), None)
            return _FakeResult(sess)
        return _FakeResult(None)

    async def get(self, model: Any, pk: Any) -> Any:
        if model is TaskModel:
            return self.task
        if model is ReportModel:
            return self.parent
        return None


class _FakeManager:
    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace

    def workspace_dir(self, session_id: str) -> Path:
        return self._workspace

    @staticmethod
    def ensure_workspace_dirs(workspace: Path) -> None:
        for sub in ("", "input", "output", "ref", ".logs"):
            (workspace / sub).mkdir(parents=True, exist_ok=True)


@pytest.fixture
def platform_env(tmp_path: Path, monkeypatch):
    uid = str(uuid.uuid4())
    storage = tmp_path / "storage"
    workspace = storage / "studio" / "sess-new"
    monkeypatch.setattr(get_settings(), "storage_path", str(storage))
    monkeypatch.setattr(
        studio_context_service,
        "get_path_factory",
        lambda: StoragePathFactory(StorageConfig(data_root=str(storage), users_subdir="users")),
    )
    test_factory = StoragePathFactory(
        StorageConfig(data_root=str(storage), users_subdir="users")
    )
    monkeypatch.setattr(_path_factory_module, "get_path_factory", lambda: test_factory)
    monkeypatch.setattr(_storage_backend_module, "get_path_factory", lambda: test_factory)
    reset_storage_backend()

    async def ensure_directory_chain_noop(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(
        studio_context_service, "ensure_directory_chain", ensure_directory_chain_noop
    )
    monkeypatch.setattr(studio_context_service, "studio_sandbox_manager", _FakeManager(workspace))
    return storage, uid, workspace


def _make_report(uid: str, storage: Path, *, version: int = 1) -> ReportModel:
    result_dir = storage / "users" / uid / "results" / "task-1"
    result_dir.mkdir(parents=True, exist_ok=True)
    csv_path = result_dir / "de.csv"
    csv_path.write_text("gene,log2fc\nA,1.2\n", encoding="utf-8")
    report_id = uuid.uuid4()
    return ReportModel(
        id=report_id,
        task_id=uuid.uuid4(),
        user_id=uuid.UUID(uid),
        flow_id="rnaseq_deseq2",
        flow_name="RNA-seq 差异分析",
        title="RNA-seq 差异分析 分析报告",
        version=version,
        files=[
            ReportFileModel(
                id=uuid.uuid4(),
                report_id=report_id,
                name="de.csv",
                type="csv",
                size=16,
                path=str(csv_path),
                is_primary=False,
            )
        ],
    )


# ===== render_context_pack_hint =====


@pytest.mark.unit
def test_render_context_pack_hint_contains_source_params_files():
    """渲染结果包含来源流程、参数、文件清单与角色、优化提示"""
    pack = {
        "source": {
            "pipeline": "rnaseq_deseq2",
            "pipeline_name": "RNA-seq 差异分析",
            "run_id": "task-1",
            "params": {"qvalue": 0.05},
            "report_id": "r-1",
            "report_title": "分析报告",
        },
        "files": [
            {"path": "/workspace/input/de.csv", "role": "产物（csv）"},
            {"path": "/workspace/input/index.html", "role": "主报告"},
        ],
        "hint": "用户希望改进。",
    }
    text = render_context_pack_hint(pack)
    assert "RNA-seq 差异分析" in text
    assert "task-1" in text
    assert "qvalue" in text
    assert "/workspace/input/de.csv" in text
    assert "产物（csv）" in text
    assert "优化提示" in text


@pytest.mark.unit
def test_render_context_pack_hint_tolerates_missing_fields():
    """缺字段时不抛异常（防御渲染）"""
    text = render_context_pack_hint({"source": {}, "files": []})
    assert "本次会话来源" in text


@pytest.mark.unit
async def test_import_chat_upload_links_current_user_file(platform_env, monkeypatch):
    """upload:// 聊天附件可安全软链进当前 Studio 工作区。"""
    storage, uid, workspace = platform_env
    upload_id = "74a2448c593a4c9caa19bb2214339c54"
    upload = storage / "users" / uid / "workspace" / "chat-uploads" / f"{upload_id}.treefile"
    upload.parent.mkdir(parents=True, exist_ok=True)
    upload.write_text("(A:1,B:1);\n", encoding="utf-8")
    monkeypatch.setattr(
        studio_context_service,
        "get_user_chat_upload_dir",
        lambda _user_id: upload.parent,
    )

    result = await import_datahub_file(
        uid, "sess-new", f"upload://{upload_id}", "TnpD_treefile", _FakeDb()
    )

    link = workspace / "input" / "TnpD_treefile"
    assert result["sandbox_path"] == "/workspace/input/TnpD_treefile"
    assert result["file_type"] == "chat_upload"
    assert _lexists(link)
    assert _readlink(link) == f"/data/platform/workspace/chat-uploads/{upload_id}.treefile"


@pytest.mark.unit
async def test_import_chat_upload_rejects_non_hex_identifier(platform_env):
    """聊天上传 ID 不得携带路径或任意文件名。"""
    _, uid, _ = platform_env

    with pytest.raises(BusinessError, match="聊天上传 file_id 格式非法"):
        await import_datahub_file(uid, "sess-new", "upload://../secret", None, _FakeDb())


# ===== link_session_file_refs（批量幂等挂载进沙盒工作区） =====


@pytest.mark.unit
async def test_link_session_file_refs_batch_and_idempotent(platform_env, monkeypatch):
    """批量引入多个上传文件；重复引入幂等；非法引用记入 errors 不中断。"""
    from omichub.application.services.studio_context_service import link_session_file_refs

    storage, uid, workspace = platform_env
    up_a = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    up_b = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    upload_dir = storage / "users" / uid / "workspace" / "chat-uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / f"{up_a}.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    (upload_dir / f"{up_b}.csv").write_text("x,y\n3,4\n", encoding="utf-8")
    monkeypatch.setattr(
        studio_context_service, "get_user_chat_upload_dir", lambda _user_id: upload_dir
    )

    refs = [f"upload://{up_a}", f"upload://{up_b}", "upload://does-not-exist"]
    paths, errors = await link_session_file_refs(uid, "sess-new", refs, _FakeDb())

    # name=None 时链接名取文件 basename（{upload_id}.csv）
    assert paths[f"upload://{up_a}"] == f"/workspace/input/{up_a}.csv"
    assert paths[f"upload://{up_b}"] == f"/workspace/input/{up_b}.csv"
    assert "upload://does-not-exist" in errors
    assert "upload://does-not-exist" not in paths

    input_names_before = sorted(os.listdir(workspace / "input"))

    # 再次引入同样的引用：幂等复用，不新增冗余链接
    paths2, errors2 = await link_session_file_refs(uid, "sess-new", refs, _FakeDb())
    assert paths2 == paths
    assert set(errors2) == set(errors)
    input_names_after = sorted(os.listdir(workspace / "input"))
    assert input_names_before == input_names_after


# ===== create_session_from_report =====


@pytest.mark.unit
async def test_create_session_from_report_packs_context(platform_env, monkeypatch):
    """端到端（fake db）：会话创建 + 产物软链 + context_pack 落 sandbox_meta"""
    storage, uid, workspace = platform_env
    report = _make_report(uid, storage)
    task = TaskModel(
        id=report.task_id,
        flow_id="rnaseq_deseq2",
        user_id=uuid.UUID(uid),
        parameters={"qvalue": 0.05, "log2fc": 1.0},
    )
    db = _FakeDb(report=report, task=task)

    agent = SimpleNamespace(
        is_active=True,
        features={"studio": {"image": "omichub-sandbox:base"}},
        model_id=uuid.uuid4(),
        name="可视化助手",
    )

    async def _get_agent(self, agent_id):
        return agent

    monkeypatch.setattr(AgentService, "get_agent", _get_agent)

    dto = await create_session_from_report(uid, report.id, "agent-1", db)

    assert dto.mode == "studio"
    assert dto.title.startswith("优化：")
    session = next(o for o in db.added if isinstance(o, ChatSessionModel))
    pack = session.sandbox_meta["context_pack"]
    assert pack["source"]["pipeline"] == "rnaseq_deseq2"
    assert pack["source"]["run_id"] == str(report.task_id)
    assert pack["source"]["params"] == {"qvalue": 0.05, "log2fc": 1.0}
    assert pack["source"]["report_id"] == str(report.id)
    assert pack["files"][0]["path"] == "/workspace/input/de.csv"
    assert pack["hint"]
    # 报告产物已软链进工作区（数据不搬家）
    link = workspace / "input" / "de.csv"
    assert _lexists(link)
    assert _readlink(link) == "/data/platform/results/task-1/de.csv"
    # 沙盒镜像沿用 Agent studio 配置
    assert session.sandbox_meta["image"] == "omichub-sandbox:base"


@pytest.mark.unit
async def test_create_session_from_report_wrong_user_404(platform_env, monkeypatch):
    """他人报告 → NotFoundError"""
    storage, uid, _ = platform_env
    report = _make_report(str(uuid.uuid4()), storage)  # 属于另一个用户
    db = _FakeDb(report=report)
    with pytest.raises(NotFoundError):
        await create_session_from_report(uid, report.id, "agent-1", db)


# ===== register_artifact_report（服务级补充：父报告缺失退化） =====


@pytest.mark.unit
async def test_register_artifact_parent_missing_degrades_to_v1(platform_env):
    """context_pack 指向的父报告已删除 → 优雅退化为 version=1 无 parent"""
    storage, uid, workspace = platform_env
    artifact = workspace / "output" / "a.png"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"img")
    session = ChatSessionModel(
        id=uuid.uuid4(),
        session_id="sess-new",
        user_id=uid,
        model_id=uuid.uuid4(),
        title="工作台",
        status="active",
        mode="studio",
        sandbox_meta={"context_pack": {"source": {"report_id": str(uuid.uuid4())}}},
    )
    db = _FakeDb(parent=None)  # 父报告已删除

    report, file_model = await register_artifact_report(uid, session, "output/a.png", "图 v1", db)
    assert report.version == 1
    assert report.parent_id is None
    assert file_model.path.endswith("a.png")
    assert db.commits == 1


@pytest.mark.unit
async def test_register_artifact_empty_title_rejected(platform_env):
    _, uid, _ = platform_env
    session = ChatSessionModel(
        id=uuid.uuid4(),
        session_id="sess-new",
        user_id=uid,
        model_id=uuid.uuid4(),
        title="工作台",
        status="active",
        mode="studio",
        sandbox_meta={},
    )
    with pytest.raises(BusinessError):
        await register_artifact_report(uid, session, "output/a.png", "  ", _FakeDb())


@pytest.mark.unit
async def test_register_artifact_report_registers_in_file_records(
    platform_env, monkeypatch: pytest.MonkeyPatch
):
    """artifact_register 登记报告时，产物应同步注册到 file_records（source=STUDIO）。"""
    storage, uid, workspace = platform_env
    artifact = workspace / "output" / "a.png"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"img")
    session = ChatSessionModel(
        id=uuid.uuid4(),
        session_id="sess-new",
        user_id=uid,
        model_id=uuid.uuid4(),
        title="工作台",
        status="active",
        mode="studio",
        sandbox_meta={},
    )
    db = _FakeDb(parent=None)

    fake_file_id = uuid.uuid4()
    calls: list[tuple[object, ...], dict[str, object]] = []

    async def fake_register(*args: object, **kwargs: object) -> SimpleNamespace:
        calls.append((args, kwargs))
        return SimpleNamespace(id=fake_file_id)

    monkeypatch.setattr(studio_context_service.FileRegistry, "register", fake_register)

    report, file_model = await register_artifact_report(
        uid, session, "output/a.png", "图 v1", db
    )

    assert report.version == 1
    assert file_model.path.endswith("a.png")
    assert len(calls) == 1
    _args, kwargs = calls[0]
    assert kwargs.get("source") == FileSource.STUDIO
    assert kwargs.get("directory", "").endswith("/output")
