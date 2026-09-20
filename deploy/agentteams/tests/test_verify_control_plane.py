from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "verify_control_plane.py"
SPEC = importlib.util.spec_from_file_location("verify_control_plane", MODULE_PATH)
assert SPEC and SPEC.loader
verify_control_plane = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verify_control_plane
SPEC.loader.exec_module(verify_control_plane)


def pod(*, privileged: bool = False, mount_path: str | None = None) -> dict:
    volume_mounts = [{"name": "scratch", "mountPath": mount_path}] if mount_path else []
    return {
        "metadata": {"name": "worker-0"},
        "spec": {
            "containers": [
                {
                    "name": "worker",
                    "securityContext": {
                        "privileged": privileged,
                        "allowPrivilegeEscalation": False,
                        "capabilities": {"drop": ["ALL"]},
                    },
                    "volumeMounts": volume_mounts,
                }
            ]
        },
    }


def test_network_policy_requires_namespace_default_deny() -> None:
    findings = verify_control_plane.check_network_policies(
        {"items": [{"spec": {"podSelector": {}, "policyTypes": ["Ingress"]}}]}
    )
    assert any("default-deny" in finding.message for finding in findings)


def test_pod_rejects_privileged_and_omic_mount() -> None:
    findings = verify_control_plane.check_pods(
        {"items": [pod(privileged=True, mount_path="/data/cygnusx")]}
    )
    messages = [finding.message for finding in findings]
    assert any("privileged" in message for message in messages)
    assert any("forbidden mount" in message for message in messages)


def test_hardened_pod_passes() -> None:
    assert verify_control_plane.check_pods({"items": [pod()]}) == []
