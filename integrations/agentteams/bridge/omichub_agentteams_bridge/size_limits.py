"""ASGI request/response size limits for the public Bridge boundary."""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodySizeLimitError(Exception):
    """Raised before an oversized request can reach a Bridge route."""


class BodySizeLimitMiddleware:
    """Buffer bounded JSON responses and reject oversized request bodies."""

    def __init__(self, app: ASGIApp, max_request_bytes: int, max_response_bytes: int) -> None:
        self.app = app
        self.max_request_bytes = max_request_bytes
        self.max_response_bytes = max_response_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        content_length = _content_length(scope)
        if content_length is not None and content_length > self.max_request_bytes:
            await _send_json_error(send, 413, "Request body exceeds Bridge limit")
            return

        request_size = 0

        async def limited_receive() -> Message:
            nonlocal request_size
            message = await receive()
            if message["type"] == "http.request":
                request_size += len(message.get("body", b""))
                if request_size > self.max_request_bytes:
                    raise BodySizeLimitError
            return message

        response_messages: list[Message] = []
        response_size = 0

        async def bounded_send(message: Message) -> None:
            nonlocal response_size
            if message["type"] == "http.response.body":
                response_size += len(message.get("body", b""))
                if response_size > self.max_response_bytes:
                    raise BodySizeLimitError
            response_messages.append(message)

        try:
            await self.app(scope, limited_receive, bounded_send)
        except BodySizeLimitError:
            await _send_json_error(
                send,
                413 if request_size > self.max_request_bytes else 502,
                "Request body exceeds Bridge limit"
                if request_size > self.max_request_bytes
                else "Bridge response exceeds configured limit",
            )
            return
        for message in response_messages:
            await send(message)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name.lower() != b"content-length":
            continue
        try:
            return int(value)
        except ValueError:
            return None
    return None


async def _send_json_error(send: Send, status_code: int, detail: str) -> None:
    body = json.dumps({"detail": detail}, separators=(",", ":")).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
