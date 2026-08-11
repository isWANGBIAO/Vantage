import io
import subprocess
import sys

from src.utils import sensitive_data
from src.utils.sensitive_data import (
    RedactingPipeLog,
    RedactingTextStream,
    redact_sensitive_text,
)


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


def test_redact_sensitive_text_removes_common_http_url_and_github_credentials():
    secrets = {
        "bearer": "bearer-secret-1234567890",
        "basic": "dXNlcjpwYXNzd29yZA==",
        "password": "url-password-123456",
        "github": "ghp_abcdefghijklmnopqrstuvwxyz1234567890",
        "token": "query-secret-1234567890",
        "json_token": "json-secret-1234567890",
        "npm_token": "npm-secret-1234567890",
        "github_env_token": "github-env-secret-1234567890",
        "npm_auth": "npm-auth-secret-1234567890",
        "password_field": "password-secret-1234567890",
        "client_secret": "client-secret-1234567890",
    }
    message = (
        f"Authorization: Bearer {secrets['bearer']}\n"
        f"authorization: Basic {secrets['basic']}\n"
        f"url=https://alice:{secrets['password']}@example.test/private\n"
        f"github={secrets['github']}\n"
        f"request?token={secrets['token']}&safe=1\n"
        f'payload={{"access_token":"{secrets["json_token"]}"}}\n'
        f"NPM_TOKEN={secrets['npm_token']}\n"
        f"GITHUB_TOKEN: {secrets['github_env_token']}\n"
        f"//registry.npmjs.org/:_authToken={secrets['npm_auth']}\n"
        f"password={secrets['password_field']}\n"
        f'payload={{"client_secret":"{secrets["client_secret"]}"}}\n'
    )

    redacted = redact_sensitive_text(message)

    assert all(secret not in redacted for secret in secrets.values())
    assert "Authorization: Bearer [REDACTED_TOKEN]" in redacted
    assert "authorization: Basic [REDACTED_TOKEN]" in redacted
    assert "https://[REDACTED_USERINFO]@example.test" in redacted
    assert "ghp_[REDACTED]" in redacted
    assert "token=[REDACTED_TOKEN]" in redacted
    assert '"access_token":"[REDACTED_TOKEN]"' in redacted
    assert "NPM_TOKEN=[REDACTED_TOKEN]" in redacted
    assert "GITHUB_TOKEN: [REDACTED_TOKEN]" in redacted
    assert ":_authToken=[REDACTED_TOKEN]" in redacted
    assert "password=[REDACTED_SECRET]" in redacted
    assert '"client_secret":"[REDACTED_SECRET]"' in redacted


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
        "embedded=XC:/Users/Alice/repo/file.py "
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

    assert "XC:/Users/Alice/repo/file.py" in redacted
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


def test_redacting_pipe_log_redacts_an_unterminated_record_at_eof(tmp_path):
    log_path = tmp_path / "child.log"
    secret = "unterminated-bearer-secret-1234567890"
    private_root = r"C:\Users\Alice\Private Photos"

    with RedactingPipeLog(
        log_path,
        path_prefixes={"<HISTORY_DIR>": private_root},
    ) as pipe_log:
        with pipe_log.capture_subprocess_output(stream_name="eof") as output:
            output.write(
                (
                    f"path={private_root}\\face.jpg "
                    f"Authorization: Bearer {secret}"
                ).encode("utf-8")
            )

    persisted = log_path.read_text(encoding="utf-8")
    assert private_root not in persisted
    assert secret not in persisted
    assert r"path=<HISTORY_DIR>\face.jpg" in persisted
    assert "Authorization: Bearer [REDACTED_TOKEN]" in persisted


def test_runtime_path_registration_updates_active_and_future_pipe_logs(tmp_path):
    media_root = tmp_path / "Private Photos"
    media_root.mkdir()
    active_log_path = tmp_path / "active.log"
    future_log_path = tmp_path / "future.log"

    with sensitive_data._RUNTIME_LOG_PATH_PREFIXES_LOCK:
        original_prefixes = dict(sensitive_data._RUNTIME_LOG_PATH_PREFIXES)

    try:
        with RedactingPipeLog(active_log_path) as active_log:
            with active_log.capture_subprocess_output(stream_name="media") as output:
                sensitive_data.register_runtime_log_path_prefixes(
                    {"<TEST_MEDIA_ROOT>": media_root}
                )
                record = (
                    f"Scanning paths: {media_root / 'history'}; "
                    f"BASE_DIR: {media_root}; "
                    "Authorization: Bearer runtime-media-secret-1234567890\n"
                )
                subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        (
                            "import os, sys; data=sys.argv[1].encode(); "
                            "mid=len(data)//2; os.write(1,data[:mid]); "
                            "os.write(1,data[mid:])"
                        ),
                        record,
                    ],
                    check=True,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )

        with RedactingPipeLog(future_log_path) as future_log:
            future_log.write_record(f"Scanning paths: {media_root / 'history'}\n")

        for log_path in (active_log_path, future_log_path):
            persisted = log_path.read_text(encoding="utf-8")
            assert str(media_root) not in persisted
            assert "runtime-media-secret-1234567890" not in persisted
            assert "<TEST_MEDIA_ROOT>" in persisted
            assert "history" in persisted
    finally:
        with sensitive_data._RUNTIME_LOG_PATH_PREFIXES_LOCK:
            sensitive_data._RUNTIME_LOG_PATH_PREFIXES.clear()
            sensitive_data._RUNTIME_LOG_PATH_PREFIXES.update(original_prefixes)
