"""安全修复单元测试 — 覆盖 SECURITY_AUDIT.md 中部分关键修复。"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from cygnusx.application.schemas.download import DownloadRequest
from cygnusx.application.services.file_service import FileService
from cygnusx.application.services.terminal_service import _generate_session_id
from cygnusx.core.exceptions import AuthorizationError
from cygnusx.infrastructure.config.storage_config import StorageConfig
from cygnusx.infrastructure.mcp.client import (
    validate_sse_url,
    validate_stdio_command,
)
from cygnusx.infrastructure.storage.path_factory import StoragePathFactory


class TestFileServiceResolveAbs:
    """#1 路径穿越防护"""

    @pytest.fixture
    def service(self, tmp_path: Path) -> FileService:
        """构造一个使用临时 storage_root 的 FileService。"""
        # FileService 需要 AsyncSession，但 _resolve_abs 不依赖 DB
        svc = object.__new__(FileService)
        svc._storage_root = tmp_path
        svc._factory = StoragePathFactory(
            StorageConfig(data_root=str(tmp_path), users_subdir="users")
        )
        return svc

    def test_resolve_abs_normal_relative_path(self, service: FileService, tmp_path: Path):
        rel = "users/123/raw/test.txt"
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("ok")
        resolved = service._resolve_abs(rel)
        assert resolved == tmp_path / rel

    def test_resolve_abs_rejects_traversal(self, service: FileService, tmp_path: Path):
        with pytest.raises(AuthorizationError):
            service._resolve_abs("../etc/passwd")

    def test_resolve_abs_rejects_absolute_path(self, service: FileService):
        with pytest.raises(AuthorizationError):
            service._resolve_abs("/etc/passwd")


class TestCloudStorageUriValidation:
    """#9 云存储 URI host 校验"""

    def test_bare_bucket_allowed(self):
        req = DownloadRequest(
            source="cloud_storage",
            cloud_provider="aliyun",
            object_uri="oss://bucket/raw/",
        )
        assert req.object_uri == "oss://bucket/raw/"

    def test_official_endpoint_allowed(self):
        req = DownloadRequest(
            source="cloud_storage",
            cloud_provider="aliyun",
            object_uri="oss://bucket.oss-cn-hangzhou.aliyuncs.com/raw/",
        )
        assert req.object_uri == "oss://bucket.oss-cn-hangzhou.aliyuncs.com/raw/"

    def test_ip_address_rejected(self):
        with pytest.raises(ValidationError):
            DownloadRequest(
                source="cloud_storage",
                cloud_provider="aliyun",
                object_uri="oss://169.254.169.254/secret",
            )

    def test_evil_external_host_rejected(self):
        with pytest.raises(ValidationError):
            DownloadRequest(
                source="cloud_storage",
                cloud_provider="aliyun",
                object_uri="oss://evil.com/secret",
            )


class TestMCPValidation:
    """#6 MCP stdio/SSE 校验"""

    def test_stdio_rejects_absolute_path(self):
        with pytest.raises(ValueError):
            validate_stdio_command("/bin/bash")

    def test_stdio_rejects_shell(self):
        with pytest.raises(ValueError):
            validate_stdio_command("bash")

    def test_stdio_allows_safe_command(self):
        validate_stdio_command("python")
        validate_stdio_command("npx")

    def test_sse_rejects_internal_ip(self):
        with pytest.raises(ValueError):
            validate_sse_url("http://169.254.169.254/meta")

    def test_sse_rejects_loopback(self):
        with pytest.raises(ValueError):
            validate_sse_url("http://127.0.0.1:8080/sse")

    def test_sse_allows_public_https(self):
        validate_sse_url("https://example.com/sse")

    def test_sse_rejects_non_http_scheme(self):
        with pytest.raises(ValueError):
            validate_sse_url("file:///etc/passwd")


class TestTerminalSessionId:
    """#12 终端会话 ID 熵"""

    def test_session_id_prefix_and_length(self):
        sid = _generate_session_id()
        assert sid.startswith("term_")
        # token_urlsafe(16) => 22 chars + prefix
        assert len(sid) > 20

    def test_session_id_unique(self):
        sids = {_generate_session_id() for _ in range(100)}
        assert len(sids) == 100
