"""工具二次确认服务。

管理 AI 提交分析任务前的用户确认记录：
- 创建确认记录（PENDING）
- 用户批准 => 调用 TaskService.submit() => SUBMITTED
- 用户拒绝 => REJECTED
- 过期 / 篡改 / 重复消费拒绝

Phase 1 使用进程内内存存储 + TTL；后续可替换为 Redis + DB 双写。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from omichub.application.schemas.task import TaskSubmitRequest
from omichub.application.schemas.tool_invocation import ToolInvocationContext
from omichub.application.services.task_service import TaskService


class ConfirmationError(Exception):
    """确认记录操作异常"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class ConfirmationRecord:
    """确认记录"""

    confirmation_id: str
    user_id: str
    agent_id: str | None
    session_id: str
    flow_id: str
    flow_name: str
    parameter_hash: str
    normalized_request: dict[str, Any]
    status: str  # PENDING / APPROVED / REJECTED / SUBMITTED / EXPIRED / INVALID
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None
    task_id: str | None = None
    rejection_reason: str | None = None


@dataclass
class ApprovalResult:
    """批准结果"""

    status: str
    task_id: str | None = None
    task_card: dict[str, Any] | None = None
    message: str | None = None


class ToolConfirmationService:
    """工具确认服务（内存实现，带 TTL）。"""

    DEFAULT_TTL_SECONDS = 1800  # 30 分钟

    def __init__(self) -> None:
        self._records: dict[str, ConfirmationRecord] = {}

    async def create(
        self,
        context: ToolInvocationContext,
        flow_id: str,
        flow_name: str,
        normalized_request: TaskSubmitRequest,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> ConfirmationRecord:
        """创建确认记录。"""
        confirmation_id = str(uuid.uuid4())
        request_dict = normalized_request.model_dump(mode="json")
        parameter_hash = self._hash_request(request_dict)
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)

        record = ConfirmationRecord(
            confirmation_id=confirmation_id,
            user_id=context.user_id,
            agent_id=context.agent_id,
            session_id=context.session_id,
            flow_id=flow_id,
            flow_name=flow_name,
            parameter_hash=parameter_hash,
            normalized_request=request_dict,
            status="PENDING",
            created_at=now,
            expires_at=expires_at,
        )
        self._records[confirmation_id] = record
        return record

    async def approve(
        self,
        context: ToolInvocationContext,
        confirmation_id: str,
        task_service: TaskService,
    ) -> ApprovalResult:
        """批准确认记录并提交任务。"""
        record = self._get_record(context, confirmation_id)
        if record is None:
            raise ConfirmationError("ACCESS_DENIED", "无权操作或确认记录不存在")

        if record.status != "PENDING":
            raise ConfirmationError("ALREADY_CONSUMED", f"确认记录状态为 {record.status}")

        if datetime.now(UTC) > record.expires_at:
            record.status = "EXPIRED"
            raise ConfirmationError("CONFIRMATION_EXPIRED", "确认已过期，请重新预检")

        # 原子消费：先置为 APPROVED
        record.status = "APPROVED"

        try:
            request = TaskSubmitRequest(**record.normalized_request)
            task_response = await task_service.submit(context.user_id, request)
        except Exception as e:  # noqa: BLE001
            record.status = "INVALID"
            raise ConfirmationError("SUBMIT_FAILED", f"任务提交失败: {e}") from e

        record.status = "SUBMITTED"
        record.consumed_at = datetime.now(UTC)
        record.task_id = str(task_response.id)

        task_card = {
            "type": "task_card",
            "task_id": str(task_response.id),
            "flow_id": task_response.flow_id,
            "status": task_response.status.upper(),
            "progress": task_response.progress,
            "task_url": f"/tasks/{task_response.id}",
            "logs_url": f"/api/v1/tasks/{task_response.id}/logs",
            "monitor_url": f"/monitor/tasks/{task_response.id}",
            "created_at": task_response.created_at.isoformat() if task_response.created_at else None,
        }

        return ApprovalResult(
            status="SUBMITTED",
            task_id=record.task_id,
            task_card=task_card,
            message="任务已提交",
        )

    async def reject(
        self,
        context: ToolInvocationContext,
        confirmation_id: str,
        reason: str | None = None,
    ) -> ConfirmationRecord:
        """拒绝确认记录。"""
        record = self._get_record(context, confirmation_id)
        if record is None:
            raise ConfirmationError("ACCESS_DENIED", "无权操作或确认记录不存在")

        if record.status not in ("PENDING", "APPROVED"):
            raise ConfirmationError("ALREADY_CONSUMED", f"确认记录状态为 {record.status}")

        record.status = "REJECTED"
        record.rejection_reason = reason
        record.consumed_at = datetime.now(UTC)
        return record

    async def get_status(
        self,
        context: ToolInvocationContext,
        confirmation_id: str,
    ) -> ConfirmationRecord | None:
        """查询确认记录状态。"""
        return self._get_record(context, confirmation_id)

    def cleanup_expired(self) -> int:
        """清理过期记录，返回清理数量。"""
        now = datetime.now(UTC)
        expired_keys = [
            k for k, r in self._records.items() if r.status == "PENDING" and r.expires_at < now
        ]
        for k in expired_keys:
            self._records[k].status = "EXPIRED"
        return len(expired_keys)

    def _get_record(
        self, context: ToolInvocationContext, confirmation_id: str
    ) -> ConfirmationRecord | None:
        """查询并校验归属的记录。"""
        record = self._records.get(confirmation_id)
        if record is None:
            return None
        if record.user_id != context.user_id:
            return None

        # 过期自动标记
        if record.status == "PENDING" and datetime.now(UTC) > record.expires_at:
            record.status = "EXPIRED"

        return record

    @staticmethod
    def _hash_request(request_dict: dict[str, Any]) -> str:
        """计算请求参数的 SHA-256 哈希。"""
        canonical = json.dumps(request_dict, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# 全局单例
_confirmation_service: ToolConfirmationService | None = None


def get_tool_confirmation_service() -> ToolConfirmationService:
    """获取全局确认服务单例。"""
    global _confirmation_service
    if _confirmation_service is None:
        _confirmation_service = ToolConfirmationService()
    return _confirmation_service
