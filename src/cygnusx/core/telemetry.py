"""可观测性核心 - OpenTelemetry 统一初始化（Trace / Metrics / Log 关联）

设计目标：
- 单一入口 ``setup_telemetry(service_name)`` 在 web/worker/beat 启动时调用一次。
- 默认通过 OTLP gRPC 导出 traces/metrics；未配置端点时 traces 降级为控制台（debug）
  或 noop，metrics 仍经 Prometheus ``/metrics`` 暴露——保证本地与测试零配置可用。
- 遥测自身的任何异常都不得中断业务启动：全部包裹在 try/except 内降级。
- 埋点代码通过全局代理 ``opentelemetry.trace.get_tracer`` / ``metrics.get_meter``
  获取实例，未初始化时自动 noop，因此无需关心初始化时序。

环境变量（经 core.config.Settings 读取）：
- telemetry_enabled: 总开关，关闭后全部 noop。
- otel_exporter_endpoint: OTLP gRPC 端点（如 http://otel-collector:4317）。
- otel_service_name: 服务名覆盖；为空时取传入的 service_name。
- metrics_enabled: 是否暴露 Prometheus /metrics。
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Any

from loguru import logger

from cygnusx.core.config import get_settings

# 记录是否已初始化，避免重复注册 provider（uvicorn --reload / 多入口场景）。
_initialized = False
# Prometheus 指标读取器引用；mount_metrics 时用它确认已注册。
_prometheus_reader: Any = None
# httpx 自动埋点为进程级全局操作，重复 instrument 会告警，故仅执行一次。
_httpx_instrumented = False

# agent.run 网关把自身 span context 发布到这里；LangGraph 图任务等跨 asyncio task
# 边界的子 span 在 contextvars 链路丢失时可显式取回父 context，避免 trace 断链。
agent_parent_context_var: ContextVar[Any] = ContextVar(
    "cygnusx_agent_parent_context", default=None
)

# Celery 消息头里携带 session_id 的自定义键（traceparent/tracestate 由 W3C propagator 写入）。
_SESSION_HEADER = "x-cygnusx-session-id"


def inject_trace_context(headers: dict[str, Any] | None) -> None:
    """把当前 span context（traceparent）与 session_id 注入消息载体（如 Celery headers）。

    无活跃 span / 未初始化 / 任何异常均为安全 no-op，绝不阻断业务。
    """
    if headers is None:
        return
    try:
        from opentelemetry.propagate import inject

        inject(headers)
        from cygnusx.middleware.trace_context import session_id_var

        session_id = session_id_var.get()
        if session_id:
            headers[_SESSION_HEADER] = session_id
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"trace context 注入失败（忽略）: {exc}")


def extract_and_attach(headers: Any) -> tuple[Any | None, Any | None]:
    """从消息载体提取 trace context 并 attach，同时恢复 session_id ContextVar。

    返回 ``(context_token, session_token)``；无载体或失败时为 ``(None, None)``。
    调用方须在作用域结束后把返回值交给 ``detach_extracted`` 复位。
    """
    if not headers:
        return None, None
    try:
        from opentelemetry import context as otel_context
        from opentelemetry.propagate import extract

        context_token = otel_context.attach(extract(dict(headers)))
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"trace context 提取失败（忽略）: {exc}")
        return None, None
    session_token = None
    try:
        session_id = headers.get(_SESSION_HEADER)
        if session_id:
            from cygnusx.middleware.trace_context import session_id_var

            session_token = session_id_var.set(str(session_id))
    except Exception:  # noqa: BLE001
        pass
    return context_token, session_token


def detach_extracted(tokens: tuple[Any | None, Any | None]) -> None:
    """与 ``extract_and_attach`` 配对：复位 session_id 并 detach context。"""
    context_token, session_token = tokens
    if session_token is not None:
        try:
            from cygnusx.middleware.trace_context import session_id_var

            session_id_var.reset(session_token)
        except Exception:  # noqa: BLE001
            pass
    if context_token is not None:
        try:
            from opentelemetry import context as otel_context

            otel_context.detach(context_token)
        except Exception:  # noqa: BLE001
            pass


def _build_resource(service_name: str) -> Any:
    """构建 OTel Resource：服务名/版本/环境，供后端按服务区分遥测来源。"""
    from opentelemetry.sdk.resources import Resource

    settings = get_settings()
    return Resource.create(
        {
            "service.name": service_name,
            "service.version": getattr(settings, "app_version", "0.1.0"),
            "deployment.environment": settings.app_env,
        }
    )


def _make_span_exporter(debug: bool) -> Any | None:
    """选择 span 导出器：有 OTLP 端点用 gRPC；否则 debug 下控制台，生产 noop。"""
    settings = get_settings()
    endpoint = settings.otel_exporter_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            return OTLPSpanExporter(endpoint=endpoint, insecure=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"OTLP span exporter 初始化失败，降级 noop: {exc}")
            return None
    if debug:
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        return ConsoleSpanExporter()
    return None


def setup_telemetry(service_name: str) -> None:
    """初始化 TracerProvider 与 MeterProvider（幂等）。

    失败时仅记录警告并退回 noop，绝不抛出，确保业务启动不受遥测影响。
    """
    global _initialized, _prometheus_reader

    settings = get_settings()
    if not settings.telemetry_enabled:
        logger.info(f"遥测已禁用（service={service_name}），使用 noop 探针")
        return
    if _initialized:
        return

    resolved_name = settings.otel_service_name or service_name
    debug = settings.app_debug

    try:
        from opentelemetry import metrics, trace
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = _build_resource(resolved_name)

        # ---- Traces ----
        tracer_provider = TracerProvider(resource=resource)
        span_exporter = _make_span_exporter(debug)
        if span_exporter is not None:
            tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
        # 应用内 span 持久化：富化 session.id/request.id + 写 JSONL，供管理端 Trace 瀑布图。
        if settings.span_store_enabled:
            try:
                from cygnusx.core.span_store import JsonlSpanExporter, CygnusXSpanProcessor

                tracer_provider.add_span_processor(CygnusXSpanProcessor())
                tracer_provider.add_span_processor(
                    BatchSpanProcessor(
                        JsonlSpanExporter(max_bytes=settings.span_store_max_mb * 1024 * 1024)
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"span 应用内持久化初始化失败: {exc}")
        trace.set_tracer_provider(tracer_provider)

        # ---- Metrics ----
        readers: list[Any] = []
        if settings.metrics_enabled:
            try:
                from opentelemetry.exporter.prometheus import PrometheusMetricReader

                _prometheus_reader = PrometheusMetricReader()
                readers.append(_prometheus_reader)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Prometheus metric reader 初始化失败: {exc}")

        endpoint = settings.otel_exporter_endpoint or os.getenv(
            "OTEL_EXPORTER_OTLP_ENDPOINT", ""
        )
        if endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                    OTLPMetricExporter,
                )

                readers.append(
                    PeriodicExportingMetricReader(
                        OTLPMetricExporter(endpoint=endpoint, insecure=True)
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"OTLP metric exporter 初始化失败: {exc}")

        if readers:
            metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=readers))

        _initialized = True
        logger.info(
            f"遥测已初始化（service={resolved_name}, otlp={'on' if endpoint else 'off'}, "
            f"prometheus={'on' if _prometheus_reader is not None else 'off'}）"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"遥测初始化失败，降级 noop: {exc}")


def instrument_app(app: Any) -> None:
    """为 FastAPI 应用挂载自动埋点（HTTP server span + 出站 httpx）。

    必须在 setup_telemetry 之后调用；失败时降级，不影响应用。
    """
    settings = get_settings()
    if not settings.telemetry_enabled:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"FastAPI 自动埋点失败: {exc}")
    global _httpx_instrumented
    if not _httpx_instrumented:
        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

            HTTPXClientInstrumentor().instrument()
            _httpx_instrumented = True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"httpx 自动埋点失败: {exc}")


def mount_metrics(app: Any) -> None:
    """把 Prometheus 指标暴露到 ``/metrics``（无鉴权，供内网 Prometheus 抓取）。"""
    settings = get_settings()
    if not settings.telemetry_enabled or not settings.metrics_enabled:
        return
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
        from starlette.responses import Response

        @app.get("/metrics", include_in_schema=False)
        async def metrics_endpoint() -> Response:  # type: ignore[no-redef]
            return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    except Exception as exc:  # noqa: BLE001
        logger.warning(f"/metrics 挂载失败: {exc}")


def get_tracer(name: str) -> Any:
    """获取全局 tracer；未初始化时返回 noop tracer，调用方无需判空。"""
    from opentelemetry import trace

    return trace.get_tracer(name)


def get_meter(name: str) -> Any:
    """获取全局 meter；未初始化时返回 noop meter。"""
    from opentelemetry import metrics

    return metrics.get_meter(name)
