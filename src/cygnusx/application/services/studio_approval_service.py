"""OmicStudio 工具审批服务 —— supervised 权限模式的人机协作闸（HITL）。

设计文档 docs/26.7.21/studio_hitl_design.md §3：
- supervised 模式下写/执行类工具（APPROVAL_REQUIRED_TOOLS）需用户批准后才进沙盒；
- 记录存 Redis（``studio:approval:{id}``，TTL 300s），多进程安全，
  规避 tool_confirmation_service 进程内内存无法跨进程消费的坑；
- chat_service 发出 approval_request 事件后 await BLPOP
  （``studio:approval:result:{id}``）等 REST 端点写入的决议；
  超时按拒绝处理（action="timeout"）。
- 审批提示是瞬态 SSE 事件，不落库；前端刷新/断流后通过
  ``GET /studio/approvals?session_id=`` 拉取 pending 记录重建审批卡。
- 拦截名单 = 硬编码 APPROVAL_REQUIRED_TOOLS ∪ tools_schema.yaml 中
  ``requires_confirm: true`` 的工具（见 approval_required_tools()）。
- 决议（含 timeout）经 record_approval_audit() 落 audit_logs 持久审计；
  approve 可携 always=True，由 REST 端点把 (session, tool) 记入会话
  sandbox_meta.permissions.always_allow，之后同会话同工具直接放行。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable
from typing import Any, cast

from loguru import logger

from cygnusx.infrastructure.cache.redis_client import get_redis

APPROVAL_REQUIRED_TOOLS: frozenset[str] = frozenset(
    {
        "sandbox_execute",
        "workspace_write",
        "workspace_edit",
        "artifact_register",
        # 编排代码可多次回调写/执行类工具，supervised 下整段审批一次，子调用不逐次弹窗
        "tool_orchestrate",
        # 普通聊天的代码执行与 Studio sandbox_execute 同险，supervised 下同闸
        "chat_sandbox_execute",
        # 公共 HTTP 元数据访问也必须由用户逐次确认，避免 Agent 隐式出网。
        "network_request",
    }
)

NETWORK_REQUEST_TOOL_NAME = "network_request"

APPROVAL_TTL_SECONDS = 300


def approval_required_tools() -> frozenset[str]:
    """审批闸拦截名单：硬编码集合 ∪ tools_schema.yaml 中 requires_confirm 的工具。

    schema 读取失败（文件缺失/解析异常/依赖不可用）时回退硬编码集合——
    已知危险工具仍被拦截，按最安全的方向降级。
    """
    try:
        from cygnusx.tools.schema_loader import schema_loader

        dynamic = {tool.name for tool in schema_loader.get_config().tools if tool.requires_confirm}
    except Exception:  # noqa: BLE001
        logger.warning("[Studio] 读取 tools_schema requires_confirm 失败，回退硬编码审批名单")
        return APPROVAL_REQUIRED_TOOLS
    return APPROVAL_REQUIRED_TOOLS | frozenset(dynamic)


def always_allow_set(sandbox_meta: dict[str, Any] | None) -> set[str]:
    """从会话 sandbox_meta.permissions.always_allow 读取"本会话总是允许"的工具集合。

    数据缺失/畸形时返回空集合（仍逐次审批，安全方向降级）。
    """
    permissions = (sandbox_meta or {}).get("permissions") or {}
    raw = permissions.get("always_allow") if isinstance(permissions, dict) else None
    if not isinstance(raw, list):
        return set()
    return {str(item) for item in raw}


def needs_approval(permission_mode: str | None, tool_name: str, always_allow: set[str]) -> bool:
    """判断工具是否需要审批。

    网络请求是跨越平台边界的副作用，即使会话没有显式选择 supervised，也必须
    先显示 URL 审批卡片；用户可选择“本会话不再询问”降低重复确认成本。
    """
    if tool_name == NETWORK_REQUEST_TOOL_NAME:
        return tool_name not in always_allow
    return (
        permission_mode == "supervised"
        and tool_name in approval_required_tools()
        and tool_name not in always_allow
    )


async def record_approval_audit(
    *,
    user_id: str,
    approval_id: str,
    session_id: str,
    tool_name: str,
    action: str,
    resolver: str,
    always: bool = False,
    reason: str | None = None,
    arguments: dict[str, Any] | None = None,
    approval_kind: str = "tool",
    method: str = "POST",
) -> None:
    """审批决议落 audit_logs（best-effort）：Redis 记录 TTL 到期后的持久审计。

    独立 session 写入，不耦合请求/聊天流事务；任何异常仅告警，不阻断审批主流程。
    """
    try:
        from cygnusx.infrastructure.database.models.audit_log import AuditLogModel
        from cygnusx.infrastructure.database.session import get_session_factory

        try:
            uid = uuid.UUID(str(user_id))
        except (ValueError, TypeError, AttributeError):
            uid = None
        args_summary = ""
        if arguments:
            try:
                args_summary = json.dumps(arguments, ensure_ascii=False, default=str)[:500]
            except (TypeError, ValueError):
                args_summary = ""
        entry = AuditLogModel(
            user_id=uid,
            username=None,
            method=method,
            path=f"/api/v1/studio/approvals/{approval_id}/{action}",
            resource_type="studio_approval",
            resource_id=approval_id,
            status_code=200,
            ip=None,
            user_agent=None,
            detail={
                "event": "approval_decision",
                "session_id": session_id,
                "tool_name": tool_name,
                "action": action,
                "resolver": resolver,
                "always": always,
                "approval_kind": approval_kind,
                **({"reason": reason} if reason else {}),
                **({"args_summary": args_summary} if args_summary else {}),
            },
        )
        factory = get_session_factory()
        async with factory() as session:
            session.add(entry)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Studio] 审批决议审计落库失败（忽略，不影响审批结果）: {}", exc)


_RECORD_KEY = "studio:approval:{approval_id}"
_RESULT_KEY = "studio:approval:result:{approval_id}"

_RESOLVE_APPROVAL_LUA = """
local record_json = redis.call('GET', KEYS[1])
if not record_json then return nil end
local record = cjson.decode(record_json)
if record.user_id ~= ARGV[1] or record.status ~= 'pending' then return nil end
record.status = ARGV[2]
if ARGV[4] ~= '' then record.reason = ARGV[4] end
local updated = cjson.encode(record)
redis.call('SETEX', KEYS[1], tonumber(ARGV[5]), updated)
redis.call('RPUSH', KEYS[2], ARGV[3])
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[5]))
return updated
"""


class StudioApprovalService:
    """Studio 工具审批记录与决议等待（Redis 存储，跨进程安全）。"""

    async def create(
        self,
        user_id: str,
        session_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        risk_hint: str = "",
        approval_kind: str = "tool",
    ) -> dict[str, Any]:
        """创建 pending 审批记录并写入 Redis（TTL 300s），返回记录字典。"""
        record: dict[str, Any] = {
            "approval_id": uuid.uuid4().hex,
            "user_id": str(user_id),
            "session_id": session_id,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "risk_hint": risk_hint,
            "approval_kind": approval_kind,
            "status": "pending",
        }
        await get_redis().setex(
            _RECORD_KEY.format(approval_id=record["approval_id"]),
            APPROVAL_TTL_SECONDS,
            json.dumps(record, ensure_ascii=False, default=str),
        )
        return record

    async def get(self, approval_id: str) -> dict[str, Any] | None:
        raw = await get_redis().get(_RECORD_KEY.format(approval_id=approval_id))
        if raw is None:
            return None
        try:
            record = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return record if isinstance(record, dict) else None

    async def list_pending(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        """列出指定会话仍处于 pending 的审批记录（附带剩余秒数 expires_in）。

        审批提示本是瞬态 SSE 事件，不落库；前端刷新/断流重进会话时用本方法
        重建待审批卡片。记录量极小（单会话同一时刻通常 ≤1 条），SCAN 全量
        匹配代价可忽略；决议 list 的 key 含 ":result:"，需排除。
        """
        redis = get_redis()
        records: list[dict[str, Any]] = []
        async for key in redis.scan_iter(match="studio:approval:*"):
            key_str = key.decode() if isinstance(key, bytes) else str(key)
            if ":result:" in key_str:
                continue
            raw = await redis.get(key_str)
            if raw is None:
                continue
            try:
                record = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if not isinstance(record, dict) or record.get("status") != "pending":
                continue
            if record.get("user_id") != str(user_id) or record.get("session_id") != session_id:
                continue
            ttl = await cast(Awaitable[int], redis.ttl(key_str))
            record["expires_in"] = ttl if ttl > 0 else 0
            records.append(record)
        return records

    async def wait_resolution(
        self,
        approval_id: str,
        timeout: int = APPROVAL_TTL_SECONDS,  # noqa: ASYNC109 - 透传 BLPOP 等待秒数
    ) -> dict[str, Any]:
        """BLPOP 等待 REST 端点写入的决议；超时返回 {"action": "timeout"}。

        BLPOP 本身是 await，不阻塞事件循环。决议 JSON 由 resolve() 以
        RPUSH 写入 ``studio:approval:result:{id}``。
        """
        key = _RESULT_KEY.format(approval_id=approval_id)
        # redis.asyncio 类型标注为 Awaitable[T] | T，async 客户端实际恒为 Awaitable
        item = await cast(
            Awaitable[tuple[str, str] | None], get_redis().blpop([key], timeout=timeout)
        )
        if item is None:
            return {"action": "timeout"}
        _, raw = item
        try:
            resolution = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning(f"[Studio] 审批 {approval_id} 决议 JSON 非法，按超时处理")
            return {"action": "timeout"}
        if not isinstance(resolution, dict):
            return {"action": "timeout"}
        return resolution

    async def resolve(
        self,
        approval_id: str,
        user_id: str,
        action: str,
        modified_args: dict[str, Any] | None = None,
        reason: str | None = None,
        always: bool = False,
    ) -> dict[str, Any] | None:
        """消费审批：校验归属与 pending 状态，写决议 list 并更新记录状态。

        返回更新后的记录；记录不存在、归属不符或已被消费（含超时落账）时返回 None。
        always=True 时决议载荷携带 always 标记，供聊天流更新本会话放行集合。
        """
        redis = get_redis()
        resolution: dict[str, Any] = {"action": action}
        if modified_args is not None:
            resolution["modified_args"] = modified_args
        if reason:
            resolution["reason"] = reason
        if always:
            resolution["always"] = True
        raw = await cast(
            Awaitable[str | bytes | None],
            redis.eval(
                _RESOLVE_APPROVAL_LUA,
                2,
                _RECORD_KEY.format(approval_id=approval_id),
                _RESULT_KEY.format(approval_id=approval_id),
                str(user_id),
                action,
                json.dumps(resolution, ensure_ascii=False, default=str),
                reason or "",
                str(APPROVAL_TTL_SECONDS),
            ),
        )
        if raw is None:
            return None
        try:
            record = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("[Studio] 审批 {} 原子决议返回非法记录", approval_id)
            return None
        return record if isinstance(record, dict) else None


_studio_approval_service: StudioApprovalService | None = None


def get_studio_approval_service() -> StudioApprovalService:
    global _studio_approval_service
    if _studio_approval_service is None:
        _studio_approval_service = StudioApprovalService()
    return _studio_approval_service
