"""OmicStudio 沙盒出站 HTTP CONNECT 代理。

仅允许 data/ai/studio.yaml 中 studio.sandbox.network.allow 声明的域名；
拒绝 IP 字面量、私网/回环/保留地址，并将 DNS 解析结果固定为已校验公网 IP，
避免沙盒通过代理访问平台内网或利用 DNS rebinding 绕过白名单。
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import os
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

_CONFIG_PATH = Path(os.environ.get("STUDIO_CONFIG_PATH", "/config/studio.yaml"))
_LISTEN_HOST = os.environ.get("STUDIO_PROXY_HOST", "0.0.0.0")
_LISTEN_PORT = int(os.environ.get("STUDIO_PROXY_PORT", "3128"))
_CONNECT_TIMEOUT = float(os.environ.get("STUDIO_PROXY_CONNECT_TIMEOUT", "10"))
_MAX_HEADER_BYTES = 64 * 1024
_MAX_CONNECTIONS = int(os.environ.get("STUDIO_PROXY_MAX_CONNECTIONS", "128"))
_ALLOWED_HTTP_PORTS = {80}
_ALLOWED_CONNECT_PORTS = {443}

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("studio-egress-proxy")


def normalize_domain(value: str) -> str:
    """规范化 YAML/请求域名，拒绝通配符与 IP 字面量。"""
    domain = value.strip().lower().rstrip(".")
    if domain.startswith("."):
        domain = domain[1:]
    if not domain or "*" in domain or "/" in domain or ":" in domain:
        raise ValueError(f"非法域名: {value}")
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        pass
    else:
        raise ValueError("白名单不允许 IP 字面量")
    return domain.encode("idna").decode("ascii")


def domain_allowed(host: str, allowed: tuple[str, ...]) -> bool:
    """精确域名或其子域匹配；`pypi.org` 同时允许 `files.pythonhosted.org` 需单列。"""
    try:
        normalized = normalize_domain(host)
    except ValueError:
        return False
    return any(normalized == item or normalized.endswith(f".{item}") for item in allowed)


def public_ip(value: str) -> bool:
    """只允许全局可路由单播地址。

    例外：198.18.0.0/15（RFC 2544 基准测试段）——本机翻墙客户端（Clash/Surge 等）
    的 fake-ip DNS 会把域名解析到该段，由宿主机的 TUN 拦截后代理出站。
    该段不具备内网 SSRF 价值（不会被路由到平台内网），故与公网地址同等放行。
    """
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if ip.is_global:
        return True
    return ip in _FAKE_IP_RANGE


# 本机代理客户端 fake-ip 常用段（198.18.0.0/15）
_FAKE_IP_RANGE = ipaddress.ip_network("198.18.0.0/15")


class AllowlistLoader:
    """按 mtime 热读取 Studio YAML 白名单。"""

    def __init__(self, path: Path = _CONFIG_PATH) -> None:
        self.path = path
        self._mtime = -1.0
        self._domains: tuple[str, ...] = ()

    def get(self) -> tuple[str, ...]:
        try:
            mtime = self.path.stat().st_mtime
        except OSError as exc:
            logger.error("无法读取白名单配置: %s", exc)
            return ()
        if mtime == self._mtime:
            return self._domains
        try:
            raw: Any = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
            values = raw.get("studio", {}).get("sandbox", {}).get("network", {}).get("allow", [])
            if not isinstance(values, list):
                raise ValueError("studio.sandbox.network.allow 必须为数组")
            domains = tuple(dict.fromkeys(normalize_domain(str(item)) for item in values))
        except Exception as exc:  # noqa: BLE001 - 配置异常必须失败关闭
            logger.error("白名单配置非法，代理失败关闭: %s", exc)
            domains = ()
        self._mtime = mtime
        self._domains = domains
        logger.info("Studio 出站白名单已加载: %s", ", ".join(domains) or "<empty>")
        return domains


async def resolve_public_endpoint(host: str, port: int) -> tuple[str, int]:
    """解析并固定到公网 IP；任一私网结果均不采用。"""
    loop = asyncio.get_running_loop()
    records = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    candidates: list[tuple[str, int]] = []
    for family, _, _, _, sockaddr in records:
        address = str(sockaddr[0])
        if public_ip(address):
            candidates.append((address, family))
    if not candidates:
        raise PermissionError("域名未解析到公网地址")
    return candidates[0]


async def _open_public(host: str, port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    address, family = await resolve_public_endpoint(host, port)
    return await asyncio.wait_for(
        asyncio.open_connection(address, port, family=family),
        timeout=_CONNECT_TIMEOUT,
    )


def _parse_authority(value: str) -> tuple[str, int]:
    parsed = urlsplit(f"//{value}")
    if not parsed.hostname or parsed.port is None:
        raise ValueError("CONNECT 目标必须为 host:port")
    return parsed.hostname, parsed.port


def _parse_http_target(target: str, headers: list[bytes]) -> tuple[str, int, str]:
    parsed = urlsplit(target)
    if parsed.scheme.lower() != "http" or not parsed.hostname:
        raise ValueError("仅支持 HTTP absolute-form 或 HTTPS CONNECT")
    port = parsed.port or 80
    path = parsed.path or "/"
    if parsed.query:
        path += f"?{parsed.query}"
    if parsed.username or parsed.password:
        raise ValueError("代理 URL 不允许凭据")
    headers[:] = [line for line in headers if not line.lower().startswith(b"host:")]
    headers.append(f"Host: {parsed.netloc}".encode())
    return parsed.hostname, port, path


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(64 * 1024):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        with contextlib.suppress(Exception):
            writer.close()
            await writer.wait_closed()


async def _tunnel(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    upstream_reader: asyncio.StreamReader,
    upstream_writer: asyncio.StreamWriter,
) -> None:
    await asyncio.gather(
        _pipe(client_reader, upstream_writer),
        _pipe(upstream_reader, client_writer),
    )


def _error_response(status: int, message: str) -> bytes:
    body = f"{message}\n".encode()
    reason = {400: "Bad Request", 403: "Forbidden", 502: "Bad Gateway"}.get(status, "Error")
    return (
        f"HTTP/1.1 {status} {reason}\r\nContent-Type: text/plain\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
    ).encode() + body


class StudioEgressProxy:
    def __init__(self, loader: AllowlistLoader | None = None) -> None:
        self.loader = loader or AllowlistLoader()
        self._semaphore = asyncio.Semaphore(_MAX_CONNECTIONS)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async with self._semaphore:
            try:
                await self._handle(reader, writer)
            except ValueError as exc:
                writer.write(_error_response(400, str(exc)))
                await writer.drain()
            except PermissionError as exc:
                writer.write(_error_response(403, str(exc)))
                await writer.drain()
            except Exception as exc:  # noqa: BLE001
                logger.warning("代理连接失败: %s", exc)
                with contextlib.suppress(Exception):
                    writer.write(_error_response(502, "上游连接失败"))
                    await writer.drain()
            finally:
                with contextlib.suppress(Exception):
                    writer.close()
                    await writer.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        raw_headers = await reader.readuntil(b"\r\n\r\n")
        if len(raw_headers) > _MAX_HEADER_BYTES:
            raise ValueError("请求头过大")
        lines = raw_headers[:-4].split(b"\r\n")
        if not lines:
            raise ValueError("空请求")
        try:
            method_b, target_b, version_b = lines[0].split(b" ", 2)
        except ValueError as exc:
            raise ValueError("非法请求行") from exc
        method = method_b.decode("ascii", errors="strict").upper()
        target = target_b.decode("ascii", errors="strict")
        version = version_b.decode("ascii", errors="strict")
        headers = [
            line
            for line in lines[1:]
            if not line.lower().startswith((b"proxy-authorization:", b"proxy-connection:"))
        ]

        if method == "CONNECT":
            host, port = _parse_authority(target)
            if port not in _ALLOWED_CONNECT_PORTS:
                raise PermissionError("CONNECT 端口未放行")
            request_bytes = None
        else:
            host, port, path = _parse_http_target(target, headers)
            if port not in _ALLOWED_HTTP_PORTS:
                raise PermissionError("HTTP 端口未放行")
            request_bytes = b" ".join((method_b, path.encode(), version.encode())) + b"\r\n"
            request_bytes += b"\r\n".join(headers) + b"\r\n\r\n"

        allowed = self.loader.get()
        if not allowed or not domain_allowed(host, allowed):
            raise PermissionError(f"域名未在 Studio 白名单中: {host}")
        upstream_reader, upstream_writer = await _open_public(host, port)
        if method == "CONNECT":
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
        else:
            assert request_bytes is not None
            upstream_writer.write(request_bytes)
            await upstream_writer.drain()
        await _tunnel(reader, writer, upstream_reader, upstream_writer)


async def main() -> None:
    proxy = StudioEgressProxy()
    server = await asyncio.start_server(proxy.handle, _LISTEN_HOST, _LISTEN_PORT)
    addresses = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    logger.info("Studio egress proxy listening on %s", addresses)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
