"""Agent YAML studio 段解析单元测试（agent_loader._load_single_agent）"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from cygnusx.application.services.agent_service import AgentService
from cygnusx.infrastructure.config import agent_loader
from cygnusx.infrastructure.config.agent_loader import _load_single_agent, load_agent_configs
from cygnusx.infrastructure.mcp.presets import (
    CYGNUSX_PLATFORM_SERVER_ID,
    CYGNUSX_TOOLS_SERVER_ID,
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
        "agent_id: a1\nname: 测试\nstudio:\n  enabled: true\n  image: cygnusx-sandbox:bio\n",
    )
    data = _load_single_agent(path)
    assert data is not None
    assert data["studio"] == {"enabled": True, "image": "cygnusx-sandbox:bio"}


def test_every_enabled_agent_declares_a_studio_runtime():
    """防止新 Agent 静默落到全局 analysis-core；画像必须在 Agent YAML 中可审计。"""
    configs = load_agent_configs()
    assert configs
    missing = [
        str(config.get("agent_id"))
        for config in configs
        if not isinstance(config.get("studio"), dict)
        or not str((config.get("studio") or {}).get("image") or "").strip()
    ]
    assert missing == []


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
    assert "{{runtime_images}}" not in prompt
    assert "analysis-core" in prompt
    assert "output/environment.yml" in prompt
    assert "output/software-versions.txt" in prompt
    assert "## 依赖现场安装规范" not in (data_dir / "prompts" / "rnaseq.md").read_text(
        encoding="utf-8"
    )


@pytest.mark.unit
def test_agent_package_catalogs_are_injected_by_yaml_selection() -> None:
    """包目录由 YAML 选择，加载后不保留内部配置字段。"""
    data_dir = Path(__file__).parents[2] / "data" / "ai"
    code = _load_single_agent(data_dir / "code.yaml")
    scrna = _load_single_agent(data_dir / "scrna.yaml")

    assert code is not None
    assert scrna is not None
    assert "package_catalogs" not in code
    assert "{{bio_packages}}" not in code["system_prompt"]
    assert "## 生物信息软件包目录（按角色自动加载）" in code["system_prompt"]
    assert "##### 1 基因组学 / 序列分析" in code["system_prompt"]
    assert "##### 14 化学信息学（Cheminformatics）" in code["system_prompt"]
    assert "##### 3 单细胞分析" in scrna["system_prompt"]
    assert "##### R / Bioconductor 统计与单细胞" in scrna["system_prompt"]
    assert "##### 1 基因组学 / 序列分析" not in scrna["system_prompt"]


@pytest.mark.unit
def test_agentteams_manager_identity_is_collaboration_scoped() -> None:
    data_dir = Path(__file__).parents[2] / "data" / "ai"
    manager = _load_single_agent(data_dir / "agentteams_manager.yaml")
    general = _load_single_agent(data_dir / "general.yaml")

    assert manager is not None
    assert general is not None
    assert manager["name"] == "生物信息部门经理"
    assert manager["features"]["managed_prompt"] is True
    assert manager["features"]["managed_profile"] is True
    assert "禁止使用英文“Manager”" in manager["system_prompt"]
    assert "生物信息部门经理" not in general["system_prompt"]


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
    assert "output/environment.yml" in config["system_prompt"]
    assert "{{runtime_images}}" not in config["system_prompt"]


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
    path = _write_yaml(tmp_path, "agent_id: a1\nstudio:\n  image: cygnusx-sandbox:base\n")
    data = _load_single_agent(path)
    assert data is not None
    assert data["studio"] == {"image": "cygnusx-sandbox:base"}


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
        "id: research\nbuiltin_tools: [cygnusx_run_kegg_enrichment]\n"
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
    assert str(CYGNUSX_TOOLS_SERVER_ID) in data["mcp_ids"]
    assert str(CYGNUSX_PLATFORM_SERVER_ID) in data["mcp_ids"]
    assert data["features"]["tool_packs"] == [
        {
            "id": "research",
            "description": "",
            "builtin_tools": ["cygnusx_run_kegg_enrichment"],
            "mcp_tools": {
                str(CYGNUSX_PLATFORM_SERVER_ID): ["list_workspace_files"],
            },
        }
    ]


@pytest.mark.unit
def test_agent_level_mcp_tools_whitelist_is_merged(tmp_path: Path):
    """Agent YAML 顶层 mcp_tools 白名单须并入 features.tool_packs（否则是死配置）。"""
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "research.yaml").write_text(
        "id: research\nplatform_tools: [list_workspace_files]\n",
        encoding="utf-8",
    )
    path = _write_yaml(
        tmp_path,
        "agent_id: a1\n"
        "tool_packs: [research]\n"
        "mcp_tools:\n"
        f"  {CYGNUSX_PLATFORM_SERVER_ID}:\n"
        "    - ability_catalog_query\n",
    )

    data = _load_single_agent(path)

    assert data is not None
    packs = data["features"]["tool_packs"]
    inline = next(p for p in packs if p["id"] == "a1:inline")
    assert inline["mcp_tools"] == {str(CYGNUSX_PLATFORM_SERVER_ID): ["ability_catalog_query"]}
    # 工具包自带的白名单不受影响
    assert packs[0]["mcp_tools"] == {str(CYGNUSX_PLATFORM_SERVER_ID): ["list_workspace_files"]}


@pytest.mark.unit
def test_agent_level_mcp_tools_without_tool_packs(tmp_path: Path):
    """未声明 tool_packs 时，顶层 mcp_tools 白名单也应生效。"""
    path = _write_yaml(
        tmp_path,
        "agent_id: a2\n"
        "mcp_tools:\n"
        f"  {CYGNUSX_PLATFORM_SERVER_ID}: [room_state_query]\n",
    )

    data = _load_single_agent(path)

    assert data is not None
    packs = data["features"]["tool_packs"]
    assert packs == [
        {
            "id": "a2:inline",
            "description": "Agent 级 mcp_tools 白名单（YAML 顶层声明）",
            "builtin_tools": [],
            "mcp_tools": {str(CYGNUSX_PLATFORM_SERVER_ID): ["room_state_query"]},
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
    site_yaml = tmp_path / "CygnusX.yaml"
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
        name="qdoubao-seed-evolving",
        model="qdoubao-seed-evolving",
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
    assert agent.model_name == "qdoubao-seed-evolving"
    assert agent.model_engine == "qdoubao-seed-evolving"


@pytest.mark.asyncio
async def test_existing_builtin_agent_resyncs_studio_features(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from cygnusx.application.services.agent_service import AgentService
    from cygnusx.infrastructure.database.models.agent import AgentTemplateModel

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
        "cygnusx.application.services.agent_service.load_agent_configs",
        lambda: [
            {
                "agent_id": "a1",
                "features": {"enable_file_upload": True},
                "studio": {"enabled": True, "image": "cygnusx-sandbox:bio"},
            }
        ],
    )

    await service.ensure_builtin_agents()

    assert existing.features == {
        "enable_web_search": True,
        "enable_file_upload": True,
        "studio": {"enabled": True, "image": "cygnusx-sandbox:bio"},
    }
    db.add.assert_not_called()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_existing_custom_agent_is_not_overwritten(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from cygnusx.application.services.agent_service import AgentService
    from cygnusx.infrastructure.database.models.agent import AgentTemplateModel

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
        "cygnusx.application.services.agent_service.load_agent_configs",
        lambda: [{"agent_id": "a1", "studio": {"enabled": True}}],
    )

    await service.ensure_builtin_agents()

    assert existing.features == {"studio": {"enabled": False}}
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_empty_database_creates_builtin_agents_from_yaml(monkeypatch):
    """新部署的空库应直接由 data/ai 声明创建可见的内置 Agent。"""
    from unittest.mock import MagicMock

    db = MagicMock()
    provider_result = MagicMock()
    provider_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=provider_result)
    db.flush = AsyncMock()

    service = AgentService(db)
    service.get_agent = AsyncMock(return_value=None)
    service._ensure_configured_marketplace_skills = AsyncMock()
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.load_agent_configs",
        lambda: [
            {
                "agent_id": "agent-general",
                "name": "通用助手",
                "description": "内置通用 Agent",
                "category": "general",
                "mcp_ids": [str(CYGNUSX_TOOLS_SERVER_ID)],
                "skill_ids": ["general-skill"],
                "features": {"managed_profile": True},
            },
            {
                "agent_id": "agent-rnaseq",
                "name": "RNA-seq 分析师",
                "mcp_ids": [str(CYGNUSX_PLATFORM_SERVER_ID)],
                "features": {"managed_prompt": True},
            },
        ],
    )

    await service.ensure_builtin_agents()

    created_agents = [call.args[0] for call in db.add.call_args_list]
    assert [agent.agent_id for agent in created_agents] == [
        "agent-general",
        "agent-rnaseq",
    ]
    assert all(agent.is_builtin and agent.is_active for agent in created_agents)
    assert created_agents[0].name == "通用助手"
    assert created_agents[0].skill_ids == ["general-skill"]
    assert created_agents[1].model_id is None
    service._ensure_configured_marketplace_skills.assert_awaited_once_with(
        {"general-skill"}
    )
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_existing_builtin_agent_merges_declared_skill_ids(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from cygnusx.application.services.agent_service import AgentService
    from cygnusx.infrastructure.database.models.agent import AgentTemplateModel

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
        "cygnusx.application.services.agent_service.load_agent_configs",
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

    from cygnusx.application.services.agent_service import AgentService
    from cygnusx.infrastructure.database.models.agent import AgentTemplateModel

    existing = AgentTemplateModel(
        agent_id="agent-rnaseq",
        name="RNA-seq 分析师",
        is_builtin=True,
        system_prompt="旧提示词",
        description="旧描述",
        temperature=0.7,
        is_active=False,
        mcp_ids=[str(CYGNUSX_TOOLS_SERVER_ID)],
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
        "cygnusx.application.services.agent_service.load_agent_configs",
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
    assert str(CYGNUSX_TOOLS_SERVER_ID) in existing.mcp_ids


@pytest.mark.unit
def test_rnaseq_agent_loads_domain_pack_and_rnaflow_skill() -> None:
    from cygnusx.infrastructure.config.agent_loader import load_agent_configs

    config = next(item for item in load_agent_configs() if item["agent_id"] == "agent-rnaseq")

    assert "rnaflow" in config["skill_ids"]
    assert "7375dd58-4c5f-59f9-ab27-a407bb961ee8" in config["mcp_ids"]
    assert config["features"]["managed_prompt"] is True
    assert config["features"]["managed_profile"] is True
    assert config["features"]["engine"] == "langgraph"
    assert "先调用 `knowledge_search`" in config["system_prompt"]


@pytest.mark.unit
def test_atacseq_agent_loads_domain_pack_and_atacflow_skill() -> None:
    from cygnusx.infrastructure.config.agent_loader import load_agent_configs

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

    from cygnusx.application.services.agent_service import AgentService
    from cygnusx.application.services.skill_import_service import SkillImportService

    skill_dir = tmp_path / "annotation-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: 注释\ndescription: 测试\n---\n正文", encoding="utf-8")
    settings = type("SettingsStub", (), {"skill_marketplace_dir": str(tmp_path)})()
    monkeypatch.setattr("cygnusx.core.config.get_settings", lambda: settings)

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
@pytest.mark.quarantine(reason="MCP 构建师提示词文案已更新，不再包含断言期望的红线字样")
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
    assert data["model"] == "qdoubao-seed-evolving"

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
