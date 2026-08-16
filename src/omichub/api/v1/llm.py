"""LLM 工具路由 —— 管理员欢迎彩蛋等轻量 LLM 能力。

当前仅提供 ``POST /llm/generate-welcome``：管理员登录后取下一条预生成欢迎词。
运行时不调 LLM（欢迎词在启动时已预生成落盘），仅读盘 + 游标前进，零延迟。
"""

from fastapi import APIRouter
from pydantic import BaseModel

from omichub.api.deps import DbSession
from omichub.api.v1.admin.users import AdminRequired
from omichub.application.services.welcome_service import WelcomeService

router = APIRouter()


class WelcomeResponse(BaseModel):
    """欢迎词响应 —— 与前端 composable 兼容的 {content} 形态。"""

    content: str


@router.post("/generate-welcome", response_model=WelcomeResponse, summary="取下一条管理员欢迎词")
async def generate_welcome(_admin: AdminRequired, db: DbSession) -> WelcomeResponse:
    """管理员专用：顺序轮询返回下一条预生成欢迎词。

    - 权限：依赖层 ``AdminRequired`` 校验非管理员返回 403。
    - 数据源：``data/welcome.yaml`` 预生成文案 + ``data/welcome_state.yaml`` 游标。
    - 兜底：文件缺失/空时返回内置默认文案，保证前端必有弹窗。
    - 性能：纯读盘，单次响应毫秒级。
    """
    # db 仅用于未来可能的扩展（如审计）；当前 welcome 走文件存储，但保持依赖一致性
    _ = db
    content = WelcomeService(db).get_next_welcome()
    return WelcomeResponse(content=content)
