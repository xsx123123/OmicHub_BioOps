"""MCP 域服务 - 工具路由、错误隔离"""

from uuid import UUID

from cygnusx.domain.mcp.entities import MCPServer
from cygnusx.domain.mcp.repositories import IMCPServerRepository
from cygnusx.domain.mcp.value_objects import ServerStatus


class MCPDomainService:
    """MCP 域服务 - Server 生命周期、工具路由、错误隔离"""

    def __init__(self, repo: IMCPServerRepository):
        self._repo = repo

    async def register_server(self, server: MCPServer) -> MCPServer:
        """注册新 MCP Server"""
        server.status = ServerStatus.OFFLINE
        return await self._repo.save(server)

    async def mark_online(self, server_id: UUID) -> None:
        """标记 Server 为在线"""
        await self._repo.update_status(server_id, ServerStatus.ONLINE.value)

    async def mark_error(self, server_id: UUID) -> None:
        """标记 Server 为错误（错误隔离）"""
        await self._repo.update_status(server_id, ServerStatus.ERROR.value)

    async def route_tool_call(self, tool_name: str) -> MCPServer | None:
        """根据工具名路由到对应的 MCP Server"""
        servers = await self._repo.list_all(active_only=True)
        for server in servers:
            if any(t.tool_name == tool_name for t in server.tools):
                return server
        return None
