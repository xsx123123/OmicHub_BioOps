"""FastAPI 应用入口"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from omichub.api.v1.router import api_router
from omichub.core.config import get_settings
from omichub.core.exceptions import OmicHubError
from omichub.core.logging import setup_logging

# 显式加载 Celery 应用：使 @shared_task 绑定到配置好的 celery_app（含 task_routes / task_default_queue）。
# 否则 web 进程会回退到 Celery 默认 app，把任务投到默认 "celery" 队列而非 "analysis"，导致 worker 消费不到。
from omichub.infrastructure.celery_app.celery import celery_app  # noqa: F401
from omichub.middleware.audit import AuditMiddleware
from omichub.middleware.auth import AuthMiddleware
from omichub.middleware.cookie import CookieRequiredMiddleware
from omichub.middleware.module_gate import ModuleGateMiddleware
from omichub.middleware.rate_limit import RateLimitMiddleware
from omichub.middleware.trace_context import TraceContextMiddleware


async def _init_default_ai_provider() -> None:
    """若数据库中无 AI Provider 配置，则从环境变量创建默认配置"""
    from omichub.core.config import get_settings
    from omichub.domain.ai_provider.entities import AIProviderConfig
    from omichub.domain.ai_provider.value_objects import ProviderType
    from omichub.infrastructure.database.repositories.ai_provider_repository import (
        SqlAlchemyAIProviderConfigRepository,
    )
    from omichub.infrastructure.database.session import get_session_factory

    settings = get_settings()
    factory = get_session_factory()
    if factory is None:
        return

    async with factory() as session:
        repo = SqlAlchemyAIProviderConfigRepository(session)
        count = await repo.count()
        if count > 0:
            return

        provider_type = (
            ProviderType.KIMI if settings.llm_provider == "kimi" else ProviderType.OPENAI
        )
        model = settings.kimi_model if settings.llm_provider == "kimi" else settings.openai_model
        base_url = (
            settings.kimi_base_url if settings.llm_provider == "kimi" else settings.openai_base_url
        )
        api_key = (
            settings.kimi_api_key if settings.llm_provider == "kimi" else settings.openai_api_key
        )

        if not api_key:
            return

        config = AIProviderConfig.create(
            name="默认 Kimi 配置" if settings.llm_provider == "kimi" else "默认 OpenAI 配置",
            provider_type=provider_type,
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=settings.ai_temperature,
        )
        config.is_default = True
        await repo.save(config)
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动与关闭

    性能优化：初始化步骤并行执行（asyncio.gather），首启耗时从「串行之和」降为
    「最慢一项」；沙盒容器池预热转后台任务，不阻塞 app 接受请求（首请求无需等容器池）。
    """
    setup_logging()
    from loguru import logger

    from omichub.core.telemetry import setup_telemetry

    setup_telemetry("web")

    settings = get_settings()
    logger.info(f"启动 {settings.app_name} (env={settings.app_env})")

    # --- 模块注册表：启动时硬校验，语法错误/key 重复/缺字段直接拒绝启动 ---
    from omichub.infrastructure.config.module_registry import init_module_registry

    registry = init_module_registry()
    logger.info(f"模块注册表已加载，共 {len(registry.modules)} 个模块")

    from omichub.infrastructure.database.session import init_db

    # --- 第 0 步：数据库连接必须先就绪（后续步骤依赖它）---
    try:
        await init_db()
        logger.info("数据库连接已就绪")
    except Exception as e:
        logger.warning(f"数据库未就绪，降级运行: {e}")

    # --- 沙盒预热：转后台 task，不阻塞 app 就绪（首请求无需等容器池）---
    async def _warmup_sandbox() -> None:
        try:
            from omichub.infrastructure.sandbox import get_sandbox_pool

            # 活跃会话绑定的容器要保留（只登记计数，不当孤儿收割/收养）
            keep: set[str] = set()
            try:
                from sqlalchemy import select

                from omichub.infrastructure.database.models.sandbox import (
                    SandboxSessionModel,
                )
                from omichub.infrastructure.database.session import get_session_factory

                factory = get_session_factory()
                if factory is not None:
                    async with factory() as session:
                        rows = await session.execute(
                            select(SandboxSessionModel.container_id).where(
                                SandboxSessionModel.container_id.isnot(None),
                                SandboxSessionModel.status.in_(
                                    ["creating", "ready", "executing", "idle", "paused"]
                                ),
                            )
                        )
                        keep = {r for (r,) in rows.all() if r}
            except Exception as e:
                logger.warning(f"查询活跃沙盒会话失败，按无保留处理: {e}")

            await get_sandbox_pool().initialize(keep_container_ids=keep)
            logger.info("沙盒容器池预热完成")
        except Exception as e:
            logger.warning(f"沙盒容器池未预热，降级运行: {e}")

    sandbox_task = asyncio.create_task(_warmup_sandbox())

    # --- 三个独立的写库初始化并行执行 ---
    async def _sync_ai_providers() -> None:
        # 从外置 YAML 同步 AI Provider 配置（推荐方式：data/ai/providers.yaml）
        try:
            from omichub.application.services.ai_provider_yaml_loader import (
                AIProviderYamlLoader,
            )
            from omichub.infrastructure.database.session import get_session_factory

            factory = get_session_factory()
            if factory is not None:
                async with factory() as session:
                    count = await AIProviderYamlLoader(session).load_and_sync()
                    if count:
                        logger.info(f"已从 YAML 同步 {count} 个 AI Provider")
                    await session.commit()
        except Exception as e:
            logger.warning(f"AI Provider YAML 同步失败，降级运行: {e}")

    async def _init_default_provider() -> None:
        # 兜底：若数据库中仍无任何 AI Provider，则从环境变量创建默认配置
        try:
            await _init_default_ai_provider()
            logger.info("AI Provider 初始化完成")
        except Exception as e:
            logger.warning(f"AI Provider 初始化失败，降级运行: {e}")

    async def _init_assistants() -> None:
        # 初始化内置聊天助手（RNA-seq 分析师、单细胞分析师等）
        try:
            from omichub.application.services.chat_service import ChatService
            from omichub.infrastructure.database.session import get_session_factory

            factory = get_session_factory()
            if factory is not None:
                async with factory() as session:
                    service = ChatService(session)
                    await service.init_builtin_assistants()
                    await session.commit()
                    logger.info("内置聊天助手初始化完成")
        except Exception as e:
            logger.warning(f"内置聊天助手初始化失败，降级运行: {e}")

    async def _init_mcp_presets() -> None:
        # 初始化/同步内置 MCP 预设（omichub-platform / omichub-tools / omichub-pipelines），
        # 确保预设工具清单（含新增的工作区文件工具）随代码演进同步进库，供 Agent 上下文组装使用。
        try:
            from omichub.application.services.mcp_service import MCPService
            from omichub.infrastructure.database.session import get_session_factory

            factory = get_session_factory()
            if factory is not None:
                async with factory() as session:
                    await MCPService(session).ensure_presets()
                    await session.commit()
                    logger.info("内置 MCP 预设初始化完成")
        except Exception as e:
            logger.warning(f"内置 MCP 预设初始化失败，降级运行: {e}")

    async def _init_builtin_agents() -> None:
        """同步内置 Agent，并安装其 YAML 声明的内置市场 Skill。"""
        try:
            from omichub.application.services.agent_service import AgentService
            from omichub.infrastructure.database.session import get_session_factory

            factory = get_session_factory()
            if factory is not None:
                async with factory() as session:
                    await AgentService(session).ensure_builtin_agents()
                    await session.commit()
                    logger.info("内置 Agent 与声明的 Skill 初始化完成")
        except Exception as e:
            logger.warning(f"内置 Agent 初始化失败，降级运行: {e}")

    async def _repair_user_storage_directories() -> None:
        """启动时为所有存量用户补齐默认目录和物理目录。"""
        try:
            from sqlalchemy import select

            from omichub.application.services.file_service import FileService
            from omichub.infrastructure.database.models.user import UserModel
            from omichub.infrastructure.database.session import get_session_factory

            factory = get_session_factory()
            if factory is None:
                return
            async with factory() as session:
                result = await session.execute(select(UserModel.id))
                user_ids = [row[0] for row in result.all()]
                for user_id in user_ids:
                    await FileService(session).ensure_default_directories(user_id)
                logger.info("用户默认目录校验完成：%d 个用户", len(user_ids))
        except Exception as e:
            logger.warning(f"用户默认目录补偿失败，降级运行: {e}")

    await asyncio.gather(
        _sync_ai_providers(),
        _init_default_provider(),
        _init_assistants(),
        _init_mcp_presets(),
        _repair_user_storage_directories(),
    )
    await _init_builtin_agents()

    # 欢迎词补齐：须在 AI Provider 同步完成之后（依赖默认 provider），
    # 故串行执行而非并入上方 gather。条数 < 阈值才调 LLM 补齐；失败仅 log，不阻塞启动。
    # 注意：补齐需串行调 LLM 多次（默认阈值 20 条，单次数秒），若在 startup 同步 await 会
    # 阻塞应用就绪 → 健康检查失败 → nginx 502。故改为后台任务，startup 立即完成，补齐异步进行。
    async def _seed_welcome() -> None:
        try:
            from omichub.application.services.welcome_service import WelcomeService
            from omichub.infrastructure.database.session import get_session_factory

            factory = get_session_factory()
            if factory is not None:
                async with factory() as session:
                    total = await WelcomeService(session).seed_if_needed()
                    await session.commit()
                    logger.info(f"管理员欢迎词就绪，共 {total} 条")
        except Exception as e:
            logger.warning(f"欢迎词补齐失败，降级使用兜底文案: {e}")

    welcome_task = asyncio.create_task(_seed_welcome())

    async def _auto_reindex_knowledge() -> None:
        """Incrementally refresh published knowledge chunks after deployment."""
        factory = None
        lock_acquired = False
        try:
            from sqlalchemy import text

            from omichub.application.services.knowledge_index_service import (
                KnowledgeIndexService,
            )
            from omichub.infrastructure.database.session import get_session_factory

            factory = get_session_factory()
            if factory is None:
                return
            async with factory() as session:
                # Prevent every web replica from embedding the same changed document.
                try:
                    lock_acquired = bool(
                        (
                            await session.execute(
                                text("SELECT pg_try_advisory_lock(:lock_key)"),
                                {"lock_key": 738421906},
                            )
                        ).scalar()
                    )
                except Exception:
                    # SQLite/dev fallback has no advisory lock; the transaction is still safe.
                    lock_acquired = True
                if not lock_acquired:
                    logger.info("知识库增量索引由其他实例执行，本实例跳过")
                    return
                rebuilt, skipped = await KnowledgeIndexService(session).ensure_published_indexes()
                await session.commit()
                logger.info("知识库增量索引完成：重建 {} 篇，跳过 {} 篇", rebuilt, skipped)
                if lock_acquired:
                    with suppress(Exception):
                        await session.execute(
                            text("SELECT pg_advisory_unlock(:lock_key)"),
                            {"lock_key": 738421906},
                        )
        except Exception as exc:  # noqa: BLE001 - indexing must not block web startup
            logger.warning("知识库自动增量索引失败，仍可手动执行 reindex 脚本: {}", exc)

    knowledge_index_task = asyncio.create_task(_auto_reindex_knowledge())
    yield

    # 关闭时清理：取消未完成的沙盒预热 + 欢迎词补齐 + 知识库索引 + 关闭数据库
    sandbox_task.cancel()
    welcome_task.cancel()
    knowledge_index_task.cancel()
    from omichub.infrastructure.database.session import close_db

    await close_db()
    logger.info("应用已关闭")


def create_app() -> FastAPI:
    """FastAPI 应用工厂"""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description="私有化多组学分析平台",
        version="0.1.0",
        docs_url="/docs" if settings.app_debug else None,
        redoc_url="/redoc" if settings.app_debug else None,
        lifespan=lifespan,
    )

    # CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 模块权限拦截中间件：受管控模块 API 的授权守卫。
    # 注册在 AuthMiddleware 之前（更内层），请求进入时 user_id 已注入 request.state。
    app.add_middleware(ModuleGateMiddleware)

    # JWT 认证中间件（全局拦截，公开路径在 PUBLIC_PATHS 中配置）
    app.add_middleware(AuthMiddleware)

    # 饼干消费拦截中间件（消费类路由的账户状态守卫）
    app.add_middleware(CookieRequiredMiddleware)

    # 审计日志中间件：记录写操作。注册在 Auth 之后（更外层），
    # 响应回流时 AuthMiddleware 已注入 request.state.user_id，可据此归属操作者。
    app.add_middleware(AuditMiddleware)

    # 限流中间件：全局每 IP 滑动窗口。最后注册=最外层，先于鉴权拦截，Redis 不可用降级放行。
    app.add_middleware(
        RateLimitMiddleware,
        max_requests=settings.rate_limit_max,
        window_seconds=settings.rate_limit_window,
        enabled=settings.rate_limit_enabled,
    )

    # 请求关联中间件：生成/透传 X-Request-ID 写入 ContextVar。
    # 最后注册=最外层，确保所有后续中间件与业务日志都带同一 request_id。
    app.add_middleware(TraceContextMiddleware)

    # OpenTelemetry 自动埋点（HTTP server span + 出站 httpx）与 /metrics 暴露。
    from omichub.core.telemetry import instrument_app, mount_metrics

    instrument_app(app)
    mount_metrics(app)

    # 全局异常处理
    @app.exception_handler(OmicHubError)
    async def omichub_error_handler(request: Request, exc: OmicHubError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    # 请求参数校验失败：返回 422 及具体字段错误，避免被下方兜底 500 吞掉。
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        def _sanitize(obj: Any) -> Any:
            """将 Pydantic error 结构中的异常对象/不可序列化值转成字符串。"""
            if isinstance(obj, list):
                return [_sanitize(item) for item in obj]
            if isinstance(obj, dict):
                return {key: _sanitize(value) for key, value in obj.items()}
            if isinstance(obj, BaseException):
                return str(obj)
            return obj

        raw_errors = exc.errors()
        safe_errors = _sanitize(raw_errors)
        logger.warning(f"Validation error on {request.method} {request.url.path}: {safe_errors}")
        return JSONResponse(
            status_code=422,
            content={"detail": "请求参数校验失败", "errors": safe_errors},
        )

    # 兜底异常处理：捕获所有未被上面精准命中的异常（如 DB 缺列、连接失败等
    # SQLAlchemyError / 编程错误），记录完整堆栈到日志，对外仅返回通用 500 提示。
    # 避免内部错误信息泄露，也避免前端把 500 误判成"密码错误"等业务错误。
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(f"Unhandled exception on {request.method} {request.url.path}: {exc}")
        return JSONResponse(
            status_code=500,
            content={"detail": "系统内部错误，请联系管理员"},
        )

    # 注册路由
    app.include_router(api_router, prefix="/api/v1")

    # 静态资源：开放 docs/ 目录供知识库图片引用（如 /docs-static/knowledge/figure/xxx.png）
    docs_static_path = Path("docs")
    if docs_static_path.is_dir():
        app.mount("/docs-static", StaticFiles(directory=docs_static_path), name="docs-static")

    # 开发模式下提供顶层重定向，便于直接访问 uvicorn 时不因缺少 /api/v1 前缀而 404
    if settings.app_debug:

        @app.get("/flows", include_in_schema=False)
        async def _redirect_flows_root(request: Request) -> RedirectResponse:
            return RedirectResponse(url=f"/api/v1/flows{request.query_params}")

        @app.get("/flows/{path:path}", include_in_schema=False)
        async def _redirect_flows_path(request: Request, path: str) -> RedirectResponse:
            return RedirectResponse(url=f"/api/v1/flows/{path}{request.query_params}")

    # 健康检查
    @app.get("/health", tags=["system"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
