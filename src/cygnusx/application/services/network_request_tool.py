"""经用户确认的受限 HTTP 访问工具。

该工具用于 GEO、NCBI、EBI 等公共网页/API 的元数据核验。它不复用分析沙箱的
网络命名空间，也不接收任意请求头、Cookie 或认证信息，避免把网络访问变成隐式
凭据转发。每次调用默认经过聊天审批卡片；只允许 GET/HEAD、公共 HTTP(S) 地址、
有限响应体和有限重定向。
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from cygnusx.application.services.studio_approval_service import NETWORK_REQUEST_TOOL_NAME

MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 30_000
MAX_REDIRECTS = 3

NETWORK_REQUEST_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": NETWORK_REQUEST_TOOL_NAME,
        "description": (
            "在用户批准后访问一个公共 HTTP(S) URL，用于核验 GEO/NCBI/EBI 等网页或 API 的元数据。"
            "只支持 GET/HEAD；不携带 Cookie、Authorization 或用户自定义请求头；禁止本机、内网、"
            "云元数据地址和 file://。响应最多读取 5 MB，文本最多回传 30000 字符；大文件只返回"
            "状态、类型、长度和最终 URL，不会自动把二进制文件塞进上下文。调用前必须在审批卡片中确认 URL。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "完整的 http:// 或 https:// URL"},
                "method": {"type": "string", "enum": ["GET", "HEAD"], "default": "GET"},
                "timeout": {"type": "integer", "minimum": 1, "maximum": 60, "default": 20},
                "max_bytes": {
                    "type": "integer",
                    "minimum": 1024,
                    "maximum": MAX_RESPONSE_BYTES,
                    "default": MAX_RESPONSE_BYTES,
                    "description": "最多读取的响应字节数，默认 5 MB",
                },
            },
            "required": ["url"],
        },
    },
}


def _public_url(url: str) -> tuple[str, str | None]:
    """校验 URL 并返回规范化 URL/错误信息。"""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return "", "URL 格式无效"
    if parsed.scheme not in {"http", "https"}:
        return "", "只允许 http:// 或 https:// URL"
    if parsed.username or parsed.password:
        return "", "URL 不允许携带用户名或密码"
    host = (parsed.hostname or "").rstrip(".").lower()
    if not host:
        return "", "URL 缺少主机名"
    if host in {"localhost", "ip6-localhost", "metadata.google.internal"} or host.endswith(
        (".localhost", ".local", ".internal")
    ):
        return "", "禁止访问本机或内部域名"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        return "", "禁止访问内网、环回、链路本地或保留地址"
    # 域名的 DNS 结果在真正请求前再次检查，防止解析到内网地址。
    return url.strip(), None


def _risk_host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "未知主机").lower()
    except ValueError:
        return "未知主机"


def _resolve_public_hostname(host: str) -> str | None:
    """Reject hostnames that resolve to non-public addresses (SSRF protection)."""
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return "域名无法解析"
    except OSError:
        return "域名解析失败"
    for item in addresses:
        try:
            address = ipaddress.ip_address(item[4][0])
        except (ValueError, IndexError):
            return "域名解析结果无效"
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            return "域名解析到内网、环回、链路本地或保留地址"
    return None


async def _validate_public_host(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        try:
            return await asyncio.wait_for(asyncio.to_thread(_resolve_public_hostname, host), timeout=3)
        except asyncio.TimeoutError:
            return "域名解析超时"
    return None


def network_request_risk_hint(args: dict[str, Any]) -> str:
    """供审批卡片展示的网络访问摘要。"""
    url = str(args.get("url") or "")
    method = str(args.get("method") or "GET").upper()
    return f"将通过受限出口发起 {method} 请求：{_risk_host(url)}；不携带用户凭据"


async def execute_network_request(args: dict[str, Any]) -> dict[str, Any]:
    """执行一次受限 HTTP 请求，返回适合 LLM 和 UI 的双通道信封。"""
    url, error = _public_url(str(args.get("url") or ""))
    if error:
        payload = {"error": error}
        return {"success": False, "result": {"llm_payload": payload, "ui_payload": payload}}
    error = await _validate_public_host(url)
    if error:
        payload = {"error": error, "url": url}
        return {"success": False, "result": {"llm_payload": payload, "ui_payload": payload}}
    method = str(args.get("method") or "GET").upper()
    if method not in {"GET", "HEAD"}:
        payload = {"error": "只支持 GET 或 HEAD 请求"}
        return {"success": False, "result": {"llm_payload": payload, "ui_payload": payload}}
    try:
        timeout = max(1, min(int(args.get("timeout") or 20), 60))
    except (TypeError, ValueError):
        timeout = 20
    try:
        max_bytes = max(1024, min(int(args.get("max_bytes") or MAX_RESPONSE_BYTES), MAX_RESPONSE_BYTES))
    except (TypeError, ValueError):
        max_bytes = MAX_RESPONSE_BYTES

    current_url = url
    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": "CygnusX-network-request/1.0", "Accept": "*/*"},
        ) as client:
            redirects = 0
            status_code = 0
            response_headers = httpx.Headers()
            body = b""
            while True:
                async with client.stream(method, current_url) as response:
                    status_code = response.status_code
                    response_headers = response.headers
                    if status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location or redirects >= MAX_REDIRECTS:
                            break
                        next_url, redirect_error = _public_url(urljoin(current_url, location))
                        if redirect_error:
                            return {
                                "success": False,
                                "result": {
                                    "llm_payload": {"error": f"重定向被拦截：{redirect_error}"},
                                    "ui_payload": {"error": f"重定向被拦截：{redirect_error}"},
                                },
                            }
                        redirect_error = await _validate_public_host(next_url)
                        if redirect_error:
                            return {
                                "success": False,
                                "result": {
                                    "llm_payload": {"error": f"重定向被拦截：{redirect_error}"},
                                    "ui_payload": {"error": f"重定向被拦截：{redirect_error}"},
                                },
                            }
                        current_url = next_url
                        redirects += 1
                        continue
                    if method != "HEAD":
                        chunks: list[bytes] = []
                        bytes_read = 0
                        async for chunk in response.aiter_bytes():
                            take = chunk[: max_bytes + 1 - bytes_read]
                            chunks.append(take)
                            bytes_read += len(take)
                            if bytes_read >= max_bytes + 1:
                                break
                        body = b"".join(chunks)
                    break
    except (httpx.HTTPError, OSError, socket.gaierror) as exc:
        payload = {"error": f"网络请求失败：{str(exc)[:500]}", "url": current_url}
        return {"success": False, "result": {"llm_payload": payload, "ui_payload": payload}}

    truncated = len(body) > max_bytes
    body = body[:max_bytes]
    content_type = response_headers.get("content-type", "").lower()
    is_text = (
        content_type.startswith("text/")
        or "json" in content_type
        or "xml" in content_type
        or "javascript" in content_type
    )
    payload: dict[str, Any] = {
        "url": url,
        "final_url": current_url,
        "host": _risk_host(current_url),
        "method": method,
        "status_code": status_code,
        "content_type": content_type,
        "content_length": response_headers.get("content-length"),
        "bytes_read": len(body),
        "truncated": truncated,
        "redirects": redirects,
        "downloadable": not is_text and len(body) > 0,
    }
    if is_text and body:
        text = body.decode("utf-8", errors="replace")
        payload["text"] = text[:MAX_TEXT_CHARS]
        payload["text_truncated"] = len(text) > MAX_TEXT_CHARS
    note = "文本内容已回传" if is_text else "非文本响应仅返回元数据，未将二进制内容回传给模型"
    payload["note"] = note
    return {"success": 200 <= status_code < 300, "result": {"llm_payload": payload, "ui_payload": dict(payload)}}
