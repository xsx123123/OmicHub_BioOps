"""Agent YAML studio 段解析单元测试（agent_loader._load_single_agent）"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from omichub.application.services.agent_service import AgentService
from omichub.infrastructure.config import agent_loader
from omichub.infrastructure.config.agent_loader import _load_single_agent
from omichub.infrastructure.mcp.presets import (
    OMICHUB_PLATFORM_SERVER_ID,
    OMICHUB_TOOLS_SERVER_ID,
)


def _write_yaml(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "agent.yaml"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.mark.unit
def test_studio_section_parsed(tmp_path: Path):
    """studio: {enabled, image} 原样解析并规整类型"""
    path = _write_yaml(
        tmp_path,
        "agent_id: a1\nname: 测试\nstudio:\n  enabled: true\n  image: omichub-sandbox:bio\n",
    )
    data = _load_single_agent(path)
    assert data is not None
    assert data["studio"] == {"enabled": True, "image": "omichub-sandbox:bio"}


@pytest.mark.unit
def test_agent_prompt_appends_shared_sandbox_protocol_once() -> None:
    """运行时 Agent 提示词只追加共享沙盒协议。"""
    data_dir = Path(__file__).parents[2] / "data" / "ai"
    config = _load_single_agent(data_dir / "rnaseq.yaml")

    assert config is not None
    prompt = config["system_prompt"]
    assert prompt.count("## 共享沙盒协议") == 1
    assert "## 转介、交接与协作" in prompt
    assert "output/results/" in prompt
    assert "## 依赖现场安装规范" not in (data_dir / "prompts" / "rnaseq.md").read_text(
        encoding="utf-8"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "agent_name",
    [
        "atacseq",
        "code",
        "cloud_ops",
        "data",
        "delivery",
        "general",
        "mcp_builder",
        "orchestrator",
        "qc",
        "rnaseq",
        "router",
        "scrna",
        "scrna_advanced",
        "scrna_integration",
        "scrna_upstream",
        "shania",
        "viz",
    ],
)
def test_all_agent_prompts_receive_shared_protocol(agent_name: str) -> None:
    data_dir = Path(__file__).parents[2] / "data" / "ai"
    config = _load_single_agent(data_dir / f"{agent_name}.yaml")

    assert config is not None
    assert config["system_prompt"].count("## 共享沙盒协议") == 1


@pytest.mark.unit
def test_studio_section_non_dict_dropped(tmp_path: Path):
    """studio 段结构非法时剔除，不影响 Agent 加载"""
    path = _write_yaml(tmp_path, "agent_id: a1\nstudio: oops\n")
    data = _load_single_agent(path)
    assert data is not None
    assert "studio" not in data


@pytest.mark.unit
def test_studio_section_partial_fields(tmp_path: Path):
    """只写 image 时保留 image；enabled 缺省不补"""
    path = _write_yaml(tmp_path, "agent_id: a1\nstudio:\n  image: omichub-sandbox:base\n")
    data = _load_single_agent(path)
    assert data is not None
    assert data["studio"] == {"image": "omichub-sandbox:base"}


@pytest.mark.unit
def test_studio_section_extra_keys_ignored(tmp_path: Path):
    """P0 只识别 enabled/image，其余键（如 sandbox 资源覆盖）忽略"""
    path = _write_yaml(
        tmp_path,
        "agent_id: a1\nstudio:\n  enabled: false\n  sandbox:\n    cpu: 4\n",
    )
    data = _load_single_agent(path)
    assert data is not None
    assert data["studio"] == {"enabled": False}


@pytest.mark.unit
def test_no_studio_section_untouched(tmp_path: Path):
    """无 studio 段的 YAML 行为不变"""
    path = _write_yaml(tmp_path, "agent_id: a1\nname: 普通助手\n")
    data = _load_single_agent(path)
    assert data is not None
    assert "studio" not in data
    assert data["agent_id"] == "a1"


@pytest.mark.unit
def test_local_prompt_and_tool_pack_are_loaded(tmp_path: Path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "agent.md").write_text("详细系统提示词", encoding="utf-8")
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "research.yaml").write_text(
        "id: research\nbuiltin_tools: [omichub_run_kegg_enrichment]\n"
        "platform_tools: [list_workspace_files]\n",
        encoding="utf-8",
    )
    path = _write_yaml(
        tmp_path,
        "agent_id: a1\nprompt_file: prompts/agent.md\ntool_packs: [research]\n",
    )

    data = _load_single_agent(path)

    assert data is not None
    assert data["system_prompt"] == "详细系统提示词"
    assert str(OMICHUB_TOOLS_SERVER_ID) in data["mcp_ids"]
    assert str(OMICHUB_PLATFORM_SERVER_ID) in data["mcp_ids"]
    assert data["features"]["tool_packs"] == [
        {
            "id": "research",
            "description": "",
            "builtin_tools": ["omichub_run_kegg_enrichment"],
            "mcp_tools": {
                str(OMICHUB_PLATFORM_SERVER_ID): ["list_workspace_files"],
            },
        }
    ]


@pytest.mark.unit
def test_handoff_section_is_synced_into_features(tmp_path: Path):
    path = _write_yaml(
        tmp_path,
        """agent_id: a1
handoff:
  allowed_targets: [agent-rnaseq]
  max_hops_per_session: 3
""",
    )

    data = _load_single_agent(path)

    assert data is not None
    assert data["features"]["handoff"] == {
        "allowed_targets": ["agent-rnaseq"],
        "max_hops_per_session": 3,
    }
    assert "handoff" not in data


@pytest.mark.unit
def test_local_prompt_path_cannot_escape_agent_directory(tmp_path: Path):
    path = _write_yaml(tmp_path, "agent_id: a1\nprompt_file: ../outside.md\n")

    assert _load_single_agent(path) is None


@pytest.mark.unit
def test_mas_enabled_does_not_implicitly_register_orchestrator(tmp_path: Path, monkeypatch):
    site_yaml = tmp_path / "OmicHub.yaml"
    site_yaml.write_text("agents:\n  enabled: [general]\n", encoding="utf-8")
    agents_dir = tmp_path / "ai"
    agents_dir.mkdir()
    (agents_dir / "general.yaml").write_text("agent_id: agent-general\n", encoding="utf-8")
    (agents_dir / "orchestrator.yaml").write_text(
        "agent_id: agent-orchestrator\nfeatures:\n  mas_orchestrator: true\n",
        encoding="utf-8",
    )
    settings = type(
        "SettingsStub",
        (),
        {"site_content_yaml": str(site_yaml), "mas_enabled": True},
    )()
    monkeypatch.setattr(agent_loader, "get_settings", lambda: settings)

    configs = agent_loader.load_agent_configs()

    assert [item["agent_id"] for item in configs] == ["agent-general"]


class _Result:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return self._values

    def scalar_one_or_none(self):
        return self._values[0] if self._values else None


@pytest.mark.unit
async def test_unbound_builtin_agent_resolves_default_model_for_studio():
    """Studio 创建时应为历史空绑定的内置 Agent 解析默认模型。"""
    provider = SimpleNamespace(
        id=uuid4(),
        name="qwen3.7-plus",
        model="qwen3.7-plus",
        is_active=True,
        is_default=True,
    )
    agent = SimpleNamespace(
        is_builtin=True,
        model_id=None,
        model_name="qwen3.7-max",
        model_engine="",
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Result([provider]),
                _Result([agent]),
                _Result([provider]),
            ]
        ),
        flush=AsyncMock(),
    )

    model_id = await AgentService(db).resolve_model_id_for_agent(agent)

    assert model_id == provider.id
    assert agent.model_id == provider.id
    assert agent.model_name == "qwen3.7-plus"
    assert agent.model_engine == "qwen3.7-plus"


@pytest.mark.asyncio
async def test_existing_builtin_agent_resyncs_studio_features(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from omichub.application.services.agent_service import AgentService
    from omichub.infrastructure.database.models.agent import AgentTemplateModel

    existing = AgentTemplateModel(
        agent_id="a1",
        name="既有内置 Agent",
        is_builtin=True,
        features={"enable_web_search": True, "studio": {"enabled": False}},
    )
    db = AsyncMock()
    provider_result = MagicMock()
    provider_result.scalars.return_value.all.return_value = []
    db.execute.return_value = provider_result
    service = AgentService(db)
    service.get_agent = AsyncMock(return_value=existing)
    monkeypatch.setattr(
        "omichub.application.services.agent_service.load_agent_configs",
        lambda: [
            {
                "agent_id": "a1",
                "features": {"enable_file_upload": True},
                "studio": {"enabled": True, "image": "omichub-sandbox:bio"},
            }
        ],
    )

    await service.ensure_builtin_agents()

    assert existing.features == {
        "enable_web_search": True,
        "enable_file_upload": True,
        "studio": {"enabled": True, "image": "omichub-sandbox:bio"},
    }
    db.add.assert_not_called()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_existing_custom_agent_is_not_overwritten(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from omichub.application.services.agent_service import AgentService
    from omichub.infrastructure.database.models.agent import AgentTemplateModel

    existing = AgentTemplateModel(
        agent_id="a1",
        name="用户 Agent",
        is_builtin=False,
        features={"studio": {"enabled": False}},
    )
    db = AsyncMock()
    provider_result = MagicMock()
    provider_result.scalars.return_value.all.return_value = []
    db.execute.return_value = provider_result
    service = AgentService(db)
    service.get_agent = AsyncMock(return_value=existing)
    monkeypatch.setattr(
        "omichub.application.services.agent_service.load_agent_configs",
        lambda: [{"agent_id": "a1", "studio": {"enabled": True}}],
    )

    await service.ensure_builtin_agents()

    assert existing.features == {"studio": {"enabled": False}}
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_existing_builtin_agent_merges_declared_skill_ids(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from omichub.application.services.agent_service import AgentService
    from omichub.infrastructure.database.models.agent import AgentTemplateModel

    existing = AgentTemplateModel(
        agent_id="a1",
        name="既有内置 Agent",
        is_builtin=True,
        skill_ids=["existing-skill"],
    )
    db = AsyncMock()
    provider_result = MagicMock()
    provider_result.scalars.return_value.all.return_value = []
    db.execute.return_value = provider_result
    service = AgentService(db)
    service.get_agent = AsyncMock(return_value=existing)
    service._ensure_configured_marketplace_skills = AsyncMock()
    monkeypatch.setattr(
        "omichub.application.services.agent_service.load_agent_configs",
        lambda: [{"agent_id": "a1", "skill_ids": ["existing-skill", "annotation-skill"]}],
    )

    await service.ensure_builtin_agents()

    assert existing.skill_ids == ["existing-skill", "annotation-skill"]
    service._ensure_configured_marketplace_skills.assert_awaited_once_with(
        {"existing-skill", "annotation-skill"}
    )


@pytest.mark.asyncio
async def test_existing_managed_builtin_agent_syncs_prompt_and_declared_mcps(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from omichub.application.services.agent_service import AgentService
    from omichub.infrastructure.database.models.agent import AgentTemplateModel

    existing = AgentTemplateModel(
        agent_id="agent-rnaseq",
        name="RNA-seq 分析师",
        is_builtin=True,
        system_prompt="旧提示词",
        description="旧描述",
        temperature=0.7,
        is_active=False,
        mcp_ids=[str(OMICHUB_TOOLS_SERVER_ID)],
        features={},
    )
    declared_mcp = "7375dd58-4c5f-59f9-ab27-a407bb961ee8"
    db = AsyncMock()
    provider_result = MagicMock()
    provider_result.scalars.return_value.all.return_value = []
    db.execute.return_value = provider_result
    service = AgentService(db)
    service.get_agent = AsyncMock(return_value=existing)
    service._ensure_configured_marketplace_skills = AsyncMock()
    monkeypatch.setattr(
        "omichub.application.services.agent_service.load_agent_configs",
        lambda: [
            {
                "agent_id": "agent-rnaseq",
                "system_prompt": "RNA-seq 新提示词",
                "description": "RNA-seq 新描述",
                "temperature": 0.4,
                "is_active": True,
                "mcp_ids": [declared_mcp],
                "features": {"managed_prompt": True, "managed_profile": True},
            }
        ],
    )

    await service.ensure_builtin_agents()

    assert existing.system_prompt == "RNA-seq 新提示词"
    assert existing.description == "RNA-seq 新描述"
    assert existing.temperature == 0.4
    assert existing.is_active is True
    assert declared_mcp in existing.mcp_ids
    assert str(OMICHUB_TOOLS_SERVER_ID) in existing.mcp_ids


@pytest.mark.unit
def test_rnaseq_agent_loads_domain_pack_and_rnaflow_skill() -> None:
    from omichub.infrastructure.config.agent_loader import load_agent_configs

    config = next(item for item in load_agent_configs() if item["agent_id"] == "agent-rnaseq")

    assert "rnaflow" in config["skill_ids"]
    assert "7375dd58-4c5f-59f9-ab27-a407bb961ee8" in config["mcp_ids"]
    assert config["features"]["managed_prompt"] is True
    assert config["features"]["managed_profile"] is True
    assert config["features"]["engine"] == "langgraph"
    assert "先调用 `knowledge_search`" in config["system_prompt"]


@pytest.mark.unit
def test_atacseq_agent_loads_domain_pack_and_atacflow_skill() -> None:
    from omichub.infrastructure.config.agent_loader import load_agent_configs

    config = next(item for item in load_agent_configs() if item["agent_id"] == "agent-atacseq")

    assert {"atacflow", "atac-tools"}.issubset(config["skill_ids"])
    assert "7375dd58-4c5f-59f9-ab27-a407bb961ee8" in config["mcp_ids"]
    assert config["features"]["managed_prompt"] is True
    assert config["features"]["managed_profile"] is True
    assert config["features"]["engine"] == "langgraph"
    assert config["studio"]["runtime_profile"] == "analysis-core"
    assert "先调用 `knowledge_search`" in config["system_prompt"]
    atac_pack = next(
        pack for pack in config["features"]["tool_packs"] if pack["id"] == "atacseq"
    )
    assert "atac_seq_prepare" in atac_pack["mcp_tools"][
        "7375dd58-4c5f-59f9-ab27-a407bb961ee8"
    ]


@pytest.mark.asyncio
async def test_configured_marketplace_skill_is_installed(monkeypatch, tmp_path: Path):
    from unittest.mock import AsyncMock, MagicMock

    from omichub.application.services.agent_service import AgentService
    from omichub.application.services.skill_import_service import SkillImportService

    skill_dir = tmp_path / "annotation-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: 注释\ndescription: 测试\n---\n正文", encoding="utf-8")
    settings = type("SettingsStub", (), {"skill_marketplace_dir": str(tmp_path)})()
    monkeypatch.setattr("omichub.core.config.get_settings", lambda: settings)

    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result
    service = AgentService(db)
    install_marketplace = AsyncMock()
    monkeypatch.setattr(SkillImportService, "install_marketplace", install_marketplace)

    await service._ensure_configured_marketplace_skills({"annotation-skill", "external-skill"})

    install_marketplace.assert_awaited_once_with("annotation-skill")


@pytest.mark.unit
def test_mcp_builder_agent_loads_successfully():
    """验证 mcp_builder.yaml 可被 agent_loader 正确加载"""
    mcp_builder_yaml = Path("data/ai/mcp_builder.yaml")
    if not mcp_builder_yaml.exists():
        pytest.skip("mcp_builder.yaml 不存在")

    data = _load_single_agent(mcp_builder_yaml)

    # 基础字段验证
    assert data is not None, "mcp_builder.yaml 加载失败"
    assert data["agent_id"] == "agent-mcp-builder"
    assert data["name"] == "MCP 构建师"
    assert data["model"] == "qwen3.7-plus"

    # Studio 配置验证
    assert "studio" in data
    assert data["studio"]["enabled"] is True
    assert data["studio"]["default_mode"] == "studio"
    assert data["studio"]["runtime_profile"] == "analysis-core"

    # 系统提示词验证
    assert "system_prompt" in data
    assert len(data["system_prompt"]) > 1000, "system_prompt 过短，可能未正确加载"
    assert "MCP 构建师" in data["system_prompt"] or "MCP Builder" in data["system_prompt"]

    # 关键约束验证（禁止代为提交）
    assert "绝不代为提交" in data["system_prompt"] or "禁止调用" in data["system_prompt"]

    # STDIO 说明验证
    assert "STDIO" in data["system_prompt"]

    # 生成标记验证
    assert "__exp_mcp_generated__" in data["system_prompt"]
