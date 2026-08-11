import io

from src.utils.sensitive_data import RedactingTextStream, redact_sensitive_text


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


def test_redact_sensitive_text_replaces_longest_explicit_path_prefix():
    message = (
        r'Traceback: File "C:\Users\Alice\repo\src\server.py", line 42; '
        r'cache=c:/users/alice/AppData/Local/Vantage/cache/result.json; '
        r'json="C:\\Users\\Alice\\repo\\src\\worker.py"'
    )
    path_prefixes = {
        "<USER_HOME>": r"C:\Users\Alice",
        "<PROJECT_ROOT>": r"C:\Users\Alice\repo",
        "<CACHE_DIR>": r"C:\Users\Alice\AppData\Local\Vantage\cache",
    }

    redacted = redact_sensitive_text(message, path_prefixes=path_prefixes)

    assert "Alice" not in redacted
    assert r'<PROJECT_ROOT>\src\server.py", line 42' in redacted
    assert "<CACHE_DIR>/result.json" in redacted
    assert r'json="<PROJECT_ROOT>\\src\\worker.py"' in redacted


def test_redact_sensitive_text_does_not_replace_partial_directory_names_or_urls():
    message = (
        "project=C:/Users/Alice/repository/file.py "
        "sibling=C:/Users/Alice/repo-other/file.py "
        "archive=C:/Users/Alice/repo.txt "
        "plus=C:/Users/Alice/repo+other/file.py "
        "paren=C:/Users/Alice/repo(backup)/file.py "
        "at=C:/Users/Alice/repo@old/file.py "
        "tilde=C:/Users/Alice/repo~old/file.py "
        "hash=C:/Users/Alice/repo#old/file.py "
        'exact="C:/Users/Alice/repo" '
        "url=https://example.test/C:/Users/Alice/repo/file.py"
    )

    redacted = redact_sensitive_text(
        message,
        path_prefixes={"<PROJECT_ROOT>": r"C:\Users\Alice\repo"},
    )

    assert "C:/Users/Alice/repository/file.py" in redacted
    assert "C:/Users/Alice/repo-other/file.py" in redacted
    assert "C:/Users/Alice/repo.txt" in redacted
    assert "C:/Users/Alice/repo+other/file.py" in redacted
    assert "C:/Users/Alice/repo(backup)/file.py" in redacted
    assert "C:/Users/Alice/repo@old/file.py" in redacted
    assert "C:/Users/Alice/repo~old/file.py" in redacted
    assert "C:/Users/Alice/repo#old/file.py" in redacted
    assert 'exact="<PROJECT_ROOT>"' in redacted
    assert "https://example.test/<PROJECT_ROOT>/file.py" in redacted


def test_redacting_text_stream_sanitizes_before_write_and_preserves_stream_contract():
    target = io.StringIO()
    stream = RedactingTextStream(
        target,
        path_prefixes={"<PROJECT_ROOT>": r"C:\Users\Alice\repo"},
    )

    written = stream.write(
        r'File "c:/users/alice/repo/src/app.py", line 7 api_key=1234567890abcdef'
    )
    stream.flush()

    persisted = target.getvalue()
    assert written == len(persisted)
    assert "Alice" not in persisted
    assert "1234567890abcdef" not in persisted
    assert '<PROJECT_ROOT>/src/app.py", line 7' in persisted
    assert "api_key=[REDACTED_API_KEY]" in persisted
    assert stream.encoding == target.encoding


def test_redacting_text_stream_fails_closed_if_redaction_raises():
    target = io.StringIO()

    def broken_redactor(_value, **_kwargs):
        raise RuntimeError("redactor unavailable")

    stream = RedactingTextStream(
        target,
        path_prefixes={"<USER_HOME>": r"C:\Users\Alice"},
        redact_fn=broken_redactor,
    )

    stream.write(r"secret path C:\Users\Alice\private.txt")

    assert target.getvalue() == "[LOG_REDACTION_FAILED]"
