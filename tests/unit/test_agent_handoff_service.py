"""Agent Handoff 无数据库协议测试。"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from omichub.application.services.agent_handoff_service import (
    MAX_HANDOFF_PACKET_BYTES,
    AgentHandoffService,
    extract_handoff_directive,
)
from omichub.application.services.agent_service import AgentService, render_persona_system_prompt
from omichub.core.exceptions import BusinessError
from omichub.infrastructure.database.models.agent import AgentTemplateModel
from omichub.infrastructure.database.models.chat import ChatSessionModel


def test_runtime_communication_contract_applies_to_every_standard_agent() -> None:
    agent = AgentTemplateModel(agent_id="agent-custom", name="自定义专家", is_active=True)

    prompt = AgentService._append_communication_contract("原始提示词", agent)

    assert prompt.startswith("原始提示词")
    assert "平台沟通与执行规范" in prompt
    assert "自己在助手列表中猜测" in prompt


def test_router_uses_a_strict_routing_communication_contract() -> None:
    router = AgentTemplateModel(
        agent_id="agent-router", name="星尘 AI", features={"router": True}, is_active=True
    )

    prompt = AgentService._append_communication_contract("路由提示词", router)

    assert "路由输出纪律" in prompt
    assert "不要执行分析" in prompt
    assert "前端规则替你" in prompt


def test_persona_renderer_includes_stable_style_but_excludes_ui_and_capabilities() -> None:
    prompt = render_persona_system_prompt(
        {
            "persona": {
                "archetype": "严谨的质量审计员",
                "traits": ["审慎", "重证据"],
                "working_style": "先核验输入，再给出结论",
                "communication_style": "区分通过、警告和阻断",
                "challenge_style": "主动指出反例和缺口",
                "status_lines": {"running": ["正在审计"]},
                "version": "agent-qc@1",
                "tools": ["workspace_write"],
                "permissions": {"admin": True},
                "persona_context": "本轮只审计批次效应",
            }
        }
    )

    assert "严谨的质量审计员" in prompt
    assert "主动指出反例和缺口" in prompt
    assert "正在审计" not in prompt
    assert "workspace_write" not in prompt
    assert "admin" not in prompt
    assert "本轮只审计批次效应" not in prompt
    assert "不得据此新增、移除或扩大工具" in prompt


def test_persona_is_inserted_before_shared_sandbox_protocol() -> None:
    agent = AgentTemplateModel(
        agent_id="agent-qc",
        features={"persona": {"archetype": "审计员"}},
        is_active=True,
    )

    prompt = AgentService._append_persona_prompt(
        "原始职责\n\n## 共享沙盒协议\n- 只能写入 output/",
        agent,
    )

    assert prompt.index("原始职责") < prompt.index("Agent Persona")
    assert prompt.index("Agent Persona") < prompt.index("共享沙盒协议")


@pytest.mark.asyncio
async def test_assemble_context_injects_persona_when_model_is_unavailable() -> None:
    agent = AgentTemplateModel(
        agent_id="agent-qc",
        name="质量审计员",
        system_prompt="原始职责提示",
        features={
            "persona": {
                "archetype": "严谨审计员",
                "traits": ["审慎"],
                "working_style": "先核验",
                "communication_style": "给出证据",
                "challenge_style": "指出缺口",
            }
        },
        is_active=True,
    )
    service = AgentService(AsyncMock())
    service._reconcile_model_bindings = AsyncMock()  # type: ignore[method-assign]
    service.get_agent = AsyncMock(return_value=agent)  # type: ignore[method-assign]
    service._get_user_capability = AsyncMock(return_value=None)  # type: ignore[method-assign]
    service._resolve_model = AsyncMock(return_value=None)  # type: ignore[method-assign]

    context = await service.assemble_context("agent-qc", user_id="user-1")

    assert context is not None
    assert "原始职责提示" in context.system_prompt
    assert "严谨审计员" in context.system_prompt
    assert "不得据此新增、移除或扩大工具" in context.system_prompt


def test_handoff_packet_stays_within_budget() -> None:
    packet = AgentHandoffService._build_packet(
        source_name="单细胞分析师",
        reason="质控完成，需要差异表达与富集分析",
        user_intent="完成差异表达与富集",
        handoff_summary="已完成过滤和双细胞处理。" * 300,
        artifacts=["workspace/qc/report.html"],
        constraints=["使用 GRCh38"],
    )

    assert len(packet.encode("utf-8")) <= MAX_HANDOFF_PACKET_BYTES
    assert packet.startswith("## 会话交接")


def test_handoff_artifacts_must_stay_in_relative_workspace_paths() -> None:
    with pytest.raises(BusinessError, match="相对路径"):
        AgentHandoffService._normalize_artifacts(["../other-user/report.html"])


def test_handoff_directive_is_extracted_from_toolbridge_envelope() -> None:
    directive = {"target_agent_id": "agent-rnaseq"}
    assert (
        extract_handoff_directive(
            {"success": True, "result": {"llm_payload": {"handoff": directive}}}
        )
        == directive
    )


@pytest.mark.asyncio
async def test_prepare_handoff_enforces_agent_whitelist_and_builds_packet() -> None:
    db = AsyncMock()
    source = AgentTemplateModel(
        agent_id="agent-scrna",
        name="单细胞分析师",
        features={"handoff": {"allowed_targets": ["agent-rnaseq"], "max_hops_per_session": 3}},
        is_active=True,
    )
    target = AgentTemplateModel(agent_id="agent-rnaseq", name="RNA-seq 分析师", is_active=True)
    db.scalar.side_effect = [
        ChatSessionModel(session_id="session-1", user_id="user-1", status="active"),
        source,
        target,
    ]
    history_result = MagicMock()
    history_result.all.return_value = []
    db.scalars.return_value = history_result

    directive = await AgentHandoffService(db).prepare_handoff(
        user_id="user-1",
        session_id="session-1",
        source_agent_id="agent-scrna",
        target_agent_id="agent-rnaseq",
        reason="质控已完成，进入差异表达阶段",
        handoff_summary="完成过滤、双细胞检测和细胞注释。",
        user_intent="继续做差异表达与富集",
        artifacts=["workspace/qc/report.html"],
        constraints=["使用 GRCh38"],
    )

    assert directive["hop_index"] == 1
    assert directive["target_agent_name"] == "RNA-seq 分析师"
    assert "workspace/qc/report.html" in directive["packet"]


@pytest.mark.asyncio
async def test_prepare_handoff_allows_any_active_non_router_target_for_dynamic_dispatch() -> None:
    db = AsyncMock()
    source = AgentTemplateModel(
        agent_id="agent-general",
        name="通用助手",
        features={"handoff": {"allowed_targets": ["*"], "max_hops_per_session": 3}},
        is_active=True,
    )
    target = AgentTemplateModel(agent_id="agent-viz", name="可视化专家", is_active=True)
    db.scalar.side_effect = [
        ChatSessionModel(session_id="session-1", user_id="user-1", status="active"),
        source,
        target,
    ]
    history_result = MagicMock()
    history_result.all.return_value = []
    db.scalars.return_value = history_result

    directive = await AgentHandoffService(db).prepare_handoff(
        user_id="user-1",
        session_id="session-1",
        source_agent_id="agent-general",
        target_agent_id="agent-viz",
        reason="该任务需要专业科研绘图能力",
        handoff_summary="尚未执行分析。",
        user_intent="画一个样本间相关性热图",
    )

    assert directive["target_agent_id"] == "agent-viz"


@pytest.mark.asyncio
async def test_dynamic_handoff_catalog_includes_current_active_agents_only() -> None:
    db = AsyncMock()
    source = AgentTemplateModel(
        agent_id="agent-general",
        name="通用助手",
        features={"handoff": {"allowed_targets": ["*"]}},
        is_active=True,
    )
    active_expert = AgentTemplateModel(
        agent_id="agent-custom-qc",
        name="质控专家",
        description="自定义质量控制流程",
        category="analysis",
        is_active=True,
    )
    router = AgentTemplateModel(
        agent_id="agent-router",
        name="星尘 AI",
        features={"router": True},
        is_active=True,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [source, active_expert, router]
    db.execute.return_value = result

    catalog_prompt = await AgentService(db)._build_handoff_catalog(source)
    payload = catalog_prompt.split("\n\n")[1]
    entries = json.loads(payload)

    assert [entry["agent_id"] for entry in entries] == ["agent-custom-qc"]
    assert entries[0]["capabilities"] == []
    assert entries[0]["chat_entry"] is True


@pytest.mark.asyncio
async def test_dynamic_handoff_catalog_enriches_builtin_agent_from_ability_yaml() -> None:
    db = AsyncMock()
    source = AgentTemplateModel(
        agent_id="agent-general",
        name="通用助手",
        features={"handoff": {"allowed_targets": ["agent-viz"]}},
        is_active=True,
    )
    expert = AgentTemplateModel(
        agent_id="agent-viz",
        name="可视化助手",
        description="旧的数据库描述",
        category="analysis",
        is_active=True,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [source, expert]
    db.execute.return_value = result

    catalog_prompt = await AgentService(db)._build_handoff_catalog(source)
    entries = json.loads(catalog_prompt.split("\n\n")[1])

    assert entries == [
        {
            "agent_id": "agent-viz",
            "name": "可视化助手",
            "description": "负责科研图形选型、脚本、版式、美化和导出规范。",
            "category": "analysis",
            "chat_entry": True,
            "capabilities": ["科研绘图", "ggplot2", "热图", "火山图", "UMAP", "系统发育树", "图注", "出版级导出"],
            "not_suitable_for": ["原始数据质控裁决", "复杂统计推断", "大规模工作流执行"],
            "handoff_when": ["需要领域统计分析", "需要文件预处理或代码调试", "需要组学结果解释"],
            "preferred_inputs": ["数据表或对象", "图形目标", "分组字段", "配色限制", "期刊或尺寸要求"],
        }
    ]


@pytest.mark.asyncio
async def test_dynamic_handoff_catalog_exposes_chat_entry_from_ability_yaml() -> None:
    db = AsyncMock()
    source = AgentTemplateModel(
        agent_id="agent-general",
        name="通用助手",
        features={"handoff": {"allowed_targets": ["agent-data"]}},
        is_active=True,
    )
    internal_role = AgentTemplateModel(
        agent_id="agent-data",
        name="数据管理员",
        description="旧的数据库描述",
        category="analysis",
        is_active=True,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [source, internal_role]
    db.execute.return_value = result

    catalog_prompt = await AgentService(db)._build_handoff_catalog(source)
    entries = json.loads(catalog_prompt.split("\n\n")[1])

    assert entries[0]["agent_id"] == "agent-data"
    assert entries[0]["chat_entry"] is False


@pytest.mark.asyncio
async def test_record_handoff_anchor_commits_in_independent_session(monkeypatch) -> None:
    import omichub.application.services.agent_handoff_service as handoff_module

    class FakeDb:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.commit = AsyncMock()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def add(self, value: object) -> None:
            self.added.append(value)

    db = FakeDb()
    monkeypatch.setattr(handoff_module, "get_session_factory", lambda: lambda: db)
    directive = {
        "source_agent_id": "agent-a",
        "target_agent_id": "agent-b",
        "reason": "进入下一专项阶段",
        "handoff_summary": "已完成前序分析。",
        "user_intent": "继续交付结果",
        "artifacts": ["output/qc.html"],
        "constraints": ["GRCh38"],
        "hop_index": 1,
    }

    event = await AgentHandoffService.record_handoff_anchor(
        user_id="user-1", session_id="session-1", directive=directive
    )

    assert event.session_id == "session-1"
    assert event.target_agent_id == "agent-b"
    assert db.added == [event]
    db.commit.assert_awaited_once()
