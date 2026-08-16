"""MCP 工具可靠性状态与执行策略。

该模块只保存进程内运行状态，不把瞬时健康状态写入 MCP 配置或数据库。
这样既能在单次 Agent 调用中做降级，也不会因为一次网络故障永久修改资源状态。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


class MCPExternalCallError(RuntimeError):
    """保留外部 MCP 失败类型，供日志与健康检查定位根因。"""

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


@dataclass(frozen=True)
class ToolRetryPolicy:
    """外部工具的有限重试策略。"""

    max_attempts: int = 3
    backoff_seconds: tuple[float, ...] = (1.0, 3.0, 5.0)

    def delay_for(self, failed_attempt: int) -> float:
        if failed_attempt <= 0:
            return 0.0
        index = min(failed_attempt - 1, len(self.backoff_seconds) - 1)
        return self.backoff_seconds[index] if self.backoff_seconds else 0.0


@dataclass
class ToolHealth:
    """单个 MCP server/tool 的运行时健康快照。"""

    success_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    last_failure: float | None = None
    last_latency_ms: float | None = None

    @property
    def status(self) -> str:
        if self.consecutive_failures >= 3:
            return "degraded"
        if self.consecutive_failures:
            return "warning"
        return "healthy"

    def snapshot(self) -> dict[str, Any]:
        total = self.success_count + self.failure_count
        return {
            "status": self.status,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": self.success_count / total if total else None,
            "consecutive_failures": self.consecutive_failures,
            "last_failure": self.last_failure,
            "last_latency_ms": self.last_latency_ms,
        }


@dataclass
class MCPHealthRegistry:
    """进程内 MCP 健康监控器，按 server/tool 隔离故障。"""

    _items: dict[str, ToolHealth] = field(default_factory=dict)

    def _get(self, key: str) -> ToolHealth:
        return self._items.setdefault(key, ToolHealth())

    def record_success(self, key: str, latency_ms: float) -> None:
        item = self._get(key)
        item.success_count += 1
        item.consecutive_failures = 0
        item.last_latency_ms = round(latency_ms, 2)

    def record_failure(self, key: str, latency_ms: float) -> None:
        item = self._get(key)
        item.failure_count += 1
        item.consecutive_failures += 1
        item.last_failure = time.time()
        item.last_latency_ms = round(latency_ms, 2)

    def snapshot(self, key: str) -> dict[str, Any]:
        return self._get(key).snapshot()

    def clear(self) -> None:
        self._items.clear()


def health_key(server_name: str, tool_name: str) -> str:
    return f"{server_name}:{tool_name}"


_default_registry = MCPHealthRegistry()


def get_default_health_registry() -> MCPHealthRegistry:
    """返回进程级注册表，让健康状态跨 Agent 请求保留。"""
    return _default_registry


async def execute_local_fallback(
    tool_name: str, arguments: dict[str, Any]
) -> dict[str, Any] | None:
    """执行无需外部数据源的确定性本地降级能力。"""
    if tool_name != "translate_sequence":
        return None

    from Bio.Seq import Seq

    raw_sequence = str(arguments.get("sequence") or "")
    sequence = "".join(raw_sequence.split()).upper().replace("U", "T")
    if not sequence:
        return {"success": False, "error": "DNA 序列不能为空"}
    invalid = sorted(set(sequence) - set("ACGTRYSWKMBDHVN"))
    if invalid:
        return {"success": False, "error": f"DNA 序列包含非法字符: {''.join(invalid)}"}
    try:
        genetic_code = int(arguments.get("genetic_code") or 1)
        protein = str(Seq(sequence).translate(table=genetic_code))
    except (TypeError, ValueError) as exc:
        return {"success": False, "error": f"无法翻译 DNA 序列: {exc}"}
    return {
        "success": True,
        "result": {
            "protein": protein,
            "amino_acid_length": len(protein),
            "nucleotide_length": len(sequence),
            "genetic_code": genetic_code,
        },
    }
