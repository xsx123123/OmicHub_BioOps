"""
LangGraph AgentState 定义
============================
贯穿 LangGraph 所有节点的状态载体，与 OmicHub 现有领域模型对齐。

设计原则:
    - Pydantic v2 BaseModel 保证类型安全
    - 所有字段有默认值，支持空状态初始化
    - 与 OmicHub 现有模型（AgentContext, TaskContext）兼容转换
"""

from __future__ import annotations

import time
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Literal

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from pydantic import BaseModel, ConfigDict, Field


# ──────────────────────────────
# 枚举类型
# ──────────────────────────────

class HITLStatus(str, Enum):
    """HITL（人工在环）状态"""
    NONE = "none"           # 无需人工干预
    PENDING = "pending"     # 等待人工输入
    RESUMED = "resumed"     # 人工已恢复执行
    REJECTED = "rejected"   # 人工拒绝，流程终止
    TIMEOUT = "timeout"     # 人工等待超时


class TaskPhase(str, Enum):
    """任务执行阶段"""
    IDLE = "idle"               # 未开始
    PARAM_GATHER = "param_gather"   # 参数收集中
    PARAM_CONFIRM = "param_confirm" # 等待参数确认（HITL）
    TASK_BUILDING = "task_building" # 构建任务
    TASK_SUBMITTED = "task_submitted" # 任务已提交
    RUNNING = "running"         # 分析运行中
    RESULT_REVIEW = "result_review" # 等待结果审核（HITL）
    COMPLETED = "completed"     # 已完成
    FAILED = "failed"           # 失败


# ──────────────────────────────
# 子模型
# ──────────────────────────────

class ToolCallRecord(BaseModel):
    """单次工具调用记录"""
    model_config = ConfigDict(frozen=False, extra="allow")

    tool_name: str = Field(description="工具名称")
    tool_input: Dict[str, Any] = Field(default_factory=dict, description="工具输入参数")
    tool_output: Optional[str] = Field(default=None, description="工具输出结果")
    success: bool = Field(default=True, description="是否成功")
    latency_ms: float = Field(default=0.0, description="调用耗时(ms)")
    timestamp: float = Field(default_factory=time.time, description="调用时间戳")
    error: Optional[str] = Field(default=None, description="错误信息")


class TaskContext(BaseModel):
    """任务上下文 —— 当用户要求执行分析任务时填充"""
    model_config = ConfigDict(frozen=False, extra="allow")

    flow_id: Optional[str] = Field(default=None, description="流程ID (rna_seq / atac_seq)")
    flow_name: Optional[str] = Field(default=None, description="流程显示名称")
    samples: List[Dict[str, Any]] = Field(default_factory=list, description="样本列表")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="分析参数")
    contrasts: Optional[List[Dict[str, Any]]] = Field(default=None, description="比较组")
    task_id: Optional[str] = Field(default=None, description="已提交的任务ID")
    recommended_params: Optional[Dict[str, Any]] = Field(default=None, description="AI推荐的参数")
    param_confirmed: bool = Field(default=False, description="参数是否已确认")


class ExecutionMetadata(BaseModel):
    """执行元数据 —— 追踪性能和诊断信息"""
    model_config = ConfigDict(frozen=False, extra="allow")

    round_count: int = Field(default=0, ge=0, le=50, description="当前轮次")
    max_rounds: int = Field(default=8, ge=1, le=50, description="最大轮次")
    start_time: float = Field(default_factory=time.time, description="开始时间戳")
    last_activity: float = Field(default_factory=time.time, description="最后活动时间")
    total_tokens: int = Field(default=0, description="累计 Token 消耗")
    prompt_tokens: int = Field(default=0, description="Prompt Token 数")
    completion_tokens: int = Field(default=0, description="Completion Token 数")
    model_id: Optional[str] = Field(default=None, description="使用的模型ID")
    agent_id: Optional[str] = Field(default=None, description="使用的 Agent ID")
    session_id: Optional[str] = Field(default=None, description="会话ID")
    user_id: Optional[int] = Field(default=None, description="用户ID")
    thread_id: Optional[str] = Field(default=None, description="LangGraph thread ID")


class HITLPayload(BaseModel):
    """HITL 中断载荷 —— 当需要人工确认时填充"""
    model_config = ConfigDict(frozen=False, extra="allow")

    interrupt_for: Literal["param_confirm", "task_submit", "result_review", "error_recovery"] = Field(
        description="中断原因"
    )
    title: str = Field(description="弹窗标题")
    description: str = Field(description="弹窗说明")
    payload: Dict[str, Any] = Field(default_factory=dict, description="待确认的数据")
    timeout_seconds: int = Field(default=300, ge=30, le=3600, description="超时时间")
    created_at: float = Field(default_factory=time.time, description="创建时间")


# ──────────────────────────────
# 主状态模型
# ──────────────────────────────

class AgentState(BaseModel):
    """
    LangGraph Agent 状态定义

    这是贯穿 LangGraph 所有节点的核心状态载体。
    所有节点接收 AgentState，处理后返回新的 AgentState。
    LangGraph 自动处理状态合并和持久化。

    兼容 OmicHub 现有模型:
        - AgentContext → 可转换为 AgentState（通过 from_agent_context 类方法）
        - TaskContext → 嵌套在 AgentState 中
    """
    model_config = ConfigDict(frozen=False, extra="allow", arbitrary_types_allowed=True)

    # ── 消息与对话 ──
    messages: List[BaseMessage] = Field(
        default_factory=list,
        description="对话历史 (langchain message 序列)"
    )

    # ── 工具调用 ──
    tool_calls: List[ToolCallRecord] = Field(
        default_factory=list,
        description="工具调用记录"
    )

    # ── 任务上下文 ──
    task_context: Optional[TaskContext] = Field(
        default=None,
        description="任务上下文（执行分析时填充）"
    )

    # ── HITL 状态 ──
    hitl_status: HITLStatus = Field(
        default=HITLStatus.NONE,
        description="HITL 状态"
    )
    hitl_payload: Optional[HITLPayload] = Field(
        default=None,
        description="当前 HITL 中断载荷"
    )
    hitl_response: Optional[Dict[str, Any]] = Field(
        default=None,
        description="人工输入的响应数据"
    )

    # ── 执行元数据 ──
    metadata: ExecutionMetadata = Field(
        default_factory=ExecutionMetadata,
        description="执行元数据"
    )

    # ── 路由控制 ──
    next_node: Optional[str] = Field(
        default=None,
        description="条件边路由目标"
    )

    # ── 系统提示词 ──
    system_prompt: Optional[str] = Field(
        default=None,
        description="系统提示词（避免每次重新组装）"
    )

    # ── 工具定义 ──
    tools: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="可用工具定义（OpenAI tools 格式）"
    )

    # ── MCP 服务器 ──
    mcp_servers: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="MCP 服务器配置"
    )

    # ── 模型配置 ──
    model_config_dict: Optional[Dict[str, Any]] = Field(
        default=None,
        description="模型连接配置"
    )

    # ── 错误处理 ──
    error: Optional[str] = Field(
        default=None,
        description="节点执行错误信息"
    )
    error_count: int = Field(
        default=0,
        ge=0,
        le=10,
        description="连续错误计数"
    )

    # ── 完成标记 ──
    is_finished: bool = Field(
        default=False,
        description="流程是否已完成"
    )
    final_response: Optional[str] = Field(
        default=None,
        description="最终响应文本"
    )

    # ──────────────────────────────
    # 序列化/反序列化辅助
    # ──────────────────────────────

    def to_checkpoint_dict(self) -> Dict[str, Any]:
        """
        转换为 LangGraph checkpoint 兼容的 dict 格式
        BaseMessage 会被序列化为 dict
        """
        data = self.model_dump(exclude_none=False, mode="json")
        # messages 需要特殊处理（BaseMessage 不是纯 JSON）
        data["messages"] = [
            {"type": msg.type, "content": msg.content, "additional_kwargs": msg.additional_kwargs}
            for msg in self.messages
        ]
        # 枚举转字符串
        data["hitl_status"] = self.hitl_status.value
        if self.task_context:
            data["task_context"] = self.task_context.model_dump(mode="json")
        if self.metadata:
            data["metadata"] = self.metadata.model_dump(mode="json")
        if self.hitl_payload:
            data["hitl_payload"] = self.hitl_payload.model_dump(mode="json")
        return data

    @classmethod
    def from_checkpoint_dict(cls, data: Dict[str, Any]) -> AgentState:
        """从 checkpoint dict 恢复 AgentState"""
        # 恢复 messages
        messages = []
        for msg_dict in data.get("messages", []):
            msg_type = msg_dict.get("type", "")
            content = msg_dict.get("content", "")
            kwargs = msg_dict.get("additional_kwargs", {})
            if msg_type == "human":
                messages.append(HumanMessage(content=content, **kwargs))
            elif msg_type == "ai":
                messages.append(AIMessage(content=content, **kwargs))
            elif msg_type == "system":
                messages.append(SystemMessage(content=content, **kwargs))
            elif msg_type == "tool":
                messages.append(ToolMessage(content=content, **kwargs))

        # 恢复子模型
        task_context = None
        if data.get("task_context"):
            task_context = TaskContext(**data["task_context"])

        metadata = ExecutionMetadata(**data.get("metadata", {}))

        hitl_payload = None
        if data.get("hitl_payload"):
            hitl_payload = HITLPayload(**data["hitl_payload"])

        hitl_status = HITLStatus(data.get("hitl_status", "none"))

        return cls(
            messages=messages,
            tool_calls=[ToolCallRecord(**tc) for tc in data.get("tool_calls", [])],
            task_context=task_context,
            hitl_status=hitl_status,
            hitl_payload=hitl_payload,
            hitl_response=data.get("hitl_response"),
            metadata=metadata,
            next_node=data.get("next_node"),
            system_prompt=data.get("system_prompt"),
            tools=data.get("tools", []),
            mcp_servers=data.get("mcp_servers", []),
            model_config_dict=data.get("model_config_dict"),
            error=data.get("error"),
            error_count=data.get("error_count", 0),
            is_finished=data.get("is_finished", False),
            final_response=data.get("final_response"),
        )

    # ──────────────────────────────
    # 便捷方法
    # ──────────────────────────────

    @property
    def last_message(self) -> Optional[BaseMessage]:
        """获取最后一条消息"""
        return self.messages[-1] if self.messages else None

    @property
    def is_last_message_ai(self) -> bool:
        """最后一条消息是否来自 AI"""
        return isinstance(self.last_message, AIMessage) if self.last_message else False

    @property
    def has_tool_calls_in_last_message(self) -> bool:
        """最后一条 AI 消息是否包含 tool_calls"""
        if not isinstance(self.last_message, AIMessage):
            return False
        return bool(self.last_message.additional_kwargs.get("tool_calls"))

    @property
    def hitl_pending(self) -> bool:
        """是否处于 HITL 等待状态"""
        return self.hitl_status == HITLStatus.PENDING

    def add_message(self, message: BaseMessage) -> AgentState:
        """添加消息并返回新状态（函数式更新）"""
        self.messages.append(message)
        self.metadata.last_activity = time.time()
        return self

    def add_tool_call(self, record: ToolCallRecord) -> AgentState:
        """添加工具调用记录"""
        self.tool_calls.append(record)
        return self

    def increment_round(self) -> AgentState:
        """增加轮次计数"""
        self.metadata.round_count += 1
        return self

    def update_tokens(self, prompt: int, completion: int) -> AgentState:
        """更新 Token 消耗"""
        self.metadata.prompt_tokens += prompt
        self.metadata.completion_tokens += completion
        self.metadata.total_tokens = self.metadata.prompt_tokens + self.metadata.completion_tokens
        return self

    def set_error(self, error_msg: str) -> AgentState:
        """设置错误状态"""
        self.error = error_msg
        self.error_count += 1
        return self

    def clear_error(self) -> AgentState:
        """清除错误"""
        self.error = None
        self.error_count = 0
        return self

    def hitl_interrupt(self, payload: HITLPayload) -> AgentState:
        """触发 HITL 中断"""
        self.hitl_status = HITLStatus.PENDING
        self.hitl_payload = payload
        self.hitl_response = None
        return self

    def hitl_resume(self, human_input: Dict[str, Any]) -> AgentState:
        """恢复 HITL 执行"""
        self.hitl_status = HITLStatus.RESUMED
        self.hitl_response = human_input
        self.hitl_payload = None
        return self

    def hitl_reject(self, reason: str = "") -> AgentState:
        """拒绝 HITL 请求，终止流程"""
        self.hitl_status = HITLStatus.REJECTED
        self.is_finished = True
        self.final_response = f"操作已取消。{reason}" if reason else "操作已取消。"
        return self

    def finish(self, response: str) -> AgentState:
        """标记流程完成"""
        self.is_finished = True
        self.final_response = response
        return self

    @classmethod
    def from_agent_context(
        cls,
        agent_context: Dict[str, Any],
        user_message: str = "",
        session_id: str = "",
        user_id: int = 0,
    ) -> AgentState:
        """
        从 OmicHub 现有的 AgentContext 创建 AgentState

        Args:
            agent_context: AgentService.assemble_context() 的返回结果
            user_message: 用户当前输入
            session_id: 会话ID
            user_id: 用户ID
        """
        messages = []

        # 系统提示词 → SystemMessage
        if agent_context.get("system_prompt"):
            messages.append(SystemMessage(content=agent_context["system_prompt"]))

        # 用户消息 → HumanMessage
        if user_message:
            messages.append(HumanMessage(content=user_message))

        # 构建 ExecutionMetadata
        metadata = ExecutionMetadata(
            model_id=agent_context.get("agent", {}).get("model_id"),
            agent_id=agent_context.get("agent", {}).get("id"),
            session_id=session_id,
            user_id=user_id,
            thread_id=f"omh_{user_id}_{session_id}_{int(time.time())}",
        )

        return cls(
            messages=messages,
            metadata=metadata,
            system_prompt=agent_context.get("system_prompt"),
            tools=agent_context.get("tools", []),
            mcp_servers=agent_context.get("mcp_servers", []),
            model_config_dict=agent_context.get("model_config"),
        )
