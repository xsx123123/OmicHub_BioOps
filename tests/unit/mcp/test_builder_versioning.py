"""MCP Builder 版本管理工具测试。"""

from __future__ import annotations

import pytest

from cygnusx.infrastructure.mcp.builder.versioning import (
    compare_versions,
    determine_version,
    is_valid_semver,
    parse_semver,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "version,ok",
    [
        ("1.0.0", True),
        ("0.1.0", True),
        ("12.34.56", True),
        ("1.2.0-beta", True),
        ("2.0.0-rc.1", True),
        ("1.0", False),
        ("v1.0.0", False),
        ("1.0.0.0", False),
        ("01.0.0", False),
        ("", False),
        ("abc", False),
    ],
)
def test_is_valid_semver(version: str, ok: bool):
    assert is_valid_semver(version) is ok


def test_determine_version_feature():
    assert determine_version("1.2.3", "feature") == "1.3.0"


def test_determine_version_fix():
    assert determine_version("1.2.3", "fix") == "1.2.4"


def test_determine_version_refactor():
    assert determine_version("1.2.3", "refactor") == "1.2.4"


def test_determine_version_breaking():
    assert determine_version("1.2.3", "breaking") == "2.0.0"


def test_determine_version_strips_prerelease():
    assert determine_version("1.2.0-beta", "feature") == "1.3.0"


def test_determine_version_invalid_parent():
    with pytest.raises(ValueError):
        determine_version("1.0", "fix")


def test_determine_version_invalid_change_type():
    with pytest.raises(ValueError):
        determine_version("1.0.0", "yolo")


def test_parse_semver():
    assert parse_semver("1.2.3-beta") == (1, 2, 3, "beta")
    assert parse_semver("1.2.3") == (1, 2, 3, None)


def test_compare_versions():
    assert compare_versions("1.0.0", "2.0.0") == -1
    assert compare_versions("2.0.0", "1.9.9") == 1
    assert compare_versions("1.2.3", "1.2.3") == 0
    # 预发布 < 正式版
    assert compare_versions("1.0.0-beta", "1.0.0") == -1
    assert compare_versions("1.0.0", "1.0.0-beta") == 1
