#!/usr/bin/env bash
# OmicHub MCP Server 启动脚本
set -euo pipefail
cd "$(dirname "$0")"

TRANSPORT="${1:-stdio}"
PORT="${2:-8900}"

exec uv run python main.py --transport "$TRANSPORT" --port "$PORT"
