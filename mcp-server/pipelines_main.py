"""独立 omichub-pipelines MCP Server 入口。"""

import sys

from client.api_client import api
from core.config import settings
from core.logger import logger
from fastmcp import FastMCP
from tools.pipelines import register

mcp = FastMCP(
    "omichub-pipelines",
    instructions="OmicHub RNA-seq 与 ATAC-seq 完整分析流程 MCP 服务",
)
register(mcp, api)


def main() -> None:
    transport = settings.transport
    port = settings.port
    args = sys.argv[1:]
    if "--transport" in args:
        index = args.index("--transport")
        if index + 1 < len(args):
            transport = args[index + 1]
    if "--port" in args:
        index = args.index("--port")
        if index + 1 < len(args):
            port = int(args[index + 1])

    if not settings.api_key:
        logger.warning("未设置 OMICSHUB_API_KEY，流水线 API 调用将失败")
    if transport == "sse":
        mcp.run(transport="sse", host=settings.host, port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
