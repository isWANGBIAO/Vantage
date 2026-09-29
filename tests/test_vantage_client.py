from __future__ import annotations

import pytest
import requests

from src.services.automation_catalog import Operation, get_operation
from src.services.vantage_client import (
    ArgumentValidationError,
    BackendHTTPError,
    BackendRedirectError,
    BackendUnavailableError,
    OperationUnavailableError,
    VantageClient,
)


class FakeResponse:
    def __init__(
        self,
        *,
        status_code=200,
        payload=None,
        lines=(),
        content=b"",
        headers=None,
        text="",
    ):
        self.status_code = status_code
        self._payload = payload
        self._lines = lines
        self.content = content
        self.headers = headers or {}
        self.text = text
        self.closed = False

    def json(self):
        return self._payload

    def iter_lines(self, *, decode_unicode=False):
        return iter(self._lines)

    def close(self):
        self.closed = True


class RecordingSession:
    def __init__(self, response=None, error=None):
        self.response = response or FakeResponse(payload={"ok": True})
        self.error = error
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.error:
            raise self.error
        return self.response


def _custom_operation(schema):
    return Operation(
        name="test.operation",
        description="Test operation.",
        method="POST",
        path="/api/test",
        input_schema=schema,
        output_kind="json",
    )


def test_json_operation_defaults_to_loopback_backend_and_returns_json():
    session = RecordingSession(FakeResponse(payload={"camera_online": True}))
    client = VantageClient(session=session)

    result = client.invoke("system.status.read")

    assert client.base_url == "http://127.0.0.1:8000"
    assert result == {"camera_online": True}
    assert session.calls == [
        (
            "GET",
            "http://127.0.0.1:8000/api/status",
            {"allow_redirects": False, "timeout": 30.0},
        )
    ]


def test_custom_backend_url_must_remain_loopback():
    client = VantageClient("http://localhost:8123")

    assert client.base_url == "http://localhost:8123"
    with pytest.raises(ValueError, match="loopback"):
        VantageClient("https://api.example.com")


def test_get_arguments_are_query_parameters_and_mutations_are_json_bodies():
    get_session = RecordingSession()
    post_session = RecordingSession()
    VantageClient(session=get_session).invoke(
        "finance.recommendations.read", {"recommendation_count": 8, "model": "local-model"}
    )
    VantageClient(session=post_session).invoke(
        "finance.recommendations.regenerate", {"recommendation_count": 7}
    )

    assert get_session.calls[0][2]["params"] == {
        "recommendation_count": 8,
        "model": "local-model",
    }
    assert "json" not in get_session.calls[0][2]
    assert post_session.calls[0][2]["json"] == {"recommendation_count": 7}
    assert "params" not in post_session.calls[0][2]


def test_path_parameters_are_substituted_and_removed_from_request_arguments():
    session = RecordingSession()

    VantageClient(session=session).invoke(
        "finance.recommendations.dismissed.restore", {"item_id": 17}
    )

    method, url, kwargs = session.calls[0]
    assert method == "DELETE"
    assert url.endswith("/api/balance_sheet/purchase_recommendations/dismissed/17")
    assert kwargs == {"allow_redirects": False, "timeout": 30.0}


def test_path_parameters_are_url_encoded():
    operation = Operation(
        name="test.path_parameter",
        description="Test path parameter encoding.",
        method="GET",
        path="/api/items/{item_id}",
        input_schema={
            "type": "object",
            "properties": {"item_id": {"type": "string"}},
            "required": ["item_id"],
        },
        output_kind="json",
    )
    session = RecordingSession()

    VantageClient(session=session).invoke(operation, {"item_id": "a/b"})

    assert session.calls[0][1].endswith("/api/items/a%2Fb")


def test_required_local_action_intent_header_is_sent():
    session = RecordingSession()

    VantageClient(session=session).invoke("system.media.open_folder", {"type": "photo"})

    assert session.calls[0][2]["headers"] == {"X-Vantage-Intent": "open-folder"}
    assert session.calls[0][2]["json"] == {"type": "photo"}


def test_schema_validates_nested_required_enum_bounds_arrays_and_additional_properties():
    operation = _custom_operation(
        {
            "type": "object",
            "properties": {
                "config": {
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string", "enum": ["safe", "fast"]},
                        "threshold": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["mode", "threshold"],
                    "additionalProperties": False,
                },
                "labels": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["config"],
            "additionalProperties": False,
        }
    )
    session = RecordingSession()

    with pytest.raises(ArgumentValidationError, match="config.mode"):
        VantageClient(session=session).invoke(operation, {"config": {"mode": "unsafe", "threshold": 0.5}})
    with pytest.raises(ArgumentValidationError, match="config.threshold"):
        VantageClient(session=session).invoke(operation, {"config": {"mode": "safe", "threshold": 2}})
    with pytest.raises(ArgumentValidationError, match=r"labels\[0\]"):
        VantageClient(session=session).invoke(
            operation, {"config": {"mode": "safe", "threshold": 0.5}, "labels": [3]}
        )
    with pytest.raises(ArgumentValidationError, match="config.unknown"):
        VantageClient(session=session).invoke(
            operation,
            {"config": {"mode": "safe", "threshold": 0.5, "unknown": True}},
        )
    with pytest.raises(ArgumentValidationError, match="config.threshold"):
        VantageClient(session=session).invoke(
            operation, {"config": {"mode": "safe", "threshold": True}}
        )
    assert session.calls == []


def test_onboarding_schema_enforces_selected_provider_when_chat_setup_is_not_skipped():
    session = RecordingSession()
    client = VantageClient(session=session)

    with pytest.raises(ArgumentValidationError, match="one allowed schema"):
        client.invoke("onboarding.complete", {"skip_chat_setup": False})

    client.invoke("onboarding.complete", {"skip_chat_setup": True})
    client.invoke(
        "onboarding.complete",
        {"skip_chat_setup": False, "selected_provider": "custom"},
    )

    assert len(session.calls) == 2


@pytest.mark.parametrize(
    ("arguments", "valid"),
    [
        ({"skip_chat_setup": True, "import_legacy_data": True}, False),
        (
            {
                "skip_chat_setup": True,
                "import_legacy_data": True,
                "legacy_root": "   ",
            },
            False,
        ),
        ({"skip_chat_setup": True, "import_legacy_data": False}, True),
        (
            {
                "skip_chat_setup": True,
                "import_legacy_data": True,
                "legacy_root": r"C:\\legacy",
            },
            True,
        ),
    ],
)
def test_onboarding_legacy_import_requires_a_nonblank_root_before_backend_call(
    arguments, valid
):
    session = RecordingSession()
    client = VantageClient(session=session)

    if valid:
        client.invoke("onboarding.complete", arguments)
        assert len(session.calls) == 1
    else:
        with pytest.raises(ArgumentValidationError):
            client.invoke("onboarding.complete", arguments)
        assert session.calls == []


@pytest.mark.parametrize("selected_provider", ["", "   "])
def test_onboarding_schema_rejects_blank_selected_provider_before_backend_call(selected_provider):
    session = RecordingSession()

    with pytest.raises(ArgumentValidationError):
        VantageClient(session=session).invoke(
            "onboarding.complete",
            {"skip_chat_setup": False, "selected_provider": selected_provider},
        )

    assert session.calls == []


def test_schema_supports_nullable_types_and_schema_valued_additional_properties():
    operation = _custom_operation(
        {
            "type": "object",
            "properties": {
                "note": {"type": ["string", "null"]},
                "metrics": {
                    "type": "object",
                    "additionalProperties": {"type": "number", "minimum": 0},
                },
            },
            "additionalProperties": False,
        }
    )
    session = RecordingSession()

    VantageClient(session=session).invoke(operation, {"note": None, "metrics": {"cpu": 0.4}})
    with pytest.raises(ArgumentValidationError, match="metrics.memory"):
        VantageClient(session=session).invoke(
            operation, {"metrics": {"memory": "high"}}
        )


def test_schema_number_validation_handles_arbitrarily_large_json_integers():
    operation = _custom_operation(
        {
            "type": "object",
            "properties": {"count": {"type": "number"}},
        }
    )
    session = RecordingSession()

    VantageClient(session=session).invoke(operation, {"count": 2**1024})

    assert len(session.calls) == 1


def test_root_arguments_must_be_an_object():
    with pytest.raises(ArgumentValidationError, match="object"):
        VantageClient(session=RecordingSession()).invoke("system.status.read", ["unexpected"])


def test_backend_connection_errors_are_actionable_and_do_not_echo_request_secrets():
    secret = "provider-secret-123"
    session = RecordingSession(error=requests.ConnectionError(f"failed while sending {secret}"))

    with pytest.raises(BackendUnavailableError) as error:
        VantageClient(session=session).invoke("models.discover", {"api_key": secret})

    assert "Vantage backend" in str(error.value)
    assert secret not in str(error.value)


def test_http_errors_are_actionable_and_do_not_echo_server_body_or_request_secrets():
    secret = "provider-secret-456"
    session = RecordingSession(FakeResponse(status_code=503, text=f"echo {secret}"))

    with pytest.raises(BackendHTTPError) as error:
        VantageClient(session=session).invoke("models.discover", {"api_key": secret})

    assert error.value.status_code == 503
    assert "503" in str(error.value)
    assert secret not in str(error.value)


def test_backend_redirect_is_reported_without_contacting_external_location():
    external_url = "https://external.example.invalid/collect"
    request_secret = "redirect-secret-test-value"

    class RedirectAdapter(requests.adapters.BaseAdapter):
        def __init__(self):
            self.sent_requests = []

        def send(self, request, **_kwargs):
            self.sent_requests.append((request.url, request.method, request.body))
            response = requests.Response()
            response.status_code = 307 if len(self.sent_requests) == 1 else 200
            response.headers["Location"] = external_url
            response._content = b"{}"
            response.url = request.url
            response.request = request
            return response

        def close(self):
            return None

    session = requests.Session()
    adapter = RedirectAdapter()
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    with pytest.raises(BackendRedirectError) as error:
        VantageClient(session=session).invoke("models.discover", {"api_key": request_secret})

    assert len(adapter.sent_requests) == 1
    url, method, body = adapter.sent_requests[0]
    assert url == "http://127.0.0.1:8000/api/llm_models/discover"
    assert method == "POST"
    body_text = body.decode("utf-8") if isinstance(body, bytes) else str(body)
    assert request_secret in body_text
    assert error.value.status_code == 307
    assert "redirect" in str(error.value).lower()


def test_stream_operations_yield_decoded_ndjson_records_and_close_response():
    response = FakeResponse(
        lines=[b'{"event":"progress","value":0.5}', b"", b'{"event":"done"}']
    )
    session = RecordingSession(response)

    result = list(VantageClient(session=session).invoke("action_plan.generate"))

    assert result == [{"event": "progress", "value": 0.5}, {"event": "done"}]
    assert session.calls[0][2]["stream"] is True
    assert response.closed is True


def test_download_returns_sanitized_basename_and_bytes():
    response = FakeResponse(
        content=b"xlsx-content",
        headers={"Content-Disposition": 'attachment; filename="..\\private\\report.xlsx"'},
    )
    session = RecordingSession(response)

    result = VantageClient(session=session).invoke("face.export")

    assert result.filename == "report.xlsx"
    assert result.content == b"xlsx-content"
    assert result.content_type is None
    assert session.calls[0][2]["stream"] is True
    assert response.closed is True


def test_multipart_transcription_maps_file_path_and_closes_file_after_request(tmp_path):
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"audio-bytes")
    captured = {}

    class InspectingSession(RecordingSession):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            field_name, upload = next(iter(kwargs["files"].items()))
            captured["field_name"] = field_name
            captured["file_name"] = upload[0]
            captured["file_bytes"] = upload[1].read()
            captured["file_handle"] = upload[1]
            captured["form"] = kwargs.get("data")
            return self.response

    session = InspectingSession(FakeResponse(payload={"text": "hello"}))

    result = VantageClient(session=session).invoke(
        "media.transcribe", {"file_path": str(audio_path)}
    )

    assert result == {"text": "hello"}
    assert captured["field_name"] == "file"
    assert captured["file_name"] == "sample.wav"
    assert captured["file_bytes"] == b"audio-bytes"
    assert captured["form"] == {}
    assert captured["file_handle"].closed is True
    assert "json" not in session.calls[0][2]


@pytest.mark.parametrize(
    "operation_name",
    ["settings.open_path"],
)
def test_operations_without_an_available_backend_target_fail_explicitly(operation_name):
    operation = get_operation(operation_name)

    with pytest.raises(OperationUnavailableError) as error:
        VantageClient(session=RecordingSession()).invoke(operation)

    assert operation_name in str(error.value)
    assert operation.unavailable_reason in str(error.value)
