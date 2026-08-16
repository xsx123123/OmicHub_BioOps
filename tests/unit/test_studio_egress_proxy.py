"""Studio 域名白名单出站代理单元测试。"""

import importlib.util
import os
import socket
import sys
from pathlib import Path

import pytest

_PROXY_PATH = Path(__file__).resolve().parents[2] / "deploy" / "studio" / "egress_proxy.py"
_spec = importlib.util.spec_from_file_location("studio_egress_proxy", _PROXY_PATH)
assert _spec is not None and _spec.loader is not None
proxy = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("studio_egress_proxy", proxy)
_spec.loader.exec_module(proxy)


@pytest.mark.unit
def test_domain_allowlist_matches_exact_and_subdomains():
    allowed = ("pypi.org", "files.pythonhosted.org")

    assert proxy.domain_allowed("pypi.org", allowed)
    assert proxy.domain_allowed("www.pypi.org", allowed)
    assert proxy.domain_allowed("files.pythonhosted.org", allowed)
    assert not proxy.domain_allowed("evilpypi.org", allowed)
    assert not proxy.domain_allowed("example.com", allowed)


@pytest.mark.unit
@pytest.mark.parametrize("value", ["127.0.0.1", "10.0.0.1", "::1", "*.pypi.org"])
def test_normalize_domain_rejects_ip_and_wildcards(value: str):
    with pytest.raises(ValueError):
        proxy.normalize_domain(value)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("127.0.0.1", False),
        ("10.1.2.3", False),
        ("169.254.169.254", False),
        ("192.0.2.1", False),
        ("1.1.1.1", True),
        ("2606:4700:4700::1111", True),
    ],
)
def test_public_ip_rejects_non_global_ranges(value: str, expected: bool):
    assert proxy.public_ip(value) is expected


@pytest.mark.unit
def test_allowlist_loader_hot_reloads_and_fails_closed(tmp_path: Path):
    path = tmp_path / "studio.yaml"
    path.write_text(
        """studio:
  sandbox:
    network:
      allow: [pypi.org, .pythonhosted.org]
""",
        encoding="utf-8",
    )
    loader = proxy.AllowlistLoader(path)
    assert loader.get() == ("pypi.org", "pythonhosted.org")

    path.write_text(
        """studio:
  sandbox:
    network:
      allow: [127.0.0.1]
""",
        encoding="utf-8",
    )
    os.utime(path, (loader._mtime + 10, loader._mtime + 10))
    assert loader.get() == ()


class _FakeLoop:
    def __init__(self, records):
        self.records = records

    async def getaddrinfo(self, host, port, type):
        assert host == "allowed.example"
        assert port == 443
        assert type == socket.SOCK_STREAM
        return self.records


@pytest.mark.unit
async def test_resolve_public_endpoint_pins_public_address(monkeypatch):
    records = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443)),
    ]
    monkeypatch.setattr(proxy.asyncio, "get_running_loop", lambda: _FakeLoop(records))

    assert await proxy.resolve_public_endpoint("allowed.example", 443) == (
        "1.1.1.1",
        socket.AF_INET,
    )


@pytest.mark.unit
async def test_resolve_public_endpoint_rejects_private_only(monkeypatch):
    records = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443)),
    ]
    monkeypatch.setattr(proxy.asyncio, "get_running_loop", lambda: _FakeLoop(records))

    with pytest.raises(PermissionError, match="公网地址"):
        await proxy.resolve_public_endpoint("allowed.example", 443)


@pytest.mark.unit
def test_proxy_parsers_restrict_protocols_and_ports():
    assert proxy._parse_authority("pypi.org:443") == ("pypi.org", 443)
    headers = []
    assert proxy._parse_http_target("http://pypi.org/simple?q=1", headers) == (
        "pypi.org",
        80,
        "/simple?q=1",
    )
    assert headers == [b"Host: pypi.org"]
    forged_headers = [b"Host: omichub-web:8000", b"X-Test: kept"]
    proxy._parse_http_target("http://pypi.org/simple", forged_headers)
    assert forged_headers == [b"X-Test: kept", b"Host: pypi.org"]
    with pytest.raises(ValueError, match="仅支持 HTTP"):
        proxy._parse_http_target("https://pypi.org/simple", [])
