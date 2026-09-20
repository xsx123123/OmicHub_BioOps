#!/usr/bin/env python3
"""Loguru/Rich logging helpers for cygnusxtools."""

from __future__ import annotations

import datetime
import logging
import sys
import warnings
from pathlib import Path

try:
    from loguru import logger

    _LOGURU_AVAILABLE = True
except ImportError:  # pragma: no cover - project depends on loguru
    logger = None
    _LOGURU_AVAILABLE = False

try:
    from rich.console import Console
    from rich.logging import RichHandler

    _RICH_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    Console = None
    RichHandler = None
    _RICH_AVAILABLE = False

_CONSOLE = Console(stderr=True) if _RICH_AVAILABLE else None


def _ensure_loguru() -> None:
    if not _LOGURU_AVAILABLE:
        raise ImportError("loguru is required for cygnusxtools logging")


class _InterceptHandler(logging.Handler):
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


def _capture_warnings() -> None:
    def _showwarning(message, category, filename, lineno, file=None, line=None):  # type: ignore[no-untyped-def]
        logger.warning(f"{category.__name__}: {message} ({filename}:{lineno})")

    warnings.showwarning = _showwarning


def _capture_std_logging() -> None:
    logging.basicConfig(handlers=[_InterceptHandler()], level=logging.DEBUG, force=True)


def _add_console_handler(log_level: str, style: str = "default", more_info: bool = False) -> None:
    if _RICH_AVAILABLE and RichHandler is not None:
        handler = RichHandler(
            show_time=True,
            show_path=style == "detailed" or more_info,
            markup=True,
            rich_tracebacks=True,
            log_time_format="[%X]",
        )
        fmt = "{message}" if style != "detailed" and not more_info else "{name}:{function}:{line} - {message}"
        logger.add(handler, format=fmt, level=log_level, enqueue=True)
        return

    fmt = (
        "<green>{time:HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )
    logger.add(sys.stderr, format=fmt, level=log_level, colorize=True, enqueue=True)


def logger_init(
    logger_name: str | None = None,
    log_level: str = "INFO",
    more_info: bool = False,
    style: str = "default",
):
    _ensure_loguru()
    logger.remove()
    _add_console_handler(log_level, style=style, more_info=more_info)
    _capture_warnings()
    _capture_std_logging()

    if logger_name:
        file_fmt = (
            "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
            "{name}:{function}:{line} | {message}"
        )
        Path(logger_name).parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            logger_name,
            format=file_fmt,
            level="DEBUG",
            colorize=False,
            enqueue=True,
            backtrace=True,
            diagnose=False,
        )
    return logger


def setup_tool_logging(
    log_dir: str | Path = "logs/cygnusxtools",
    log_file_prefix: str = "cygnusxtools",
    log_level: str = "INFO",
    style: str = "default",
):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = Path(log_dir) / f"{log_file_prefix}_{timestamp}.log"
    return logger_init(str(log_file), log_level=log_level, style=style), log_file


def log_header(title: str) -> None:
    logger.info(f"[bold cyan]{'=' * 10} {title.upper()} {'=' * 10}[/bold cyan]")


def log_section(title: str) -> None:
    logger.info(f"[bold blue]--- {title} ---[/bold blue]")


def log_success(msg: str) -> None:
    logger.info(f"[bold green]OK[/bold green] {msg}")


def log_warning(msg: str) -> None:
    logger.warning(f"[bold yellow]WARN[/bold yellow] {msg}")


def log_error(msg: str) -> None:
    logger.error(f"[bold red]ERROR[/bold red] {msg}")


def log_info(msg: str) -> None:
    logger.info(msg)


def get_logger():
    return logger
