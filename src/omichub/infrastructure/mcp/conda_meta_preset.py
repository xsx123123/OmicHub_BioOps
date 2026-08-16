"""conda-meta-mcp 内置 stdio 预设 — conda 生态元数据查询 MCP server。

Agent 在沙盒现场装包（micromamba install）前，用本 server 的工具确认
包名（Python import 名 / PyPI 名 → conda 包名）、所属 channel、平台 build
与依赖图，把"凭记忆猜包名盲装"变成"先查权威元数据再装"。

server 本体（conda-forge 的 conda-meta-mcp 包，CLI 名 ``cmm``）随 web 镜像
内置（见 deploy/docker/Dockerfile，装在独立 env 并软链到 /usr/local/bin）。
若容器 PATH 中没有 cmm（如旧镜像），种子化会优雅跳过，不影响其它预设。
"""

from __future__ import annotations

import uuid

CONDA_META_MCP_SERVER_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "conda-meta-mcp.stdio")
CONDA_META_MCP_SERVER_NAME = "conda-meta-mcp"
CONDA_META_MCP_COMMAND = "cmm"
CONDA_META_MCP_ARGS = ("run",)
CONDA_META_MCP_DESCRIPTION = (
    "Conda 生态权威元数据（只读）：按名称搜索包的 channel/版本/平台 build（package_search）、"
    "把 Python import 名或 PyPI 名映射为 conda 包名（import_mapping / pypi_to_conda）、"
    "查询依赖图 depends/whoneeds（repoquery）、按文件路径找包（file_path_search）。"
    "沙盒现场装 conda 包前应先查询，确认包名与 channel 后再安装。"
)
# 首次查询需拉取通道 repodata（conda-forge/bioconda 体积大），比默认 30s 放宽
CONDA_META_MCP_TIMEOUT = 60
