from clinical_trial_matcher.core.logger import redact_text


def test_redacts_groq_keys():
    text = "key=gsk_FAKE1234567890"
    assert "gsk_FAKE1234567890" not in redact_text(text)
    assert "[REDACTED]" in redact_text(text)


def test_redacts_bearer_tokens():
    text = "Authorization: Bearer abc.def.ghi"
    assert "abc.def.ghi" not in redact_text(text)
    assert "[REDACTED]" in redact_text(text)


def test_redacts_password_assignments():
    text = "password=supersecret api_key=abc123"
    redacted = redact_text(text)
    assert "supersecret" not in redacted
    assert "abc123" not in redacted


def test_redacts_email_and_phone():
    redacted = redact_text("contact jane.doe@example.com or 555-123-4567")
    assert "jane.doe@example.com" not in redacted
    assert "555-123-4567" not in redacted
    assert "[EMAIL_REDACTED]" in redacted
    assert "[PHONE_REDACTED]" in redacted
