from client.network import SubmitError
from client.publication_result import failure_info, failure_text


def test_structured_failure_is_bounded_and_redacts_credentials():
    failure = failure_info(
        {"category": "network", "retryable": True,
         "reason": "POST https://private.example/upload?token=secret Authorization:Bearer abc123 failed"},
        operation="upload_put", campaign_id="campaign-0123456789abcdef",
    )
    assert failure["category"] == "network"
    assert failure["operation"] == "upload_put"
    assert failure["campaignId"] == "campaign-0123456789abcdef"
    assert "private.example" not in failure["reason"]
    assert "secret" not in failure["reason"]
    assert "abc123" not in failure["reason"]
    assert len(failure["reason"]) <= 200


def test_transport_status_and_legacy_string_have_actionable_causes():
    rate_limit = failure_info(
        SubmitError("rate limited", retryable=True, status_code=429),
        operation="create_run",
    )
    assert rate_limit["category"] == "rate_limited"
    assert rate_limit["retryable"] is True
    assert rate_limit["statusCode"] == 429
    mismatch = failure_info(
        "saved runtime identity differs from this client", operation="reconstruct",
    )
    assert mismatch["category"] == "incompatible"
    assert mismatch["retryable"] is False
    assert "original compatible client" in failure_text(mismatch)
    disk = failure_info(
        FileNotFoundError("/Users/example/private/campaign.json is missing"),
        operation="journal_reopen",
    )
    assert "/Users/example" not in disk["reason"]
    assert disk["operation"] == "journal_reopen"
    assert disk["category"] == "corrupt_evidence"
    expired = failure_info("retry_deadline_expired", operation="replay")
    assert expired["category"] == "expired"
    assert expired["retryable"] is False
    assert "do not restart" in expired["nextAction"]
