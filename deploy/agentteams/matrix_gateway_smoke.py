#!/usr/bin/env python3
"""Perform an operator-confirmed Matrix Gateway room round-trip smoke test.

The script reads the Gateway Manager credential only from the command line or an
operator-managed environment variable. It never writes credentials to disk.
Use ``--confirm-write`` to create a disposable room and post a test message.
For the optional external-leg check, send a message from Element after the
script prints the room URL; it will verify the message returns via Gateway
sync before the requested timeout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def request_json(
    base_url: str,
    manager_token: str,
    method: str,
    path: str,
    payload: dict | None = None,
) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Gateway-Identity": "bioops-manager",
            "X-Gateway-Token": manager_token,
        },
    )
    try:
        with urlopen(request, timeout=15) as response:  # noqa: S310 - operator supplies URL.
            parsed = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gateway returned HTTP {exc.code}: {detail}") from exc
    except (URLError, OSError) as exc:
        raise RuntimeError(f"Could not reach Gateway: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Gateway returned a non-object JSON response")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-url", required=True, help="Gateway base URL, for example http://127.0.0.1:8089")
    parser.add_argument(
        "--manager-token",
        default=os.environ.get("AGENTTEAMS_GATEWAY_MANAGER_TOKEN", ""),
        help="Gateway Manager token; defaults to AGENTTEAMS_GATEWAY_MANAGER_TOKEN",
    )
    parser.add_argument(
        "--identities",
        default="cygnusx-user,bioops-manager",
        help="Comma-separated Matrix identities to include in the disposable room",
    )
    parser.add_argument(
        "--wait-external-seconds",
        type=int,
        default=0,
        help="After posting the CygnusX message, wait for an Element-originated response",
    )
    parser.add_argument(
        "--confirm-write",
        action="store_true",
        help="Required: permits disposable room creation and an CygnusX test message",
    )
    args = parser.parse_args()

    if not args.manager_token:
        parser.error("--manager-token or AGENTTEAMS_GATEWAY_MANAGER_TOKEN is required")
    if not args.confirm_write:
        parser.error("Refusing to create a Matrix room without --confirm-write")
    if not 0 <= args.wait_external_seconds <= 300:
        parser.error("--wait-external-seconds must be between 0 and 300")

    try:
        health = request_json(args.gateway_url, args.manager_token, "GET", "/healthz")
        if health.get("status") != "ok":
            raise RuntimeError("Gateway health endpoint did not return status=ok")

        identities = [item.strip() for item in args.identities.split(",") if item.strip()]
        session_id = f"smoke-{uuid.uuid4().hex}"
        room = request_json(
            args.gateway_url,
            args.manager_token,
            "POST",
            "/rooms",
            {"session_id": session_id, "identities": identities},
        )
        room_id = str(room.get("room_id") or "")
        if not room_id:
            raise RuntimeError("Gateway room creation response did not include room_id")
        element_url = room.get("element_room_url")
        print(f"Created disposable room: {room_id}")
        print(f"Element room URL: {element_url or '(Gateway did not provide one)'}")

        marker = f"CygnusX Matrix smoke {session_id}"
        request_json(
            args.gateway_url,
            args.manager_token,
            "POST",
            f"/rooms/{room_id}/messages",
            {
                "sender_identity": "cygnusx-user",
                "content": marker,
                "source": "cygnusx",
                "sender": {"name": "CygnusX smoke test"},
            },
        )
        messages = request_json(
            args.gateway_url,
            args.manager_token,
            "GET",
            f"/rooms/{room_id}/messages?{urlencode({'limit': 100})}",
        )
        if not any(event.get("content") == marker for event in messages.get("events", [])):
            raise RuntimeError("CygnusX test message was not visible in the Matrix room timeline")
        print("Verified CygnusX → Matrix room message delivery.")

        if args.wait_external_seconds:
            print("Send a message from Element now; waiting for Matrix → CygnusX sync…")
            deadline = time.monotonic() + args.wait_external_seconds
            since = messages.get("next_batch")
            while time.monotonic() < deadline:
                query = urlencode({"since": since}) if since else ""
                events = request_json(
                    args.gateway_url,
                    args.manager_token,
                    "GET",
                    f"/rooms/{room_id}/messages{f'?{query}' if query else ''}",
                )
                external = [event for event in events.get("events", []) if event.get("origin") == "external"]
                if external:
                    print(f"Verified Matrix → CygnusX event return: {external[-1].get('event_id')}")
                    break
                since = events.get("next_batch") or since
                time.sleep(2)
            else:
                raise RuntimeError("Timed out waiting for an Element-originated message")

        print("Matrix Gateway smoke test passed.")
        return 0
    except RuntimeError as exc:
        print(f"Matrix Gateway smoke test failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
