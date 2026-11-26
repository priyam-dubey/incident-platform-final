from redaction import redact


def test_short_password_assignment_is_redacted_and_label_kept():
    r = redact("MongoNetworkError password=hunter2 host=db")
    assert "hunter2" not in r.text and "password=[REDACTED:CREDENTIAL]" in r.text and "host=db" in r.text
    assert "credential_assignment" in r.redacted_categories


def test_variants():
    for raw in ('pwd: abc', "secret='x1'", 'client_secret=zz', 'passphrase = "a b"'):
        assert "[REDACTED:CREDENTIAL]" in redact(raw).text


def test_plain_text_untouched():
    assert redact("password reset email sent").text == "password reset email sent"
