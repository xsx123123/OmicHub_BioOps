"""第二轮安全修复单元测试 — 覆盖本轮审计新增的关键修复。"""

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from cygnusx.application.schemas.task import TaskSubmitRequest
from cygnusx.application.services.ai_tools import AIToolExecutor
from cygnusx.application.services.chat_service import ChatService
from cygnusx.core.security import create_access_token, decode_token
from cygnusx.core.config import Settings
from cygnusx.infrastructure.mcp.client import (
    validate_stdio_args,
    validate_stdio_command,
    validate_working_dir,
)
from cygnusx.middleware.login_rate_limit import _client_ip


class DummyRequest:
    """用于 login_rate_limit 测试的轻量 Request 替身。"""

    def __init__(self, headers: dict[str, str] | None = None, client_host: str = "127.0.0.1"):
        self.headers = headers or {}
        self.client = type("Client", (), {"host": client_host})()


class TestLoginRateLimitClientIp:
    """#5 登录限流 X-Forwarded-For 防伪造：取链中最后一个 IP。"""

    def test_no_proxy_uses_direct_client(self):
        req = DummyRequest(client_host="192.168.1.10")
        assert _client_ip(req) == "192.168.1.10"

    def test_xff_takes_last_trusted_ip(self):
        # 客户端伪造 1.1.1.1，但 nginx 追加真实 IP 10.0.0.5 在末尾
        req = DummyRequest(headers={"x-forwarded-for": "1.1.1.1, 10.0.0.5"})
        assert _client_ip(req) == "10.0.0.5"

    def test_x_real_ip_fallback(self):
        req = DummyRequest(headers={"x-real-ip": "10.0.0.8"})
        assert _client_ip(req) == "10.0.0.8"


def test_rate_limit_ban_settings_are_loaded_from_environment(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_BAN_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_BAN_THRESHOLD", "7")
    monkeypatch.setenv("RATE_LIMIT_BAN_WINDOW", "600")
    monkeypatch.setenv("RATE_LIMIT_BAN_SECONDS", "1800")

    settings = Settings(_env_file=None)

    assert settings.rate_limit_ban_enabled is False
    assert settings.rate_limit_ban_threshold == 7
    assert settings.rate_limit_ban_window == 600
    assert settings.rate_limit_ban_seconds == 1800


class TestMCPArgsValidation:
    """#3 MCP stdio command / args 校验加固。"""

    def test_stdio_rejects_path_traversal(self):
        with pytest.raises(ValueError):
            validate_stdio_command("../bin/bash")

    def test_stdio_rejects_command_not_in_path(self):
        with pytest.raises(ValueError):
            validate_stdio_command("definitely_not_a_real_binary_12345")

    def test_stdio_allows_safe_command_in_path(self):
        validate_stdio_command("python")

    def test_stdio_args_reject_shell_metacharacters(self):
        with pytest.raises(ValueError):
            validate_stdio_args(["-c", "evil; rm -rf /"])
        with pytest.raises(ValueError):
            validate_stdio_args(["|", "whoami"])
        with pytest.raises(ValueError):
            validate_stdio_args(["$(id)"])

    def test_stdio_args_reject_absolute_path(self):
        with pytest.raises(ValueError):
            validate_stdio_args(["/etc/passwd"])

    def test_stdio_args_reject_path_traversal(self):
        with pytest.raises(ValueError):
            validate_stdio_args(["../../etc/shadow"])

    def test_working_dir_allows_empty_and_absolute(self):
        # 空值与绝对路径均合法：cwd 需要绝对路径才能定位本地脚本型 MCP（如 node build/index.js）
        validate_working_dir("")
        validate_working_dir(None)
        validate_working_dir("/data/cygnusx/mcp/Ensembl-MCP-Server")

    def test_working_dir_rejects_traversal_and_metachar(self):
        with pytest.raises(ValueError):
            validate_working_dir("/data/../etc")
        with pytest.raises(ValueError):
            validate_working_dir("/data/x; rm -rf /")


class TestChatAttachmentSSRF:
    """#2 Chat 附件读取 SSRF 防护。"""

    def test_internal_ip_url_blocked(self):
        assert ChatService._is_internal_url("http://169.254.169.254/latest/meta-data/")

    def test_loopback_blocked(self):
        assert ChatService._is_internal_url("http://127.0.0.1:8080/secret")

    def test_private_ip_blocked(self):
        assert ChatService._is_internal_url("http://192.168.1.10/secret")

    def test_public_url_allowed(self):
        assert not ChatService._is_internal_url("https://example.com/file.txt")

    def test_non_http_scheme_blocked(self):
        assert ChatService._is_internal_url("file:///etc/passwd")


class TestAIToolSchemaValidation:
    """#4 AI Tool Call 参数 schema 校验。"""

    @pytest.mark.asyncio
    async def test_submit_task_rejects_missing_required_fields(self):
        executor = object.__new__(AIToolExecutor)
        result = await executor._submit_task({"parameters": {}})
        assert result["success"] is False
        assert "参数校验失败" in result["error"]

    def test_submit_task_accepts_valid_arguments(self):
        executor = object.__new__(AIToolExecutor)
        # 只校验 schema，不实际提交（无 DB）
        try:
            TaskSubmitRequest(
                flow_id="rna_seq",
                name="test task",
                parameters={"key": "value"},
                sample_sheet=[{"sample": "s1"}],
            )
        except ValidationError as exc:
            pytest.fail(f"合法参数不应校验失败: {exc}")

    @pytest.mark.asyncio
    async def test_query_status_rejects_invalid_uuid(self):
        executor = object.__new__(AIToolExecutor)
        result = await executor._query_status({"task_id": "not-a-uuid"})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_query_status_valid_uuid_passes_schema(self):
        """合法 UUID 应通过 schema 校验并进入业务层；无 DB 时抛出属性错误。"""
        executor = object.__new__(AIToolExecutor)
        with pytest.raises(AttributeError):
            await executor._query_status({"task_id": str(uuid4())})


class TestJWTTokenVersion:
    """#6 JWT token_version 吊销机制。"""

    def test_token_contains_token_version(self):
        token = create_access_token(subject="user-123", token_version=7)
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "user-123"
        assert payload["token_version"] == 7

    def test_decode_rejects_invalid_token(self):
        assert decode_token("not.a.token") is None


class TestChatUploadPathIsolation:
    """#8 聊天文件上传路径隔离。"""

    def test_resolve_attachment_path_rejects_malformed_url(self):
        assert ChatService._resolve_attachment_path("/api/v1/files/chat-upload/") is None

    def test_resolve_attachment_path_rejects_missing_user_segment(self):
        assert (
            ChatService._resolve_attachment_path("/api/v1/files/chat-upload/filename.txt")
            is None
        )


class TestSandboxNetworkIsolationConfig:
    """#7 沙盒网络隔离配置项存在。"""

    def test_sandbox_network_isolated_default_true(self):
        from cygnusx.core.config import get_settings

        assert get_settings().sandbox_network_isolated is True
