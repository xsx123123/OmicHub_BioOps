import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from omichub.application.services.agentteams_context_refs import (
    check_context_ref,
    check_context_refs,
)
from omichub.application.services.agentteams_service import AgentTeamsService
from omichub.core.config import Settings


def test_context_ref_classifies_workspace_uri_and_unreadable(tmp_path: Path) -> None:
    readable = tmp_path / "input.fastq"
    readable.write_text("reads", encoding="utf-8")

    checks = check_context_refs(
        [
            {"kind": "file", "location": "input.fastq"},
            {"kind": "artifact", "uri": "s3://bucket/case/result.tsv"},
            {"kind": "file", "id": "file://unregistered"},
        ],
        workspace_root=tmp_path,
    )

    assert [item.category for item in checks] == ["workspace", "uri", "unreadable"]
    assert checks[0].readable is True
    assert checks[1].reason == "s3 URI 有专用产物解析工具"
    assert checks[2].reason == "不支持的 URI 协议: file"


def test_context_ref_distinguishes_missing_path_and_directory(tmp_path: Path) -> None:
    missing = check_context_ref(
        {"kind": "workspace", "location": "missing.tsv"}, workspace_root=tmp_path
    )
    directory = tmp_path / "results"
    directory.mkdir()
    directory_check = check_context_ref(
        {"kind": "workspace", "location": "results"}, workspace_root=tmp_path
    )

    assert missing.reason == "路径不存在"
    assert directory_check.reason == "路径是目录，不是普通文件"


def test_unreadable_context_blocks_plan_item_and_records_event() -> None:
    service = AgentTeamsService(Settings(agentteams_bridge_enabled=True))
    request = AsyncMock(return_value={"event_id": "blocked-1"})
    service._request = request

    asyncio.run(
        service.start_chat_planning(
            case_id="case-1",
            requester_ref="user-1",
            objective="执行分析",
            context_refs=[{"kind": "file", "id": "file://unregistered"}],
        )
    )

    assert request.await_count == 1
    assert request.await_args.args == ("/v1/cases/case-1/evidence",)
    assert request.await_args.kwargs["json"]["event_type"] == "work_item.blocked"
    assert request.await_args.kwargs["json"]["payload"]["references"][0]["reason"] == (
        "不支持的 URI 协议: file"
    )


def test_context_ref_accepts_project_run_protocol_path(tmp_path: Path) -> None:
    run = tmp_path / "projects" / "mouse-sc" / "runs" / "agentteams-case-20260819-120000"
    output = run / "output"
    output.mkdir(parents=True)
    report = output / "delivery-summary.md"
    report.write_text("ok", encoding="utf-8")

    check = check_context_ref(
        {
            "kind": "project",
            "id": "project-1",
            "location": "projects/mouse-sc/runs/agentteams-case-20260819-120000/output/delivery-summary.md",
        },
        workspace_root=tmp_path,
    )

    assert check.readable is True
    assert check.category == "workspace"
