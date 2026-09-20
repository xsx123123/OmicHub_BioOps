"""日志模块单元测试"""

from pathlib import Path

import pytest
from loguru import logger

from cygnusx.core import logging as logging_module
from cygnusx.core.logging import _resolve_log_dir, setup_logging


@pytest.fixture(autouse=True)
def _reset_logger():
    """每个测试前后清理 loguru handler，避免相互影响。"""
    yield
    logger.remove()


class TestResolveLogDir:
    """测试日志目录解析。"""

    def test_honors_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CYGNUSX_LOG_DIR", str(tmp_path))
        assert _resolve_log_dir() == tmp_path

    def test_creates_missing_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log_dir = tmp_path / "new_logs"
        monkeypatch.setenv("CYGNUSX_LOG_DIR", str(log_dir))
        assert _resolve_log_dir() == log_dir
        assert log_dir.exists()


class TestSetupLogging:
    """测试日志初始化。"""

    def test_creates_expected_log_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CYGNUSX_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("SERVICE_NAME", "test-web")
        monkeypatch.setenv("CYGNUSX_LOG_LEVEL", "INFO")

        setup_logging()

        # 验证主日志、JSON 日志、error 日志文件已创建
        assert (tmp_path / "cygnusx.log").exists()
        assert (tmp_path / "cygnusx.json.log").exists()
        assert (tmp_path / "error.log").exists()

    def test_service_binding(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CYGNUSX_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("SERVICE_NAME", "test-worker")

        setup_logging()

        # 验证 service extra 已绑定
        assert logger._core.extra["service"] == "test-worker"  # type: ignore[attr-defined]

    def test_log_message_lands_in_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CYGNUSX_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("SERVICE_NAME", "test-web")
        monkeypatch.setenv("CYGNUSX_LOG_LEVEL", "INFO")

        setup_logging()

        test_message = "unit-test-log-message"
        logger.info(test_message)

        # 立即刷新（enqueue=True 异步写入，需等待一小会儿）
        import time

        time.sleep(0.2)

        log_text = (tmp_path / "cygnusx.log").read_text(encoding="utf-8")
        assert test_message in log_text
        assert "test-web" in log_text

        json_log_text = (tmp_path / "cygnusx.json.log").read_text(encoding="utf-8")
        assert test_message in json_log_text

    def test_error_log_only_contains_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CYGNUSX_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("SERVICE_NAME", "test-web")
        monkeypatch.setenv("CYGNUSX_LOG_LEVEL", "INFO")

        setup_logging()

        logger.info("info-message")
        logger.error("error-message")

        import time

        time.sleep(0.2)

        error_text = (tmp_path / "error.log").read_text(encoding="utf-8")
        assert "error-message" in error_text
        assert "info-message" not in error_text


class TestEnvironmentVariables:
    """测试环境变量默认值。"""

    def test_default_service_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SERVICE_NAME", raising=False)
        # 重新加载模块以触发模块级 setup_logging
        import importlib

        importlib.reload(logging_module)
        assert logging_module.SERVICE_NAME == "app"

    def test_default_log_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CYGNUSX_LOG_LEVEL", raising=False)
        import importlib

        importlib.reload(logging_module)
        assert logging_module.LOG_LEVEL == "INFO"
