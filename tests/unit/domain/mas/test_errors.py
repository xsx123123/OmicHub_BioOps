from omichub.domain.mas.errors import ErrorCategory, classify_error


def test_retry_policy_is_server_owned_and_bounded() -> None:
    assert classify_error("NETWORK_TIMEOUT").retryable
    assert classify_error("NETWORK_TIMEOUT").max_attempts == 3
    assert not classify_error("QUALITY_GATE_FAILED").retryable
    assert classify_error("QUALITY_GATE_FAILED").requires_approval
    unknown = classify_error("UNTRUSTED_MODEL_TEXT")
    assert unknown.category == ErrorCategory.UNKNOWN
    assert unknown.requires_approval
