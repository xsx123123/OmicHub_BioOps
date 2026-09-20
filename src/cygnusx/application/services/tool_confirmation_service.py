"""工具二次确认服务。

统一管理 AI 写操作的人类确认凭证，两类记录：
- kind=task：分析流程预检确认（PENDING → 人类 approve → APPROVED → 提交 → SUBMITTED）
- kind=tool：通用工具确认（bridge requires_confirm 工具，PENDING → 人类 approve
  → APPROVED → 模型携带 _confirmation_id 重试 → CONSUMED 后执行）

核心不变量：APPROVED 状态只能由人类通道写入（JWT 会话的 REST approve 端点）；
模型通道（builtin chat handler / MCP 工具参数）无法自行制造 APPROVED。
例外：显式携带 extra["human_confirmed"]=True 的上下文（外部 REST API-Key 通道，
其人类凭证是用户配置的 API Key 与 CLI 审批），允许一步消费 PENDING。

存储优先 Redis（多 worker 共享、原生 TTL），不可用时回退进程内内存。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from cygnusx.application.schemas.task import TaskSubmitRequest
from cygnusx.application.schemas.tool_invocation import ToolInvocationContext
from cygnusx.application.services.task_service import TaskService

logger = logging.getLogger(__name__)

# tool 记录消费时禁止进入哈希的参数（控制面字段）
_CONTROL_ARGUMENT_KEYS = {"_confirmation_id", "_confirmed"}

_STATUS_PENDING = "PENDING"
_STATUS_APPROVED = "APPROVED"
_STATUS_REJECTED = "REJECTED"
_STATUS_SUBMITTED = "SUBMITTED"
_STATUS_CONSUMED = "CONSUMED"
_STATUS_EXPIRED = "EXPIRED"
_STATUS_INVALID = "INVALID"

# Lua: 原子状态机迁移。ARGV[1]=新状态 ARGV[2]=consumed_at ISO ARGV[3]=回写 TTL 秒，
# ARGV[4..]=允许的前置状态。key 不存在返回 nil；不匹配返回当前记录原文（changed=false）；
# 成功写入并返回 {record=..., changed=true}。
_TRANSITION_LUA = """
local raw = redis.call('GET', KEYS[1])
if not raw then return nil end
local rec = cjson.decode(raw)
for i = 4, #ARGV do
  if rec['status'] == ARGV[i] then
    rec['status'] = ARGV[1]
    rec['consumed_at'] = ARGV[2]
    redis.call('SET', KEYS[1], cjson.encode(rec), 'EX', tonumber(ARGV[3]) or 3600)
    return cjson.encode({record = rec, changed = true})
  end
end
return cjson.encode({record = rec, changed = false})
"""


class ConfirmationError(Exception):
    """确认记录操作异常"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class ConfirmationRecord:
    """确认记录（task 与 tool 两类共用）。"""

    confirmation_id: str
    user_id: str
    kind: str  # "task" | "tool"
    flow_id: str
    flow_name: str
    parameter_hash: str
    normalized_request: dict[str, Any]
    status: str
    created_at: datetime
    expires_at: datetime
    agent_id: str | None = None
    session_id: str = ""
    tool_name: str = ""
    consumed_at: datetime | None = None
    task_id: str | None = None
    rejection_reason: str | None = None

    def to_json(self) -> str:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        data["expires_at"] = self.expires_at.isoformat()
        data["consumed_at"] = self.consumed_at.isoformat() if self.consumed_at else None
        return json.dumps(data, ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, raw: str) -> ConfirmationRecord:
        data = json.loads(raw)
        return cls(
            confirmation_id=data["confirmation_id"],
            user_id=data["user_id"],
            kind=data.get("kind", "task"),
            flow_id=data.get("flow_id", ""),
            flow_name=data.get("flow_name", ""),
            parameter_hash=data.get("parameter_hash", ""),
            normalized_request=data.get("normalized_request", {}),
            status=data["status"],
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]),
            agent_id=data.get("agent_id"),
            session_id=data.get("session_id", ""),
            tool_name=data.get("tool_name", ""),
            consumed_at=(
                datetime.fromisoformat(data["consumed_at"]) if data.get("consumed_at") else None
            ),
            task_id=data.get("task_id"),
            rejection_reason=data.get("rejection_reason"),
        )


@dataclass
class ApprovalResult:
    """批准结果"""

    status: str
    task_id: str | None = None
    task_card: dict[str, Any] | None = None
    message: str | None = None


class _MemoryStore:
    """进程内存储（单 worker / 测试 / Redis 不可用时）。"""

    name = "memory"

    def __init__(self) -> None:
        self._records: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def save(self, record: ConfirmationRecord) -> None:
        async with self._lock:
            self._purge_locked()
            self._records[record.confirmation_id] = record.to_json()

    async def get(self, confirmation_id: str) -> ConfirmationRecord | None:
        async with self._lock:
            raw = self._records.get(confirmation_id)
            if raw is None:
                return None
            record = ConfirmationRecord.from_json(raw)
            if record.status == _STATUS_PENDING and datetime.now(UTC) > record.expires_at:
                record.status = _STATUS_EXPIRED
                self._records[confirmation_id] = record.to_json()
            return record

    async def transition(
        self, confirmation_id: str, *, expected: tuple[str, ...], to: str
    ) -> ConfirmationRecord | None:
        async with self._lock:
            raw = self._records.get(confirmation_id)
            if raw is None:
                return None
            record = ConfirmationRecord.from_json(raw)
            if record.status not in expected:
                return record
            record.status = to
            if to != _STATUS_PENDING:
                record.consumed_at = datetime.now(UTC)
            self._records[confirmation_id] = record.to_json()
            return record

    def _purge_locked(self) -> None:
        now = datetime.now(UTC)
        stale = [
            k
            for k, raw in self._records.items()
            if ConfirmationRecord.from_json(raw).expires_at < now - timedelta(hours=1)
        ]
        for k in stale:
            del self._records[k]


class _RedisStore:
    """Redis 存储：SET 带 TTL + Lua 原子迁移，多 worker 共享。"""

    name = "redis"
    _KEY_PREFIX = "cygnusx:tool_confirm:"

    def __init__(self, client: Any) -> None:
        self._client = client
        self._transition = client.register_script(_TRANSITION_LUA)

    async def save(self, record: ConfirmationRecord) -> None:
        ttl = max(1, int((record.expires_at - datetime.now(UTC)).total_seconds()) + 60)
        await self._client.set(self._KEY_PREFIX + record.confirmation_id, record.to_json(), ex=ttl)

    async def get(self, confirmation_id: str) -> ConfirmationRecord | None:
        raw = await self._client.get(self._KEY_PREFIX + confirmation_id)
        if raw is None:
            return None
        record = ConfirmationRecord.from_json(raw)
        if record.status == _STATUS_PENDING and datetime.now(UTC) > record.expires_at:
            await self.transition(confirmation_id, expected=(_STATUS_PENDING,), to=_STATUS_EXPIRED)
            record.status = _STATUS_EXPIRED
        return record

    async def transition(
        self, confirmation_id: str, *, expected: tuple[str, ...], to: str
    ) -> ConfirmationRecord | None:
        key = self._KEY_PREFIX + confirmation_id
        ttl = await self._client.ttl(key)
        raw = await self._client.eval(
            _TRANSITION_LUA,
            1,
            key,
            to,
            datetime.now(UTC).isoformat(),
            str(ttl if ttl > 0 else ToolConfirmationService.DEFAULT_TTL_SECONDS * 2),
            *expected,
        )
        if raw is None:
            return None
        data = json.loads(raw)
        return ConfirmationRecord.from_json(data["record"])

class ToolConfirmationService:
    """工具确认服务。人类凭证状态机：APPROVED 仅能由人类通道写入。"""

    DEFAULT_TTL_SECONDS = 1800  # 30 分钟

    def __init__(self, store: Any | None = None) -> None:
        self._explicit_store = store
        self._store: Any | None = None

    async def _get_store(self) -> Any:
        if self._store is not None:
            return self._store
        if self._explicit_store is not None:
            self._store = self._explicit_store
            return self._store
        try:
            from cygnusx.infrastructure.cache.redis_client import get_redis

            store = _RedisStore(get_redis())
            await store.get("connection-probe")  # 轻量 ping（key 不存在返回 None）
            self._store = store
            logger.info("ToolConfirmationService 使用 Redis 存储")
        except Exception as e:  # noqa: BLE001
            self._store = _MemoryStore()
            logger.warning("ToolConfirmationService Redis 不可用，回退内存存储: %s", e)
        return self._store

    # ===== 创建 =====

    async def create(
        self,
        context: ToolInvocationContext,
        flow_id: str,
        flow_name: str,
        normalized_request: TaskSubmitRequest,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> ConfirmationRecord:
        """创建 task 类确认记录（分析流程预检）。"""
        request_dict = normalized_request.model_dump(mode="json")
        record = ConfirmationRecord(
            confirmation_id=str(uuid.uuid4()),
            user_id=context.user_id,
            kind="task",
            flow_id=flow_id,
            flow_name=flow_name,
            parameter_hash=self._hash(request_dict),
            normalized_request=request_dict,
            status=_STATUS_PENDING,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
            agent_id=context.agent_id,
            session_id=context.session_id,
        )
        store = await self._get_store()
        await store.save(record)
        return record

    async def create_for_tool(
        self,
        user_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        session_id: str = "",
        agent_id: str | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> ConfirmationRecord:
        """创建 tool 类确认记录（requires_confirm 工具）。"""
        payload = {k: v for k, v in arguments.items() if k not in _CONTROL_ARGUMENT_KEYS}
        record = ConfirmationRecord(
            confirmation_id=str(uuid.uuid4()),
            user_id=user_id,
            kind="tool",
            flow_id="",
            flow_name=tool_name,
            tool_name=tool_name,
            parameter_hash=self._hash(payload),
            normalized_request=payload,
            status=_STATUS_PENDING,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
            agent_id=agent_id,
            session_id=session_id,
        )
        store = await self._get_store()
        await store.save(record)
        return record

    # ===== 人类通道 =====

    async def approve_by_human(
        self, *, user_id: str, confirmation_id: str
    ) -> ConfirmationRecord:
        """人类（JWT 会话 REST 端点）批准一条 tool 记录：PENDING → APPROVED。

        这是 APPROVED 状态的唯一写入点；模型工具通道不存在等价调用。
        """
        record = await self._require_owned(user_id, confirmation_id)
        if record.kind != "tool":
            raise ConfirmationError("WRONG_KIND", "task 记录请使用 tool-confirmations 端点")
        if record.status == _STATUS_APPROVED:
            return record
        store = await self._get_store()
        updated = await store.transition(
            confirmation_id, expected=(_STATUS_PENDING,), to=_STATUS_APPROVED
        )
        if updated is None:
            raise ConfirmationError("ACCESS_DENIED", "确认记录不存在")
        if updated.status != _STATUS_APPROVED:
            raise ConfirmationError("ALREADY_CONSUMED", f"确认记录状态为 {updated.status}")
        return updated

    # ===== 消费 =====

    async def approve(
        self,
        context: ToolInvocationContext,
        confirmation_id: str,
        task_service: TaskService,
    ) -> ApprovalResult:
        """消费 task 记录并提交任务。

        - 携带 extra["human_confirmed"] 的人类通道（REST）：允许 PENDING 一步消费；
        - 模型通道：要求记录已被人类点卡置为 APPROVED；已 SUBMITTED 幂等返回。
        """
        record = await self._require_owned(context.user_id, confirmation_id)
        if record.kind != "task":
            raise ConfirmationError("WRONG_KIND", "tool 记录请使用 tool-invocations 端点")
        human_channel = bool((context.extra or {}).get("human_confirmed"))

        if record.status == _STATUS_SUBMITTED and record.task_id:
            return ApprovalResult(
                status=_STATUS_SUBMITTED,
                task_id=record.task_id,
                message="任务已提交（确认记录此前已消费）",
            )

        if record.status == _STATUS_PENDING and not human_channel:
            raise ConfirmationError(
                "CONFIRMATION_REQUIRED",
                "等待用户在确认卡上确认后才能提交，请勿自行重试",
            )
        expected = (
            (_STATUS_PENDING, _STATUS_APPROVED) if human_channel else (_STATUS_APPROVED,)
        )
        if record.status not in expected:
            raise ConfirmationError("ALREADY_CONSUMED", f"确认记录状态为 {record.status}")
        if datetime.now(UTC) > record.expires_at:
            await self._transition(confirmation_id, (_STATUS_PENDING, _STATUS_APPROVED), _STATUS_EXPIRED)
            raise ConfirmationError("CONFIRMATION_EXPIRED", "确认已过期，请重新预检")

        store = await self._get_store()
        updated = await store.transition(
            confirmation_id, expected=(_STATUS_PENDING, _STATUS_APPROVED), to=_STATUS_APPROVED
        )
        if updated is None or updated.status != _STATUS_APPROVED:
            raise ConfirmationError("ALREADY_CONSUMED", "确认记录已被消费")

        try:
            request = TaskSubmitRequest(**record.normalized_request)
            task_response = await task_service.submit(context.user_id, request)
        except Exception as e:  # noqa: BLE001
            await self._transition(confirmation_id, (_STATUS_APPROVED,), _STATUS_INVALID)
            raise ConfirmationError("SUBMIT_FAILED", f"任务提交失败: {e}") from e

        consumed = await store.transition(
            confirmation_id, expected=(_STATUS_APPROVED,), to=_STATUS_SUBMITTED
        )
        if consumed is None or consumed.status != _STATUS_SUBMITTED:
            raise ConfirmationError("SUBMIT_FAILED", "任务已提交但确认记录消费失败，请检查任务状态")
        record.status = _STATUS_SUBMITTED
        record.consumed_at = datetime.now(UTC)
        record.task_id = str(task_response.id)
        await store.save(record)

        task_card = {
            "type": "task_card",
            "task_id": str(task_response.id),
            "flow_id": task_response.flow_id,
            "status": task_response.status.upper(),
            "progress": task_response.progress,
            "task_url": f"/tasks/{task_response.id}",
            "logs_url": f"/api/v1/tasks/{task_response.id}/logs",
            "monitor_url": f"/monitor/tasks/{task_response.id}",
            "created_at": (
                task_response.created_at.isoformat() if task_response.created_at else None
            ),
        }
        return ApprovalResult(
            status=_STATUS_SUBMITTED,
            task_id=record.task_id,
            task_card=task_card,
            message="任务已提交",
        )

    async def consume_tool_confirmation(
        self,
        user_id: str,
        confirmation_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        human_confirmed: bool = False,
    ) -> ConfirmationRecord:
        """模型携带 _confirmation_id 重试 requires_confirm 工具时的消费校验。

        要求：kind=tool、归属当前用户、未过期、状态 APPROVED（人类点卡）、
        参数哈希与首次确认时一致。通过后原子置 CONSUMED（一次性）。
        human_confirmed=True（外部 API-Key/JWT 通道）允许 PENDING 一步消费。
        """
        record = await self._require_owned(user_id, confirmation_id)
        if record.kind != "tool":
            raise ConfirmationError("WRONG_KIND", "task 记录请使用 tool-confirmations 端点")

        payload = {k: v for k, v in arguments.items() if k not in _CONTROL_ARGUMENT_KEYS}
        if record.tool_name != tool_name or record.parameter_hash != self._hash(payload):
            # 参数被改动 —— 旧确认作废，防止"确认 A 执行 B"
            await self._transition(
                confirmation_id, (_STATUS_PENDING, _STATUS_APPROVED), _STATUS_INVALID
            )
            raise ConfirmationError(
                "ARGS_CHANGED", "确认后的参数与本次调用不一致，已作废旧确认，请重新发起"
            )
        if datetime.now(UTC) > record.expires_at:
            await self._transition(
                confirmation_id, (_STATUS_PENDING, _STATUS_APPROVED), _STATUS_EXPIRED
            )
            raise ConfirmationError("CONFIRMATION_EXPIRED", "确认已过期，请重新发起")

        if record.status == _STATUS_CONSUMED:
            raise ConfirmationError("ALREADY_CONSUMED", "该确认已被使用，不能重复执行")
        if record.status == _STATUS_PENDING and not human_confirmed:
            raise ConfirmationError(
                "CONFIRMATION_REQUIRED",
                "等待用户在确认卡上确认后才能执行，请提醒用户点击确认卡",
            )

        expected = (_STATUS_PENDING, _STATUS_APPROVED) if human_confirmed else (_STATUS_APPROVED,)
        store = await self._get_store()
        updated = await store.transition(confirmation_id, expected=expected, to=_STATUS_CONSUMED)
        if updated is None:
            raise ConfirmationError("ACCESS_DENIED", "确认记录不存在")
        if updated.status != _STATUS_CONSUMED:
            raise ConfirmationError("ALREADY_CONSUMED", f"确认记录状态为 {updated.status}")
        return updated

    async def reject(
        self,
        user_id: str,
        confirmation_id: str,
        reason: str | None = None,
    ) -> ConfirmationRecord:
        """拒绝确认记录。"""
        record = await self._require_owned(user_id, confirmation_id)
        if record.status not in (_STATUS_PENDING, _STATUS_APPROVED):
            raise ConfirmationError("ALREADY_CONSUMED", f"确认记录状态为 {record.status}")
        updated = await self._transition(
            confirmation_id, (_STATUS_PENDING, _STATUS_APPROVED), _STATUS_REJECTED
        )
        if updated is None:
            raise ConfirmationError("ACCESS_DENIED", "确认记录不存在")
        updated.rejection_reason = reason
        store = await self._get_store()
        await store.save(updated)
        return updated

    async def get_status(self, user_id: str, confirmation_id: str) -> ConfirmationRecord | None:
        """查询确认记录状态。"""
        try:
            return await self._require_owned(user_id, confirmation_id)
        except ConfirmationError:
            return None

    # ===== 内部 =====

    async def _require_owned(self, user_id: str, confirmation_id: str) -> ConfirmationRecord:
        store = await self._get_store()
        record = await store.get(confirmation_id)
        if record is None or record.user_id != user_id:
            raise ConfirmationError("ACCESS_DENIED", "无权操作或确认记录不存在")
        return record

    async def _transition(
        self, confirmation_id: str, expected: tuple[str, ...], to: str
    ) -> ConfirmationRecord | None:
        store = await self._get_store()
        return await store.transition(confirmation_id, expected=expected, to=to)

    @staticmethod
    def _hash(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# 全局单例
_confirmation_service: ToolConfirmationService | None = None


def get_tool_confirmation_service() -> ToolConfirmationService:
    """获取全局确认服务单例。"""
    global _confirmation_service
    if _confirmation_service is None:
        _confirmation_service = ToolConfirmationService()
    return _confirmation_service
