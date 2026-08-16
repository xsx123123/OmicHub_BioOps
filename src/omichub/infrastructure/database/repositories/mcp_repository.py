"""MCP 域仓储实现 — SQLAlchemy"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.domain.mcp.entities import MCPServer, MCPToolRegistry
from omichub.domain.mcp.repositories import IMCPServerRepository
from omichub.domain.mcp.value_objects import ReviewStatus, ServerPool, ServerStatus, Transport
from omichub.infrastructure.database.models.mcp import MCPServerModel


class SqlAlchemyMCPServerRepository(IMCPServerRepository):
    """MCP Server 仓储实现"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, server_id: UUID) -> MCPServer | None:
        model = await self._session.get(MCPServerModel, server_id)
        return self._to_entity(model) if model else None

    async def get_by_name(self, name: str) -> MCPServer | None:
        result = await self._session.execute(
            select(MCPServerModel).where(MCPServerModel.name == name)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_all(self, active_only: bool = False) -> list[MCPServer]:
        query = select(MCPServerModel)
        if active_only:
            query = query.where(MCPServerModel.status == ServerStatus.ONLINE.value)
        query = query.order_by(desc(MCPServerModel.created_at))
        result = await self._session.execute(query)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def get_by_ids(self, ids: list[UUID]) -> list[MCPServer]:
        if not ids:
            return []
        result = await self._session.execute(
            select(MCPServerModel).where(MCPServerModel.id.in_(ids))
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def save(self, server: MCPServer) -> MCPServer:
        model = await self._session.get(MCPServerModel, server.id)
        if model is None:
            model = self._to_model(server)
            self._session.add(model)
        else:
            self._update_model(model, server)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def delete(self, server_id: UUID, *, force: bool = False) -> bool:
        model = await self._session.get(MCPServerModel, server_id)
        if model is None:
            return False
        if model.is_preset and not force:
            return False
        await self._session.delete(model)
        await self._session.flush()
        return True

    async def update_status(self, server_id: UUID, status: str) -> None:
        model = await self._session.get(MCPServerModel, server_id)
        if model is not None:
            model.status = status
            await self._session.flush()

    @staticmethod
    def _to_entity(m: MCPServerModel) -> MCPServer:
        tools = [
            MCPToolRegistry(
                tool_name=t.get("name", ""),
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
                server_id=m.id,
            )
            for t in (m.tools or [])
        ]
        return MCPServer(
            id=m.id,
            name=m.name,
            description=m.description,
            transport=Transport(m.transport),
            command=m.command,
            args=list(m.args or []),
            url=m.url,
            env=m.env or {},
            registry=m.package_registry,
            working_dir=m.working_dir,
            version=m.version,
            status=ServerStatus(m.status),
            is_enabled=m.is_enabled,
            tools=tools,
            timeout=m.timeout,
            auto_restart=m.auto_restart,
            is_preset=m.is_preset,
            pool=ServerPool(m.pool or "production"),
            expires_at=m.expires_at,
            created_by=m.created_by,
            current_version=m.current_version or "1.0.0",
            generation_meta=m.generation_meta or {},
            review_status=ReviewStatus(m.review_status or "approved"),
            is_template=bool(m.is_template),
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

    @staticmethod
    def _to_model(s: MCPServer) -> MCPServerModel:
        return MCPServerModel(
            id=s.id,
            name=s.name,
            description=s.description,
            transport=s.transport.value,
            command=s.command,
            args=list(s.args or []),
            url=s.url,
            env=s.env,
            package_registry=s.registry,
            working_dir=s.working_dir,
            version=s.version,
            status=s.status.value,
            is_enabled=s.is_enabled,
            tools=[
                {"name": t.tool_name, "description": t.description, "inputSchema": t.input_schema}
                for t in s.tools
            ],
            timeout=s.timeout,
            auto_restart=s.auto_restart,
            is_preset=s.is_preset,
            pool=s.pool.value,
            expires_at=s.expires_at,
            created_by=s.created_by,
            current_version=s.current_version,
            generation_meta=s.generation_meta or {},
            review_status=s.review_status.value,
            is_template=s.is_template,
        )

    @staticmethod
    def _update_model(m: MCPServerModel, s: MCPServer) -> MCPServerModel:
        m.description = s.description
        m.transport = s.transport.value
        m.command = s.command
        m.args = list(s.args or [])
        m.url = s.url
        m.env = s.env
        m.package_registry = s.registry
        m.working_dir = s.working_dir
        m.version = s.version
        m.status = s.status.value
        m.is_enabled = s.is_enabled
        m.tools = [
            {"name": t.tool_name, "description": t.description, "inputSchema": t.input_schema}
            for t in s.tools
        ]
        m.timeout = s.timeout
        m.auto_restart = s.auto_restart
        m.pool = s.pool.value
        m.expires_at = s.expires_at
        m.created_by = s.created_by
        m.current_version = s.current_version
        m.generation_meta = s.generation_meta or {}
        m.review_status = s.review_status.value
        m.is_template = s.is_template
        return m
