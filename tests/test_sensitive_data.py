from src.utils.sensitive_data import redact_sensitive_text


def test_redact_sensitive_text_removes_provider_api_key_values():
    secret = "2615cad9be45f50badccd2fa5ffc2bd4596c01eb937c5204388a9c59dfc77b19"
    message = (
        f"Rate limit exceeded for api_key: {secret} "
        f'body={{"error":{{"message":"api_key: {secret}"}}}}'
    )

    redacted = redact_sensitive_text(message)

    assert secret not in redacted
    assert "api_key: [REDACTED_API_KEY]" in redacted


def test_redact_sensitive_text_removes_sk_style_keys():
    assert redact_sensitive_text("bad sk-1234567890abcdef") == "bad sk-[REDACTED]"
