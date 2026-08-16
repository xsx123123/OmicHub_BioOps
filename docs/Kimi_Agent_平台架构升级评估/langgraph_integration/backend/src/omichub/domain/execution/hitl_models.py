"""
HITL（人工在环）领域模型
=========================
定义 HITL 请求、响应、历史记录等模型。

HITL 流程:
    1. LangGraph 节点触发 interrupt → 创建 HITLRequest
    2. 前端收到 hitl_request SSE 事件 → 渲染确认弹窗
    3. 用户操作 → POST /api/v1/agent/hitl/resume → 创建 HITLResponse
    4. LangGraph 从 interrupt 恢复 → 继续执行
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class HITLAction(str, Enum):
    """人工操作类型"""
    CONFIRM = "confirm"       # 确认并继续
    MODIFY = "modify"         # 修改后继续
    REJECT = "reject"         # 拒绝并终止
    DEFER = "defer"           # 稍后处理（保存草稿）


class HITLType(str, Enum):
    """HITL 中断类型"""
    PARAM_CONFIRM = "param_confirm"     # 参数确认
    TASK_SUBMIT = "task_submit"         # 任务提交确认
    RESULT_REVIEW = "result_review"     # 结果审核
    ERROR_RECOVERY = "error_recovery"   # 错误恢复确认


class HITLRequest(BaseModel):
    """
    HITL 中断请求 —— 当 LangGraph 需要人工确认时创建

    存储于数据库，前端通过 SSE 实时推送。
    """
    model_config = ConfigDict(frozen=False, extra="allow")

    # 标识
    id: str = Field(default_factory=lambda: f"hitl_{uuid.uuid4().hex[:12]}", description="HITL 请求ID")
    thread_id: str = Field(description="关联的 LangGraph thread ID")
    session_id: str = Field(description="关联的会话ID")
    user_id: int = Field(description="目标用户ID")

    # 内容
    hitl_type: HITLType = Field(description="中断类型")
    title: str = Field(description="弹窗标题")
    description: str = Field(description="弹窗说明")
    payload: Dict[str, Any] = Field(default_factory=dict, description="待确认的数据")

    # 状态
    status: str = Field(default="pending", description="pending / responded / expired / cancelled")

    # 时间
    created_at: float = Field(default_factory=time.time, description="创建时间")
    timeout_seconds: int = Field(default=300, ge=30, le=3600, description="超时秒数")
    responded_at: Optional[float] = Field(default=None, description="响应时间")

    # 过期检查
    @property
    def is_expired(self) -> bool:
        if self.status != "pending":
            return False
        return (time.time() - self.created_at) > self.timeout_seconds

    @property
    def remaining_seconds(self) -> int:
        if self.status != "pending":
            return 0
        remaining = self.timeout_seconds - int(time.time() - self.created_at)
        return max(0, remaining)


class HITLResponse(BaseModel):
    """
    HITL 人工响应 —— 用户操作后的结果

    用于恢复 LangGraph 执行。
    """
    model_config = ConfigDict(frozen=False, extra="allow")

    request_id: str = Field(description="对应的 HITLRequest ID")
    action: HITLAction = Field(description="人工操作类型")
    human_input: Dict[str, Any] = Field(default_factory=dict, description="人工输入数据")
    comment: Optional[str] = Field(default=None, description="备注/说明")
    responded_by: int = Field(description="响应用户ID")
    responded_at: float = Field(default_factory=time.time, description="响应时间")


class HITLHistoryRecord(BaseModel):
    """
    HITL 历史记录 —— 用于审计和回溯
    """
    model_config = ConfigDict(frozen=False, extra="allow")

    id: str = Field(default_factory=lambda: f"hhr_{uuid.uuid4().hex[:12]}")
    thread_id: str = Field(description="Thread ID")
    session_id: str = Field(description="Session ID")
    user_id: int = Field(description="User ID")
    hitl_type: HITLType = Field(description="中断类型")
    request_payload: Dict[str, Any] = Field(description="请求载荷")
    response_action: HITLAction = Field(description="响应操作")
    response_input: Dict[str, Any] = Field(default_factory=dict, description="响应输入")
    latency_seconds: float = Field(description="人工响应耗时")
    created_at: float = Field(default_factory=time.time, description="创建时间")
