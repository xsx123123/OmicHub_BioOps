"""Studio 会话 handoff：目标 Agent 沙盒镜像解析（_resolve_handoff_studio_image）。"""

from types import SimpleNamespace

import pytest

from cygnusx.application.services import chat_service
from cygnusx.infrastructure.config import runtime_image_loader


def test_resolve_handoff_studio_image_prefers_explicit_image() -> None:
    features = {
        "studio": {"image": "cygnusx-studio-plot:latest", "runtime_profile": "analysis-plot"}
    }
    assert (
        chat_service._resolve_handoff_studio_image(features) == "cygnusx-studio-plot:latest"
    )


def test_resolve_handoff_studio_image_from_runtime_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Registry:
        def select(self, caps: set, kind: str, preferred_profile: str | None = None):
            assert kind == "studio"
            assert preferred_profile == "analysis-plot"
            return "analysis-plot", SimpleNamespace(image="cygnusx-studio-plot:latest")

    monkeypatch.setattr(runtime_image_loader, "get_runtime_images", lambda: _Registry())
    features = {"studio": {"runtime_profile": "analysis-plot"}}
    assert (
        chat_service._resolve_handoff_studio_image(features) == "cygnusx-studio-plot:latest"
    )


def test_resolve_handoff_studio_image_bad_profile_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Registry:
        def select(self, caps: set, kind: str, preferred_profile: str | None = None):
            raise KeyError(preferred_profile)

    monkeypatch.setattr(runtime_image_loader, "get_runtime_images", lambda: _Registry())
    features = {"studio": {"runtime_profile": "missing-profile"}}
    assert chat_service._resolve_handoff_studio_image(features) is None


def test_resolve_handoff_studio_image_without_studio_features() -> None:
    assert chat_service._resolve_handoff_studio_image(None) is None
    assert chat_service._resolve_handoff_studio_image({}) is None
    assert chat_service._resolve_handoff_studio_image({"studio": {}}) is None
