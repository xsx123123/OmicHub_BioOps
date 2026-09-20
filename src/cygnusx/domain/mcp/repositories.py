"""MCP 域仓储接口"""

from typing import Protocol
from uuid import UUID

from cygnusx.domain.mcp.entities import MCPServer


class IMCPServerRepository(Protocol):
    """MCP Server 仓储接口"""

    async def get_by_id(self, server_id: UUID) -> MCPServer | None: ...

    async def get_by_name(self, name: str) -> MCPServer | None: ...

    async def list_all(self, active_only: bool = False) -> list[MCPServer]: ...

    async def get_by_ids(self, ids: list[UUID]) -> list[MCPServer]: ...

    async def save(self, server: MCPServer) -> MCPServer: ...

    async def delete(self, server_id: UUID, *, force: bool = False) -> bool: ...

    async def update_status(self, server_id: UUID, status: str) -> None: ...
