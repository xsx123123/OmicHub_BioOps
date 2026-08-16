"""Studio P1 平台联动工具单元测试：datahub_import / platform_result_import /
artifact_register / update_plan / pipeline_query（fake db + fake manager）"""

import contextlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

import pytest

from omichub.application.services import studio_context_service, studio_tools
from omichub.application.services.studio_tools import (
    execute_studio_tool,
    normalize_plan_steps,
)
from omichub.core.config import get_settings
from omichub.infrastructure.config.storage_config import StorageConfig
from omichub.infrastructure.database.models.chat import ChatSessionModel
from omichub.infrastructure.database.models.file import FileRecordModel
from omichub.infrastructure.database.models.report import ReportFileModel, ReportModel
from omichub.infrastructure.storage.path_factory import StoragePathFactory


def _lexists(path: Path) -> bool:
    """同步断言辅助：宿主侧软链悬空时也可见（避免在 async 测试中直接调 os.path）"""
    return os.path.lexists(path)


def _readlink(path: Path) -> str:
    """同步断言辅助：读软链目标（避免在 async 测试中直接调 os）"""
    return os.readlink(path)

# ===== 最小替身 =====


class _FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeDb:
    """最小 AsyncSession 替身：按 select 实体路由固定返回值，记录 add 的对象。"""

    def __init__(
        self,
        *,
        file_record: Any = None,
        report: Any = None,
        session: Any = None,
        parent: Any = None,
    ) -> None:
        self.file_record = file_record
        self.report = report
        self.session = session
        self.parent = parent
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def refresh(self, obj: Any) -> None:
        from datetime import datetime

        for attr in ("created_at", "updated_at"):
            if hasattr(obj, attr) and getattr(obj, attr) is None:
                setattr(obj, attr, datetime.now())

    async def commit(self) -> None:
        pass

    async def execute(self, stmt: Any) -> _FakeResult:
        entity = None
        with contextlib.suppress(Exception):
            entity = stmt.column_descriptions[0].get("entity")
        if entity is FileRecordModel:
            return _FakeResult(self.file_record)
        if entity is ReportModel:
            return _FakeResult(self.report)
        if entity is ChatSessionModel:
            return _FakeResult(self.session)
        return _FakeResult(None)

    async def get(self, model: Any, pk: Any) -> Any:
        if model is ReportModel:
            return self.parent
        return None


class _FakeManager:
    """只提供工作区路径能力的 manager 替身（平台联动工具不触沙盒容器）。"""

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
    """settings.storage_path 指向临时存储根 + fake manager 工作区，返回 (storage, uid, workspace)。"""
    uid = str(uuid.uuid4())
    storage = tmp_path / "storage"
    (storage / "users" / uid / "raw").mkdir(parents=True)
    workspace = tmp_path / "ws" / "sess-1"
    monkeypatch.setattr(get_settings(), "storage_path", str(storage))
    monkeypatch.setattr(
        studio_context_service,
        "get_path_factory",
        lambda: StoragePathFactory(
            StorageConfig(data_root=str(storage), users_subdir="users")
        ),
    )
    fake = _FakeManager(workspace)
    monkeypatch.setattr(studio_tools, "studio_sandbox_manager", fake)
    monkeypatch.setattr(studio_context_service, "studio_sandbox_manager", fake)
    return storage, uid, workspace


def _make_file_record(uid: str, name: str = "a.csv", status: str = "active") -> FileRecordModel:
    return FileRecordModel(
        id=uuid.uuid4(),
        user_id=uuid.UUID(uid),
        original_name=name,
        storage_path=f"users/{uid}/raw/{name}",
        size=8,
        file_type="csv",
        status=status,
    )


# ===== datahub_import =====


@pytest.mark.unit
async def test_datahub_import_happy_path(platform_env):
    """正常引入：软链目标为容器内 /data/platform 路径，payload 带沙盒路径与 input 清单"""
    storage, uid, workspace = platform_env
    (storage / "users" / uid / "raw" / "a.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    record = _make_file_record(uid)
    db = _FakeDb(file_record=record)

    result = await execute_studio_tool(
        "datahub_import", {"file_id": str(record.id)}, "sess-1", user_id=uid, db=db
    )

    assert result["success"] is True
    llm = result["result"]["llm_payload"]
    assert llm["sandbox_path"] == "/workspace/input/a.csv"
    assert llm["size"] == 8
    assert llm["file_type"] == "csv"
    assert "/workspace/input/a.csv" in llm["input_files"]
    link = workspace / "input" / "a.csv"
    assert _lexists(link)
    assert _readlink(link) == "/data/platform/raw/a.csv"


@pytest.mark.unit
async def test_datahub_import_dedupes_on_name_collision(platform_env):
    """同名文件第二次引入自动加 " (2)" 后缀"""
    storage, uid, workspace = platform_env
    (storage / "users" / uid / "raw" / "a.csv").write_text("x\n", encoding="utf-8")
    record = _make_file_record(uid)
    db = _FakeDb(file_record=record)

    first = await execute_studio_tool(
        "datahub_import", {"file_id": str(record.id)}, "sess-1", user_id=uid, db=db
    )
    second = await execute_studio_tool(
        "datahub_import", {"file_id": str(record.id)}, "sess-1", user_id=uid, db=db
    )
    assert first["result"]["llm_payload"]["sandbox_path"] == "/workspace/input/a.csv"
    assert second["result"]["llm_payload"]["sandbox_path"] == "/workspace/input/a (2).csv"


@pytest.mark.unit
async def test_datahub_import_wrong_user_rejected(platform_env):
    """他人文件（查询按 user_id 过滤命中为空）→ 友好错误"""
    _, uid, _ = platform_env
    db = _FakeDb(file_record=None)  # user_id 过滤后查不到
    result = await execute_studio_tool(
        "datahub_import", {"file_id": str(uuid.uuid4())}, "sess-1", user_id=uid, db=db
    )
    assert result["success"] is False
    assert "不存在或无权访问" in result["result"]["llm_payload"]["error"]


@pytest.mark.unit
async def test_datahub_import_inactive_rejected(platform_env):
    """非 active 状态文件拒绝引入"""
    _, uid, _ = platform_env
    record = _make_file_record(uid, status="archived")
    db = _FakeDb(file_record=record)
    result = await execute_studio_tool(
        "datahub_import", {"file_id": str(record.id)}, "sess-1", user_id=uid, db=db
    )
    assert result["success"] is False
    assert "archived" in result["result"]["llm_payload"]["error"]


@pytest.mark.unit
async def test_datahub_import_missing_physical_file_rejected(platform_env):
    """记录在但磁盘文件丢失 → 友好错误"""
    _, uid, _ = platform_env
    record = _make_file_record(uid)
    db = _FakeDb(file_record=record)
    result = await execute_studio_tool(
        "datahub_import", {"file_id": str(record.id)}, "sess-1", user_id=uid, db=db
    )
    assert result["success"] is False
    assert "已丢失" in result["result"]["llm_payload"]["error"]


@pytest.mark.unit
async def test_datahub_import_requires_db_and_user(platform_env):
    """缺 db / user_id 的调用方式（如裸跑）→ 友好错误而非异常"""
    result = await execute_studio_tool("datahub_import", {"file_id": str(uuid.uuid4())}, "sess-1")
    assert result["success"] is False
    assert "数据库上下文" in result["result"]["llm_payload"]["error"]


# ===== POST /studio/sessions/{id}/import（datahub_import 的 REST 入口） =====


@pytest.mark.unit
async def test_import_endpoint_happy_path(platform_env):
    """REST 引入：与工具同一服务路径，响应含沙盒路径与 input 清单"""
    from omichub.api.v1.studio import import_data_file
    from omichub.application.schemas.studio import ImportStudioDataFileRequest
    from omichub.application.services.chat_service import ChatService

    storage, uid, workspace = platform_env
    (storage / "users" / uid / "raw" / "a.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    record = _make_file_record(uid)
    session = _make_studio_session(uid, None)
    db = _FakeDb(file_record=record, session=session)

    resp = await import_data_file(
        uid,
        ChatService(db),
        db,
        "sess-1",
        ImportStudioDataFileRequest(file_id=str(record.id)),
    )

    assert resp.sandbox_path == "/workspace/input/a.csv"
    assert resp.name == "a.csv"
    assert resp.size == 8
    assert resp.file_type == "csv"
    assert resp.input_files == ["/workspace/input/a.csv"]
    assert _readlink(workspace / "input" / "a.csv") == "/data/platform/raw/a.csv"


@pytest.mark.unit
async def test_import_endpoint_wrong_user_rejected(platform_env):
    """他人文件 → NotFoundError（与工具一致，不泄露存在性）"""
    from omichub.api.v1.studio import import_data_file
    from omichub.application.schemas.studio import ImportStudioDataFileRequest
    from omichub.application.services.chat_service import ChatService
    from omichub.core.exceptions import NotFoundError

    _, uid, _ = platform_env
    session = _make_studio_session(uid, None)
    db = _FakeDb(file_record=None, session=session)  # user_id 过滤后查不到

    with pytest.raises(NotFoundError):
        await import_data_file(
            uid,
            ChatService(db),
            db,
            "sess-1",
            ImportStudioDataFileRequest(file_id=str(uuid.uuid4())),
        )


@pytest.mark.unit
async def test_import_endpoint_rejects_non_studio_session(platform_env):
    """非 studio 会话 → 404（不泄露会话存在性）"""
    from omichub.api.v1.studio import import_data_file
    from omichub.application.schemas.studio import ImportStudioDataFileRequest
    from omichub.application.services.chat_service import ChatService
    from omichub.core.exceptions import NotFoundError

    _, uid, _ = platform_env
    session = _make_studio_session(uid, None)
    session.mode = "chat"
    db = _FakeDb(session=session)

    with pytest.raises(NotFoundError):
        await import_data_file(
            uid,
            ChatService(db),
            db,
            "sess-1",
            ImportStudioDataFileRequest(file_id=str(uuid.uuid4())),
        )


# ===== platform_result_import =====


@pytest.mark.unit
async def test_platform_result_import_links_report_files(platform_env):
    """报告产物全部软链进 input/，payload 含角色与沙盒路径"""
    storage, uid, workspace = platform_env
    result_dir = storage / "users" / uid / "results" / "task-1"
    result_dir.mkdir(parents=True)
    csv_path = result_dir / "de.csv"
    csv_path.write_text("gene,log2fc\nA,1.2\n", encoding="utf-8")
    report = ReportModel(
        id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        user_id=uuid.UUID(uid),
        flow_id="rnaseq",
        flow_name="RNA-seq",
        title="RNA-seq 分析报告",
        files=[
            ReportFileModel(
                id=uuid.uuid4(),
                report_id=uuid.uuid4(),
                name="de.csv",
                type="csv",
                size=16,
                path=str(csv_path),
                is_primary=False,
            )
        ],
    )
    db = _FakeDb(report=report)

    result = await execute_studio_tool(
        "platform_result_import", {"report_id": str(report.id)}, "sess-1", user_id=uid, db=db
    )

    assert result["success"] is True
    llm = result["result"]["llm_payload"]
    assert llm["title"] == "RNA-seq 分析报告"
    assert llm["imported"][0]["sandbox_path"] == "/workspace/input/de.csv"
    assert _lexists(workspace / "input" / "de.csv")
    assert _readlink(workspace / "input" / "de.csv") == "/data/platform/results/task-1/de.csv"


@pytest.mark.unit
async def test_platform_result_import_wrong_user_rejected(platform_env):
    _, uid, _ = platform_env
    db = _FakeDb(report=None)
    result = await execute_studio_tool(
        "platform_result_import", {"report_id": str(uuid.uuid4())}, "sess-1", user_id=uid, db=db
    )
    assert result["success"] is False
    assert "不存在或无权访问" in result["result"]["llm_payload"]["error"]


# ===== artifact_register =====


def _make_studio_session(uid: str, parent_id: uuid.UUID | None) -> ChatSessionModel:
    sandbox_meta: dict[str, Any] = {"image": "omichub-sandbox:bio"}
    if parent_id is not None:
        sandbox_meta["context_pack"] = {"source": {"report_id": str(parent_id)}}
    return ChatSessionModel(
        id=uuid.uuid4(),
        session_id="sess-1",
        user_id=uid,
        model_id=uuid.uuid4(),
        title="工作台",
        status="active",
        mode="studio",
        sandbox_meta=sandbox_meta,
    )


@pytest.mark.unit
async def test_artifact_register_versions_from_context_pack(platform_env):
    """context_pack 指向 v2 父报告 → 新报告 version=3 且 parent_id 挂接"""
    storage, uid, workspace = platform_env
    artifact = workspace / "output" / "volcano_v2.png"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"png-bytes")

    parent_id = uuid.uuid4()
    parent = ReportModel(
        id=parent_id, task_id=uuid.uuid4(), user_id=uuid.UUID(uid), flow_id="rnaseq", version=2
    )
    session = _make_studio_session(uid, parent_id)
    db = _FakeDb(session=session, parent=parent)

    result = await execute_studio_tool(
        "artifact_register",
        {"path": "output/volcano_v2.png", "title": "火山图 v3", "description": "调配色"},
        "sess-1",
        user_id=uid,
        db=db,
    )

    assert result["success"] is True
    llm = result["result"]["llm_payload"]
    assert llm["version"] == 3
    assert llm["parent_id"] == str(parent_id)
    # 产物已复制进报告中心存储区（工作区清理后仍存续）
    # 新路径归置到 projects/{title}/runs/studio-{timestamp}/output/ 下
    copied_candidates = list(
        (storage / "users" / uid / "projects").rglob("volcano_v2.png")
    )
    assert len(copied_candidates) == 1
    copied = copied_candidates[0]
    assert copied.read_bytes() == b"png-bytes"
    # 报告与文件行均已入库（add 到会话）
    report_row = next(o for o in db.added if isinstance(o, ReportModel))
    assert report_row.flow_id == "studio" and report_row.flow_name == "OmicStudio"
    assert report_row.status == "completed"
    file_row = next(o for o in db.added if isinstance(o, ReportFileModel))
    assert file_row.type == "png" and file_row.path == str(copied)


@pytest.mark.unit
async def test_artifact_register_without_context_pack_is_v1(platform_env):
    """无 context_pack（自由分析会话）→ version=1 且无 parent"""
    _, uid, workspace = platform_env
    artifact = workspace / "output" / "pca.png"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"img")
    session = _make_studio_session(uid, None)
    db = _FakeDb(session=session)

    result = await execute_studio_tool(
        "artifact_register",
        {"path": "output/pca.png", "title": "PCA 聚类图"},
        "sess-1",
        user_id=uid,
        db=db,
    )
    llm = result["result"]["llm_payload"]
    assert result["success"] is True
    assert llm["version"] == 1
    assert llm["parent_id"] is None


@pytest.mark.unit
async def test_artifact_register_rejects_non_output_path(platform_env):
    """path 必须落在 output/ 内（守卫拦截 input/ 下的文件）"""
    _, uid, _ = platform_env
    session = _make_studio_session(uid, None)
    db = _FakeDb(session=session)
    result = await execute_studio_tool(
        "artifact_register",
        {"path": "input/a.csv", "title": "x"},
        "sess-1",
        user_id=uid,
        db=db,
    )
    assert result["success"] is False
    assert "产物目录" in result["result"]["llm_payload"]["error"]


# ===== update_plan =====


@pytest.mark.unit
def test_normalize_plan_steps_happy():
    steps, error = normalize_plan_steps(
        {"steps": [{"title": "加载数据", "status": "in_progress"}, {"title": "画图", "status": "pending"}]}
    )
    assert error is None
    assert steps == [
        {"title": "加载数据", "status": "in_progress"},
        {"title": "画图", "status": "pending"},
    ]


@pytest.mark.unit
def test_normalize_plan_steps_invalid():
    assert normalize_plan_steps({})[1] is not None  # steps 缺失
    assert normalize_plan_steps({"steps": []})[1] is not None  # 空计划
    assert normalize_plan_steps({"steps": [{"status": "pending"}]})[1] is not None  # 缺 title
    steps, _ = normalize_plan_steps({"steps": [{"title": "x", "status": "weird"}]})
    assert steps[0]["status"] == "pending"  # 非法 status 宽容降级


@pytest.mark.unit
async def test_update_plan_fallback_executor_echoes():
    """兜底执行器（未经 chat_service 拦截的直接调用）校验并回显"""
    result = await execute_studio_tool(
        "update_plan",
        {"steps": [{"title": f"步骤{i}", "status": "pending"} for i in range(3)]},
        "sess-1",
    )
    assert result["success"] is True
    assert len(result["result"]["llm_payload"]["steps"]) == 3
    bad = await execute_studio_tool("update_plan", {"steps": "not-a-list"}, "sess-1")
    assert bad["success"] is False


# ===== pipeline_query =====


@pytest.mark.unit
async def test_pipeline_query_returns_catalog():
    """返回平台流程 + 工具只读目录，体积受限"""
    result = await execute_studio_tool("pipeline_query", {}, "sess-1")
    assert result["success"] is True
    llm = result["result"]["llm_payload"]
    assert isinstance(llm["flows"], list) and isinstance(llm["tools"], list)
    assert len(json.dumps(llm, ensure_ascii=False)) <= 6500


@pytest.mark.unit
async def test_pipeline_query_keyword_filter():
    """关键词过滤：不匹配条目不出现"""
    result = await execute_studio_tool("pipeline_query", {"query": "zzz-不存在的词"}, "sess-1")
    assert result["success"] is True
    llm = result["result"]["llm_payload"]
    assert llm["flows"] == [] and llm["tools"] == []

# ===== POST /studio/sessions/{id}/files/edit（workspace_edit 回滚入口） =====


@pytest.mark.unit
async def test_edit_endpoint_forwards_exact_replacement(monkeypatch):
    from omichub.api.v1.studio import edit_workspace_file
    from omichub.application.schemas.studio import EditStudioFileRequest

    uid = str(uuid.uuid4())
    session = _make_studio_session(uid, None)
    session.session_id = "sess-edit"

    class _Service:
        async def get_session(self, session_id: str, user_id: str):
            assert session_id == "sess-edit"
            assert user_id == uid
            return session

    class _Manager:
        def __init__(self):
            self.call = None

        async def edit_file(self, *args, **kwargs):
            self.call = (args, kwargs)
            return {"path": "scripts/a.py", "diff": "--- a\n+++ b\n", "size": 3}

    manager = _Manager()
    monkeypatch.setattr("omichub.api.v1.studio.studio_sandbox_manager", manager)

    response = await edit_workspace_file(
        uid,
        _Service(),
        "sess-edit",
        EditStudioFileRequest(path="scripts/a.py", old_string="new", new_string="old"),
    )

    assert response.path == "scripts/a.py"
    assert response.diff == "--- a\n+++ b\n"
    assert manager.call[0][:4] == ("sess-edit", "scripts/a.py", "new", "old")
    assert manager.call[1]["user_id"] == uid


@pytest.mark.unit
async def test_edit_endpoint_rejects_non_studio_session(monkeypatch):
    from omichub.api.v1.studio import edit_workspace_file
    from omichub.application.schemas.studio import EditStudioFileRequest
    from omichub.core.exceptions import NotFoundError

    uid = str(uuid.uuid4())
    session = _make_studio_session(uid, None)
    session.mode = "chat"

    class _Service:
        async def get_session(self, session_id: str, user_id: str):
            return session

    with pytest.raises(NotFoundError):
        await edit_workspace_file(
            uid,
            _Service(),
            "sess-edit",
            EditStudioFileRequest(path="a.py", old_string="new", new_string="old"),
        )


# ===== PUT /studio/sessions/{id}/files/write（工作区编辑器整文件保存） =====


@pytest.mark.unit
async def test_save_endpoint_writes_complete_script(monkeypatch):
    from omichub.api.v1.studio import save_workspace_file
    from omichub.application.schemas.studio import SaveStudioFileRequest

    uid = str(uuid.uuid4())
    session = _make_studio_session(uid, None)
    session.session_id = "sess-save"

    class _Service:
        async def get_session(self, session_id: str, user_id: str):
            assert session_id == "sess-save"
            assert user_id == uid
            return session

    class _Manager:
        def __init__(self):
            self.call = None

        async def write_file(self, *args, **kwargs):
            self.call = (args, kwargs)
            return {"path": "scripts/hello.py", "size": 15}

    manager = _Manager()
    monkeypatch.setattr("omichub.api.v1.studio.studio_sandbox_manager", manager)

    response = await save_workspace_file(
        uid,
        _Service(),
        "sess-save",
        SaveStudioFileRequest(path="scripts/hello.py", content="print('hello')\n"),
    )

    assert response.path == "scripts/hello.py"
    assert response.size == 15
    assert manager.call[0][:3] == ("sess-save", "scripts/hello.py", "print('hello')\n")
    assert manager.call[1]["user_id"] == uid


@pytest.mark.unit
async def test_save_endpoint_rejects_non_studio_session(monkeypatch):
    from omichub.api.v1.studio import save_workspace_file
    from omichub.application.schemas.studio import SaveStudioFileRequest
    from omichub.core.exceptions import NotFoundError

    uid = str(uuid.uuid4())
    session = _make_studio_session(uid, None)
    session.mode = "chat"

    class _Service:
        async def get_session(self, session_id: str, user_id: str):
            return session

    with pytest.raises(NotFoundError):
        await save_workspace_file(
            uid,
            _Service(),
            "sess-save",
            SaveStudioFileRequest(path="scripts/hello.py", content="print('hello')\n"),
        )
