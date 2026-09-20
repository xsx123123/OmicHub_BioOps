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


# 连续失败达到该阈值即视为 degraded 并打开熔断。
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 3
# 熔断冷却默认值；生产上由 Settings.mcp_circuit_breaker_cooldown_seconds 覆盖。
DEFAULT_CIRCUIT_BREAKER_COOLDOWN_SECONDS = 60.0

# ===== 熔断计分的失败分类 =====
# 只有传输层 / server 级失败（timeout、connection_error、command_not_found、
# server 内部错等）才说明 server 本身不健康，应计入熔断。
# tool_error（工具按协议返回 isError，多由调用方传坏参数触发）、validation 与
# file_reference（参数里的文件引用解析失败）都是「调用方错误」：LLM 连续幻觉几次
# 坏参数不应把健康 server 短路，因此不计入熔断统计。
CIRCUIT_EXCLUDED_FAILURE_KINDS = frozenset(
    {"tool_error", "validation", "file_reference"}
)


def counts_toward_circuit_breaker(failure_kind: str | None) -> bool:
    """该失败是否计入熔断。None/未知 kind 视为 server 级异常，保守计入。"""
    return str(failure_kind or "unknown").lower() not in CIRCUIT_EXCLUDED_FAILURE_KINDS


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
    # 熔断冷却截止时刻（time.time() 口径）；None 表示未处于冷却。
    circuit_open_until: float | None = None
    # 半开试探占位：True 时其他并发调用继续短路，避免一窝蜂试探。
    probe_in_flight: bool = False

    @property
    def status(self) -> str:
        if self.consecutive_failures >= CIRCUIT_BREAKER_FAILURE_THRESHOLD:
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
    """进程内 MCP 健康监控器，按 server/tool 隔离故障。

    所有方法都是同步的、没有 await 点，check-and-set 在单事件循环内
    天然原子，因此 asyncio 并发下无需额外加锁。
    """

    _items: dict[str, ToolHealth] = field(default_factory=dict)
    circuit_cooldown_seconds: float = DEFAULT_CIRCUIT_BREAKER_COOLDOWN_SECONDS

    def _get(self, key: str) -> ToolHealth:
        return self._items.setdefault(key, ToolHealth())

    def try_acquire_call(self, key: str) -> str:
        """熔断门控，返回 "closed" / "half_open" / "open"。

        - closed：未熔断，正常调用；
        - half_open：冷却窗口已过，获准一次试探调用（占位，阻止并发试探）；
        - open：冷却中或已有试探在途，调用方应短路走兜底链。
        """
        item = self._get(key)
        if item.consecutive_failures < CIRCUIT_BREAKER_FAILURE_THRESHOLD:
            return "closed"
        now = time.time()
        if item.circuit_open_until is not None and now < item.circuit_open_until:
            return "open"
        if item.probe_in_flight:
            return "open"
        item.probe_in_flight = True
        return "half_open"

    def record_success(self, key: str, latency_ms: float) -> None:
        item = self._get(key)
        item.success_count += 1
        item.consecutive_failures = 0
        item.last_latency_ms = round(latency_ms, 2)
        # 成功即恢复 healthy：释放半开占位并关闭熔断。
        item.probe_in_flight = False
        item.circuit_open_until = None

    def record_failure(self, key: str, latency_ms: float) -> None:
        item = self._get(key)
        item.failure_count += 1
        item.consecutive_failures += 1
        item.last_failure = time.time()
        item.last_latency_ms = round(latency_ms, 2)
        item.probe_in_flight = False
        if item.consecutive_failures >= CIRCUIT_BREAKER_FAILURE_THRESHOLD:
            # 达到 degraded 阈值（含半开试探失败），重新进入冷却窗口。
            item.circuit_open_until = time.time() + self.circuit_cooldown_seconds

    def release_probe(self, key: str) -> None:
        """释放半开试探占位，但不改动成功/失败计数与熔断窗口。

        用于不计入熔断的调用方错误（tool_error/validation 等）：半开试探若收到
        此类响应，说明请求已到达 server 并正常返回，占位必须释放，否则熔断
        永久卡在 open；但调用方错误不应重置失败计数，健康度维持原状。
        """
        self._get(key).probe_in_flight = False

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
