"""星尘 AI 统一入口（agent-router 智能路由器）分派正确性与配置一致性测试

覆盖：
- 分派正确性：router 模型输出 JSON → _route_to_agent 正确分派到每个已注册专家
- 典型用户问句 → 期望专家 的参数化映射（mock router 决策输出）
- 边界与容错：空输出、纯思考、空 agent_id、幻觉 consult_agent_ids、expect_handoff 异常值
- 配置一致性：data/ai/*.yaml 可加载、router.md 只依赖运行时目录、
  CygnusX.yaml agents.enabled 配置文件齐全
"""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import cygnusx.application.services.chat_service as chat_service_module
from cygnusx.application.schemas.agent import AgentTemplateDTO
from cygnusx.application.services.chat_service import ROUTER_SYSTEM_PROMPT, ChatService
from cygnusx.infrastructure.config import agent_loader

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_DIR = REPO_ROOT / "data" / "ai"
SITE_YAML = REPO_ROOT / "data" / "CygnusX.yaml"
ROUTER_PROMPT_MD = AI_DIR / "prompts" / "router.md"


# ---------------------------------------------------------------------------
# fixtures / 桩
# ---------------------------------------------------------------------------


def _candidate(agent_id: str, category: str, name: str, router: bool = False) -> AgentTemplateDTO:
    return AgentTemplateDTO(
        agent_id=agent_id,
        name=name,
        description=f"{name} 描述",
        avatar="🧬",
        color="#123456",
        category=category,
        features={"router": True} if router else {},
    )


# 与 data/CygnusX.yaml agents.enabled 对齐的完整候选清单
CANDIDATES = [
    _candidate("agent-router", "general", "智能助手", router=True),
    _candidate("agent-general", "general", "通用助手"),
    _candidate("agent-rnaseq", "analysis", "RNA-seq 分析师"),
    _candidate("agent-scrna", "analysis", "单细胞分析师"),
    _candidate("agent-code", "code", "代码助手"),
    _candidate("agent-viz", "visualization", "可视化专家"),
    _candidate("shania", "companion", "傻妞"),
]

EXPERT_IDS = [c.agent_id for c in CANDIDATES if not c.features.get("router")]


def _catalog_entry(dto: AgentTemplateDTO) -> dict[str, Any]:
    """模拟注册表 chat_router_catalog 条目(双注册表统一后 chat 候选的唯一来源)。"""
    return {
        "agent_id": dto.agent_id,
        "name": dto.name,
        "description": dto.description,
        "category": dto.category,
        "chat_entry": True,
        "capabilities": [],
        "not_suitable_for": [],
        "handoff_when": [],
        "preferred_inputs": [],
        "routing_hints": [],
        "capability_tags": [],
        "routing_notes": "",
        "persona": {},
        "avatar": dto.avatar,
        "color": dto.color,
    }


def _catalog_from(dtos: list[AgentTemplateDTO]) -> list[dict[str, Any]]:
    return [_catalog_entry(c) for c in dtos if not c.features.get("router")]


class _FakeCapabilityRegistry:
    """快照桩:与真实注册表一样过滤 features.router / chat_entry=false 候选。"""

    def __init__(self, dtos: list[AgentTemplateDTO] | None = None) -> None:
        self._dtos = CANDIDATES if dtos is None else dtos

    def snapshot(self) -> dict[str, Any]:
        return {
            "chat_router_catalog": _catalog_from(self._dtos),
            "flow_router_catalog": [],
        }


def test_runtime_router_prompt_keeps_decision_on_stardust_ai() -> None:
    assert "星尘 AI" in ROUTER_SYSTEM_PROMPT
    assert "不要执行分析" in ROUTER_SYSTEM_PROMPT
    assert "前端关键词规则" in ROUTER_SYSTEM_PROMPT
    assert "运行时候选专家目录" in ROUTER_SYSTEM_PROMPT
    assert "领域词只用于选择合适的专家" in ROUTER_SYSTEM_PROMPT
    assert "不能仅因“单细胞”创建流程型 Case" in ROUTER_SYSTEM_PROMPT
    assert "emoji" in ROUTER_SYSTEM_PROMPT


class _FakeAgentService:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def list_agents(self, active_only: bool = False) -> list[AgentTemplateDTO]:
        return CANDIDATES

    async def assemble_context(self, agent_id: str) -> Any:
        if agent_id not in {c.agent_id for c in CANDIDATES}:
            return None
        return SimpleNamespace(
            agent_id=agent_id,
            model_config=SimpleNamespace(name="qwen3.7-max", api_key="k"),
        )


def _fake_chat_stream(text: str):
    async def _stream(**kwargs: Any):
        yield SimpleNamespace(type="text", content=text, metadata={})
        yield SimpleNamespace(type="done", content="", metadata={"usage": {}})

    return _stream


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> ChatService:
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", _FakeAgentService
    )
    monkeypatch.setattr(
        "cygnusx.application.services.agentteams_capability_registry"
        ".get_agentteams_capability_registry",
        lambda: _FakeCapabilityRegistry(),
    )
    return ChatService(db=SimpleNamespace())


@pytest.fixture
def router_ctx() -> Any:
    return SimpleNamespace(model_config=SimpleNamespace(name="qwen3.7-max", api_key="k"))


def _mock_router_output(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr(
        chat_service_module.provider_manager, "chat_stream", _fake_chat_stream(text)
    )


def _enable_consultation(monkeypatch: pytest.MonkeyPatch, max_experts: int = 3) -> None:
    monkeypatch.setattr(
        chat_service_module,
        "get_settings",
        lambda: SimpleNamespace(
            multi_expert_consultation_enabled=True,
            multi_expert_consultation_max_experts=max_experts,
        ),
    )


# ---------------------------------------------------------------------------
# a. 分派正确性：每个已注册专家 agent
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("agent_id", EXPERT_IDS)
async def test_dispatch_to_each_registered_expert(
    service: ChatService, router_ctx: Any, monkeypatch, agent_id: str
):
    """router 模型输出各专家 agent_id 时，_route_to_agent 正确分派且 reason 透传"""
    reason = f"转接 {agent_id} 的理由"
    _mock_router_output(monkeypatch, json.dumps({"agent_id": agent_id, "reason": reason}))
    ctx, info = await service._route_to_agent(router_ctx, "用户需求")
    assert ctx is not None and ctx.agent_id == agent_id
    assert info is not None
    assert info["agent_id"] == agent_id
    assert info["reason"] == reason
    assert info["expect_handoff"] is False
    assert info["consult_agent_ids"] == []
    assert {"agent_id", "name", "avatar", "color", "reason"} <= set(info)


@pytest.mark.unit
async def test_router_agent_itself_never_dispatched(
    service: ChatService, router_ctx: Any, monkeypatch
):
    """features.router=true 的 agent-router 被排除在候选之外，幻觉选中时回退"""
    _mock_router_output(monkeypatch, json.dumps({"agent_id": "agent-router", "reason": "选自己"}))
    ctx, info = await service._route_to_agent(router_ctx, "随便聊聊")
    assert ctx is not None and ctx.agent_id == "agent-general"
    assert info is not None and info["agent_id"] == "agent-general"
    assert info["transition"]["visible"] is True
    assert info["transition"]["title"] == "已匹配通用助手"


@pytest.mark.unit
async def test_router_excludes_runtime_internal_chat_role(
    router_ctx: Any, monkeypatch: pytest.MonkeyPatch
):
    """能力目录标记 chat_entry=false 的 Case 内部角色被注册表过滤，
    不进 chat_router_catalog；router 幻觉选中时回退通用助手。"""
    internal_role = _candidate("agent-internal-review", "analysis", "内部审计角色")
    candidates = [*CANDIDATES, internal_role]

    class FakeAgentService:
        def __init__(self, _db: Any) -> None:
            pass

        async def list_agents(self, active_only: bool = False) -> list[AgentTemplateDTO]:
            return candidates

        async def assemble_context(self, agent_id: str) -> Any:
            if agent_id not in {candidate.agent_id for candidate in candidates}:
                return None
            return SimpleNamespace(
                agent_id=agent_id,
                model_config=SimpleNamespace(name="qwen3.7-max", api_key="k"),
            )

    # 注册表负责 chat_entry 过滤:内部角色不出现在快照候选目录中。
    monkeypatch.setattr(
        "cygnusx.application.services.agentteams_capability_registry"
        ".get_agentteams_capability_registry",
        lambda: _FakeCapabilityRegistry(CANDIDATES),
    )
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.AgentService", FakeAgentService
    )
    _mock_router_output(
        monkeypatch,
        json.dumps({"agent_id": internal_role.agent_id, "reason": "错误选择内部角色"}),
    )

    ctx, info = await ChatService(db=SimpleNamespace())._route_to_agent(router_ctx, "随便聊聊")

    assert ctx is not None and ctx.agent_id == "agent-general"
    assert info is not None and info["agent_id"] == "agent-general"


# ---------------------------------------------------------------------------
# b. 典型用户问句 → 期望专家（mock router 决策输出，断言落到正确 agent）
# ---------------------------------------------------------------------------

QUESTION_ROUTING_CASES = [
    ("帮我做RNA-seq差异表达分析", "agent-rnaseq", "转录组差异表达需求"),
    ("这个 bulk 转录组数据怎么做富集分析", "agent-rnaseq", "富集分析属 RNA-seq 领域"),
    ("画一个火山图", "agent-viz", "科研绘图需求"),
    ("帮我把这张图美化成出版级", "agent-viz", "图表美化"),
    ("帮我调试这段python代码", "agent-code", "代码调试需求"),
    ("在沙盒里运行这个脚本", "agent-code", "沙盒执行"),
    ("分析这个10x单细胞数据", "agent-scrna", "10x 单细胞数据"),
    ("这个 h5ad 文件的细胞类型怎么注释", "agent-scrna", "单细胞注释"),
    ("傻妞陪我聊聊", "shania", "用户点名傻妞"),
    ("你好", "agent-general", "闲聊问候"),
    ("我工作区里有什么文件", "agent-general", "纯文件操作"),
]


@pytest.mark.unit
@pytest.mark.parametrize(
    "question, expected_agent, reason",
    QUESTION_ROUTING_CASES,
    ids=[c[0] for c in QUESTION_ROUTING_CASES],
)
async def test_question_routes_to_expected_expert(
    service: ChatService,
    router_ctx: Any,
    monkeypatch,
    question: str,
    expected_agent: str,
    reason: str,
):
    """模拟 router 对典型问句的决策输出，断言分派落到期望专家且 reason 透传"""
    _mock_router_output(monkeypatch, json.dumps({"agent_id": expected_agent, "reason": reason}))
    ctx, info = await service._route_to_agent(router_ctx, question)
    assert ctx is not None and ctx.agent_id == expected_agent
    assert info is not None
    assert info["agent_id"] == expected_agent
    assert info["reason"] == reason


@pytest.mark.unit
async def test_text_intake_no_longer_bypasses_router(
    service: ChatService, router_ctx: Any, monkeypatch
):
    """缺参数只影响专家后续 intake，不能在 Router 前强制改派通用助手。"""
    captured: dict[str, Any] = {}

    async def route_with_model(**kwargs: Any):
        captured.update(kwargs)
        yield SimpleNamespace(
            type="text",
            content=json.dumps({"agent_id": "agent-rnaseq", "reason": "转录组研究计划"}),
            metadata={},
        )

    monkeypatch.setattr(chat_service_module.provider_manager, "chat_stream", route_with_model)
    ctx, info = await service._route_to_agent(
        router_ctx,
        "我有两个 TP53 分组，想挖掘新颖发现，请写详细计划",
    )

    assert ctx is not None and ctx.agent_id == "agent-rnaseq"
    assert info is not None and info["reason"] == "转录组研究计划"
    assert "TP53" in captured["messages"][0]["content"]


@pytest.mark.unit
async def test_router_receives_uploaded_file_manifest_and_can_select_visualization_expert(
    service: ChatService, router_ctx: Any, monkeypatch
):
    captured: dict[str, Any] = {}

    async def route_visualization_request(**kwargs: Any):
        captured.update(kwargs)
        yield SimpleNamespace(
            type="text",
            content=json.dumps({"agent_id": "agent-viz", "reason": "差异表达可视化交付"}),
            metadata={},
        )

    monkeypatch.setattr(chat_service_module.provider_manager, "chat_stream", route_visualization_request)
    ctx, info = await service._route_to_agent(
        router_ctx,
        "请基于上传的差异表达 CSV 生成火山图和热图，并给出结果总结。",
        attachments=[
            {
                "name": "synthetic_gene_expression_3000 - Untitled.csv",
                "type": "file",
                "mime_type": "text/csv",
            }
        ],
    )

    assert ctx is not None and ctx.agent_id == "agent-viz"
    assert info is not None and info["reason"] == "差异表达可视化交付"
    assert "synthetic_gene_expression_3000 - Untitled.csv" in captured["messages"][0]["content"]
    assert "附件清单" in captured["messages"][0]["content"]


@pytest.mark.unit
async def test_router_does_not_override_model_target_with_keyword_rules(
    service: ChatService, router_ctx: Any, monkeypatch
):
    """专家目标必须来自 Router JSON；用户文本中的关键词不能覆盖模型决策。"""
    _mock_router_output(
        monkeypatch,
        json.dumps({"agent_id": "agent-general", "reason": "模型决定由通用助手处理"}),
    )

    ctx, info = await service._route_to_agent(router_ctx, "请画一个火山图")

    assert ctx is not None and ctx.agent_id == "agent-general"
    assert info is not None and info["agent_id"] == "agent-general"
    assert info["reason"] == "模型决定由通用助手处理"


# ---------------------------------------------------------------------------
# c. 边界与容错
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_empty_model_output_falls_back_general(
    service: ChatService, router_ctx: Any, monkeypatch
):
    _mock_router_output(monkeypatch, "")
    ctx, info = await service._route_to_agent(router_ctx, "你好")
    assert ctx is not None and ctx.agent_id == "agent-general"
    assert info is not None and info["agent_id"] == "agent-general"
    assert info["reason"]  # 兜底理由非空


@pytest.mark.unit
async def test_pure_thinking_without_json_falls_back_general(
    service: ChatService, router_ctx: Any, monkeypatch
):
    _mock_router_output(
        monkeypatch, "用户在问 RNA-seq，我觉得应该选 rnaseq 专家，但我没输出 JSON。"
    )
    ctx, info = await service._route_to_agent(router_ctx, "帮我做差异分析")
    assert ctx is not None and ctx.agent_id == "agent-general"
    assert info is not None and info["agent_id"] == "agent-general"


@pytest.mark.unit
async def test_empty_agent_id_falls_back_general(
    service: ChatService, router_ctx: Any, monkeypatch
):
    _mock_router_output(monkeypatch, '{"agent_id": "", "reason": "空 id"}')
    ctx, info = await service._route_to_agent(router_ctx, "你好")
    assert ctx is not None and ctx.agent_id == "agent-general"
    assert info is not None and info["agent_id"] == "agent-general"


@pytest.mark.unit
async def test_null_agent_id_falls_back_general(service: ChatService, router_ctx: Any, monkeypatch):
    _mock_router_output(monkeypatch, '{"agent_id": null, "reason": "null id"}')
    ctx, info = await service._route_to_agent(router_ctx, "你好")
    assert ctx is not None and ctx.agent_id == "agent-general"
    assert info is not None and info["agent_id"] == "agent-general"


@pytest.mark.unit
async def test_hallucinated_consult_agents_filtered(
    service: ChatService, router_ctx: Any, monkeypatch
):
    """consult_agent_ids 含幻觉/自身 agent 时被过滤，合法项保留"""
    _enable_consultation(monkeypatch)
    _mock_router_output(
        monkeypatch,
        json.dumps(
            {
                "agent_id": "agent-rnaseq",
                "reason": "主专家",
                "consult_agent_ids": [
                    "agent-scrna",  # 合法
                    "agent-not-exist",  # 幻觉 → 过滤
                    "agent-rnaseq",  # 与主专家相同 → 过滤
                    "agent-code",
                    "agent-code",  # 重复 → 去重
                ],
            }
        ),
    )
    ctx, info = await service._route_to_agent(router_ctx, "单细胞做完做富集")
    assert ctx is not None and ctx.agent_id == "agent-rnaseq"
    assert info is not None
    assert info["consult_agent_ids"] == ["agent-scrna", "agent-code"]


@pytest.mark.unit
async def test_consult_agents_capped_by_max_experts(
    service: ChatService, router_ctx: Any, monkeypatch
):
    """合法 consult_agent_ids 数量受 max_experts 上限截断"""
    _enable_consultation(monkeypatch, max_experts=2)
    _mock_router_output(
        monkeypatch,
        json.dumps(
            {
                "agent_id": "agent-rnaseq",
                "reason": "r",
                "consult_agent_ids": ["agent-scrna", "agent-code", "agent-viz"],
            }
        ),
    )
    ctx, info = await service._route_to_agent(router_ctx, "跨领域需求")
    assert info is not None
    assert len(info["consult_agent_ids"]) <= 2


@pytest.mark.unit
async def test_consult_disabled_by_default(service: ChatService, router_ctx: Any, monkeypatch):
    """multi_expert_consultation_enabled 默认关闭时 consult_agent_ids 恒为空"""
    _mock_router_output(
        monkeypatch,
        json.dumps(
            {
                "agent_id": "agent-rnaseq",
                "reason": "r",
                "consult_agent_ids": ["agent-scrna"],
            }
        ),
    )
    ctx, info = await service._route_to_agent(router_ctx, "跨领域需求")
    assert info is not None and info["consult_agent_ids"] == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw_value, expected",
    [
        (True, True),
        (False, False),
        ("true", True),  # 非空字符串被 bool() 视为 True
        ("yes", True),
        ("", False),
        (None, False),
        (0, False),
        (1, True),
        ([], False),
        (["agent-scrna"], True),  # 非空列表被 bool() 视为 True（宽松转换）
    ],
)
async def test_expect_handoff_abnormal_values(
    service: ChatService, router_ctx: Any, monkeypatch, raw_value: Any, expected: bool
):
    """expect_handoff 经 bool() 宽松转换，不抛异常"""
    _mock_router_output(
        monkeypatch,
        json.dumps({"agent_id": "agent-scrna", "reason": "r", "expect_handoff": raw_value}),
    )
    ctx, info = await service._route_to_agent(router_ctx, "跨阶段需求")
    assert ctx is not None and ctx.agent_id == "agent-scrna"
    assert info is not None and info["expect_handoff"] is expected


@pytest.mark.unit
async def test_consult_agent_ids_not_a_list_ignored(
    service: ChatService, router_ctx: Any, monkeypatch
):
    """consult_agent_ids 为字符串等非法类型时安全忽略"""
    _enable_consultation(monkeypatch)
    _mock_router_output(
        monkeypatch,
        json.dumps({"agent_id": "agent-rnaseq", "reason": "r", "consult_agent_ids": "agent-scrna"}),
    )
    ctx, info = await service._route_to_agent(router_ctx, "需求")
    assert info is not None and info["consult_agent_ids"] == []


@pytest.mark.unit
async def test_json_embedded_in_code_block(service: ChatService, router_ctx: Any, monkeypatch):
    """模型把 JSON 包在 markdown 代码块里也能容错提取"""
    _mock_router_output(monkeypatch, '```json\n{"agent_id": "agent-viz", "reason": "绘图"}\n```')
    ctx, info = await service._route_to_agent(router_ctx, "画个热图")
    assert ctx is not None and ctx.agent_id == "agent-viz"
    assert info is not None and info["agent_id"] == "agent-viz"


# ---------------------------------------------------------------------------
# d. 配置一致性
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_all_enabled_agent_yamls_loadable():
    """data/CygnusX.yaml agents.enabled 中每个 agent 的 yaml 都能被 agent_loader 加载"""
    enabled = agent_loader._load_enabled_agents(SITE_YAML)
    assert enabled, "agents.enabled 不应为空"
    configs = agent_loader.load_agent_configs()
    loaded_ids = {c["agent_id"] for c in configs}
    for name in enabled:
        yaml_path = AI_DIR / f"{name}.yaml"
        assert yaml_path.exists(), f"agents.enabled 中的 {name} 缺少配置文件 {yaml_path}"
    # 每个启用的 agent 文件都成功加载（load_agent_configs 静默跳过失败项，需显式断言数量）
    assert len(configs) >= len(enabled), (
        f"启用 {len(enabled)} 个 agent，仅加载成功 {len(configs)} 个: {loaded_ids}"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "yaml_name",
    [
        "router",
        "general",
        "rnaseq",
        "atacseq",
        "scrna",
        "scrna_upstream",
        "scrna_integration",
        "scrna_advanced",
        "code",
        "viz",
        "shania",
    ],
)
def test_single_agent_yaml_loadable(yaml_name: str):
    """每个已注册专家 agent 的 yaml 单独加载成功且 agent_id 字段非空"""
    config = agent_loader._load_single_agent(AI_DIR / f"{yaml_name}.yaml")
    assert config is not None, f"{yaml_name}.yaml 加载失败"
    assert config.get("agent_id"), f"{yaml_name}.yaml 缺少 agent_id"
    assert config.get("system_prompt"), f"{yaml_name}.yaml 未解析出 system_prompt"


@pytest.mark.unit
def test_router_prompt_uses_runtime_catalog_instead_of_static_candidates():
    """Router 只能依据运行时目录，避免静态候选表随 Agent 增删而漂移。"""
    prompt_text = ROUTER_PROMPT_MD.read_text(encoding="utf-8")
    assert "运行时候选目录（唯一依据）" in prompt_text
    assert "不维护、记忆或引用任何静态 Agent 名单" in prompt_text
    assert "| agent_id | 名称 | 适用请求 |" not in prompt_text
    assert "领域路由与执行授权分离" in prompt_text
    assert "不能仅因“单细胞”创建流程型 Case" in prompt_text


@pytest.mark.unit
def test_site_yaml_enabled_agents_have_config_files():
    """data/CygnusX.yaml agents.enabled 中的每个 agent 都有对应配置文件"""
    enabled = agent_loader._load_enabled_agents(SITE_YAML)
    assert enabled == [
        "router",
        "general",
        "agentteams_manager",
        "rnaseq",
        "atacseq",
        "scrna",
        "scrna_upstream",
        "scrna_integration",
        "scrna_advanced",
        "code",
        "viz",
        "data",
        "qc",
        "delivery",
        "cloud_ops",
        "shania",
        "mcp_builder",
        "skill_builder",
    ]
    for name in enabled:
        assert (AI_DIR / f"{name}.yaml").exists(), f"{name}.yaml 不存在"
