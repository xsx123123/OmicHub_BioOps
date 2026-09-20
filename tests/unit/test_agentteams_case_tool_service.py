"""聊天协作 Case 工具的安全边界测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from cygnusx.application.services.agent_service import AgentService
from cygnusx.application.services.agentteams_case_tool_service import (
    AgentTeamsCaseToolService,
    agentteams_next_actor,
)
from cygnusx.core.exceptions import BusinessError


@pytest.mark.parametrize("agent_file", ["code.yaml", "viz.yaml", "scrna.yaml"])
def test_specialist_agents_expose_agentteams_case_creation_tool(agent_file: str) -> None:
    from pathlib import Path

    import yaml

    config_path = Path(__file__).parents[2] / "data" / "ai" / agent_file
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert "agentteams_case" in config["tool_packs"]


def test_case_tool_contract_is_confirmed_and_idempotent() -> None:
    from cygnusx.tools.schema_loader import schema_loader

    schema = schema_loader.get_tool("create_agentteams_case")

    assert schema is not None
    assert schema.requires_confirm is True
    assert schema.annotations.idempotent is True
    assert schema.extra["control_tool"] == "agentteams_case"
    assert schema.input_schema["required"] == ["objective", "project_id", "flow_id"]
    assert "origin_consultation_id" in schema.input_schema["properties"]
    assert "consultation_summary" in schema.input_schema["properties"]


def test_session_project_ownership_accepts_only_bound_project() -> None:
    service = AgentTeamsCaseToolService()

    assert service._session_owns_project({"project_ref": {"kind": "project", "id": "p-1"}}, "p-1")
    assert not service._session_owns_project(
        {"project_ref": {"kind": "project", "id": "p-1"}}, "p-2"
    )


def test_idempotency_record_reuses_recent_case_without_objective_storage() -> None:
    service = AgentTeamsCaseToolService()
    meta: dict[str, object] = {}
    service._bind_case(meta, "hash", "case-1", "交付目标", "received")

    reused = service._get_recent_case(meta, "hash")

    assert reused == {"case_id": "case-1", "title": "交付目标", "status": "received"}
    idempotency = meta["agentteams_case_idempotency"]
    assert isinstance(idempotency, dict)
    record: dict[str, Any] = idempotency["hash"]
    assert "objective" not in record
    assert meta["execution_mode"] == "cluster_case"
    routing: dict[str, Any] = meta["execution_routing"]
    assert routing["case_id"] == "case-1"
    assert routing["reason"] == "user_confirmed_agentteams_case"


def test_sample_context_references_reject_raw_like_missing_reference() -> None:
    with pytest.raises(BusinessError, match="kind 和 id"):
        AgentTeamsCaseToolService._safe_refs([{"kind": "sample"}])

    assert AgentTeamsCaseToolService._safe_refs([{"kind": "sample", "id": "sample-1"}]) == [
        {"kind": "sample", "id": "sample-1"}
    ]


def test_chat_entry_switch_hides_case_tool_from_model() -> None:
    tools = [
        {"function": {"name": "workspace_read"}},
        {"function": {"name": "create_agentteams_case"}},
    ]

    filtered = AgentService._filter_runtime_builtin_tools(
        tools, agentteams_chat_entry_enabled=False
    )

    assert [tool["function"]["name"] for tool in filtered] == ["workspace_read"]


def test_case_tool_system_prompt_suffix_is_only_added_when_available() -> None:
    tools = [{"function": {"name": "create_agentteams_case"}}]

    assert AgentService._has_builtin_tool(tools, "create_agentteams_case")
    assert not AgentService._has_builtin_tool(tools, "parallel_subagents")


def test_chat_case_flow_whitelist_defaults_and_parsing() -> None:
    assert AgentTeamsCaseToolService._allowed_flows("rna_seq, atac_seq, rna_seq") == {
        "rna_seq",
        "atac_seq",
    }


def test_quality_running_is_assigned_to_quality_auditor() -> None:
    assert agentteams_next_actor("quality_running") == "quality-auditor"


def test_consultation_source_is_normalized_and_bounded() -> None:
    source = AgentTeamsCaseToolService._consultation_source(
        "  consult-001  ",
        "  建议先核验样本质量，\n再确认差异分析设计。  ",
    )

    assert source == {
        "origin_consultation_id": "consult-001",
        "consultation_summary": "建议先核验样本质量， 再确认差异分析设计。",
    }
    assert AgentTeamsCaseToolService._consultation_source(None, None) == {
        "origin_consultation_id": None,
        "consultation_summary": None,
    }


@pytest.mark.asyncio
async def test_case_creation_requires_a_user_confirmation_after_card() -> None:
    class FakeDb:
        async def scalar(self, _query):
            return None

    context = SimpleNamespace(db=FakeDb(), session_id="session-1")
    meta = {
        "agentteams_case_confirmation": {"key": {"requested_at": datetime.now(UTC).isoformat()}}
    }

    with pytest.raises(BusinessError, match="用户在确认卡上确认"):
        await AgentTeamsCaseToolService._require_pending_confirmation(context, meta, "key")


@pytest.mark.parametrize(
    "content",
    [
        "确认创建",
        "同意",
        "取消",
        "不用了",
        "换个方案",
    ],
)
def test_case_confirmation_rejects_unstructured_text_reply(content: str) -> None:
    message = SimpleNamespace(content=content, metadata_json={})

    assert not AgentTeamsCaseToolService._is_explicit_confirmation_message(
        message, "key", {"token": "random-token"}
    )


def test_case_confirmation_accepts_matching_structured_marker() -> None:
    message = SimpleNamespace(
        content="取消",
        metadata_json={
            "agentteams_case_confirmation": {
                "key": "key",
                "token": "random-token",
                "confirmed": True,
            }
        },
    )

    assert AgentTeamsCaseToolService._is_explicit_confirmation_message(
        message, "key", {"token": "random-token"}
    )


def test_case_confirmation_rejects_mismatched_structured_token() -> None:
    message = SimpleNamespace(
        content="确认创建",
        metadata_json={
            "agentteams_case_confirmation": {
                "key": "key",
                "token": "wrong-token",
                "confirmed": True,
            }
        },
    )

    assert not AgentTeamsCaseToolService._is_explicit_confirmation_message(
        message, "key", {"token": "random-token"}
    )
