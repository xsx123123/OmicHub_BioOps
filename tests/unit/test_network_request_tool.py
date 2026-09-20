"""受限公共 HTTP 元数据工具的边界测试。"""

from __future__ import annotations

import pytest

from cygnusx.application.services.network_request_tool import (
    MAX_RESPONSE_BYTES,
    NETWORK_REQUEST_TOOL_SCHEMA,
    _public_url,
    network_request_risk_hint,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("url", "error_fragment"),
    [
        ("file:///tmp/secret", "只允许"),
        ("http://localhost:8000/", "禁止"),
        ("http://127.0.0.1:8000/", "禁止"),
        ("http://10.0.0.1/", "禁止"),
        ("https://user:pass@example.com/", "不允许"),
    ],
)
def test_public_url_rejects_non_public_targets(url: str, error_fragment: str) -> None:
    _, error = _public_url(url)
    assert error is not None
    assert error_fragment in error


@pytest.mark.unit
def test_network_schema_and_risk_hint_are_explicit() -> None:
    assert NETWORK_REQUEST_TOOL_SCHEMA["function"]["name"] == "network_request"
    assert NETWORK_REQUEST_TOOL_SCHEMA["function"]["parameters"]["properties"]["max_bytes"]["maximum"] == MAX_RESPONSE_BYTES
    hint = network_request_risk_hint({"url": "https://eutils.ncbi.nlm.nih.gov/", "method": "GET"})
    assert "eutils.ncbi.nlm.nih.gov" in hint
    assert "不携带用户凭据" in hint
