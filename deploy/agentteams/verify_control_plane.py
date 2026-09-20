#!/usr/bin/env python3
"""Read-only acceptance checks for a separately deployed AgentTeams control plane.

This verifier intentionally consumes only the Kubernetes API exposed by ``kubectl``. It does
not assume a particular AgentTeams / HiClaw CRD schema, create resources, or read CygnusX data.
It verifies the deployment invariants that are stable across controller releases: an independent
namespace, isolated network policy, non-privileged Pods, and no forbidden host or CygnusX mounts.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

FORBIDDEN_HOST_PATHS = ("/var/run/docker.sock", "/data/cygnusx", "/var/lib/omic")
FORBIDDEN_MOUNT_TOKENS = ("docker.sock", "cygnusx", "postgres", "redis", "workflow")


@dataclass(frozen=True)
class Finding:
    check: str
    message: str


def kubectl_json(kubectl: str, namespace: str, *arguments: str) -> dict[str, Any]:
    completed = subprocess.run(
        [kubectl, "-n", namespace, *arguments, "-o", "json"],
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown kubectl error"
        raise RuntimeError(f"kubectl {' '.join(arguments)} failed: {detail}")
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError(f"kubectl {' '.join(arguments)} returned a non-object response")
    return payload


def _containers(pod: dict[str, Any]) -> list[dict[str, Any]]:
    spec = pod.get("spec", {})
    if not isinstance(spec, dict):
        return []
    values: list[dict[str, Any]] = []
    for key in ("containers", "initContainers", "ephemeralContainers"):
        items = spec.get(key, [])
        if isinstance(items, list):
            values.extend(item for item in items if isinstance(item, dict))
    return values


def check_namespace(namespace: dict[str, Any], expected: str) -> list[Finding]:
    name = namespace.get("metadata", {}).get("name")
    if name != expected:
        return [Finding("namespace", f"expected namespace {expected!r}, got {name!r}")]
    return []


def check_network_policies(policies: dict[str, Any]) -> list[Finding]:
    items = policies.get("items", [])
    if not isinstance(items, list) or not items:
        return [Finding("network-policy", "no NetworkPolicy exists in the control-plane namespace")]
    has_default_deny = False
    has_ingress = False
    has_egress = False
    for policy in items:
        if not isinstance(policy, dict):
            continue
        spec = policy.get("spec", {})
        types = set(spec.get("policyTypes", [])) if isinstance(spec, dict) else set()
        selector = spec.get("podSelector", {}) if isinstance(spec, dict) else {}
        if selector == {} and {"Ingress", "Egress"}.issubset(types):
            has_default_deny = True
        has_ingress = has_ingress or "Ingress" in types
        has_egress = has_egress or "Egress" in types
    findings: list[Finding] = []
    if not has_default_deny:
        findings.append(
            Finding("network-policy", "missing namespace-wide default-deny ingress/egress policy")
        )
    if not has_ingress or not has_egress:
        findings.append(
            Finding("network-policy", "policies must explicitly govern both ingress and egress")
        )
    return findings


def check_pods(pods: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    items = pods.get("items", [])
    if not isinstance(items, list) or not items:
        return [Finding("pods", "no control-plane Pods were found")]
    for pod in items:
        if not isinstance(pod, dict):
            continue
        metadata = pod.get("metadata", {})
        spec = pod.get("spec", {})
        pod_name = metadata.get("name", "<unknown>") if isinstance(metadata, dict) else "<unknown>"
        if not isinstance(spec, dict):
            findings.append(Finding("pod-security", f"{pod_name}: missing Pod spec"))
            continue
        if spec.get("hostNetwork") or spec.get("hostPID") or spec.get("hostIPC"):
            findings.append(
                Finding("pod-security", f"{pod_name}: host namespace sharing is forbidden")
            )
        for volume in spec.get("volumes", []):
            if not isinstance(volume, dict):
                continue
            host_path = volume.get("hostPath")
            if isinstance(host_path, dict):
                path = str(host_path.get("path", ""))
                if path.startswith(FORBIDDEN_HOST_PATHS) or any(
                    token in path.lower() for token in FORBIDDEN_MOUNT_TOKENS
                ):
                    findings.append(
                        Finding(
                            "volume-isolation", f"{pod_name}: forbidden hostPath mount {path!r}"
                        )
                    )
        for container in _containers(pod):
            container_name = container.get("name", "<unknown>")
            security = container.get("securityContext", {})
            security = security if isinstance(security, dict) else {}
            if security.get("privileged") is True:
                findings.append(
                    Finding(
                        "pod-security",
                        f"{pod_name}/{container_name}: privileged containers are forbidden",
                    )
                )
            if security.get("allowPrivilegeEscalation") is not False:
                findings.append(
                    Finding(
                        "pod-security",
                        f"{pod_name}/{container_name}: allowPrivilegeEscalation must be false",
                    )
                )
            capabilities = security.get("capabilities", {})
            if isinstance(capabilities, dict) and "ALL" not in capabilities.get("drop", []):
                findings.append(
                    Finding(
                        "pod-security", f"{pod_name}/{container_name}: must drop ALL capabilities"
                    )
                )
            for mount in container.get("volumeMounts", []):
                if not isinstance(mount, dict):
                    continue
                mount_path = str(mount.get("mountPath", ""))
                normalized = str(PurePosixPath(mount_path))
                if normalized.startswith(FORBIDDEN_HOST_PATHS) or any(
                    token in normalized.lower() for token in FORBIDDEN_MOUNT_TOKENS
                ):
                    findings.append(
                        Finding(
                            "volume-isolation",
                            f"{pod_name}/{container_name}: forbidden mount {mount_path!r}",
                        )
                    )
    return findings


def verify(kubectl: str, namespace_name: str) -> list[Finding]:
    namespace = kubectl_json(kubectl, namespace_name, "get", "namespace", namespace_name)
    policies = kubectl_json(kubectl, namespace_name, "get", "networkpolicy")
    pods = kubectl_json(kubectl, namespace_name, "get", "pods")
    return [
        *check_namespace(namespace, namespace_name),
        *check_network_policies(policies),
        *check_pods(pods),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify AgentTeams control-plane isolation")
    parser.add_argument("--namespace", default="agentteams-system")
    parser.add_argument("--kubectl", default="kubectl")
    args = parser.parse_args()

    kubectl_path = shutil.which(args.kubectl)
    if kubectl_path is None:
        print(
            f"AgentTeams control-plane verification failed: {args.kubectl!r} is not installed",
            file=sys.stderr,
        )
        return 2
    try:
        findings = verify(kubectl_path, args.namespace)
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(f"AgentTeams control-plane verification failed: {exc}", file=sys.stderr)
        return 2
    if findings:
        print("AgentTeams control-plane verification failed:", file=sys.stderr)
        for finding in findings:
            print(f"- [{finding.check}] {finding.message}", file=sys.stderr)
        return 1
    print(f"AgentTeams control-plane verification passed for namespace {args.namespace!r}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
