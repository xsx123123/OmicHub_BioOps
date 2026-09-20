#!/usr/bin/env python3
"""Validate an AgentTeams Bridge deployment before starting a real demonstration.

The script is deliberately controller-agnostic: it validates only the Bridge configuration and,
when requested, performs a read-only `/healthz` probe. It never starts containers, submits tasks,
or reads CygnusX data directories.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REQUIRED_IDENTITIES = {
    "approval-authority",
    "bioops-manager",
    "data-steward",
    "workflow-operator",
    "quality-auditor",
    "delivery-reporter",
}


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        values[key.strip()] = value.strip()
    return values


def is_placeholder(value: str | None) -> bool:
    normalized = (value or "").strip().lower()
    return not normalized or normalized.startswith("replace-") or normalized.startswith("change-me")


def validate_bridge_env(values: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for key in (
        "BRIDGE_CYGNUSX_BASE_URL",
        "BRIDGE_GATEWAY_URL",
        "BRIDGE_GATEWAY_MANAGER_TOKEN",
        "BRIDGE_STATE_STORE_URL",
        "BRIDGE_APPROVAL_SIGNING_SECRET",
        "BRIDGE_IDENTITIES",
        "BRIDGE_ALLOWED_FLOW_IDS",
    ):
        if is_placeholder(values.get(key)):
            errors.append(f"{key} is missing or still a template placeholder")
    upstream_credentials = [
        key
        for key in ("BRIDGE_CYGNUSX_SERVICE_TOKEN", "BRIDGE_CYGNUSX_API_KEY")
        if not is_placeholder(values.get(key))
    ]
    if not upstream_credentials:
        errors.append(
            "configure exactly one of BRIDGE_CYGNUSX_SERVICE_TOKEN or BRIDGE_CYGNUSX_API_KEY"
        )
    elif len(upstream_credentials) > 1:
        errors.append(
            "configure only one of BRIDGE_CYGNUSX_SERVICE_TOKEN or BRIDGE_CYGNUSX_API_KEY"
        )
    identities: dict[str, str] = {}
    for entry in values.get("BRIDGE_IDENTITIES", "").split(","):
        if ":" not in entry:
            continue
        name, token = entry.split(":", maxsplit=1)
        identities[name.strip()] = token.strip()
    missing = sorted(REQUIRED_IDENTITIES.difference(identities))
    if missing:
        errors.append(f"BRIDGE_IDENTITIES is missing roles: {', '.join(missing)}")
    placeholders = sorted(name for name, token in identities.items() if is_placeholder(token))
    if placeholders:
        errors.append(f"BRIDGE_IDENTITIES has placeholder tokens for: {', '.join(placeholders)}")
    return errors


def validate_cygnusx_env(values: dict[str, str]) -> list[str]:
    errors: list[str] = []
    if values.get("AGENTTEAMS_BRIDGE_ENABLED", "false").lower() != "true":
        errors.append("AGENTTEAMS_BRIDGE_ENABLED must be true before the CygnusX proxy is enabled")
    for key in (
        "AGENTTEAMS_BRIDGE_URL",
        "AGENTTEAMS_BRIDGE_MANAGER_TOKEN",
        "AGENTTEAMS_BRIDGE_DATA_STEWARD_TOKEN",
        "AGENTTEAMS_BRIDGE_APPROVAL_TOKEN",
        "AGENTTEAMS_BRIDGE_WORKFLOW_OPERATOR_TOKEN",
        "AGENTTEAMS_INTEGRATION_TOKEN",
    ):
        if is_placeholder(values.get(key)):
            errors.append(f"{key} is missing or still a template placeholder")
    return errors


def validate_gateway_env(values: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for key in (
        "GATEWAY_IDENTITIES",
        "GATEWAY_MATRIX_HOMESERVER_URL",
        "GATEWAY_MATRIX_SERVICE_TOKEN",
        "GATEWAY_MATRIX_IDENTITIES",
        "GATEWAY_ELEMENT_BASE_URL",
        "GATEWAY_CYGNUSX_INTEGRATION_TOKEN",
    ):
        if is_placeholder(values.get(key)):
            errors.append(f"{key} is missing or still a template placeholder")
    if "bioops-manager:" not in values.get("GATEWAY_IDENTITIES", ""):
        errors.append("GATEWAY_IDENTITIES is missing bioops-manager")
    matrix_identities = values.get("GATEWAY_MATRIX_IDENTITIES", "")
    for identity in ("bioops-manager", "cygnusx-user"):
        if f"{identity}=" not in matrix_identities:
            errors.append(f"GATEWAY_MATRIX_IDENTITIES is missing {identity}")
    return errors


def check_healthz(
    base_url: str, label: str, retries: int = 1, retry_delay_seconds: float = 1.0
) -> str:
    request = Request(f"{base_url.rstrip('/')}/healthz", headers={"Accept": "application/json"})
    last_error: RuntimeError | None = None
    for attempt in range(retries):
        try:
            with urlopen(request, timeout=10) as response:  # noqa: S310 - operator supplies the endpoint.
                payload = response.read().decode(errors="replace")
            if '"status":"ok"' not in payload.replace(" ", ""):
                raise RuntimeError(
                    f"{label} health probe did not return the expected status=ok response"
                )
            return f"{label} health probe succeeded: {base_url.rstrip('/')}/healthz"
        except HTTPError as exc:
            last_error = RuntimeError(f"{label} health probe returned HTTP {exc.code}")
        except (URLError, ConnectionError, OSError) as exc:
            last_error = RuntimeError(f"{label} health probe could not connect: {exc}")
        if attempt + 1 < retries:
            time.sleep(retry_delay_seconds)
    assert last_error is not None
    raise last_error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge-env", type=Path, required=True, help="Deployed Bridge env file")
    parser.add_argument("--cygnusx-env", type=Path, help="Deployed CygnusX env file")
    parser.add_argument("--gateway-env", type=Path, help="Deployed Matrix Gateway env file")
    parser.add_argument("--bridge-url", help="Bridge URL used only with --check-health")
    parser.add_argument("--gateway-url", help="Gateway URL used only with --check-health")
    parser.add_argument(
        "--health-retries",
        type=int,
        default=5,
        help="Number of read-only health probe attempts after startup (default: 5)",
    )
    parser.add_argument(
        "--check-health", action="store_true", help="Read-only GET /healthz after config checks"
    )
    args = parser.parse_args()

    errors: list[str] = []
    if not args.bridge_env.is_file():
        errors.append(f"Bridge env file does not exist: {args.bridge_env}")
    else:
        errors.extend(validate_bridge_env(parse_env_file(args.bridge_env)))
    if args.cygnusx_env:
        if not args.cygnusx_env.is_file():
            errors.append(f"CygnusX env file does not exist: {args.cygnusx_env}")
        else:
            errors.extend(validate_cygnusx_env(parse_env_file(args.cygnusx_env)))
    if args.gateway_env:
        if not args.gateway_env.is_file():
            errors.append(f"Gateway env file does not exist: {args.gateway_env}")
        else:
            errors.extend(validate_gateway_env(parse_env_file(args.gateway_env)))
    if args.check_health and not (args.bridge_url or args.gateway_url):
        errors.append("--check-health requires --bridge-url and/or --gateway-url")
    if args.health_retries < 1:
        errors.append("--health-retries must be at least 1")
    if errors:
        print("AgentTeams deployment preflight failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("AgentTeams configuration preflight passed.")
    if args.check_health:
        try:
            if args.bridge_url:
                print(check_healthz(args.bridge_url, "Bridge", retries=args.health_retries))
            if args.gateway_url:
                print(check_healthz(args.gateway_url, "Matrix Gateway", retries=args.health_retries))
        except RuntimeError as exc:
            print(f"AgentTeams deployment preflight failed: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
