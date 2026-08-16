"""
Agent API 路由（LangGraph 扩展）
=================================
新增路由:
    - POST /api/v1/agent/hitl/resume    HITL 恢复
    - GET  /api/v1/agent/checkpoints    检查点查询
    - POST /api/v1/agent/cancel         取消执行
    - GET  /api/v1/agent/status         执行状态查询

现有路由兼容:
    - POST /api/v1/chat/stream          由 ChatService 路由到 LangGraphRuntime
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from omichub.api.deps import CurrentUser, get_current_user
from omichub.application.services.hitl_service import HITLService
from omichub.application.services.stream_adapter import StreamAdapter, create_sse_response
from omichub.domain.execution.hitl_models import HITLAction
from omichub.infrastructure.execution.langgraph_runtime import LangGraphRuntimeService


router = APIRouter(prefix="/agent", tags=["agent-langgraph"])


# ──────────────────────────────
# 请求/响应模型
# ──────────────────────────────

class HITLResumeRequest(BaseModel):
    """HITL 恢复请求"""
    request_id: str = Field(description="HITL 请求ID")
    action: HITLAction = Field(description="操作类型: confirm / modify / reject / defer")
    human_input: Dict[str, Any] = Field(default_factory=dict, description="人工输入数据")
    comment: Optional[str] = Field(default=None, description="备注")


class HITLResumeResponse(BaseModel):
    """HITL 恢复响应"""
    success: bool
    thread_id: str = ""
    message: str = ""
    action: str = ""


class CancelRequest(BaseModel):
    """取消执行请求"""
    thread_id: str = Field(description="LangGraph thread ID")


class StatusResponse(BaseModel):
    """状态查询响应"""
    thread_id: str
    status: str
    user_id: Optional[int] = None
    session_id: Optional[str] = None


# ──────────────────────────────
# 依赖注入（由 lifespan 或 deps 提供实例）
# ──────────────────────────────

# 这些实例在 main.py lifespan 中创建并注入
_langgraph_runtime: Optional[LangGraphRuntimeService] = None
_hitl_service: Optional[HITLService] = None


def set_langgraph_services(
    runtime: LangGraphRuntimeService,
    hitl: HITLService,
) -> None:
    """在 main.py lifespan 中调用，注入服务实例"""
    global _langgraph_runtime, _hitl_service
    _langgraph_runtime = runtime
    _hitl_service = hitl


def get_runtime() -> LangGraphRuntimeService:
    if not _langgraph_runtime:
        raise HTTPException(status_code=503, detail="LangGraph 运行时未初始化")
    return _langgraph_runtime


def get_hitl_service() -> HITLService:
    if not _hitl_service:
        raise HTTPException(status_code=503, detail="HITL 服务未初始化")
    return _hitl_service


# ──────────────────────────────
# 路由
# ──────────────────────────────

@router.post("/hitl/resume", response_model=HITLResumeResponse)
async def hitl_resume(
    req: HITLResumeRequest,
    user: CurrentUser = Depends(get_current_user),
    hitl_service: HITLService = Depends(get_hitl_service),
) -> HITLResumeResponse:
    """
    HITL 人工响应 —— 恢复中断的 LangGraph 执行

    流程:
        1. 用户在前端确认/修改/拒绝 HITL 弹窗
        2. 前端调用此 API
        3. HITLService 记录响应并恢复 LangGraph
    """
    result = await hitl_service.handle_response(
        request_id=req.request_id,
        action=req.action,
        human_input=req.human_input,
        user_id=user.id,
        comment=req.comment,
    )

    return HITLResumeResponse(
        success=result.get("success", False),
        thread_id=result.get("thread_id", ""),
        message=result.get("message", ""),
        action=result.get("action", ""),
    )


@router.get("/hitl/pending")
async def get_pending_hitl(
    session_id: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
    hitl_service: HITLService = Depends(get_hitl_service),
) -> List[Dict[str, Any]]:
    """
    获取当前用户的待处理 HITL 请求

    用于页面刷新后恢复弹窗状态。
    """
    requests = await hitl_service.get_pending_requests(
        user_id=user.id,
        session_id=session_id,
    )
    return [
        {
            "id": r.id,
            "hitl_type": r.hitl_type.value,
            "title": r.title,
            "description": r.description,
            "payload": r.payload,
            "thread_id": r.thread_id,
            "remaining_seconds": r.remaining_seconds,
        }
        for r in requests
    ]


@router.post("/hitl/cancel")
async def cancel_hitl(
    request_id: str,
    user: CurrentUser = Depends(get_current_user),
    hitl_service: HITLService = Depends(get_hitl_service),
) -> Dict[str, bool]:
    """取消 HITL 请求"""
    success = await hitl_service.cancel_request(request_id, user.id)
    return {"success": success}


@router.post("/cancel")
async def cancel_execution(
    req: CancelRequest,
    user: CurrentUser = Depends(get_current_user),
    runtime: LangGraphRuntimeService = Depends(get_runtime),
) -> Dict[str, bool]:
    """
    取消 LangGraph 执行

    通过 thread_id 取消运行中的任务。
    """
    success = await runtime.cancel(req.thread_id)
    return {"success": success}


@router.get("/status/{thread_id}", response_model=StatusResponse)
async def get_execution_status(
    thread_id: str,
    user: CurrentUser = Depends(get_current_user),
    runtime: LangGraphRuntimeService = Depends(get_runtime),
) -> StatusResponse:
    """查询 LangGraph 执行状态"""
    status_data = await runtime.get_status(thread_id)
    return StatusResponse(
        thread_id=status_data.get("thread_id", thread_id),
        status=status_data.get("status", "unknown"),
        user_id=status_data.get("user_id"),
        session_id=status_data.get("session_id"),
    )


@router.get("/checkpoints/{thread_id}")
async def get_checkpoints(
    thread_id: str,
    limit: int = 10,
    user: CurrentUser = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """
    获取线程的检查点历史

    用于调试和状态回溯。
    """
    # 通过 checkpoint saver 查询
    from omichub.infrastructure.checkpoint.postgres_checkpoint import OmicHubCheckpointSaver

    saver = OmicHubCheckpointSaver()
    checkpoints = []

    async for ckpt in saver.alist(
        config={"configurable": {"thread_id": thread_id}},
        limit=limit,
    ):
        checkpoints.append({
            "checkpoint_id": ckpt.config["configurable"].get("checkpoint_id"),
            "metadata": ckpt.metadata,
            "parent_id": ckpt.parent_config["configurable"].get("checkpoint_id") if ckpt.parent_config else None,
        })

    return checkpoints
