"""Use real HTTP chunked framing, as .NET JsonContent does, against the fixture."""

import http.client
import io
import json
from types import SimpleNamespace

import pytest

from src.native.testing.fixture_backend import Handler, start_fixture


def test_chunked_native_writes_preserve_fixture_mode_and_exact_chat_text():
    server = start_fixture()
    client = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)

    def request(method, path, body=None):
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        chunks = (data[i:i + 3] for i in range(0, len(data), 3)) if data is not None else None
        client.request(method, path, body=chunks, headers={"Content-Type": "application/json"}, encode_chunked=data is not None)
        response = client.getresponse()
        raw = response.read()
        assert response.status == 200 or response.status == 202
        return raw

    try:
        request("POST", "/__test__/reset", {"onboarded": False, "job_mode": "hold"})
        assert json.loads(request("GET", "/api/v1/onboarding"))["completed"] is False
        job = json.loads(request("POST", "/api/v1/action-plan/jobs", {"model": "exact-model"}))
        assert job["request"]["model"] == "exact-model"
        request("GET", f"/api/v1/action-plan/jobs/{job['id']}/events")
        assert json.loads(request("GET", "/api/v1/action-plan/jobs"))["active"]["id"] == job["id"]
        request("POST", f"/api/v1/action-plan/jobs/{job['id']}/cancel", {})
        assert json.loads(request("GET", f"/api/v1/action-plan/jobs/{job['id']}"))["status"] == "cancelled"
        text = "精确的 chunked 消息，跨 UTF-8 字符边界"
        request("POST", "/api/v1/chat", {"message": text})
        context = json.loads(request("GET", "/api/v1/chat/context"))
        assert any(message["role"] == "user" and message["content"] == text for message in context["messages"])
    finally:
        client.close()
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize(("headers", "body"), [
    ({"Transfer-Encoding": "chunked", "Content-Length": "2"}, b"{}"),
    ({"Transfer-Encoding": "gzip"}, b""),
    ({"Transfer-Encoding": "chunked"}, b"2\r\n{\r\n"),
    ({"Transfer-Encoding": "chunked"}, b"2000001\r\n"),
    ({"Content-Length": "-1"}, b""),
    ({"Content-Length": "4"}, b"{}"),
])
def test_fixture_rejects_ambiguous_oversized_or_truncated_body(headers, body):
    fake = SimpleNamespace(headers=headers, rfile=io.BytesIO(body))
    with pytest.raises(ValueError):
        Handler.read_body(fake)
