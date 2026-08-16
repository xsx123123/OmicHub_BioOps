"""
LangGraphExecutor
==================
继承 OmicHub 现有的 BaseExecutor，注册到 registry.py。

功能:
    - 封装 LangGraph StateGraph 为 BaseExecutor 接口
    - 兼容现有 TaskService 的调用方式
    - 内部使用 LangGraphRuntimeService 执行

设计:
    - Executor 是「外壳」，真正逻辑在 RuntimeService
    - 保持与 LocalSnakemakeExecutor / BinaryExecutor 相同的调用契约
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from omichub.domain.execution.agent_state import AgentState
from omichub.infrastructure.execution.base import BaseExecutor, ExecutionContext, ExecutionResult
from omichub.infrastructure.execution.langgraph_runtime import LangGraphRuntimeService


class LangGraphExecutor(BaseExecutor):
    """
    LangGraph 执行器 —— 注册到 registry.py

    使用方式:
        # registry.py 注册
        _EXECUTORS = {
            "snakemake": LocalSnakemakeExecutor,
            "binary": BinaryExecutor,
            "langgraph": LangGraphExecutor,  # 新增
        }

        # flows/*.yaml 配置
        execution:
          engine: langgraph   # 启用 LangGraph 执行
          snakefile: "/workflow/Snakefile"
          container_image: "omichub/flow-rnaseq:v1.0"
    """

    def __init__(self, runtime_service: Optional[LangGraphRuntimeService] = None):
        self._runtime = runtime_service

    @property
    def name(self) -> str:
        return "langgraph"

    @property
    def supports_hitl(self) -> bool:
        """是否支持 HITL"""
        return True

    @property
    def supports_checkpoint(self) -> bool:
        """是否支持断点续跑"""
        return True

    async def execute(self, ctx: ExecutionContext) -> ExecutionResult:
        """
        执行入口 —— 兼容 BaseExecutor 接口

        Args:
            ctx: ExecutionContext 包含 snakefile / config / work_dir 等

        Returns:
            ExecutionResult 包含状态 / 日志 / 返回码
        """
        if not self._runtime:
            return ExecutionResult(
                status="failed",
                returncode=1,
                stdout="",
                stderr="LangGraphRuntimeService 未初始化",
            )

        try:
            # 从 ExecutionContext 构建 AgentState
            state = self._build_agent_state(ctx)

            # 运行 LangGraph（异步迭代事件流）
            events = []
            async for event in self._runtime.stream(state):
                events.append(event)

            # 提取最终结果
            final_state = event.get("state") if events else None
            if final_state and final_state.is_finished:
                return ExecutionResult(
                    status="success" if not final_state.error else "failed",
                    returncode=0 if not final_state.error else 1,
                    stdout=final_state.final_response or "执行完成",
                    stderr=final_state.error or "",
                )

            # HITL 中断中
            if final_state and final_state.hitl_pending:
                return ExecutionResult(
                    status="hitl_pending",
                    returncode=0,
                    stdout=final_state.hitl_payload.description if final_state.hitl_payload else "等待人工确认",
                    stderr="",
                )

            return ExecutionResult(
                status="success",
                returncode=0,
                stdout="LangGraph 执行完成",
                stderr="",
            )

        except Exception as e:
            return ExecutionResult(
                status="failed",
                returncode=1,
                stdout="",
                stderr=f"LangGraphExecutor 异常: {str(e)}",
            )

    async def cancel(self, execution_id: str) -> bool:
        """取消执行"""
        if self._runtime:
            return await self._runtime.cancel(execution_id)
        return False

    async def get_status(self, execution_id: str) -> Dict[str, Any]:
        """获取执行状态"""
        if self._runtime:
            return await self._runtime.get_status(execution_id)
        return {"status": "unknown"}

    async def resume_hitl(
        self,
        thread_id: str,
        human_input: Dict[str, Any],
    ) -> bool:
        """
        恢复 HITL 中断的执行

        Args:
            thread_id: LangGraph thread ID
            human_input: 人工输入数据
        """
        if self._runtime:
            return await self._runtime.resume_hitl(thread_id, human_input)
        return False

    # ── 内部方法 ──

    def _build_agent_state(self, ctx: ExecutionContext) -> AgentState:
        """从 ExecutionContext 构建初始 AgentState"""
        from omichub.domain.execution.agent_state import ExecutionMetadata, TaskContext

        # 解析 ctx 中的任务信息
        task_context = None
        if ctx.config_file:
            import yaml
            try:
                with open(ctx.config_file) as f:
                    config = yaml.safe_load(f)
                task_context = TaskContext(
                    flow_id=config.get("flow_id"),
                    parameters=config.get("params", {}),
                    samples=config.get("samples", []),
                    contrasts=config.get("contrasts"),
                )
            except Exception:
                pass

        metadata = ExecutionMetadata(
            thread_id=f"exec_{ctx.work_dir.replace('/', '_')}",
        )

        return AgentState(
            messages=[],
            task_context=task_context,
            metadata=metadata,
        )


# ──────────────────────────────
# 注册到 registry.py 的辅助函数
# ──────────────────────────────

def register_langgraph_executor(registry: Dict[str, Any], runtime_service: LangGraphRuntimeService) -> None:
    """
    将 LangGraphExecutor 注册到执行器注册表

    用法（在 registry.py 或 main.py 生命周期中）:
        from omichub.infrastructure.execution.langgraph_executor import register_langgraph_executor
        from omichub.infrastructure.execution.langgraph_runtime import LangGraphRuntimeService

        runtime = LangGraphRuntimeService(...)
        register_langgraph_executor(_EXECUTORS, runtime)
    """
    executor = LangGraphExecutor(runtime_service=runtime_service)
    registry["langgraph"] = executor
