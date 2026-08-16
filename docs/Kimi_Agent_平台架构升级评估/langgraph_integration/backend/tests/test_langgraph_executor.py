"""
LangGraphExecutor 测试
=======================
测试 LangGraphExecutor 的核心功能:
    - 执行器注册
    - 状态转换
    - HITL 中断与恢复
    - 错误处理
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from omichub.domain.execution.agent_state import (
    AgentState,
    ExecutionMetadata,
    HITLPayload,
    HITLStatus,
    TaskContext,
    ToolCallRecord,
)
from omichub.infrastructure.execution.langgraph_executor import LangGraphExecutor, register_langgraph_executor
from omichub.infrastructure.execution.base import ExecutionContext, ExecutionResult


# ── Fixtures ──

@pytest.fixture
def mock_runtime():
    """Mock LangGraphRuntimeService"""
    runtime = AsyncMock()
    runtime.stream = AsyncMock(return_value=async_generator([
        {"type": "text", "data": {"content": "Hello", "thread_id": "test_1"}, "state": None},
        {"type": "done", "data": {"content": "Done", "thread_id": "test_1", "metadata": {}}, "state": None},
    ]))
    runtime.cancel = AsyncMock(return_value=True)
    runtime.get_status = AsyncMock(return_value={"status": "completed"})
    runtime.resume_hitl = AsyncMock(return_value=async_generator([
        {"type": "text", "data": {"content": "Resumed", "thread_id": "test_1"}, "state": None},
        {"type": "done", "data": {"content": "Done", "thread_id": "test_1"}, "state": None},
    ]))
    return runtime


@pytest.fixture
def executor(mock_runtime):
    """LangGraphExecutor 实例"""
    return LangGraphExecutor(runtime_service=mock_runtime)


@pytest.fixture
def sample_agent_state():
    """示例 AgentState"""
    return AgentState(
        messages=[
            SystemMessage(content="You are a bioinformatics assistant."),
            HumanMessage(content="Analyze my RNA-seq data."),
        ],
        metadata=ExecutionMetadata(
            thread_id="test_thread_001",
            agent_id="bio_assistant",
            user_id=1,
            session_id="session_001",
        ),
    )


async def async_generator(items):
    """辅助: 创建异步生成器"""
    for item in items:
        yield item


# ── 测试用例 ──

class TestLangGraphExecutor:
    """LangGraphExecutor 测试"""

    def test_name(self, executor):
        """测试执行器名称"""
        assert executor.name == "langgraph"

    def test_supports_hitl(self, executor):
        """测试 HITL 支持"""
        assert executor.supports_hitl is True

    def test_supports_checkpoint(self, executor):
        """测试检查点支持"""
        assert executor.supports_checkpoint is True

    @pytest.mark.asyncio
    async def test_execute_success(self, executor, mock_runtime):
        """测试正常执行"""
        ctx = ExecutionContext(
            snakefile="/workflow/Snakefile",
            config_file=None,
            work_dir="/tmp/test",
        )

        result = await executor.execute(ctx)

        assert isinstance(result, ExecutionResult)
        assert result.status == "success"
        mock_runtime.stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_without_runtime(self):
        """测试未初始化 runtime 时的执行"""
        exec_without_runtime = LangGraphExecutor(runtime_service=None)
        ctx = ExecutionContext(work_dir="/tmp/test")

        result = await exec_without_runtime.execute(ctx)

        assert result.status == "failed"
        assert "未初始化" in result.stderr

    @pytest.mark.asyncio
    async def test_cancel(self, executor, mock_runtime):
        """测试取消执行"""
        success = await executor.cancel("thread_001")
        assert success is True
        mock_runtime.cancel.assert_called_once_with("thread_001")

    @pytest.mark.asyncio
    async def test_get_status(self, executor, mock_runtime):
        """测试状态查询"""
        status = await executor.get_status("thread_001")
        assert status["status"] == "completed"

    @pytest.mark.asyncio
    async def test_resume_hitl(self, executor, mock_runtime):
        """测试 HITL 恢复"""
        success = await executor.resume_hitl(
            thread_id="thread_001",
            human_input={"action": "confirm", "confirmed_params": {}},
        )
        assert success is True
        mock_runtime.resume_hitl.assert_called_once()


class TestAgentState:
    """AgentState 模型测试"""

    def test_initial_state(self):
        """测试初始状态"""
        state = AgentState()
        assert state.hitl_status == HITLStatus.NONE
        assert state.is_finished is False
        assert state.error is None
        assert state.metadata.round_count == 0

    def test_add_message(self):
        """测试添加消息"""
        state = AgentState()
        msg = HumanMessage(content="Hello")

        state.add_message(msg)

        assert len(state.messages) == 1
        assert state.last_message == msg

    def test_hitl_interrupt(self):
        """测试 HITL 中断"""
        state = AgentState()
        payload = HITLPayload(
            interrupt_for="param_confirm",
            title="Confirm",
            description="Please confirm",
        )

        state.hitl_interrupt(payload)

        assert state.hitl_status == HITLStatus.PENDING
        assert state.hitl_payload == payload

    def test_hitl_resume(self):
        """测试 HITL 恢复"""
        state = AgentState()
        state.hitl_interrupt(HITLPayload(
            interrupt_for="param_confirm",
            title="Confirm",
            description="Please confirm",
        ))

        state.hitl_resume({"confirmed": True})

        assert state.hitl_status == HITLStatus.RESUMED
        assert state.hitl_response == {"confirmed": True}
        assert state.hitl_payload is None

    def test_hitl_reject(self):
        """测试 HITL 拒绝"""
        state = AgentState()
        state.hitl_reject("User cancelled")

        assert state.hitl_status == HITLStatus.REJECTED
        assert state.is_finished is True
        assert "取消" in state.final_response

    def test_finish(self):
        """测试完成"""
        state = AgentState()
        state.finish("Task completed successfully")

        assert state.is_finished is True
        assert state.final_response == "Task completed successfully"

    def test_token_tracking(self):
        """测试 Token 消耗追踪"""
        state = AgentState()
        state.update_tokens(prompt=100, completion=50)

        assert state.metadata.prompt_tokens == 100
        assert state.metadata.completion_tokens == 50
        assert state.metadata.total_tokens == 150

    def test_error_handling(self):
        """测试错误处理"""
        state = AgentState()
        state.set_error("Something went wrong")

        assert state.error == "Something went wrong"
        assert state.error_count == 1

        state.clear_error()
        assert state.error is None
        assert state.error_count == 0

    def test_serialization_roundtrip(self, sample_agent_state):
        """测试序列化/反序列化往返"""
        # 添加一些工具调用记录
        sample_agent_state.add_tool_call(ToolCallRecord(
            tool_name="search_genome",
            tool_input={"query": "TP53"},
            tool_output='{"results": []}',
            success=True,
        ))

        # to_dict → from_dict
        checkpoint_dict = sample_agent_state.to_checkpoint_dict()
        restored = AgentState.from_checkpoint_dict(checkpoint_dict)

        assert restored.metadata.thread_id == sample_agent_state.metadata.thread_id
        assert restored.metadata.agent_id == sample_agent_state.metadata.agent_id
        assert len(restored.messages) == len(sample_agent_state.messages)
        assert len(restored.tool_calls) == 1
        assert restored.tool_calls[0].tool_name == "search_genome"

    def test_round_limit(self, sample_agent_state):
        """测试轮次限制"""
        sample_agent_state.metadata.max_rounds = 5
        sample_agent_state.metadata.round_count = 5

        assert sample_agent_state.metadata.round_count >= sample_agent_state.metadata.max_rounds


class TestHITLModels:
    """HITL 模型测试"""

    def test_hitl_request_expiration(self):
        """测试 HITL 请求过期"""
        from omichub.domain.execution.hitl_models import HITLRequest, HITLType

        request = HITLRequest(
            thread_id="test_thread",
            session_id="test_session",
            user_id=1,
            hitl_type=HITLType.PARAM_CONFIRM,
            title="Test",
            description="Test description",
            timeout_seconds=1,
        )

        assert not request.is_expired

        # 模拟过期
        import time
        time.sleep(1.1)
        assert request.is_expired

    def test_hitl_request_remaining(self):
        """测试剩余时间计算"""
        from omichub.domain.execution.hitl_models import HITLRequest, HITLType

        request = HITLRequest(
            thread_id="test_thread",
            session_id="test_session",
            user_id=1,
            hitl_type=HITLType.PARAM_CONFIRM,
            title="Test",
            description="Test",
            timeout_seconds=300,
        )

        assert request.remaining_seconds > 0
        assert request.remaining_seconds <= 300


class TestRegistration:
    """执行器注册测试"""

    def test_register_langgraph_executor(self, mock_runtime):
        """测试注册函数"""
        registry = {}
        register_langgraph_executor(registry, mock_runtime)

        assert "langgraph" in registry
        assert isinstance(registry["langgraph"], LangGraphExecutor)


# ── 运行 ──

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
