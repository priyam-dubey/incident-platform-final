from redaction import redact, DEFAULT_CATEGORIES


def test_redacts_email_address() -> None:
    result = redact("Contact alice@company.com for details")
    assert "alice@company.com" not in result.text
    assert "[REDACTED:EMAIL]" in result.text
    assert "email" in result.redacted_categories


def test_redacts_api_key_labeled_token() -> None:
    result = redact("Request failed with api_key=sk_live_abcdef1234567890ABCDEF1234")
    assert "sk_live_abcdef1234567890ABCDEF1234" not in result.text
    assert "api_key" in result.redacted_categories


def test_redacts_aws_access_key() -> None:
    result = redact("Using credentials AKIAIOSFODNN7EXAMPLE for S3 access")
    assert "AKIAIOSFODNN7EXAMPLE" not in result.text
    assert "aws_access_key" in result.redacted_categories


def test_redacts_jwt() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    result = redact(f"Auth header: {jwt}")
    assert jwt not in result.text
    assert "jwt" in result.redacted_categories


def test_redacts_credit_card_with_separators() -> None:
    result = redact("Card on file: 4111-1111-1111-1111")
    assert "4111-1111-1111-1111" not in result.text
    assert "credit_card" in result.redacted_categories


def test_does_not_flag_clean_text() -> None:
    result = redact("connection pool exhausted after 30000ms, retrying")
    assert not result.was_modified
    assert result.text == "connection pool exhausted after 30000ms, retrying"


def test_multiple_categories_in_one_string_are_all_redacted() -> None:
    text = "user alice@company.com used key AKIAIOSFODNN7EXAMPLE"
    result = redact(text)
    assert "alice@company.com" not in result.text
    assert "AKIAIOSFODNN7EXAMPLE" not in result.text
    assert set(result.redacted_categories) == {"email", "aws_access_key"}


def test_unknown_category_raises() -> None:
    import pytest

    with pytest.raises(ValueError):
        redact("hello", categories=frozenset({"not_a_real_category"}))


def test_ipv4_and_phone_are_not_redacted_by_default() -> None:
    # Documented default-off categories - internal IPs and phone-shaped
    # numeric strings are common in legitimate infra evidence.
    result = redact("upstream 10.0.4.17 timed out, order phone 555-123-4567")
    assert "10.0.4.17" in result.text
    assert "555-123-4567" in result.text
    assert not result.was_modified


def test_ipv4_redaction_is_available_when_explicitly_requested() -> None:
    result = redact("upstream 10.0.4.17 timed out", categories=frozenset({"ipv4"}))
    assert "10.0.4.17" not in result.text
    assert "ipv4" in result.redacted_categories


def test_default_categories_constant_matches_documented_set() -> None:
    assert DEFAULT_CATEGORIES == frozenset(
        {"email", "api_key", "aws_access_key", "jwt", "credit_card"}
    )


def test_bare_epoch_millisecond_timestamp_is_not_falsely_redacted() -> None:
    # Regression test for a real bug caught during development: a bare
    # 13-digit epoch-ms timestamp (extremely common in telemetry evidence)
    # was being matched by an overly loose credit-card pattern.
    result = redact("event occurred at timestamp 1754380800123 during the incident")
    assert "1754380800123" in result.text
    assert not result.was_modified


def test_unformatted_16_digit_number_is_still_treated_as_credit_card() -> None:
    result = redact("card number 4111111111111111 on file")
    assert "4111111111111111" not in result.text
    assert "credit_card" in result.redacted_categories


def test_grouped_credit_card_with_spaces_is_redacted() -> None:
    result = redact("card: 4111 1111 1111 1111 declined")
    assert "4111 1111 1111 1111" not in result.text
    assert "credit_card" in result.redacted_categories
