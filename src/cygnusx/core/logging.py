"""日志配置 - 基于 loguru 的统一日志管理

目标：
- 所有服务（web/beat/worker）使用统一日志格式与落盘路径。
- 同时输出可读文本、结构化 JSON、ERROR 独立日志。
- 支持通过环境变量控制服务名、日志级别与落盘目录。

环境变量：
- SERVICE_NAME: 服务标识，如 web/beat/worker，默认 app
- CYGNUSX_LOG_LEVEL: 日志级别，默认 INFO
- CYGNUSX_LOG_DIR: 日志根目录，默认 /app/logs；本地开发无法写入时自动回退到 ./logs
"""

import logging
import os
import sys
from pathlib import Path

from loguru import logger

from cygnusx.core.config import get_settings

# 容器内统一落盘路径；本地开发可覆盖
DEFAULT_LOG_DIR = "/app/logs"
# 本地开发回退路径（项目根目录下的 logs/）
FALLBACK_LOG_DIR = "logs"
# 最后一层兜底，避免容器 bind mount 权限异常导致服务启动失败。
LAST_RESORT_LOG_DIR = "/tmp/cygnusx/logs"

SERVICE_NAME = os.getenv("SERVICE_NAME", "app")
LOG_LEVEL = os.getenv("CYGNUSX_LOG_LEVEL", "INFO").upper()
LOG_ROTATION = os.getenv("CYGNUSX_LOG_ROTATION", "50 MB")
LOG_RETENTION = os.getenv("CYGNUSX_LOG_RETENTION", "30 days")
LOG_COMPRESSION = os.getenv("CYGNUSX_LOG_COMPRESSION", "zip")


class InterceptHandler(logging.Handler):
    """将标准库 logging 转发到 loguru，避免日志分散到 root logger。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame = logging.currentframe()
        depth = 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _is_writable_log_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        test_file = path / ".write_test"
        test_file.write_text("")
        test_file.unlink()
        return True
    except OSError:
        return False


def _resolve_log_dir() -> Path:
    """解析日志根目录。

    优先使用 CYGNUSX_LOG_DIR；不可写时回退到本地 logs/，再回退到 /tmp。
    这样 bind mount 权限异常时服务仍能启动，问题会通过 stdout 日志暴露。
    """
    raw_dir = os.getenv("CYGNUSX_LOG_DIR", DEFAULT_LOG_DIR)
    candidates = [Path(raw_dir), Path(FALLBACK_LOG_DIR), Path(LAST_RESORT_LOG_DIR)]
    tried: set[Path] = set()

    for candidate in candidates:
        path = candidate.resolve()
        if path in tried:
            continue
        tried.add(path)
        if _is_writable_log_dir(path):
            return path

    # /tmp 理论上应始终可写；保留 fail-fast 以暴露极端环境问题。
    raise PermissionError(f"No writable log directory found: {', '.join(str(p) for p in tried)}")


def _text_format() -> str:
    """文本日志格式：包含服务名、时间、级别、位置信息。"""
    return (
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
        "{extra[service]} | {name}:{function}:{line} | {message}"
    )


def _console_format() -> str:
    """控制台日志格式：带颜色，便于开发调试。"""
    return (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{extra[service]}</cyan> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )


def _telemetry_patch(record: "logging.LogRecord") -> None:  # type: ignore[type-arg]
    """向每条日志注入 trace_id / span_id / request_id，实现 Log↔Trace 关联。

    从当前 OpenTelemetry span 读取 trace/span id（无有效 span 时为 0），从
    trace_context 的 ContextVar 读取 request_id。所有导入均做容错，遥测缺失时
    仅写入空值，绝不影响日志本身。
    """
    extra = record["extra"]  # type: ignore[index]
    trace_id = 0
    span_id = 0
    try:
        from opentelemetry import trace as _otel_trace

        span = _otel_trace.get_current_span()
        ctx = span.get_span_context()
        if ctx is not None and ctx.trace_id:
            trace_id = ctx.trace_id
            span_id = ctx.span_id
    except Exception:  # noqa: BLE001
        pass
    request_id = ""
    session_id = ""
    try:
        from cygnusx.middleware.trace_context import request_id_var, session_id_var

        request_id = request_id_var.get()
        session_id = session_id_var.get()
    except Exception:  # noqa: BLE001
        pass
    extra.setdefault("trace_id", f"{trace_id:032x}" if trace_id else "")
    extra.setdefault("span_id", f"{span_id:016x}" if span_id else "")
    extra.setdefault("request_id", request_id)
    extra.setdefault("session_id", session_id)


def setup_logging() -> None:
    """初始化日志配置。

    配置 4 个 sink：
    1. stdout：开发可读，带颜色。
    2. cygnusx.log：文本主日志，按 50 MB 轮转，保留 30 天。
    3. cygnusx.json.log：结构化 JSON，供后续 Loki/Promtail 抓取。
    4. error.log：仅 ERROR 及以上，便于快速定位故障。
    """
    settings = get_settings()
    # 每次初始化时重新读取环境变量，便于测试与运行时覆盖
    log_level = os.getenv("CYGNUSX_LOG_LEVEL", LOG_LEVEL).upper()
    level = log_level if log_level in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} else "INFO"
    if not os.getenv("CYGNUSX_LOG_LEVEL"):
        # 未显式设置时，开发环境允许 DEBUG
        level = "DEBUG" if settings.app_debug else "INFO"

    service_name = os.getenv("SERVICE_NAME", SERVICE_NAME)
    log_dir = _resolve_log_dir()
    rotation = os.getenv("CYGNUSX_LOG_ROTATION", LOG_ROTATION)
    retention = os.getenv("CYGNUSX_LOG_RETENTION", LOG_RETENTION)
    compression = os.getenv("CYGNUSX_LOG_COMPRESSION", LOG_COMPRESSION)

    # 移除默认 handler
    logger.remove()

    # 1. stdout
    logger.add(
        sys.stdout,
        level=level,
        format=_console_format(),
        colorize=True,
        backtrace=True,
        diagnose=settings.app_debug,
    )

    # 2. 主日志文件
    logger.add(
        log_dir / "cygnusx.log",
        level="INFO",
        rotation=rotation,
        retention=retention,
        compression=compression,
        format=_text_format(),
        enqueue=True,
        backtrace=True,
        diagnose=settings.app_debug,
    )

    # 3. JSON 结构化日志（供 Loki 抓取）
    logger.add(
        log_dir / "cygnusx.json.log",
        level="INFO",
        rotation=rotation,
        retention=retention,
        compression=compression,
        serialize=True,
        enqueue=True,
    )

    # 4. ERROR 级别单独抽离
    logger.add(
        log_dir / "error.log",
        level="ERROR",
        rotation=rotation,
        retention=retention,
        compression=compression,
        format=_text_format(),
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )

    # 绑定服务名到上下文，并注入 trace/span/request 关联字段
    logger.configure(extra={"service": service_name}, patcher=_telemetry_patch)

    # 兼容仍使用 logging.getLogger(...) 的旧代码和第三方库日志。
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)


# 全局默认 logger；调用方优先使用 setup_logging() 重新初始化
# （web/beat/worker 的入口均已调用）。
setup_logging()
