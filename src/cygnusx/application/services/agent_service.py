"""Agent 应用服务 — 模板 CRUD、内置 Agent 初始化、调度上下文组装

调度中枢调用 ``assemble_context(agent_id)`` 拿到一次 LLM 请求所需的全部拼装件：
绑定的模型配置、系统提示词（含技能 prompt 后缀）、OpenAI tools、MCP server 实体。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.schemas.agent import (
    USER_AGENT_FEATURE_KEYS,
    AgentTemplateDTO,
    CreateAgentRequest,
    UpdateAgentRequest,
    UserAgentCapabilityDTO,
    UserAgentCapabilityRequest,
    UserSelectableMCPDTO,
)
from cygnusx.application.services.agent_handoff_service import HANDOFF_TOOL_NAME
from cygnusx.application.services.site_settings_service import SiteSettingsService
from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import BusinessError, NotFoundError
from cygnusx.domain.mcp.entities import MCPServer, MCPToolRegistry
from cygnusx.domain.mcp.value_objects import (
    ReviewStatus,
    ServerPool,
    ServerStatus,
    Transport,
)
from cygnusx.domain.skill.entities import Skill
from cygnusx.infrastructure.config.agent_ability_catalog import agent_ability_catalog
from cygnusx.infrastructure.config.agent_loader import load_agent_configs
from cygnusx.infrastructure.database.models.agent import (
    AgentTemplateModel,
    UserAgentCapabilityModel,
)
from cygnusx.infrastructure.database.models.ai_provider import AIProviderConfigModel
from cygnusx.infrastructure.database.models.mcp import MCPServerModel
from cygnusx.infrastructure.database.models.skill import SkillModel
from cygnusx.infrastructure.database.repositories.mcp_repository import (
    SqlAlchemyMCPServerRepository,
)
from cygnusx.infrastructure.mcp.conda_meta_preset import (
    CONDA_META_MCP_SERVER_ID,
    CONDA_META_MCP_SERVER_NAME,
)
from cygnusx.infrastructure.mcp.pipeline_preset import (
    CYGNUSX_PIPELINES_SERVER_ID,
    CYGNUSX_PIPELINES_SERVER_NAME,
)
from cygnusx.infrastructure.mcp.presets import (
    CYGNUSX_PLATFORM_SERVER_ID,
    CYGNUSX_TOOLS_SERVER_ID,
    CYGNUSX_TOOLS_SERVER_NAME,
    SEQOUT_SERVER_ID,
    SEQOUT_SERVER_NAME,
    WORKSPACE_FILES_SYSTEM_PROMPT_SUFFIX,
    get_preset_by_name,
)
from cygnusx.tools.schema_loader import schema_loader

logger = logging.getLogger(__name__)

# 内置预设 server 的确定性常量 ID，按名称索引。
# 用于兼容历史 DB 记录 ID 漂移（记录名相同但 id 与确定性常量不一致）：
# 组装工具白名单时若按 server.id 未命中，可退回按预设名称匹配白名单。
_PRESET_IDS_BY_NAME: dict[str, uuid.UUID] = {
    "cygnusx-platform": CYGNUSX_PLATFORM_SERVER_ID,
    CYGNUSX_PIPELINES_SERVER_NAME: CYGNUSX_PIPELINES_SERVER_ID,
    CYGNUSX_TOOLS_SERVER_NAME: CYGNUSX_TOOLS_SERVER_ID,
    SEQOUT_SERVER_NAME: SEQOUT_SERVER_ID,
    CONDA_META_MCP_SERVER_NAME: CONDA_META_MCP_SERVER_ID,
}


def _mcp_mount_allowed_for_agent(server: MCPServer) -> bool:
    """审批链门禁：builder 实验池（AI 生成）MCP 未经人工审核通过不得挂载执行。

    预置 preset 与非 builder 的手工注册 server 位于 production 池，且
    ``review_status`` 默认值即为 APPROVED，不会被此条件误伤。
    """
    if server.pool != ServerPool.EXPERIMENTAL:
        return True
    return server.review_status == ReviewStatus.APPROVED

AGENTTEAMS_CASE_SYSTEM_PROMPT_SUFFIX = """## AgentTeams 协作 Case

你可以使用 `create_agentteams_case` 创建 AgentTeams 协作 Case。它适用于需要跨角色协作、
人工审批、长耗时流程执行、质量闸门或正式交付验收的任务。

- 普通问答、参数解释、一次性小任务和轻量并行任务不要创建 Case。
- 目标、项目、流程或交付物不明确时先澄清；不得在信息不足时发起建单。
- 当任务已明确且确实需要正式协作时，先用一句话说明触发理由，并在同一轮主动调用该工具
  展示确认卡；不要只给出“是否创建”的文字建议，也不要要求用户另行寻找手动入口。
- 首次工具调用只发起受控确认，不得伪造 `_confirmed`。用户点击确认卡后，平台才会创建 Case；
  创建后用户可在聊天卡片中随时取消。
- 若请求来自多专家会诊，须把会诊事件提供的 `consultation_id` 和 `consultation_summary`
  分别填入 `origin_consultation_id`、`consultation_summary`，以保留 Case 来源追溯。
- 创建成功后告知用户打开协作 Case，继续完成预检、审批和交付验收。
"""

AGENT_COMMUNICATION_SYSTEM_PROMPT_SUFFIX = """## 平台沟通与执行规范

- 默认使用专业、自然、克制的中文：先说明当前结论或状态，再给出依据和下一步。
- 不使用卖萌语气、颜文字或无必要的 emoji；不要以“请上传数据，我来一步步操作”一类
  空泛话术收尾。缺少输入时，明确列出缺少的文件、字段、分组或参数，并说明如何提供。
- 先检查当前会话已经给出的信息和可用工作区文件；能通过工具确认的事实必须调用工具，
  工具返回后只陈述真实结果。已完成、待确认和未能执行的事项必须明确区分。
- 用户要求执行分析或产出文件时，先给出简短执行计划；完成后交付结果路径、关键参数和
  可复现的下一步。没有执行就不要暗示已经完成。
- 任务不属于当前职责且系统提供了转交工具时，选择最合适的 Agent 并转交；不要让用户
  自己在助手列表中猜测该选谁。
"""

ROUTER_COMMUNICATION_SYSTEM_PROMPT_SUFFIX = """## 路由输出纪律

- 你的职责是理解意图、选择可用专家并输出规定的路由 JSON；不要执行分析、不要生成工作台
  指令，也不要向用户输出解释性话术。
- 不使用 emoji、寒暄或“请上传数据”式兜底。输入信息不足时仍须根据当前可用目录选择最
  合适的首接 Agent，并将缺失项交由该 Agent 继续澄清。
- 运行时提供的 Agent 目录是唯一有效候选集；不得引用目录外 Agent，也不得让前端规则替你
  做领域判断。
"""

PERSONA_SYSTEM_PROMPT_HEADER = "## Agent Persona（仅影响表达与协作方式）"
PERSONA_TEXT_FIELDS = (
    ("archetype", "角色原型"),
    ("working_style", "工作方式"),
    ("communication_style", "表达风格"),
    ("challenge_style", "质疑与追问方式"),
)
PERSONA_MAX_FIELD_CHARS = 600
PERSONA_MAX_TRAITS = 8
SHARED_SANDBOX_PROTOCOL_HEADER = "## 共享沙盒协议"


def _bounded_persona_text(value: Any) -> str:
    """Normalize admin-authored Persona prose without changing its meaning."""
    return re.sub(r"\s+", " ", str(value or "")).strip()[:PERSONA_MAX_FIELD_CHARS]


def render_persona_system_prompt(features: dict[str, Any] | None) -> str:
    """Render only stable Persona prose into a deterministic system-prompt block.

    Persona is presentation guidance, not a capability declaration.  In particular,
    status_lines are UI-only and the renderer deliberately ignores unknown keys such
    as tools, permissions, quotas, or a per-run persona_context.
    """
    raw = (features or {}).get("persona")
    if not isinstance(raw, dict):
        return ""

    lines = [PERSONA_SYSTEM_PROMPT_HEADER]
    archetype_and_style: list[str] = []
    for key, label in PERSONA_TEXT_FIELDS:
        value = _bounded_persona_text(raw.get(key))
        if value:
            archetype_and_style.append(f"- {label}：{value}")
    traits = [
        _bounded_persona_text(item)
        for item in raw.get("traits", [])
        if _bounded_persona_text(item)
    ][:PERSONA_MAX_TRAITS]
    if traits:
        archetype_and_style.append(f"- 稳定特质：{'、'.join(traits)}")
    if not archetype_and_style:
        return ""

    lines.extend(archetype_and_style)
    lines.extend(
        [
            "",
            "表达边界：",
            "- 以上内容只用于调整表达、解释顺序、追问方式和风险提醒。",
            "- 不得据此新增、移除或扩大工具、MCP、Skill、审批、配额或数据访问权限。",
            "- 不得把 Persona 偏好当作事实、证据、质量标准或执行结果；事实仍以工具和真实结果为准。",
        ]
    )
    return "\n".join(lines)


def _generate_agent_id(name: str) -> str:
    """根据名称生成唯一 agent_id"""
    base = re.sub(r"[^a-z0-9\u4e00-\u9fa5]+", "-", name.strip().lower()).strip("-") or "agent"
    suffix = uuid.uuid4().hex[:6]
    return f"{base}-{suffix}"


@dataclass
class AgentContext:
    """调度中枢组装出的一次请求上下文"""

    agent: AgentTemplateModel
    model_config: AIProviderConfigModel | None
    system_prompt: str
    tools: list[dict[str, Any]] = field(default_factory=list)
    mcp_servers: list[MCPServer] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)
    features: dict[str, Any] = field(default_factory=dict)
    user_capabilities_customized: bool = False
    temperature: float = 0.7
    max_tokens: int = 65536


class AgentService:
    """Agent 模板应用服务"""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._mcp_repo = SqlAlchemyMCPServerRepository(db)

    # --- 内置 Agent 初始化 ---

    async def ensure_builtin_agents(self) -> None:
        """从 YAML 加载内置 Agent 配置，幂等落库"""
        yaml_configs = load_agent_configs()
        if not yaml_configs:
            return

        configured_skill_ids = {
            str(skill_id).strip()
            for cfg in yaml_configs
            for skill_id in (cfg.get("skill_ids") or [])
            if str(skill_id).strip()
        }
        await self._ensure_configured_marketplace_skills(configured_skill_ids)

        # 预加载所有启用的模型配置，按 name 建索引
        model_result = await self._db.execute(
            select(AIProviderConfigModel).where(
                AIProviderConfigModel.is_active == True  # noqa: E712
            )
        )
        active_models = list(model_result.scalars().all())
        models_by_name = {m.name: m for m in active_models}
        models_by_id = {m.id: m for m in active_models}
        default_model = next((model for model in active_models if model.is_default), None)
        fallback_model = default_model or (active_models[0] if active_models else None)

        for cfg in yaml_configs:
            existing = await self.get_agent(cfg["agent_id"])
            if existing is not None:
                # 内置 Agent 的 YAML 是平台能力声明的来源；同步 features，
                # 但不覆盖管理员可能调整过的模型、提示词或绑定关系。
                if existing.is_builtin:
                    existing_features = dict(existing.features or {})
                    existing_features.update(dict(cfg.get("features") or {}))
                    if cfg.get("studio"):
                        existing_features["studio"] = cfg["studio"]
                    else:
                        existing_features.pop("studio", None)
                    existing.features = existing_features
                    # 内置 Agent 的 MCP/Skill 绑定由 YAML tool_packs 声明驱动：以声明集合
                    # 为基础重建（而不是与历史值合并），从而清除历史漂移（如通用/代码/可视化
                    # 助手误挂 ensmbl/go-server/pipelines）与已失效的旧 server ID。
                    # 核心 builtin 预设 cygnusx-tools（富集/绘图/记忆/交接/子Agent/Case 工具）、
                    # cygnusx-platform（工作区文件）与 seqout（公共数据库检索）始终保留，
                    # 其余 server 一律以声明为准。
                    declared_mcp_ids = [
                        str(value)
                        for value in (cfg.get("mcp_ids") or [])
                        if self._parse_uuid(value)
                    ]
                    configured_mcp_ids = list(
                        dict.fromkeys(
                            [
                                *declared_mcp_ids,
                                str(CYGNUSX_TOOLS_SERVER_ID),
                                str(CYGNUSX_PLATFORM_SERVER_ID),
                                str(SEQOUT_SERVER_ID),
                            ]
                        )
                    )
                    existing.mcp_ids = configured_mcp_ids
                    declared_skills = [
                        str(skill_id).strip()
                        for skill_id in (cfg.get("skill_ids") or [])
                        if str(skill_id).strip()
                    ]
                    existing.skill_ids = list(dict.fromkeys(declared_skills))

                    if existing_features.get("managed_prompt") and cfg.get("system_prompt"):
                        existing.system_prompt = str(cfg["system_prompt"])
                    if existing_features.get("managed_profile"):
                        for field_name in (
                            "name",
                            "description",
                            "welcome_message",
                            "avatar",
                            "color",
                            "category",
                            "temperature",
                            "max_tokens",
                            "is_active",
                        ):
                            if field_name in cfg:
                                setattr(existing, field_name, cfg[field_name])

                    if existing.model_id not in models_by_id:
                        configured_model = models_by_name.get(str(cfg.get("model") or ""))
                        target_model = configured_model or fallback_model
                    else:
                        target_model = None
                    if target_model is not None:
                        existing.model_id = target_model.id
                        existing.model_name = target_model.name
                        existing.model_engine = target_model.model
                continue

            # 按 model name 解析 model_id
            model_name = cfg.get("model", "")
            model_id = None
            model_engine = ""
            if model_name and model_name in models_by_name:
                provider = models_by_name[model_name]
                model_id = provider.id
                model_engine = provider.model  # 真实模型名

            # 构建落库字段：mcp_ids/skill_ids 以 YAML tool_packs 声明的集合为准，
            # 不再隐式注入默认 server（tool_packs 已保证 tools/platform 的绑定）。
            mcp_ids = cfg.get("mcp_ids", [])
            # 统一功能开关：yaml features 原样保留，studio 段归入 features["studio"]，
            # 不新增列（调度中枢经 AgentContext.features 读取）
            features = dict(cfg.get("features") or {})
            if cfg.get("studio"):
                features["studio"] = cfg["studio"]
            # 新建 builtin Agent 同样保证三个核心预设在场：tools/platform/seqout
            mcp_ids = list(
                dict.fromkeys(
                    [
                        *(mcp_ids or []),
                        str(CYGNUSX_TOOLS_SERVER_ID),
                        str(CYGNUSX_PLATFORM_SERVER_ID),
                        str(SEQOUT_SERVER_ID),
                    ]
                )
            )
            agent_data = {
                "agent_id": cfg["agent_id"],
                "name": cfg.get("name", ""),
                "description": cfg.get("description", ""),
                "avatar": cfg.get("avatar", "\U0001f916"),
                "color": cfg.get("color", "#4f8ef7"),
                "category": cfg.get("category", "general"),
                "model_id": model_id,
                "model_name": model_name,
                "model_engine": model_engine,
                "system_prompt": cfg.get("system_prompt", ""),
                "welcome_message": cfg.get("welcome_message", ""),
                "mcp_ids": mcp_ids,
                "skill_ids": cfg.get("skill_ids", []),
                "features": features,
                "temperature": cfg.get("temperature", 0.7),
                "max_tokens": cfg.get("max_tokens", 65536),
                "is_builtin": True,
                "is_active": True,
            }
            self._db.add(AgentTemplateModel(**agent_data))
        await self._db.flush()

    async def _ensure_configured_marketplace_skills(self, skill_ids: set[str]) -> None:
        """安装 YAML 声明且存在于内置市场的 Skill，保留外部 Skill 的管理方式。"""
        if not skill_ids:
            return

        from cygnusx.application.services.skill_import_service import SkillImportService
        from cygnusx.core.config import get_settings

        marketplace = get_settings().skill_marketplace_dir
        available_ids = {
            skill_id
            for skill_id in skill_ids
            if (Path(marketplace) / skill_id / "SKILL.md").is_file()
        }
        if not available_ids:
            return

        result = await self._db.execute(
            select(SkillModel.skill_id).where(SkillModel.skill_id.in_(available_ids))
        )
        installed_ids = {str(skill_id) for skill_id in result.scalars().all()}
        installer = SkillImportService(self._db)
        for skill_id in sorted(available_ids - installed_ids):
            try:
                await installer.install_marketplace(skill_id)
            except BusinessError as exc:
                logging.getLogger(__name__).warning(
                    "内置 Agent Skill 自动安装失败 %s: %s", skill_id, exc
                )

    # --- 查询 ---

    async def list_agents(self, active_only: bool = False) -> list[AgentTemplateDTO]:
        await self.ensure_builtin_agents()
        await self._reconcile_model_bindings()
        query = select(AgentTemplateModel)
        if active_only:
            query = query.where(AgentTemplateModel.is_active == True)  # noqa: E712
        query = query.order_by(AgentTemplateModel.is_default.desc(), AgentTemplateModel.created_at)
        result = await self._db.execute(query)
        return [self._to_dto(a) for a in result.scalars().all()]

    async def list_user_selectable_mcps(self) -> list[UserSelectableMCPDTO]:
        """列出普通用户可挂载的启用 MCP，不返回命令、环境变量等管理配置。"""
        result = await self._db.execute(
            select(MCPServerModel)
            .where(MCPServerModel.is_enabled == True)  # noqa: E712
            .order_by(MCPServerModel.name)
        )
        return [
            UserSelectableMCPDTO(
                id=server.id,
                name=server.name,
                description=server.description or "",
                status=server.status or "offline",
                tool_count=len(server.tools or []),
            )
            for server in result.scalars().all()
        ]

    async def get_agent(self, agent_id: str) -> AgentTemplateModel | None:
        result = await self._db.execute(
            select(AgentTemplateModel).where(AgentTemplateModel.agent_id == agent_id)
        )
        return result.scalar_one_or_none()

    async def get_agent_dto(self, agent_id: str) -> AgentTemplateDTO:
        await self._reconcile_model_bindings()
        agent = await self.get_agent(agent_id)
        if not agent:
            raise NotFoundError("Agent 不存在")
        return self._to_dto(agent)

    async def get_user_capabilities(
        self, user_id: str, agent_id: str
    ) -> UserAgentCapabilityDTO:
        """返回用户在该 Agent 上的有效能力选择，不暴露或修改系统提示词。"""
        agent = await self.get_agent(agent_id)
        if agent is None or not agent.is_active:
            raise NotFoundError("Agent 不存在或已停用")
        capability = await self._get_user_capability(user_id, agent_id)
        if capability is None:
            return UserAgentCapabilityDTO(
                agent_id=agent_id,
                model_id=agent.model_id,
                mcp_ids=[str(item) for item in (agent.mcp_ids or [])],
                skill_ids=[str(item) for item in (agent.skill_ids or [])],
                features=self._effective_user_features(agent.features),
                is_customized=False,
            )
        return UserAgentCapabilityDTO(
            agent_id=agent_id,
            model_id=capability.model_id or agent.model_id,
            mcp_ids=[str(item) for item in (capability.mcp_ids or [])],
            skill_ids=[str(item) for item in (capability.skill_ids or [])],
            features=self._effective_user_features(agent.features, capability.features),
            is_customized=True,
        )

    async def update_user_capabilities(
        self, user_id: str, agent_id: str, req: UserAgentCapabilityRequest
    ) -> UserAgentCapabilityDTO:
        """保存用户自己的模型、MCP、Skill 选择，全部限制在管理员已启用资产内。"""
        agent = await self.get_agent(agent_id)
        if agent is None or not agent.is_active:
            raise NotFoundError("Agent 不存在或已停用")

        mcp_ids = self._dedupe_ids(req.mcp_ids)
        skill_ids = self._dedupe_ids(req.skill_ids)
        await self._validate_user_capability_assets(req.model_id, mcp_ids, skill_ids)
        features = self._validate_user_feature_selection(agent.features, req.features)

        capability = await self._get_user_capability(user_id, agent_id)
        if capability is None:
            capability = UserAgentCapabilityModel(
                user_id=uuid.UUID(user_id),
                agent_id=agent_id,
            )
            self._db.add(capability)
        capability.model_id = req.model_id
        capability.mcp_ids = mcp_ids
        capability.skill_ids = skill_ids
        capability.features = features
        await self._db.flush()
        return await self.get_user_capabilities(user_id, agent_id)

    async def reset_user_capabilities(self, user_id: str, agent_id: str) -> None:
        """删除个人覆盖，让 Agent 恢复管理员模板配置。"""
        capability = await self._get_user_capability(user_id, agent_id)
        if capability is not None:
            await self._db.delete(capability)
            await self._db.flush()

    async def _get_user_capability(
        self, user_id: str, agent_id: str
    ) -> UserAgentCapabilityModel | None:
        result = await self._db.execute(
            select(UserAgentCapabilityModel).where(
                UserAgentCapabilityModel.user_id == uuid.UUID(user_id),
                UserAgentCapabilityModel.agent_id == agent_id,
            )
        )
        return result.scalar_one_or_none()

    async def _validate_user_capability_assets(
        self,
        model_id: uuid.UUID | None,
        mcp_ids: list[str],
        skill_ids: list[str],
    ) -> None:
        if model_id is not None:
            model = await self._resolve_model(model_id)
            if model is None:
                raise BusinessError("所选模型不存在或已停用")

        if mcp_ids:
            try:
                mcp_uuids = [uuid.UUID(item) for item in mcp_ids]
            except ValueError as exc:
                raise BusinessError("MCP 标识无效") from exc
            result = await self._db.execute(
                select(MCPServerModel.id).where(
                    MCPServerModel.id.in_(mcp_uuids), MCPServerModel.is_enabled == True,  # noqa: E712
                    # 审批链：builder 实验池 server 须审核通过方可挂载；
                    # preset / 手工注册 server（production 池，默认 approved）不受影响。
                    or_(
                        MCPServerModel.pool.is_(None),
                        MCPServerModel.pool != ServerPool.EXPERIMENTAL.value,
                        MCPServerModel.review_status == ReviewStatus.APPROVED.value,
                    ),
                )
            )
            if len(set(result.scalars().all())) != len(mcp_uuids):
                raise BusinessError("所选 MCP 不存在或未启用")

        if skill_ids:
            result = await self._db.execute(
                select(SkillModel.skill_id).where(
                    SkillModel.skill_id.in_(skill_ids), SkillModel.is_active == True  # noqa: E712
                )
            )
            if set(result.scalars().all()) != set(skill_ids):
                raise BusinessError("所选 Skill 不存在或未启用")

    @staticmethod
    def _dedupe_ids(items: list[str]) -> list[str]:
        return list(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))

    @staticmethod
    def _effective_user_features(
        agent_features: dict[str, Any] | None,
        user_features: dict[str, bool] | None = None,
    ) -> dict[str, bool]:
        """用户只能关闭管理员开放的扩展能力，不能越权启用管理员关闭的能力。"""
        admin_features = dict(agent_features or {})
        saved_features = dict(user_features or {})
        return {
            key: bool(admin_features.get(key)) and bool(saved_features.get(key, admin_features.get(key)))
            for key in USER_AGENT_FEATURE_KEYS
        }

    @staticmethod
    def _validate_user_feature_selection(
        agent_features: dict[str, Any] | None,
        features: dict[str, bool],
    ) -> dict[str, bool]:
        invalid_keys = set(features) - USER_AGENT_FEATURE_KEYS
        if invalid_keys:
            raise BusinessError("不支持修改该 Agent 功能开关")
        admin_features = dict(agent_features or {})
        enabled_features = {key: bool(value) for key, value in features.items()}
        if any(enabled and not admin_features.get(key) for key, enabled in enabled_features.items()):
            raise BusinessError("不能启用管理员未开放的 Agent 功能")
        return enabled_features

    # --- CRUD ---

    async def update_agent(self, agent_id: str, req: UpdateAgentRequest) -> AgentTemplateDTO:
        agent = await self.get_agent(agent_id)
        if not agent:
            raise NotFoundError("Agent 不存在")
        try:
            data = req.model_dump(exclude_unset=True)
            if data.get("is_default"):
                await self._clear_other_defaults()
            self._normalize_json_lists(data)
            # 部分更新未提交 model_id 时，必须保留既有绑定及其展示标签。
            if "model_id" in data:
                await self._validate_model_id(data)
                await self._sync_model_labels(data)
            for key, value in data.items():
                setattr(agent, key, value)
            await self._db.flush()
            await self._db.refresh(agent)
            return self._to_dto(agent)
        except IntegrityError as exc:
            await self._db.rollback()
            raise BusinessError("绑定的模型配置不存在或数据冲突，请检查模型选择") from exc
        except SQLAlchemyError as exc:
            await self._db.rollback()
            import logging

            logging.getLogger(__name__).exception(f"更新 Agent {agent_id} 数据库错误: {exc}")
            raise BusinessError("保存 Agent 时数据库出错，请稍后重试或联系管理员") from exc

    async def create_agent(self, req: CreateAgentRequest) -> AgentTemplateDTO:
        agent_id = req.agent_id.strip() if req.agent_id else ""
        if not agent_id:
            agent_id = _generate_agent_id(req.name)
        if await self.get_agent(agent_id) is not None:
            raise BusinessError(f"Agent ID '{agent_id}' 已存在")
        try:
            data = req.model_dump()
            data["agent_id"] = agent_id
            data.pop("is_builtin", None)
            self._normalize_json_lists(data)
            await self._validate_model_id(data)
            await self._sync_model_labels(data)
            agent = AgentTemplateModel(**data)
            self._db.add(agent)
            await self._db.flush()
            await self._db.refresh(agent)
            return self._to_dto(agent)
        except IntegrityError as exc:
            await self._db.rollback()
            raise BusinessError("绑定的模型配置不存在或数据冲突，请检查模型选择") from exc
        except SQLAlchemyError as exc:
            await self._db.rollback()
            import logging

            logging.getLogger(__name__).exception(f"创建 Agent {agent_id} 数据库错误: {exc}")
            raise BusinessError("创建 Agent 时数据库出错，请稍后重试或联系管理员") from exc

    @staticmethod
    def _normalize_json_lists(data: dict[str, Any]) -> None:
        """把前端可能传 null 的数组字段归一为 []，避免 ORM 写入 JSONB null 后与默认值不一致。"""
        for key in ("mcp_ids", "skill_ids"):
            if key in data and data[key] is None:
                data[key] = []

    async def _validate_model_id(self, data: dict[str, Any]) -> None:
        """校验 model_id 指向的 provider 真实存在且已启用，避免数据库 FK 500 或调用失败。"""
        model_id = data.get("model_id")
        if model_id is None:
            return
        result = await self._db.execute(
            select(AIProviderConfigModel.id).where(
                AIProviderConfigModel.id == model_id,
                AIProviderConfigModel.is_active == True,  # noqa: E712
            )
        )
        if result.scalar_one_or_none() is None:
            raise BusinessError("绑定的模型配置不存在、已被删除或未启用，请重新选择模型")

    async def _sync_model_labels(self, data: dict[str, Any]) -> None:
        """根据 model_id 同步 model_engine / model_name，确保展示与调用一致。"""
        model_id = data.get("model_id")
        if model_id is None:
            data["model_engine"] = ""
            data["model_name"] = ""
            return
        result = await self._db.execute(
            select(AIProviderConfigModel).where(
                AIProviderConfigModel.id == model_id,
                AIProviderConfigModel.is_active == True,  # noqa: E712
            )
        )
        provider = result.scalar_one_or_none()
        if provider is not None:
            data["model_engine"] = provider.model
            data["model_name"] = provider.name
        else:
            # 校验已通过时这里不应发生；保留兜底，避免空指针
            data["model_engine"] = ""
            data["model_name"] = ""

    async def _reconcile_model_bindings(self) -> None:
        """修复历史失效绑定，并让助手展示标签与当前 Provider 配置保持一致。"""
        providers_result = await self._db.execute(
            select(AIProviderConfigModel)
            .where(AIProviderConfigModel.is_active == True)  # noqa: E712
            .order_by(
                AIProviderConfigModel.is_default.desc(),
                AIProviderConfigModel.updated_at.desc(),
            )
        )
        active_providers = list(providers_result.scalars().all())
        providers_by_id = {provider.id: provider for provider in active_providers}
        fallback_provider = active_providers[0] if active_providers else None

        agents_result = await self._db.execute(
            select(AgentTemplateModel).where(
                AgentTemplateModel.model_id.is_not(None) | (AgentTemplateModel.is_builtin == True)  # noqa: E712
            )
        )
        changed = False
        for agent in agents_result.scalars().all():
            provider = providers_by_id.get(agent.model_id) or fallback_provider
            if provider is None:
                if agent.model_id is not None or agent.model_name or agent.model_engine:
                    agent.model_id = None
                    agent.model_name = ""
                    agent.model_engine = ""
                    changed = True
                continue

            if (
                agent.model_id != provider.id
                or agent.model_name != provider.name
                or agent.model_engine != provider.model
            ):
                agent.model_id = provider.id
                agent.model_name = provider.name
                agent.model_engine = provider.model
                changed = True

        if changed:
            await self._db.flush()

    async def delete_agent(self, agent_id: str) -> bool:
        agent = await self.get_agent(agent_id)
        if not agent:
            raise NotFoundError("Agent 不存在")
        if agent.is_builtin:
            # 内置 Agent 软删除：若其是默认助手，先转移默认状态
            if agent.is_default:
                successor = await self._find_default_successor(agent.category, agent.agent_id)
                if successor is not None:
                    successor.is_default = True
                agent.is_default = False
            agent.is_active = False
            await self._db.flush()
            return True
        await self._db.delete(agent)
        await self._db.flush()
        return True

    async def toggle_agent(self, agent_id: str) -> AgentTemplateDTO:
        agent = await self.get_agent(agent_id)
        if not agent:
            raise NotFoundError("Agent 不存在")

        new_active = not agent.is_active
        if not new_active and agent.is_default:
            # 停用默认 Agent 前，需将默认状态转移给同分类其他启用 Agent
            successor = await self._find_default_successor(agent.category, agent.agent_id)
            if successor is None:
                raise BusinessError(
                    "当前分类至少需要保留一个启用的 Agent，请先创建或启用其他 Agent 再停用默认助手"
                )
            successor.is_default = True
            agent.is_default = False

        agent.is_active = new_active
        await self._db.flush()
        await self._db.refresh(agent)
        return self._to_dto(agent)

    async def _find_default_successor(
        self, category: str, exclude_agent_id: str
    ) -> AgentTemplateModel | None:
        """查找同分类下可接替默认状态的其他启用 Agent，按创建时间优先取最新的。"""
        result = await self._db.execute(
            select(AgentTemplateModel)
            .where(
                AgentTemplateModel.category == category,
                AgentTemplateModel.is_active == True,  # noqa: E712
                AgentTemplateModel.agent_id != exclude_agent_id,
            )
            .order_by(AgentTemplateModel.created_at.desc())
        )
        return result.scalars().first()

    async def set_default_agent(self, agent_id: str) -> None:
        agent = await self.get_agent(agent_id)
        if not agent:
            raise NotFoundError("Agent 不存在")
        await self._clear_other_defaults()
        agent.is_default = True
        await self._db.flush()

    async def _clear_other_defaults(self) -> None:
        result = await self._db.execute(
            select(AgentTemplateModel).where(AgentTemplateModel.is_default == True)  # noqa: E712
        )
        for existing in result.scalars().all():
            existing.is_default = False

    # --- 调度上下文组装 ---

    async def assemble_context(
        self,
        agent_id: str,
        user_id: str | None = None,
        tool_query: str | None = None,
        model_id: uuid.UUID | None = None,
    ) -> AgentContext | None:
        """供调度中枢调用：组装一次 LLM 请求所需的全部拼装件。

        Agent 自身不存在时返回 None；模型缺失/未启用通过 ChatChunk.error 在调用方处理。
        """
        await self._reconcile_model_bindings()
        agent = await self.get_agent(agent_id)
        if agent is None or not agent.is_active:
            return None

        runtime_model_id = model_id or agent.model_id
        runtime_mcp_ids = list(agent.mcp_ids or [])
        runtime_skill_ids = list(agent.skill_ids or [])
        runtime_features = dict(agent.features or {})
        user_capabilities_customized = False
        if user_id is not None:
            capability = await self._get_user_capability(user_id, agent_id)
            if capability is not None:
                user_capabilities_customized = True
                runtime_model_id = model_id or capability.model_id or agent.model_id
                runtime_mcp_ids = list(capability.mcp_ids or [])
                runtime_skill_ids = list(capability.skill_ids or [])
                runtime_features.update(
                    self._effective_user_features(agent.features, capability.features)
                )

        # 1. 解析绑定模型：优先用户选择，否则使用 Agent 模板绑定
        model_config = await self._resolve_model(runtime_model_id)
        if model_config is None:
            return AgentContext(
                agent=agent,
                model_config=None,
                system_prompt=self._append_communication_contract(
                    self._append_persona_prompt(agent.system_prompt, agent), agent
                ),
                features=runtime_features,
                user_capabilities_customized=user_capabilities_customized,
            )

        # 2. 收集绑定的 MCP server 及其工具，转成 OpenAI tools
        mcp_servers: list[MCPServer] = []
        tools: list[dict[str, Any]] = []
        tool_pack_config = self._tool_pack_config(runtime_features)
        mcp_uuids: list[uuid.UUID] = [
            u for u in (self._parse_uuid(mid) for mid in runtime_mcp_ids) if u is not None
        ]
        cygnusx_selected = CYGNUSX_TOOLS_SERVER_ID in mcp_uuids
        other_uuids = [u for u in mcp_uuids if u != CYGNUSX_TOOLS_SERVER_ID]
        if other_uuids:
            mcp_servers = await self._mcp_repo.get_by_ids(other_uuids)
            resolved_ids = {server.id for server in mcp_servers}
            # 兜底：预设 server 若确定性常量 ID 未命中（历史 ID 漂移或冷启动，
            # ensure_presets 尚未归一化），按名称解析，避免平台/流水线工具丢失。
            for preset_id, preset_name in (
                (CYGNUSX_PLATFORM_SERVER_ID, "cygnusx-platform"),
                (CYGNUSX_PIPELINES_SERVER_ID, CYGNUSX_PIPELINES_SERVER_NAME),
                (SEQOUT_SERVER_ID, SEQOUT_SERVER_NAME),
                (CONDA_META_MCP_SERVER_ID, CONDA_META_MCP_SERVER_NAME),
            ):
                if preset_id in mcp_uuids and preset_id not in resolved_ids:
                    by_name = await self._mcp_repo.get_by_name(preset_name)
                    if by_name is not None and by_name.is_enabled:
                        mcp_servers.append(by_name)
                        resolved_ids.add(by_name.id)
            for server in mcp_servers:
                # 离线/被禁用的外部 MCP 不向 LLM 暴露工具，避免模型选到必失败的慢工具。
                if not server.is_enabled:
                    continue
                # 审批链：builder 实验池 MCP 未通过人工审核不得挂载执行。
                if not _mcp_mount_allowed_for_agent(server):
                    continue
                allowed_names = tool_pack_config["mcp_tools"].get(str(server.id))
                if allowed_names is None:
                    # 历史 ID 漂移时白名单按确定性预设名再匹配一次
                    allowed_names = tool_pack_config["mcp_tools"].get(
                        str(_PRESET_IDS_BY_NAME.get(server.name, server.id))
                    )
                for t in server.tools:
                    if allowed_names and t.tool_name not in allowed_names:
                        continue
                    tools.append(
                        {
                            "type": "function",
                            "function": {
                                "name": t.tool_name,
                                "description": t.description or "",
                                "parameters": t.input_schema
                                or {"type": "object", "properties": {}},
                            },
                        }
                    )

        # 内置 preset 可能在应用启动并发初始化期间尚未落库；使用代码定义的
        # preset 作为运行时兜底，确保已绑定平台 MCP 的 Agent 不会丢失工具。
        # 已通过常量 ID 或名称回退解析到同名 server 时不再重复注入。
        if CYGNUSX_PLATFORM_SERVER_ID in mcp_uuids and not any(
            server.id == CYGNUSX_PLATFORM_SERVER_ID or server.name == "cygnusx-platform"
            for server in mcp_servers
        ):
            platform_preset = get_preset_by_name("cygnusx-platform")
            if platform_preset is not None:
                allowed_platform_names = tool_pack_config["mcp_tools"].get(
                    str(CYGNUSX_PLATFORM_SERVER_ID)
                )
                preset_tools = [
                    tool
                    for tool in platform_preset["tools"]
                    if not allowed_platform_names or tool["name"] in allowed_platform_names
                ]
                platform_tools = [
                    MCPToolRegistry(
                        tool_name=tool["name"],
                        description=tool["description"],
                        input_schema=tool["inputSchema"],
                        server_id=CYGNUSX_PLATFORM_SERVER_ID,
                        annotations=dict(tool.get("annotations") or {}),
                    )
                    for tool in preset_tools
                ]
                mcp_servers.append(
                    MCPServer(
                        id=CYGNUSX_PLATFORM_SERVER_ID,
                        name="cygnusx-platform",
                        description=platform_preset["description"],
                        transport=Transport.BUILTIN,
                        status=ServerStatus.ONLINE,
                        is_enabled=True,
                        is_preset=True,
                        tools=platform_tools,
                    )
                )
                tools.extend(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.tool_name,
                            "description": tool.description,
                            "parameters": tool.input_schema
                            or {"type": "object", "properties": {}},
                        },
                    }
                    for tool in platform_tools
                )

        # 2.5 自动注入 cygnusx-tools builtin preset（显式选中，或为空时保持默认）
        cygnusx_tools_server = self._build_cygnusx_tools_server()
        if cygnusx_tools_server and (cygnusx_selected or not mcp_uuids):
            mcp_servers.append(cygnusx_tools_server)
            builtin_tools = schema_loader.to_openai_tools()
            allowed_builtin_names = tool_pack_config["builtin_tools"]
            if allowed_builtin_names:
                builtin_tools = [
                    tool
                    for tool in builtin_tools
                    if tool.get("function", {}).get("name") in allowed_builtin_names
                ]
            builtin_tools = self._filter_runtime_builtin_tools(
                builtin_tools,
                agentteams_chat_entry_enabled=await self._agentteams_chat_entry_enabled(),
            )
            selection_config = schema_loader.get_config().tool_selection
            if str(selection_config.get("mode", "full")).lower() == "retrieval" and tool_query:
                pinned_names = {"ask_user", "transfer_to_agent", "web_search"}
                selected, selection_mode = schema_loader.select_tools(
                    tool_query, pinned_names=pinned_names
                )
                selected_names = {tool.name for tool in selected}
                logger.info(
                    "tool_selection mode=%s query=%r recalled_tools=%s",
                    selection_mode,
                    tool_query[:500],
                    sorted(selected_names),
                )
                builtin_tools = [
                    tool for tool in builtin_tools if tool.get("function", {}).get("name") in selected_names
                ]
            tools.extend(builtin_tools)

        # 3. 系统提示词 = Agent 设定 + 技能 L1 索引 + cygnusx-tools 清单。
        # 技能采用三层渐进式披露：L1 仅注入 name+description 索引（每技能约 100 tokens）；
        # L2 正文由模型命中后调用 use_skill 工具按需加载；L3 references/assets 用
        # skill_resource 按需读取。Studio 会话另用结构化 capability_catalog 机制。
        # Stable Persona is rendered once from the admin-controlled Agent template.
        # It is intentionally added before skills/tool hints and platform contracts;
        # those operational rules remain authoritative over presentation preferences.
        system_prompt = self._append_persona_prompt(agent.system_prompt, agent)
        skills = await self._load_skills(runtime_skill_ids)
        skill_index = self._build_skills_index(skills)
        if skill_index:
            system_prompt = f"{system_prompt}\n\n{skill_index}" if system_prompt else skill_index
        if skills:
            from cygnusx.domain.skill.services import build_skill_tools

            tools.extend(build_skill_tools(skills))
        if cygnusx_tools_server and (cygnusx_selected or not mcp_uuids):
            tool_hint = schema_loader.build_system_hint(
                {
                    str(tool.get("function", {}).get("name") or "")
                    for tool in builtin_tools
                }
            )
            if tool_hint:
                system_prompt = f"{system_prompt}\n\n{tool_hint}" if system_prompt else tool_hint
        if self._has_builtin_tool(builtin_tools, "create_agentteams_case"):
            system_prompt = (
                f"{system_prompt}\n\n{AGENTTEAMS_CASE_SYSTEM_PROMPT_SUFFIX}"
                if system_prompt
                else AGENTTEAMS_CASE_SYSTEM_PROMPT_SUFFIX
            )
        if any(server.id == CYGNUSX_PLATFORM_SERVER_ID for server in mcp_servers):
            system_prompt = (
                f"{system_prompt}\n\n{WORKSPACE_FILES_SYSTEM_PROMPT_SUFFIX}"
                if system_prompt
                else WORKSPACE_FILES_SYSTEM_PROMPT_SUFFIX
            )
        if self._has_builtin_tool(builtin_tools, HANDOFF_TOOL_NAME):
            handoff_catalog = await self._build_handoff_catalog(agent)
            if handoff_catalog:
                system_prompt = f"{system_prompt}\n\n{handoff_catalog}" if system_prompt else handoff_catalog
        system_prompt = self._append_communication_contract(system_prompt, agent)

        return AgentContext(
            agent=agent,
            model_config=model_config,
            system_prompt=system_prompt,
            tools=tools,
            mcp_servers=mcp_servers,
            skills=skills,
            features=runtime_features,
            user_capabilities_customized=user_capabilities_customized,
            temperature=agent.temperature,
            max_tokens=agent.max_tokens,
        )

    @staticmethod
    def _append_persona_prompt(system_prompt: str, agent: AgentTemplateModel) -> str:
        persona_prompt = render_persona_system_prompt(agent.features)
        if not persona_prompt:
            return system_prompt
        if not system_prompt:
            return persona_prompt
        # agent_loader appends the shared sandbox protocol to the prompt file. Keep
        # Persona after the Agent's role prompt but before that authoritative protocol.
        marker = f"\n{SHARED_SANDBOX_PROTOCOL_HEADER}"
        marker_index = system_prompt.find(marker)
        if marker_index >= 0:
            role_prompt = system_prompt[:marker_index].rstrip()
            safety_prompt = system_prompt[marker_index:].lstrip()
            return f"{role_prompt}\n\n{persona_prompt}\n\n{safety_prompt}"
        return f"{system_prompt}\n\n{persona_prompt}"

    @staticmethod
    def _append_communication_contract(system_prompt: str, agent: AgentTemplateModel) -> str:
        """将统一沟通规范注入所有运行时 Agent，兼容数据库中已存在的内置提示词。"""
        features = agent.features or {}
        suffix = (
            ROUTER_COMMUNICATION_SYSTEM_PROMPT_SUFFIX
            if features.get("router")
            else AGENT_COMMUNICATION_SYSTEM_PROMPT_SUFFIX
        )
        return f"{system_prompt}\n\n{suffix}" if system_prompt else suffix

    async def _agentteams_chat_entry_enabled(self) -> bool:
        settings = get_settings()
        return (
            settings.agentteams_chat_entry_enabled
            or await SiteSettingsService(self._db).is_agentteams_chat_entry_enabled()
        )

    @staticmethod
    def _filter_runtime_builtin_tools(
        tools: list[dict[str, Any]], *, agentteams_chat_entry_enabled: bool
    ) -> list[dict[str, Any]]:
        if agentteams_chat_entry_enabled:
            return tools
        return [
            tool
            for tool in tools
            if tool.get("function", {}).get("name") != "create_agentteams_case"
        ]

    @staticmethod
    def _has_builtin_tool(tools: list[dict[str, Any]], tool_name: str) -> bool:
        return any(tool.get("function", {}).get("name") == tool_name for tool in tools)

    async def _build_handoff_catalog(self, source: AgentTemplateModel) -> str:
        handoff_config = dict((source.features or {}).get("handoff") or {})
        allowed_targets = {str(item) for item in handoff_config.get("allowed_targets", [])}
        if not allowed_targets:
            return ""
        allow_all_active_targets = "*" in allowed_targets
        result = await self._db.execute(
            select(AgentTemplateModel)
            .where(AgentTemplateModel.is_active == True)  # noqa: E712
            .order_by(AgentTemplateModel.category, AgentTemplateModel.name)
        )
        catalog = []
        for candidate in result.scalars().all():
            if (
                candidate.agent_id == source.agent_id
                or (candidate.features or {}).get("router")
                or not (allow_all_active_targets or candidate.agent_id in allowed_targets)
            ):
                continue
            ability = agent_ability_catalog.get(candidate.agent_id)
            from cygnusx.application.services.agentteams_capability_registry import (
                persona_routing_summary,
            )

            # F5 渐进暴露：转交（派单）目录只注入 summary 层触发分类器；
            # 四段契约下沉 detail 层，由会诊/派单确认阶段按需加载。
            # 依据: 实测 — 改造前 3058 tokens → 改造后 1715 tokens
            # （口径: tiktoken cl100k_base，scripts/measure_capability_catalog_tokens.py，
            # 日期 2026-08-21）。
            catalog.append(
                {
                    "agent_id": candidate.agent_id,
                    "name": candidate.name,
                    "description": ability.get("summary") or candidate.description,
                    "category": candidate.category,
                    "chat_entry": ability.get("chat_entry", True),
                    "persona": persona_routing_summary(candidate.features),
                }
            )
        if not catalog:
            return ""
        return (
            "## 当前可转交的 Agent（运行时目录）\n\n"
            f"{json.dumps(catalog, ensure_ascii=False)}\n\n"
            "目录中的 persona 字段是目标 Agent 配置的表达风格来源；回答其他 Agent 的性格、工作方式或交付边界时优先依据该字段，不要只根据 description 推断。\n"
            "当用户任务不属于你的职责且目标明确时，必须调用 `transfer_to_agent` 转交给目录中的目标。"
            "不要让用户手动挑选 Agent，也不要编造目录外的 Agent。"
        )

    async def _resolve_model(self, model_id: uuid.UUID | None) -> AIProviderConfigModel | None:
        """严格按 Agent 绑定的 model_id 解析模型，避免 fallback 导致调用与设置不一致。"""
        if model_id is None:
            return None
        result = await self._db.execute(
            select(AIProviderConfigModel).where(
                AIProviderConfigModel.id == model_id,
                AIProviderConfigModel.is_active == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def resolve_model_id_for_agent(
        self, agent: AgentTemplateModel
    ) -> uuid.UUID | None:
        """返回 Agent 当前可用的模型 ID，并修复内置 Agent 的历史空绑定。"""
        await self._reconcile_model_bindings()
        model = await self._resolve_model(agent.model_id)
        return model.id if model is not None else None

    async def _load_skills(self, skill_ids: list[Any]) -> list[Skill]:
        if not skill_ids:
            return []
        from cygnusx.application.services.skill_service import SkillService

        result = await self._db.execute(
            select(SkillModel).where(
                SkillModel.skill_id.in_([str(skill_id) for skill_id in skill_ids]),
                SkillModel.is_active == True,  # noqa: E712
            )
        )
        return [SkillService._to_entity(model) for model in result.scalars().all()]

    @staticmethod
    def _build_skills_prompt(skills: list[Skill]) -> str:
        if not skills:
            return ""
        from cygnusx.application.services.skill_service import SkillService

        return SkillService.build_skills_prompt(skills)

    @staticmethod
    def _build_skills_index(skills: list[Skill]) -> str:
        """L1：仅 name+description 元数据索引，正文经 use_skill 按需加载"""
        if not skills:
            return ""
        from cygnusx.application.services.skill_service import SkillService

        return SkillService.build_skills_index(skills)

    async def _build_skill_prompt(self, skill_ids: list[Any]) -> str:
        """兼容旧调用方；新代码优先使用结构化 skills。"""
        return self._build_skills_prompt(await self._load_skills(skill_ids))

    @staticmethod
    def _build_cygnusx_tools_server() -> MCPServer | None:
        """构造虚拟的 cygnusx-tools builtin MCP Server。"""
        tools = schema_loader.list_tools()
        if not tools:
            return None
        return MCPServer(
            id=CYGNUSX_TOOLS_SERVER_ID,
            name=CYGNUSX_TOOLS_SERVER_NAME,
            description="CygnusX 生信工具箱 MCP",
            transport=Transport.BUILTIN,
            is_enabled=True,
            is_preset=True,
            status=ServerStatus.ONLINE,
            tools=[
                MCPToolRegistry(
                    tool_name=t.name,
                    description=t.description,
                    input_schema=t.input_schema,
                    server_id=CYGNUSX_TOOLS_SERVER_ID,
                )
                for t in tools
            ],
        )

    @staticmethod
    def _tool_pack_config(features: dict[str, Any]) -> dict[str, Any]:
        """汇总 YAML 工具包的内置/MCP 工具白名单。"""
        builtin_tools: set[str] = set()
        mcp_tools: dict[str, set[str]] = {}
        for pack in features.get("tool_packs", []) if isinstance(features, dict) else []:
            if not isinstance(pack, dict):
                continue
            builtin_tools.update(
                str(tool).strip()
                for tool in pack.get("builtin_tools", [])
                if str(tool).strip()
            )
            for server_id, tool_names in (pack.get("mcp_tools") or {}).items():
                if not isinstance(tool_names, list):
                    continue
                names = {
                    str(tool).strip() for tool in tool_names if str(tool).strip()
                }
                if names:
                    mcp_tools.setdefault(str(server_id), set()).update(names)
        return {"builtin_tools": builtin_tools, "mcp_tools": mcp_tools}

    @staticmethod
    def _parse_uuid(value: Any) -> uuid.UUID | None:
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (ValueError, AttributeError, TypeError):
            return None

    # --- DTO ---

    @staticmethod
    def _to_dto(a: AgentTemplateModel) -> AgentTemplateDTO:
        return AgentTemplateDTO(
            agent_id=a.agent_id,
            name=a.name,
            description=a.description,
            avatar=a.avatar,
            color=a.color,
            category=a.category,
            model_id=a.model_id,
            model_name=a.model_name,
            model_engine=a.model_engine,
            system_prompt=a.system_prompt,
            welcome_message=a.welcome_message,
            mcp_ids=list(a.mcp_ids or []),
            skill_ids=list(a.skill_ids or []),
            features=dict(a.features or {}),
            temperature=a.temperature,
            max_tokens=a.max_tokens,
            is_builtin=a.is_builtin,
            is_active=a.is_active,
            is_default=a.is_default,
            created_at=a.created_at,
            updated_at=a.updated_at,
        )
