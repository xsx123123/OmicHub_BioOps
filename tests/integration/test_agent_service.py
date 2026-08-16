"""Agent 应用服务集成测试 — 覆盖创建/更新/停用默认等核心流程。"""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.schemas.agent import CreateAgentRequest, UpdateAgentRequest
from omichub.application.services.agent_service import AgentService
from omichub.core.exceptions import BusinessError
from omichub.infrastructure.database.models.agent import AgentTemplateModel
from omichub.infrastructure.database.models.ai_provider import AIProviderConfigModel
from omichub.infrastructure.database.session import get_session_factory

pytestmark = pytest.mark.integration


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    """提供已回滚的数据库会话，避免测试污染真实数据。"""
    factory = get_session_factory()
    async with factory() as session:
        # 简单探测数据库是否可达，不可达时跳过本文件全部测试
        try:
            await session.execute(text("SELECT 1"))
        except Exception as exc:
            pytest.skip(f"数据库未就绪，跳过 service 集成测试: {exc}")
        yield session
        await session.rollback()


@pytest.fixture
async def service(db: AsyncSession) -> AgentService:
    return AgentService(db)


async def test_create_agent_does_not_duplicate_is_active(service: AgentService) -> None:
    """创建 Agent 时不应因重复传入 is_active 关键字而抛出 TypeError。"""
    req = CreateAgentRequest(name="创建测试", category="general")
    created = await service.create_agent(req)
    assert created.name == "创建测试"
    assert created.is_active is True
    assert created.is_builtin is False


async def test_update_agent_returns_dto(service: AgentService) -> None:
    """更新 Agent 后应能正常序列化为 DTO，不应触发懒加载异常。"""
    req = CreateAgentRequest(name="更新测试", category="general")
    created = await service.create_agent(req)

    updated = await service.update_agent(
        created.agent_id,
        UpdateAgentRequest(name="更新测试-改", system_prompt="新设定"),
    )
    assert updated.name == "更新测试-改"
    assert updated.system_prompt == "新设定"
    assert updated.updated_at is not None


async def test_toggle_default_agent_transfers_default(service: AgentService) -> None:
    """停用默认 Agent 时应自动将默认状态转移给同分类其他启用 Agent。"""
    # 使用唯一分类，避免与数据库中已有内置 Agent 互相干扰
    category = f"test-{uuid4().hex[:8]}"
    a1 = await service.create_agent(CreateAgentRequest(name="默认一号", category=category))
    a2 = await service.create_agent(CreateAgentRequest(name="默认二号", category=category))

    await service.set_default_agent(a1.agent_id)

    # 停用默认 Agent
    toggled = await service.toggle_agent(a1.agent_id)
    assert toggled.is_active is False
    assert toggled.is_default is False

    # 默认状态应转移给 a2
    successor = await service.get_agent(a2.agent_id)
    assert successor is not None
    assert successor.is_default is True
    assert successor.is_active is True


async def test_toggle_default_agent_without_successor_raises(service: AgentService) -> None:
    """当同分类没有其他启用 Agent 时，停用默认 Agent 应抛出业务异常。"""
    category = f"test-{uuid4().hex[:8]}"
    agent = await service.create_agent(CreateAgentRequest(name="孤独默认", category=category))
    await service.set_default_agent(agent.agent_id)

    with pytest.raises(BusinessError):
        await service.toggle_agent(agent.agent_id)


async def test_update_agent_syncs_model_labels(service: AgentService, db: AsyncSession) -> None:
    """更新 model_id 时应同步 model_engine / model_name。"""
    provider = AIProviderConfigModel(
        id=uuid4(),
        name="测试模型配置",
        provider_type="kimi",
        model="qwen3.7-plus",
        base_url="https://example.com/v1",
        api_key="sk-test",
        is_active=True,
    )
    db.add(provider)
    await db.flush()

    agent = await service.create_agent(CreateAgentRequest(name="模型同步", category="general"))
    updated = await service.update_agent(
        agent.agent_id,
        UpdateAgentRequest(model_id=provider.id),
    )
    assert updated.model_id == provider.id
    assert updated.model_name == "测试模型配置"
    assert updated.model_engine == "qwen3.7-plus"


async def test_update_agent_with_empty_model_id_clears_labels(service: AgentService) -> None:
    """清空 model_id 时应同时清空 model_engine / model_name。"""
    agent = await service.create_agent(
        CreateAgentRequest(name="清空模型", category="general", model_id=None)
    )
    updated = await service.update_agent(
        agent.agent_id,
        UpdateAgentRequest(model_id=None),
    )
    assert updated.model_id is None
    assert updated.model_name == ""
    assert updated.model_engine == ""


async def test_update_agent_with_nonexistent_model_id_raises(service: AgentService) -> None:
    """更新 Agent 时传入不存在的 model_id 应抛出业务异常，而不是数据库 500。"""
    agent = await service.create_agent(CreateAgentRequest(name="模型校验", category="general"))
    with pytest.raises(BusinessError, match="模型配置不存在"):
        await service.update_agent(
            agent.agent_id,
            UpdateAgentRequest(model_id=uuid4()),
        )


async def test_update_agent_with_null_mcps_and_skills(service: AgentService) -> None:
    """mcp_ids / skill_ids 传 null 时应归一化为空数组，不触发 500。"""
    agent = await service.create_agent(CreateAgentRequest(name="空数组", category="general"))
    updated = await service.update_agent(
        agent.agent_id,
        UpdateAgentRequest(mcp_ids=None, skill_ids=None),
    )
    assert updated.mcp_ids == []
    assert updated.skill_ids == []


async def test_update_default_agent_with_model_and_mounts(
    service: AgentService, db: AsyncSession
) -> None:
    """默认 Agent 也可以正常修改绑定模型和 MCP/技能挂载，不应报系统错误。"""
    provider = AIProviderConfigModel(
        id=uuid4(),
        name="默认模型",
        provider_type="openai",
        model="qwen3.7-plus",
        base_url="https://example.com/v1",
        api_key="sk-test",
        is_active=True,
    )
    db.add(provider)
    await db.flush()

    agent = await service.create_agent(CreateAgentRequest(name="默认助手", category="general"))
    await service.set_default_agent(agent.agent_id)

    mcp_ids = [str(uuid4()), str(uuid4())]
    updated = await service.update_agent(
        agent.agent_id,
        UpdateAgentRequest(
            model_id=provider.id,
            mcp_ids=mcp_ids,
            skill_ids=["skill-a"],
            features={"enable_web_search": True},
            is_default=True,
        ),
    )
    assert updated.model_id == provider.id
    assert updated.model_name == "默认模型"
    assert updated.model_engine == "qwen3.7-plus"
    assert updated.mcp_ids == mcp_ids
    assert updated.skill_ids == ["skill-a"]
    assert updated.is_default is True


async def test_update_agent_rejects_inactive_model(service: AgentService, db: AsyncSession) -> None:
    """绑定到未启用模型时应给出明确业务错误，而不是保存后调用失败。"""
    provider = AIProviderConfigModel(
        id=uuid4(),
        name="停用模型",
        provider_type="openai",
        model="qwen3.7-plus",
        base_url="https://example.com/v1",
        api_key="sk-test",
        is_active=False,
    )
    db.add(provider)
    await db.flush()

    agent = await service.create_agent(CreateAgentRequest(name="停用模型测试", category="general"))
    with pytest.raises(BusinessError, match="模型配置"):
        await service.update_agent(
            agent.agent_id,
            UpdateAgentRequest(model_id=provider.id),
        )


async def test_list_agents_reconciles_stale_binding_to_active_default(
    service: AgentService, db: AsyncSession
) -> None:
    """停用 Provider 的历史绑定应迁移到当前默认模型，并刷新助手展示名称。"""
    await db.execute(update(AIProviderConfigModel).values(is_default=False))
    retired_provider = AIProviderConfigModel(
        id=uuid4(),
        name="旧模型配置",
        provider_type="openai",
        model="legacy-model",
        base_url="https://example.com/v1",
        api_key="sk-old",
        is_active=False,
    )
    qwen_provider = AIProviderConfigModel(
        id=uuid4(),
        name="Qwen 3.7 Flash",
        provider_type="openai_compatible",
        model="qwen3.7-flash",
        base_url="https://example.com/v1",
        api_key="sk-qwen",
        is_active=True,
        is_default=True,
    )
    db.add_all([retired_provider, qwen_provider])
    await db.flush()

    stale_agent = AgentTemplateModel(
        agent_id=f"stale-model-{uuid4().hex[:8]}",
        name="旧模型助手",
        category="general",
        model_id=retired_provider.id,
        model_name=retired_provider.name,
        model_engine=retired_provider.model,
    )
    db.add(stale_agent)
    await db.flush()

    agents = await service.list_agents()
    repaired = next(agent for agent in agents if agent.agent_id == stale_agent.agent_id)

    assert repaired.model_id == qwen_provider.id
    assert repaired.model_name == "Qwen 3.7 Flash"
    assert repaired.model_engine == "qwen3.7-flash"


async def test_reconcile_binds_unbound_builtin_agent_to_active_default(
    service: AgentService, db: AsyncSession
) -> None:
    """历史内置 Agent 缺失 model_id 时应恢复到可用默认模型。"""
    await db.execute(update(AIProviderConfigModel).values(is_default=False))
    provider = AIProviderConfigModel(
        id=uuid4(),
        name="Studio 默认模型",
        provider_type="openai_compatible",
        model="qwen3.7-plus",
        base_url="https://example.com/v1",
        api_key="sk-default",
        is_active=True,
        is_default=True,
    )
    builtin_agent = AgentTemplateModel(
        agent_id=f"builtin-unbound-{uuid4().hex[:8]}",
        name="单细胞分析师",
        category="scrna",
        is_builtin=True,
        model_id=None,
        model_name="qwen3.7-max",
        model_engine="",
    )
    db.add_all([provider, builtin_agent])
    await db.flush()

    await service._reconcile_model_bindings()

    assert builtin_agent.model_id == provider.id
    assert builtin_agent.model_name == "Studio 默认模型"
    assert builtin_agent.model_engine == "qwen3.7-plus"
