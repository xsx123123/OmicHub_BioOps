"""CygnusX MCP Server — 多组学分析平台统一 AI 助手操作接口

启动方式:
  stdio (默认): python main.py
  SSE:          python main.py --transport sse --port 8900

配置:
  编辑 config.yaml 修改连接、工具组开关等设置
  环境变量 (CYGNUSX_*) 优先级高于 config.yaml
"""

import sys

from fastmcp import FastMCP

from client.api_client import api
from core.config import settings
from core.logger import logger
from tools import register_all_tools
from resources.catalog import register as register_resources
from prompts.workflows import register as register_prompts

mcp = FastMCP(
    settings.server_name,
    instructions=settings.server_description,
)

register_all_tools(mcp, api)
register_resources(mcp, api)
register_prompts(mcp, api)


def main() -> None:
    transport = settings.transport
    port = settings.port

    args = sys.argv[1:]
    if "--transport" in args:
        idx = args.index("--transport")
        if idx + 1 < len(args):
            transport = args[idx + 1]
    if "--port" in args:
        idx = args.index("--port")
        if idx + 1 < len(args):
            port = int(args[idx + 1])

    if not settings.api_key:
        logger.warning("未设置 CYGNUSX_API_KEY，API 调用将会失败")

    if transport == "sse" and settings.host != "127.0.0.1":
        logger.warning(
            f"SSE 传输无鉴权且绑定 {settings.host}:{port}，任何可达者都能使用本服务配置的 API Key；"
            "请确保处于可信内网，或改绑 127.0.0.1 并经由带鉴权的反向代理暴露。"
        )

    logger.info(f"CygnusX MCP Server 启动 (transport={transport}, base_url={settings.base_url})")

    if transport == "sse":
        mcp.run(transport="sse", host=settings.host, port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
