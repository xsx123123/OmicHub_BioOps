"""MCP 应用服务 - Server CRUD、工具发现、调用路由、预设初始化"""

from __future__ import annotations

import asyncio
import time
from functools import cmp_to_key
from typing import Any
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.schemas.mcp import (
    CreateMCPServerDTO,
    MCPLogEntryDTO,
    MCPServerDTO,
    MCPServerVersionDTO,
    MCPToolDTO,
    UpdateMCPServerDTO,
)
from cygnusx.application.schemas.tool_invocation import ToolInvocationContext
from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import (
    ConflictError,
    MCPConnectionError,
    NotFoundError,
    ValidationError,
)
from cygnusx.domain.mcp.entities import MCPServer, MCPToolRegistry
from cygnusx.domain.mcp.services import MCPDomainService
from cygnusx.domain.mcp.value_objects import ServerStatus, Transport
from cygnusx.infrastructure.database.models.mcp_builder import MCPVersionModel
from cygnusx.infrastructure.database.models.mcp_log import MCPLogModel
from cygnusx.infrastructure.database.repositories.mcp_repository import (
    SqlAlchemyMCPServerRepository,
)
from cygnusx.infrastructure.mcp.builder.versioning import (
    CONFIG_SNAPSHOT_FIELDS as _CONFIG_SNAPSHOT_FIELDS,
)
from cygnusx.infrastructure.mcp.builder.versioning import (
    compare_versions,
    is_valid_semver,
    parse_semver,
)
from cygnusx.infrastructure.mcp.builder.versioning import (
    extract_config_snapshot as _config_snapshot,
)
from cygnusx.infrastructure.mcp.client import (
    MCPClient,
    validate_sse_url,
    validate_stdio_command,
    validate_working_dir,
)
from cygnusx.infrastructure.mcp.conda_meta_preset import (
    CONDA_META_MCP_ARGS,
    CONDA_META_MCP_COMMAND,
    CONDA_META_MCP_DESCRIPTION,
    CONDA_META_MCP_SERVER_ID,
    CONDA_META_MCP_SERVER_NAME,
    CONDA_META_MCP_TIMEOUT,
)
from cygnusx.infrastructure.mcp.presets import (
    CYGNUSX_PIPELINES_SERVER_ID,
    CYGNUSX_PIPELINES_SERVER_NAME,
    CYGNUSX_PLATFORM_SERVER_ID,
    CYGNUSX_TOOLS_SERVER_ID,
    CYGNUSX_TOOLS_SERVER_NAME,
    PRESET_SERVERS,
    SEQOUT_SERVER_ID,
    SEQOUT_SERVER_NAME,
    _build_cygnusx_tools_preset,
    get_preset_by_name,
)

#: 启停/状态类噪音字段：仅这些字段变化时不打配置快照、不 bump 版本
_NOISE_UPDATE_FIELDS = frozenset({"is_enabled", "status", "tools"})

#: 连接类字段：变更后需重新发现工具，保证 Agent 侧工具清单与新连接一致
_CONNECTION_FIELDS = frozenset(
    {"transport", "command", "args", "url", "env", "working_dir", "registry"}
)

#: 注册/更新后自动发现工具的最长等待（秒）：挂死的 server 不能拖住管理端请求
_AUTODISCOVER_TIMEOUT = 15.0

_PRESET_VERSION_PIN_KEY = "preset_version_pinned"

_MCP_HEALTH_PROBES: dict[str, tuple[str, dict[str, Any]]] = {
    "cygnusx-platform": ("platform_get_current_time", {"timezone": "Asia/Shanghai"}),
    "ensmbl": ("translate_sequence", {"sequence": "ATGGCC", "genetic_code": 1}),
    "go-server": ("get_go_term", {"id": "GO:0008150"}),
}


def _enum_str(value: Any, fallback: str) -> str:
    """枚举/字符串统一取枚举值；None 时回退默认"""
    if value is None:
        return fallback
    return value.value if hasattr(value, "value") else str(value)


async def next_patch_version(db: AsyncSession, server: MCPServer) -> str:
    """在 server 当前最大版本（含历史版本行）上 bump patch，保证 (server, version) 唯一。

    无法解析任何版本号时从 1.0.0 起算。MCPService 与 MCPBuilderService 共用，
    保证两条版本管理路径的版本号递进口径一致。
    """
    result = await db.execute(
        select(MCPVersionModel.version).where(
            MCPVersionModel.mcp_server_id == server.id
        )
    )
    candidates = [
        v
        for v in [server.current_version, *result.scalars().all()]
        if is_valid_semver(v)
    ]
    if not candidates:
        return "1.0.0"
    base = max(candidates, key=cmp_to_key(compare_versions))
    major, minor, patch, _pre = parse_semver(base)
    return f"{major}.{minor}.{patch + 1}"


def _server_to_dto(s: MCPServer) -> MCPServerDTO:
    return MCPServerDTO(
        id=s.id,
        name=s.name,
        description=s.description,
        transport=s.transport.value,
        command=s.command,
        args=list(s.args or []),
        url=s.url,
        env=dict(s.env or {}),
        registry=s.registry,
        working_dir=s.working_dir,
        # 遗留 version 字段兜底读 current_version，保证前端版本标签可见
        version=s.version or s.current_version,
        current_version=s.current_version,
        pool=_enum_str(s.pool, "production"),
        review_status=_enum_str(s.review_status, "approved"),
        expires_at=s.expires_at,
        status=s.status.value if hasattr(s.status, "value") else str(s.status),
        is_enabled=s.is_enabled,
        timeout=s.timeout,
        auto_restart=s.auto_restart,
        is_preset=s.is_preset,
        tool_count=len(s.tools),
        tools=[_tool_to_dto(t) for t in s.tools],
        created_at=s.created_at,
    )


def _tool_to_dto(t: MCPToolRegistry | dict[str, Any]) -> MCPToolDTO:
    if isinstance(t, dict):
        return MCPToolDTO(
            name=t.get("name", ""),
            description=t.get("description", ""),
            input_schema=t.get("inputSchema", {}),
        )
    return MCPToolDTO(name=t.tool_name, description=t.description, input_schema=t.input_schema)


def _tool_snapshot(tools: list[MCPToolRegistry]) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.tool_name,
            "description": tool.description,
            "inputSchema": tool.input_schema,
            "annotations": tool.annotations,
        }
        for tool in tools
    ]


def _preset_tools(preset: dict[str, Any], server_id: UUID) -> list[MCPToolRegistry]:
    return [
        MCPToolRegistry(
            tool_name=tool["name"],
            description=tool["description"],
            input_schema=tool["inputSchema"],
            server_id=server_id,
            annotations=dict(tool.get("annotations") or {}),
        )
        for tool in preset["tools"]
    ]


class MCPService:
    """MCP 集成应用服务"""

    def __init__(self, db: AsyncSession):
        self._db = db
        self._repo = SqlAlchemyMCPServerRepository(db)
        self._domain = MCPDomainService(self._repo)
        self._client = MCPClient()
        self._settings = get_settings()

    async def _normalize_preset_identity(self, name: str, deterministic_id: UUID) -> None:
        """把「同名但 id 与确定性常量不一致」的预设记录归一化到常量 ID。

        历史版本曾用随机 uuid4 种子化 platform / conda-meta 等预设，导致 DB 记录 id
        与代码常量不一致：Agent 绑定按常量 ID 查不到该 server，工具白名单按常量 ID
        也匹配失败，出现同一 server 双身份/工具重复暴露。归一化时同步迁移全部子表
        外键（logs / versions / builds / visibility），幂等。
        """
        existing = await self._repo.get_by_name(name)
        if existing is None or existing.id == deterministic_id:
            return
        if await self._repo.get_by_id(deterministic_id) is not None:
            # 常量 ID 已有记录：删除旧的重复记录（logs/versions/visibility 为 ON DELETE CASCADE）
            await self._repo.delete(existing.id, force=True)
            return

        from sqlalchemy import text

        # 唯一约束 mcp_servers_name_key：先把旧行临时改名，再插入同名新行，
        # 否则 INSERT 与旧行同名会违反唯一约束。
        legacy_name = f"{name}.legacy-{str(existing.id)[:8]}"
        await self._db.execute(
            text("UPDATE mcp_servers SET name = :legacy_name WHERE id = :old_id"),
            {"legacy_name": legacy_name, "old_id": existing.id},
        )
        await self._db.execute(
            text(
                "INSERT INTO mcp_servers (id, name, description, transport, command, url, env, status, tools, "
                "timeout, auto_restart, is_preset, created_at, updated_at, args, registry, working_dir, version, "
                "is_enabled, pool, expires_at, created_by, current_version, generation_meta, review_status, "
                "is_template) "
                "SELECT :new_id, :name, description, transport, command, url, env, status, tools, timeout, "
                "auto_restart, is_preset, created_at, updated_at, args, registry, working_dir, version, "
                "is_enabled, pool, expires_at, created_by, current_version, generation_meta, review_status, "
                "is_template FROM mcp_servers WHERE id = :old_id"
            ),
            {"new_id": deterministic_id, "name": name, "old_id": existing.id},
        )
        for table, column in (
            ("mcp_logs", "service_id"),
            ("mcp_versions", "mcp_server_id"),
            ("mcp_builds", "mcp_server_id"),
            ("mcp_visibility", "mcp_server_id"),
        ):
            await self._db.execute(
                text(f"UPDATE {table} SET {column} = :new_id WHERE {column} = :old_id"),
                {"new_id": deterministic_id, "old_id": existing.id},
            )
        await self._db.execute(
            text("DELETE FROM mcp_servers WHERE id = :old_id"),
            {"old_id": existing.id},
        )
        await self._db.flush()
        logger.info(
            "MCP 预设身份归一化: {name} {old} -> {new}",
            name=name,
            old=existing.id,
            new=deterministic_id,
        )

    async def ensure_presets(self, *, force_preset_sync: bool = False) -> None:
        """初始化预设 MCP 服务（含 cygnusx-tools 动态预设与 conda-meta-mcp stdio 预设，幂等）"""
        # 预设身份归一化：把历史随机 ID 的预设记录对齐到确定性常量 ID，再走下方按名同步。
        # 每个归一化在独立 savepoint 内执行，单个失败不中止后续预设的初始化。
        for preset_name, preset_id in (
            (CYGNUSX_PIPELINES_SERVER_NAME, CYGNUSX_PIPELINES_SERVER_ID),
            ("cygnusx-platform", CYGNUSX_PLATFORM_SERVER_ID),
            (CYGNUSX_TOOLS_SERVER_NAME, CYGNUSX_TOOLS_SERVER_ID),
            (SEQOUT_SERVER_NAME, SEQOUT_SERVER_ID),
            (CONDA_META_MCP_SERVER_NAME, CONDA_META_MCP_SERVER_ID),
        ):
            try:
                async with self._db.begin_nested():
                    await self._normalize_preset_identity(preset_name, preset_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("MCP 预设身份归一化失败 {name}: {exc}", name=preset_name, exc=exc)

        valid_names = {p["name"] for p in PRESET_SERVERS} | {
            CYGNUSX_TOOLS_SERVER_NAME,
            CONDA_META_MCP_SERVER_NAME,
        }
        for server in await self._repo.list_all():
            if server.is_preset and server.name not in valid_names:
                await self._repo.delete(server.id, force=True)

        for preset in PRESET_SERVERS:
            existing = await self._repo.get_by_name(preset["name"])
            if existing is not None:
                # 预设工具随代码演进（如新增工作区文件工具），需把最新工具清单同步进库，
                # 否则已存在部署的 builtin 预设工具不会出现在 LLM 工具清单里。
                if preset["name"] in (
                    CYGNUSX_PIPELINES_SERVER_NAME,
                    "cygnusx-platform",
                    SEQOUT_SERVER_NAME,
                ):
                    await self._sync_preset_server(existing, preset, force_preset_sync)
                continue
            preset_id = (
                CYGNUSX_PLATFORM_SERVER_ID
                if preset["name"] == "cygnusx-platform"
                else SEQOUT_SERVER_ID
                if preset["name"] == SEQOUT_SERVER_NAME
                else CYGNUSX_PIPELINES_SERVER_ID
                if preset["name"] == CYGNUSX_PIPELINES_SERVER_NAME
                else uuid4()
            )
            tools = [
                MCPToolRegistry(
                    tool_name=t["name"],
                    description=t["description"],
                    input_schema=t["inputSchema"],
                    server_id=preset_id,
                )
                for t in preset["tools"]
            ]
            server = MCPServer(
                id=preset_id,
                name=preset["name"],
                description=preset["description"],
                transport=Transport.BUILTIN,
                status=ServerStatus.ONLINE,
                tools=tools,
                timeout=self._settings.mcp_default_timeout,
                auto_restart=True,
                is_preset=True,
            )
            await self._repo.save(server)
            await self._snapshot_config_version(
                server,
                source="register",
                changelog="注册 MCP Server（初始配置）",
            )

        # 动态生信工具箱 preset：工具清单来自 tools_schema.yaml + 动态 Flow 配置，
        # 与 platform/pipelines 一样每次 ensure_presets 重同步快照——只在首建时写入
        # 会与 Flow 配置永久漂移（同口径处理：仅更新 DB 注册表工具清单，
        # 不动 agent 绑定白名单，被移除的工具自然不再暴露给 LLM）。
        cygnusx_preset = _build_cygnusx_tools_preset()
        existing_cygnusx = await self._repo.get_by_id(CYGNUSX_TOOLS_SERVER_ID)
        if existing_cygnusx is None:
            server = MCPServer(
                id=CYGNUSX_TOOLS_SERVER_ID,
                name=CYGNUSX_TOOLS_SERVER_NAME,
                description=cygnusx_preset["description"],
                transport=Transport.BUILTIN,
                status=ServerStatus.ONLINE,
                tools=_preset_tools(cygnusx_preset, CYGNUSX_TOOLS_SERVER_ID),
                timeout=self._settings.mcp_default_timeout,
                auto_restart=True,
                is_preset=True,
            )
            await self._repo.save(server)
        elif existing_cygnusx.name == CYGNUSX_TOOLS_SERVER_NAME:
            await self._sync_preset_server(existing_cygnusx, cygnusx_preset, force_preset_sync)

        # stdio 预设：conda-meta-mcp（装包前查询 conda 元数据）
        await self._ensure_conda_meta_mcp()

    async def _sync_preset_server(
        self, existing: MCPServer, preset: dict[str, Any], force_preset_sync: bool
    ) -> None:
        """把 builtin 预设的最新工具清单/描述同步进库（幂等，版本 pin 保护）。

        platform / pipelines / cygnusx-tools 共用同一口径：工具快照有变化且未被
        回滚 pin（或 force 同步）时，先补齐现有工具的初始快照再 bump patch 写入
        升级版本；只替换 server.tools 注册表，不删任何 agent 绑定。
        """
        target_tools = _preset_tools(preset, existing.id)
        has_tool_changes = _tool_snapshot(existing.tools) != _tool_snapshot(target_tools)
        metadata = dict(existing.generation_meta or {})
        is_version_pinned = bool(metadata.get(_PRESET_VERSION_PIN_KEY))

        if has_tool_changes and (force_preset_sync or not is_version_pinned):
            # 存量预设也先补齐其现有工具的 v1.0.0 初始快照，随后再写入升级版本，
            # 以便管理端能显示并切换回注册时的配置。
            await self._snapshot_config_version(
                existing,
                source="register",
                changelog="注册 MCP Server（初始配置）",
            )
            existing.tools = target_tools
            existing.current_version = await self._next_patch_version(existing)
            existing.version = existing.current_version
            metadata.pop(_PRESET_VERSION_PIN_KEY, None)
            existing.generation_meta = metadata
            await self._repo.save(existing)
            await self._snapshot_config_version(
                existing,
                source="preset",
                changelog="内置 MCP 预设升级：同步最新工具清单",
            )

        # 描述随代码演进（如补充「饼干余额查询」能力说明），同步进库，
        # 否则能力目录仍按旧描述展示，模型不知道该预设可查余额。
        preset_desc = str(preset.get("description") or "")
        if preset_desc and existing.description != preset_desc:
            existing.description = preset_desc
        existing.status = ServerStatus.ONLINE
        existing.is_enabled = True
        await self._repo.save(existing)

    async def _ensure_conda_meta_mcp(self) -> None:
        """种子化 conda-meta-mcp stdio 预设（幂等）。

        - 镜像里没有 cmm（旧镜像）时优雅跳过，不产生坏记录；
        - 已有记录但离线/无工具（如上次启动时 cmm 尚不可用）时重试工具发现；
        - stdio 预设不走 _autodiscover_tools（该入口对 is_preset 早退，
          为 builtin 预设服务），直接调 test_server 发现并落库工具快照。
        """
        existing = await self._repo.get_by_id(CONDA_META_MCP_SERVER_ID)
        if existing is None:
            try:
                validate_stdio_command(CONDA_META_MCP_COMMAND)
            except ValueError as exc:
                logger.warning("conda-meta-mcp 预设跳过种子化: {}", exc)
                return
            server = MCPServer(
                id=CONDA_META_MCP_SERVER_ID,
                name=CONDA_META_MCP_SERVER_NAME,
                description=CONDA_META_MCP_DESCRIPTION,
                transport=Transport.STDIO,
                command=CONDA_META_MCP_COMMAND,
                args=list(CONDA_META_MCP_ARGS),
                status=ServerStatus.OFFLINE,
                timeout=CONDA_META_MCP_TIMEOUT,
                auto_restart=True,
                is_preset=True,
            )
            try:
                await self._repo.save(server)
            except IntegrityError:
                # 多 worker 并发种子化：另一进程已写入同 ID 记录，回滚后复用它
                await self._db.rollback()
                server = await self._repo.get_by_id(CONDA_META_MCP_SERVER_ID)
                if server is None:
                    return
            else:
                await self._snapshot_config_version(
                    server,
                    source="register",
                    changelog="注册内置 conda-meta-mcp 预设（初始配置）",
                )
        else:
            server = existing
            if server.status == ServerStatus.ONLINE and server.tools:
                return
        # 即时发现工具：成功则工具快照 + ONLINE 落库；失败仅记录日志（test_server
        # 内部不抛异常），保留离线状态待下次启动重试，不阻断启动。
        try:
            await asyncio.wait_for(self.test_server(server.id), timeout=CONDA_META_MCP_TIMEOUT + 10)
        except Exception as exc:  # noqa: BLE001
            logger.warning("conda-meta-mcp 预设工具发现失败（稍后自动重试）: {}", exc)

    async def list_servers(self, active_only: bool = False) -> list[MCPServerDTO]:
        await self.ensure_presets()
        servers = await self._repo.list_all(active_only=active_only)
        return [_server_to_dto(s) for s in servers]

    async def get_server(self, server_id: UUID) -> MCPServerDTO:
        await self.ensure_presets()
        server = await self._repo.get_by_id(server_id)
        if server is None:
            raise NotFoundError("MCP Server 不存在")
        return _server_to_dto(server)

    async def register_server(self, req: CreateMCPServerDTO) -> MCPServerDTO:
        """注册新的外部 MCP Server（stdio/sse）"""
        existing = await self._repo.get_by_name(req.name)
        if existing is not None:
            raise ConflictError(f"MCP Server 名称已存在: {req.name}")
        transport = (
            Transport(req.transport)
            if req.transport in ("stdio", "sse", "streamable_http")
            else Transport.STDIO
        )
        if transport == Transport.STDIO:
            try:
                validate_stdio_command(req.command or "")
                validate_working_dir(req.working_dir)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
        elif transport in (Transport.SSE, Transport.STREAMABLE_HTTP):
            try:
                validate_sse_url(req.url or "")
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
        server = MCPServer(
            id=uuid4(),
            name=req.name,
            description=req.description,
            transport=transport,
            command=req.command,
            args=list(req.args or []),
            url=req.url,
            env=req.env,
            registry=req.registry,
            working_dir=req.working_dir,
            status=ServerStatus.OFFLINE,
            timeout=req.timeout,
            auto_restart=req.auto_restart,
            is_preset=False,
        )
        server = await self._domain.register_server(server)
        # 注册后即时发现工具（热加载）：新 MCP 立刻进入 Agent 可用工具清单，
        # 无需重启容器或手工点「测试」。发现失败不阻断注册（保留离线/错误状态 + 日志）。
        await self._autodiscover_tools(server.id, action="注册")
        server = await self._repo.get_by_id(server.id) or server
        # 写入初始版本快照：注册即产生 v1.0.0 历史记录，版本历史不为空
        await self._snapshot_config_version(
            server,
            source="register",
            changelog="注册 MCP Server（初始配置）",
        )
        return _server_to_dto(server)

    async def delete_server(self, server_id: UUID) -> bool:
        return await self._repo.delete(server_id)

    async def update_server(
        self,
        server_id: UUID,
        req: UpdateMCPServerDTO,
        actor_id: UUID | str | None = None,
    ) -> MCPServerDTO:
        """更新 MCP Server 配置（配置类变更自动打版本快照）"""
        server = await self._repo.get_by_id(server_id)
        if server is None:
            raise NotFoundError("MCP Server 不存在")
        data = req.model_dump(exclude_unset=True)
        # DTO 中 transport 是字符串，直接 setattr 会污染实体的枚举类型，
        # 导致仓储 save() 取 s.transport.value 时报 AttributeError
        if data.get("transport") is not None:
            try:
                data["transport"] = Transport(data["transport"])
            except ValueError as exc:
                raise ValidationError(f"不支持的传输方式: {data['transport']}") from exc
        for key, value in data.items():
            setattr(server, key, value)
        # 校验更新后的配置
        transport = server.transport
        if transport == Transport.STDIO:
            try:
                validate_stdio_command(server.command or "")
                validate_working_dir(server.working_dir)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
        elif transport in (Transport.SSE, Transport.STREAMABLE_HTTP):
            try:
                validate_sse_url(server.url or "")
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
        # 仅启停/状态噪音字段变更时不打快照
        changed_fields = sorted(set(data) - _NOISE_UPDATE_FIELDS)
        if changed_fields:
            server.current_version = await self._next_patch_version(server)
            server.version = server.current_version  # 同步遗留字段，保证展示一致
        await self._repo.save(server)
        if changed_fields:
            await self._snapshot_config_version(
                server,
                source="admin",
                changelog=f"管理员更新配置：{', '.join(changed_fields)}",
                actor_id=actor_id,
            )
        # 连接类配置变更后重新发现工具，保证工具清单跟随新连接热更新
        if set(data) & _CONNECTION_FIELDS:
            await self._autodiscover_tools(server_id, action="更新")
            server = await self._repo.get_by_id(server_id) or server
        return _server_to_dto(server)

    async def list_server_versions(self, server_id: UUID) -> list[MCPServerVersionDTO]:
        """MCP Server 版本历史（按创建时间倒序）

        历史版本行为空时（如版本控制上线前注册的存量 server），按当前配置
        懒回填一条初始快照，保证版本历史与展示的版本号一致。
        """
        server = await self._repo.get_by_id(server_id)
        if server is None:
            raise NotFoundError("MCP Server 不存在")

        async def _query_rows() -> list[MCPVersionModel]:
            result = await self._db.execute(
                select(MCPVersionModel)
                .where(MCPVersionModel.mcp_server_id == server_id)
                .order_by(MCPVersionModel.created_at.desc())
            )
            return list(result.scalars().all())

        rows = await _query_rows()
        if not rows:
            await self._snapshot_config_version(
                server,
                source="register",
                changelog="注册 MCP Server（初始配置）",
            )
            await self._db.flush()
            rows = await _query_rows()
        return [
            MCPServerVersionDTO(
                id=v.id,
                version=v.version,
                is_major=v.is_major,
                source=v.source,
                changelog=v.changelog,
                created_by=v.created_by,
                created_at=v.created_at,
                has_config_snapshot=bool(v.config_snapshot),
            )
            for v in rows
        ]

    async def rollback_server(
        self,
        server_id: UUID,
        version: str,
        actor_id: UUID | str | None = None,
    ) -> MCPServerDTO:
        """回滚到指定版本（任意 server 均可），回滚本身产生一条新版本记录"""
        server = await self._repo.get_by_id(server_id)
        if server is None:
            raise NotFoundError("MCP Server 不存在")
        result = await self._db.execute(
            select(MCPVersionModel).where(
                MCPVersionModel.mcp_server_id == server_id,
                MCPVersionModel.version == version,
            )
        )
        target = result.scalar_one_or_none()
        if target is None:
            raise NotFoundError(f"版本 {version} 不存在")
        # 还原配置快照（只还原快照里有的键）
        snapshot = target.config_snapshot or {}
        for key, value in snapshot.items():
            if key == "transport":
                server.transport = Transport(value)
            elif key in _CONFIG_SNAPSHOT_FIELDS:
                setattr(server, key, value)
        if target.tools_snapshot:
            server.tools = [
                MCPToolRegistry(
                    tool_name=t.get("name", ""),
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema") or {},
                    server_id=server.id,
                )
                for t in target.tools_snapshot
            ]
        if server.is_preset:
            metadata = dict(server.generation_meta or {})
            metadata[_PRESET_VERSION_PIN_KEY] = True
            server.generation_meta = metadata
        server.current_version = target.version
        server.version = target.version  # 同步遗留字段
        await self._repo.save(server)
        # 回滚本身作为一条新版本记录（版本号在当前最大版本上 bump patch，保证唯一）
        new_version = await self._next_patch_version(server)
        await self._snapshot_config_version(
            server,
            version=new_version,
            source="rollback",
            changelog=f"回滚到 v{target.version}",
            actor_id=actor_id,
        )
        return _server_to_dto(server)

    async def _autodiscover_tools(self, server_id: UUID, *, action: str) -> None:
        """注册/更新后即时发现工具（热加载入口）.

        复用 test_server 的发现 + 落库 + 日志逻辑；任何失败（连不上、超时、
        协议错误）都只落日志、不抛异常——注册/更新主流程绝不被发现环节阻断。
        builtin/预设的工具清单由 ensure_presets 从代码同步（热加载走
        POST /mcp/presets/reload），不参与外部发现。
        """
        server = await self._repo.get_by_id(server_id)
        if server is None or server.is_preset or server.transport == Transport.BUILTIN:
            return
        try:
            await asyncio.wait_for(self.test_server(server_id), timeout=_AUTODISCOVER_TIMEOUT)
        except TimeoutError:
            await self._add_log(
                server_id, "warning",
                f"{action}后自动发现工具超时（{_AUTODISCOVER_TIMEOUT:.0f}s），可稍后手动「测试」连接",
                "internal",
            )
        except Exception as e:  # noqa: BLE001
            await self._add_log(
                server_id, "warning", f"{action}后自动发现工具失败: {e}", "internal"
            )

    async def test_server(self, server_id: UUID) -> dict[str, Any]:
        """测试连接并发现工具"""
        try:
            tools = await self.list_tools(server_id)
            await self._add_log(
                server_id, "info", f"测试连接成功，发现 {len(tools)} 个工具", "internal"
            )
            return {"success": True, "tool_count": len(tools), "status": "online"}
        except Exception as e:  # noqa: BLE001
            await self._add_log(server_id, "error", f"测试连接失败: {e}", "internal")
            return {"success": False, "tool_count": 0, "status": "error", "error": str(e)}

    async def audit_health(self) -> dict[str, Any]:
        """只读审计所有启用 MCP，不用 fallback 掩盖外部服务故障。"""
        await self.ensure_presets()
        rows: list[dict[str, Any]] = []
        for server in await self._repo.list_all():
            if not server.is_enabled:
                continue
            started = time.perf_counter()
            row: dict[str, Any] = {
                "id": str(server.id),
                "name": server.name,
                "transport": server.transport.value,
                "configured_status": server.status.value,
                "tool_discovery": "pending",
                "probe": "skipped",
            }
            try:
                tools = await asyncio.wait_for(
                    self._client.list_tools(server), timeout=min(server.timeout, 15)
                )
                row["tool_discovery"] = "ok"
                row["tool_count"] = len(tools)
                probe = _MCP_HEALTH_PROBES.get(server.name)
                if probe is not None:
                    tool_name, arguments = probe
                    result = await self._client._call_tool_inner(
                        server, tool_name, arguments, user_id="mcp-health-audit"
                    )
                    row["probe"] = "ok" if result.get("success") else "failed"
                    if not result.get("success"):
                        row["failure_kind"] = result.get("failure_kind", "tool_error")
                        row["error"] = str(result.get("error") or "工具探针失败")[:500]
                row["healthy"] = row["tool_discovery"] == "ok" and row["probe"] != "failed"
            except TimeoutError:
                row.update(
                    healthy=False,
                    tool_discovery="failed",
                    failure_kind="timeout",
                    error="工具发现超时",
                )
            except Exception as exc:  # noqa: BLE001
                row.update(
                    healthy=False,
                    tool_discovery="failed",
                    failure_kind="connection_error",
                    error=(str(exc) or type(exc).__name__)[:500],
                )
            row["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
            rows.append(row)
        healthy_count = sum(1 for row in rows if row.get("healthy"))
        return {
            "healthy": healthy_count == len(rows),
            "summary": {
                "total": len(rows),
                "healthy": healthy_count,
                "unhealthy": len(rows) - healthy_count,
            },
            "servers": rows,
        }

    async def list_tools(self, server_id: UUID) -> list[MCPToolDTO]:
        """获取指定 Server 的工具列表（builtin 即时返回；外部即时发现）"""
        server = await self._repo.get_by_id(server_id)
        if server is None:
            raise NotFoundError("MCP Server 不存在")
        try:
            tools = await self._client.list_tools(server)
        except Exception as e:  # noqa: BLE001
            # 连接/发现失败：标 error + 落日志，并抛 MCPConnectionError(503) 把真实原因回传前端，
            # 避免「连不上却显示 online、0 工具」的误导状态。
            server.status = ServerStatus.ERROR
            await self._repo.save(server)
            await self._add_log(server_id, "error", f"连接/发现工具失败: {e}", "internal")
            raise MCPConnectionError(f"MCP Server 连接失败: {e}") from e
        # 更新存储的工具快照 + 状态
        server.tools = [
            MCPToolRegistry(
                tool_name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
                server_id=server.id,
            )
            for t in tools
        ]
        # 直接在实体上置 online 再 save：mark_online 走 update_status 改的是同一会话身份映射里的
        # model，紧随其后的 save() 会用实体里陈旧的 status 覆盖回 offline，导致连上了仍显示离线。
        server.status = ServerStatus.ONLINE
        await self._repo.save(server)
        return [_tool_to_dto(t) for t in tools]

    async def invoke_tool(
        self, server_id: UUID, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """调用指定 Server 的工具（带路由校验与错误隔离）"""
        server = await self._repo.get_by_id(server_id)
        if server is None:
            raise NotFoundError("MCP Server 不存在")
        # 路由校验：确认工具属于该 server（builtin 允许未刷入快照的直接调用）
        routed = await self._domain.route_tool_call(tool_name)
        if (routed is None or routed.id != server.id) and server.transport != Transport.BUILTIN:
            raise NotFoundError(f"工具 {tool_name} 不属于该 Server")
        result = await self._client.call_tool(server, tool_name, arguments)
        if not result.get("success"):
            await self._domain.mark_error(server.id)
            await self._add_log(
                server_id,
                "error",
                f"工具调用失败 {tool_name}: {result.get('error', '')}",
                "internal",
            )
        else:
            await self._add_log(server_id, "info", f"工具调用成功 {tool_name}", "internal")
        return result

    async def invoke_pipeline_tool(
        self,
        user_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        session_id: str = "pipeline-frontend",
    ) -> dict[str, Any]:
        """以当前用户上下文调用内置 cygnusx-pipelines 工具。"""
        await self.ensure_presets()
        server = await self._repo.get_by_id(CYGNUSX_PIPELINES_SERVER_ID)
        if server is None or server.name != CYGNUSX_PIPELINES_SERVER_NAME:
            raise NotFoundError("cygnusx-pipelines MCP Server 不存在")
        preset = get_preset_by_name(CYGNUSX_PIPELINES_SERVER_NAME)
        tool_names = {tool["name"] for tool in (preset or {}).get("tools", [])}
        if tool_name not in tool_names:
            raise NotFoundError(f"流水线工具不存在: {tool_name}")
        context = ToolInvocationContext(
            user_id=user_id,
            session_id=session_id,
            db=self._db,
        )
        result = await self._client.call_tool(
            server,
            tool_name,
            arguments,
            user_id=user_id,
            context=context,
        )
        if result.get("success"):
            await self._add_log(server.id, "info", f"用户调用成功 {tool_name}", "frontend")
        else:
            await self._add_log(
                server.id,
                "error",
                f"用户调用失败 {tool_name}: {result.get('error', '')}",
                "frontend",
            )
        return result

    async def list_logs(self, server_id: UUID, tail: int = 100) -> list[MCPLogEntryDTO]:
        """获取 MCP Server 最近日志"""
        from sqlalchemy import desc, select

        result = await self._db.execute(
            select(MCPLogModel)
            .where(MCPLogModel.service_id == server_id)
            .order_by(desc(MCPLogModel.timestamp))
            .limit(tail)
        )
        logs = result.scalars().all()
        return [
            MCPLogEntryDTO(
                timestamp=log.timestamp,
                level=log.level,
                message=log.message,
                source=log.source,
            )
            for log in reversed(logs)
        ]

    async def _add_log(
        self, server_id: UUID, level: str, message: str, source: str = "internal"
    ) -> None:
        """写入一条 MCP 日志"""
        from datetime import datetime

        self._db.add(
            MCPLogModel(
                service_id=server_id,
                timestamp=datetime.utcnow(),
                level=level,
                message=message,
                source=source,
            )
        )
        await self._db.flush()

    async def _next_patch_version(self, server: MCPServer) -> str:
        return await next_patch_version(self._db, server)

    async def _snapshot_config_version(
        self,
        server: MCPServer,
        *,
        version: str | None = None,
        source: str,
        changelog: str,
        actor_id: UUID | str | None = None,
    ) -> None:
        """写入一行配置版本快照（幂等：同 (server, version) 已存在则跳过）"""
        version = version or server.current_version
        existing = await self._db.execute(
            select(MCPVersionModel).where(
                MCPVersionModel.mcp_server_id == server.id,
                MCPVersionModel.version == version,
            )
        )
        if existing.scalar_one_or_none() is not None:
            return
        self._db.add(
            MCPVersionModel(
                mcp_server_id=server.id,
                version=version,
                is_major=False,
                config_snapshot=_config_snapshot(server),
                tools_snapshot=_tool_snapshot(server.tools),
                source=source,
                changelog=changelog,
                created_by=UUID(str(actor_id)) if actor_id else None,
            )
        )
        await self._db.flush()
