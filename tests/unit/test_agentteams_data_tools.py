from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.schemas.tool_invocation import ToolInvocationContext
from cygnusx.application.services.agentteams_data_tool_service import AgentTeamsDataToolService
from cygnusx.application.services.agentteams_quality_gate_service import (
    AgentTeamsQualityGateService,
)
from cygnusx.application.services.pipeline_result_service import PipelineResultService
from cygnusx.core.exceptions import ValidationError
from cygnusx.infrastructure.config.storage_config import StorageConfig
from cygnusx.infrastructure.storage import LocalStorageBackend
from cygnusx.infrastructure.storage.minio_store import ObjectMeta
from cygnusx.infrastructure.storage.path_factory import StoragePathFactory
from cygnusx.tools.schema_loader import ToolsSchemaLoader

USER_ID = "00000000-0000-0000-0000-000000000001"
TASK_ID = "00000000-0000-0000-0000-000000000002"


class _Rows:
    def all(self):
        return []


class _Db(AsyncSession):
    def __init__(self):
        pass

    async def scalars(self, _statement):
        return _Rows()


def _context() -> ToolInvocationContext:
    return ToolInvocationContext(user_id=USER_ID, session_id="case-1", db=_Db())


@pytest.mark.asyncio
async def test_task_summary_reads_qc_metrics_and_artifacts(tmp_path, monkeypatch) -> None:
    run_root = tmp_path / "users" / USER_ID / "projects" / "demo" / "runs" / "run-1"
    work_dir = run_root / "work"
    output_dir = run_root / "output"
    work_dir.mkdir(parents=True)
    output_dir.mkdir()
    (output_dir / "qc_summary.json").write_text(
        '{"mapping_rate": 30, "q30_pct": 91, "duplicate_rate": 0.2}', encoding="utf-8"
    )
    (output_dir / "result.tsv").write_text("gene\tvalue\nA\t1\n", encoding="utf-8")

    class Factory:
        def __init__(self):
            self.data_root = tmp_path

        def projects_dir(self, user_id):
            return tmp_path / "users" / user_id / "projects"

        def task_dir(self, user_id, task_id):
            return tmp_path / "users" / user_id / "tasks" / task_id

        def relative_to_root(self, path):
            return str(path.resolve().relative_to(self.data_root.resolve()))

    monkeypatch.setattr(
        "cygnusx.application.services.pipeline_result_service.get_path_factory", lambda: Factory()
    )
    path_factory = StoragePathFactory(
        StorageConfig(data_root=str(tmp_path), users_subdir="users")
    )
    backend = LocalStorageBackend(path_factory=path_factory)
    task = SimpleNamespace(
        flow_id="rna_seq",
        status="success",
        parameters={},
        progress=1.0,
        work_dir=str(work_dir),
        result_path=str(output_dir),
        error_message="",
    )
    with patch(
        "cygnusx.application.services.pipeline_result_service.TaskService.get_task",
        new_callable=AsyncMock,
        return_value=task,
    ):
        summary = await PipelineResultService(_context(), backend=backend).get_task_summary(TASK_ID)

    assert summary["metrics"] == {"mapping_rate": 0.3, "q30": 0.91, "duplicate_rate": 0.2}
    assert {item["path"] for item in summary["artifacts"]} == {
        "output/qc_summary.json",
        "output/result.tsv",
    }


@pytest.mark.asyncio
async def test_task_file_preview_rejects_traversal_and_symlink(tmp_path, monkeypatch) -> None:
    root = tmp_path / "task"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    (root / "link.txt").symlink_to(outside)

    path_factory = StoragePathFactory(
        StorageConfig(data_root=str(tmp_path), users_subdir="users")
    )
    monkeypatch.setattr(
        "cygnusx.application.services.pipeline_result_service.get_path_factory",
        lambda: path_factory,
    )
    backend = LocalStorageBackend(path_factory=path_factory)
    service = PipelineResultService(_context(), backend=backend)

    with pytest.raises(ValidationError):
        await service._resolve_preview_path(root, "../secret.txt")
    with pytest.raises(ValidationError):
        await service._resolve_preview_path(root, "link.txt")


@pytest.mark.asyncio
async def test_workspace_preview_is_requester_scoped(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / USER_ID / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "notes.txt").write_text("verified evidence", encoding="utf-8")

    class Factory:
        data_root = tmp_path

        def user_root(self, user_id):
            return tmp_path / user_id

        def workspace_dir(self, user_id):
            return tmp_path / user_id / "workspace"

        def relative_to_root(self, path):
            return str(path.resolve().relative_to(self.data_root.resolve()))

    factory = Factory()
    monkeypatch.setattr(
        "cygnusx.infrastructure.storage.path_factory.get_path_factory",
        lambda: factory,
    )
    monkeypatch.setattr(
        "cygnusx.application.services.pipeline_result_service.get_path_factory",
        lambda: factory,
    )
    monkeypatch.setattr(
        "cygnusx.application.services.agentteams_data_tool_service.get_path_factory",
        lambda: factory,
    )
    from cygnusx.infrastructure.storage import reset_storage_backend

    reset_storage_backend()
    backend = LocalStorageBackend(path_factory=factory)
    monkeypatch.setattr(
        "cygnusx.application.services.pipeline_result_service.get_storage_backend",
        lambda: backend,
    )
    service = AgentTeamsDataToolService()
    result = await service.workspace_file_preview(
        user_id=USER_ID, path="workspace/notes.txt", context=_context()
    )
    assert result["content"] == "verified evidence"

    with pytest.raises(ValidationError):
        await service.workspace_file_preview(
            user_id="00000000-0000-0000-0000-000000000003",
            path="workspace/notes.txt",
            context=_context(),
        )


def test_mapping_rate_thirty_percent_is_blocked() -> None:
    result = AgentTeamsQualityGateService().evaluate(
        "rna_seq", {"mapping_rate": 0.30, "q30": 0.91, "duplicate_rate": 0.20}
    )
    assert result["decision"] == "BLOCKED"
    assert result["audit_event"] == {
        "event_type": "quality.hard_gate",
        "decision": "BLOCKED",
        "reason": "mapping_rate 30.0% 低于阈值 70.0%",
        "metric": "mapping_rate",
        "value": 0.3,
        "threshold": 0.7,
        "flow_id": "rna_seq",
        "rule_version": "1.0.0",
    }


def test_agentteams_evidence_tools_are_registered_read_only() -> None:
    loader = ToolsSchemaLoader("tool_configs/tools_schema.yaml")
    for name in (
        "task_result_summary",
        "task_file_preview",
        "workspace_file_preview",
        "artifact_fetch",
        "task_compare_metrics",
        "rule_threshold_lookup",
    ):
        schema = loader.get_tool(name)
        assert schema is not None
        assert schema.annotations.read_only_hint is True
        assert schema.requires_confirm is False


def test_artifact_fetch_downloads_owned_case_object(tmp_path) -> None:
    class CaseService:
        async def get_case(self, case_id: str, requester_ref: str):
            assert case_id == "case-1"
            assert requester_ref == USER_ID
            return {"case_id": case_id, "requester_ref": requester_ref}

    class Store:
        bucket = "agentteams-evidence"

        def list_case_objects(self, case_id: str):
            return [ObjectMeta(key="work-1/result.csv", size_bytes=7)]

        def fetch_case_object(self, case_id: str, key: str, destination):
            destination.write_bytes(b"a,b\n1,2")
            return destination

    class Telemetry:
        async def record_artifact_fetch(self, *, size_bytes: int):
            assert size_bytes == 7

    service = AgentTeamsDataToolService(
        case_service=CaseService(), minio_store=Store(), telemetry_service=Telemetry()
    )
    context = _context()
    context.extra["workdir"] = str(tmp_path)
    result = asyncio.run(
        service.artifact_fetch(
            user_id=USER_ID,
            case_id="case-1",
            artifact_ref="s3://agentteams-evidence/case-1/work-1/result.csv",
            context=context,
        )
    )

    assert result == {
        "local_path": str(tmp_path / "result.csv"),
        "size_bytes": 7,
        "sha256": hashlib.sha256(b"a,b\n1,2").hexdigest(),
    }


class _RoomDb(_Db):
    """scalar 返回 None：房间不存在，用于验证访问校验之后的分支。"""

    async def scalar(self, _statement):
        return None


def _room_service() -> AgentTeamsDataToolService:
    return AgentTeamsDataToolService(
        case_service=SimpleNamespace(), minio_store=SimpleNamespace()
    )


@pytest.mark.asyncio
async def test_room_messages_read_accepts_namespace_prefixed_room_id() -> None:
    """Agent 上下文中可见的房间标识是命名空间 case_id（room-<id>），
    与绑定 room_id 指向同一房间，不应误判为越权。"""
    bound = "d027d5a12c8e4bb09ff1102e44a9b07b"
    context = ToolInvocationContext(user_id=USER_ID, session_id="s-1", db=_RoomDb())
    context.extra["room_id"] = bound
    with pytest.raises(ValidationError, match="ROOM_NOT_FOUND"):
        await _room_service().room_messages_read(
            user_id=USER_ID, room_id=f"room-{bound}", context=context
        )


@pytest.mark.asyncio
async def test_room_messages_read_rejects_other_room_id() -> None:
    context = ToolInvocationContext(user_id=USER_ID, session_id="s-1", db=_RoomDb())
    context.extra["room_id"] = "d027d5a12c8e4bb09ff1102e44a9b07b"
    with pytest.raises(ValidationError, match="ROOM_ACCESS_DENIED"):
        await _room_service().room_messages_read(
            user_id=USER_ID, room_id="room-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", context=context
        )


@pytest.mark.asyncio
async def test_room_facts_query_accepts_namespace_prefixed_room_id() -> None:
    bound = "d027d5a12c8e4bb09ff1102e44a9b07b"
    context = ToolInvocationContext(user_id=USER_ID, session_id="s-1", db=_RoomDb())
    context.extra["room_id"] = bound
    with pytest.raises(ValidationError, match="ROOM_NOT_FOUND"):
        await _room_service().room_facts_query(
            user_id=USER_ID, room_id=f"room-{bound}", context=context
        )


@pytest.mark.asyncio
async def test_room_messages_read_paginates_to_latest_events() -> None:
    """Bridge 事件流为 oldest-first 分页；房间流中 agent_stream 等高频事件
    占满首页后，最新消息在后续页，必须沿 next_cursor 翻到流末尾。"""
    bound = "d027d5a12c8e4bb09ff1102e44a9b07b"
    room = SimpleNamespace(room_id=bound, owner_id=USER_ID, case_id=None)

    class RoomDb(_Db):
        async def scalar(self, _statement):
            return room

    class CaseService:
        async def get_case_events(self, case_id, requester_ref, *, cursor=None, limit=100):
            assert case_id == f"room-{bound}"
            assert requester_ref == USER_ID
            if cursor is None:
                return {
                    "events": [
                        {
                            "event_id": "e1",
                            "event_type": "room.user_message",
                            "recorded_at": "2026-08-26T12:31:44+00:00",
                            "payload": {"content": "hi"},
                        },
                        {
                            "event_id": "s1",
                            "event_type": "room.agent_stream",
                            "recorded_at": "2026-08-26T12:31:50+00:00",
                            "payload": {"content": "<delta>"},
                        },
                    ],
                    "next_cursor": "s1",
                }
            assert cursor == "s1"
            return {
                "events": [
                    {
                        "event_id": "e2",
                        "event_type": "room.agent_message",
                        "recorded_at": "2026-08-26T12:32:10+00:00",
                        "payload": {"content": "单细胞专家的回复", "agent_id": "agent-scrna"},
                    }
                ],
                "next_cursor": None,
            }

    service = AgentTeamsDataToolService(
        case_service=CaseService(), minio_store=SimpleNamespace()
    )
    context = ToolInvocationContext(user_id=USER_ID, session_id="s-1", db=RoomDb())
    context.extra["room_id"] = bound
    result = await service.room_messages_read(user_id=USER_ID, context=context)

    assert [message["content"] for message in result["messages"]] == [
        "hi",
        "单细胞专家的回复",
    ]
    assert result["messages"][1]["agent_id"] == "agent-scrna"
    assert result["scan_truncated"] is False
