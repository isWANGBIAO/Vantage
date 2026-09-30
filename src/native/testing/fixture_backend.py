"""Isolated synthetic /api/v1 server for native UI smoke tests.

No backend imports, filesystem user data, model calls, or camera/microphone use.
Only loopback binding is supported. All visible values are artificial fixtures.
"""
from __future__ import annotations
import argparse
import base64
import copy
import json
import io
import zipfile
import os
from pathlib import Path
import signal
import threading
import uuid
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAMAAAACACAIAAADS5vE8AAACFUlEQVR4nO3dMU7cQBiA0WxwnSvkAFRwgZRI6TgAN0gNB6CBS1CQPqkSKV3KVHuGnIGCmgZRsR6kTxNZ0Xvlyvq9sj5NsbZndyc/7t/N9Pvo29T5X/7cTp1//Xg3df75p+Op82df//dTp/PfExCJgEgERCIgEgGRCIhkd+h3oP3ni3/8Vdiyh1/nr35uBSIREMkyPOL059dyArcy1m38VsaHs+/rB1iBSAREIiASAZEIiERAJAIiERCJgEgERCIgEgGRCIhEQCQCIhEQiYBIBEQiIBIBkSyHH7p+fi8sPpXtofd1G3/p4P5sMMcKRCIgEgGRCIhEQCQCIhEQiYBIBEQiIBIBkQiIREAkAiIREImASAREIiASAZEIiERAJAIiERCJgEgERCIgEgGRCIhEQCQCIhEQyXJo35fhxjBvZP+edZvfP+lmfY4ViERAJAIiERCJgEgERCIgEgGRCIhEQCQCIhEQiYBIBEQiIBIBkQiIREAkAiIREImASAREIiASAZEIiERAJAIiERCJgEgERCIgkuXw/jGDjWHeyP496za+f9J+NMcKRCIgEgGRCIhEQCQCIhEQiYBIBEQiIBIBkQiIREAkAiIREImASAREIiASAZEIiGQZHvHx9qacYD8+JLqYOv3lz4enSZd3aPb1twKRCIhk9/fyauoJvBe2buPvhQ1ZgUgERCIgEgGRCIhEQCQCInkCiKtP0c1BFKkAAAAASUVORK5CYII=")
JPEG = base64.b64decode("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAAYABgDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwCKiiiug+NCiiigAooooAKKKKAP/9k=")
STAMP = "2026-01-01T12:00:00+00:00"
TODAY = {"exists": True, "analysis": {"body": "## 综合分析\n\n本页使用合成数据，专用于原生客户端验收。"}, "plan": {"body": "## 今日行动计划\n\n- [ ] 阅读 30 分钟\n- [ ] 完成原生客户端检查\n- [x] 整理项目任务"}, "meta": {"generated_at": STAMP, "model": "fixture-model", "provider_route": "fixture", "fallback_used": False, "stats": {}}, "date": "2026-01-01", "filename": "fixture-plan.json", "id": "fixture-plan"}


def settings(onboarded=True):
    values = {"version": 2, "onboarding_completed": onboarded, "launch_at_login": False, "display_language": "zh-CN", "theme": "dark", "theme_mode": "dark", "action_plan_auto_generate": False, "action_plan_check_interval_minutes": 0}
    for kind in ("voice", "image"):
        values.update({f"{kind}_provider_mode": "inherit_ai", f"{kind}_base_url": "", f"{kind}_api_key": "", f"{kind}_has_api_key": False, f"{kind}_model": "fixture-model", f"{kind}_models": ["fixture-model"], f"{kind}_last_refreshed_at": None})
    provider = {"route": "fixture", "name": "Synthetic provider", "type": "openai-compatible", "enabled": True, "api_key": "********", "base_url": "http://127.0.0.1:9/v1", "model": "fixture-model", "models": ["fixture-model"], "last_refreshed_at": None}
    return {"settings": values, "provider": {"version": 2, "selected_provider": "fixture", "sampling_defaults": {"temperature": 1.0}, "model_profiles": {}, "providers": {"fixture": provider}}, "migration": {"completed": False, "source_path": None, "imported_at": None}, "runtime_paths": {}}


def state(onboarded=True):
    initial = copy.deepcopy(TODAY)
    initial["id"] = "fixture-initial-" + uuid.uuid4().hex
    initial["filename"] = initial["id"] + ".json"
    return {"today": initial, "settings": settings(onboarded), "job_mode": "success", "job": None, "events_reads": 0, "messages": [{"role": "assistant", "content": TODAY["plan"]["body"]}, {"role": "user", "content": "如何安排今天？"}, {"role": "assistant", "content": "先完成最重要的任务，再留出休息时间。"}], "requests": [], "dismissed": [], "face_running": False}


def context(s):
    return {"base_context_version": s["today"]["id"], "context_version": f"fixture-{len(s['messages'])}", "has_action_plan_context": True, "messages": copy.deepcopy(s["messages"]), "display_messages": [{"role": "assistant", "content": TODAY["plan"]["body"]}], "stats": {"input_tokens": 42, "output_tokens": 18}, "preferred_model": "fixture-model", "preferred_provider_route": "fixture", "preferred_model_option_id": "fixture::fixture-model"}


def job(request):
    return {"id": "fixture-job-" + uuid.uuid4().hex, "status": "running", "trigger": "manual", "request": {"reasoning_effort": None, "service_tier": None, "model": None, "provider_route": None, "replace_today": False, "wait_for_provider_ready": False, **request}, "created_at": STAMP, "updated_at": STAMP, "progress": {"phase": "plan", "events_received": 0}, "result": None, "error": None, "source_revision": "fixture-revision", "result_identity": None, "event_cursor": 0, "reused": False}



def finance_summary():
    return {"time_cost": {"daily_average": 50.0, "monthly_total": 1500.0, "per_minute": 50 / 1440, "per_day_month": 50.0, "latest_date": "2026-01-01", "source": {"daily_average": None, "monthly_total": None, "monthly_average": None}}, "assets": {key: {"value": value, "field": key, "sheet": "Synthetic"} for key, value in {"fixed_assets": 3000, "current_assets": 7000, "total_assets": 10000, "liabilities": 2000, "equity": 8000, "cash_and_stock": 7000}.items()}, "budget": {"sheet": "Synthetic", "monthly_required": 1000, "monthly_optional": 500, "required_count": 2, "optional_count": 1, "source_column": "Monthly"}}


def usage_payload():
    row = {"prompt_tokens": 420, "completion_tokens": 180, "total_tokens": 600, "prompt_cache_hit_tokens": 100, "prompt_cache_miss_tokens": 320, "prompt_cache_hit_rate": 100 / 420 * 100, "completion_reasoning_tokens": 30, "total_duration": 10.0, "average_duration": 10.0, "average_tokens_per_call": 600.0, "average_tokens_per_second": 60.0, "output_tokens_per_second": 18.0, "session_count": 1, "call_count": 1, "completed_call_count": 1, "failed_call_count": 0, "earliest_call_at": STAMP, "latest_call_at": STAMP}
    return {"summary": row, "by_source": [{**row, "source": "chat"}], "by_day": [{**row, "date": "2026-01-01"}], "sessions": [{**row, "session_id": "fixture-session", "source": "chat", "model": "fixture-model"}], "recent_calls": [{**row, "call_id": "fixture-call", "session_id": "fixture-session", "created_at": STAMP, "model": "fixture-model", "status": "completed", "duration": 10.0}], "speed_series": [{**row, "call_id": "fixture-call", "created_at": STAMP, "model": "fixture-model", "duration": 10.0}]}


def face_payload():
    return {"heaviest": {"url": "/api/v1/media/image?path=synthetic-heavy.png", "date": STAMP, "score": 60.0}, "lightest": {"url": "/api/v1/media/image?path=synthetic-light.png", "date": STAMP, "score": 20.0}, "trend_plot": "/static/plots/synthetic-trend.png?t=1", "trend_views": {key: {"label": title, "points": [{"timestamp": 1767268800, "datetime": "2026-01-01 12:00:00", "score": 20.0}, {"timestamp": 1767272400, "datetime": "2026-01-01 13:00:00", "score": 60.0}]} for key, title in [("day", "24 hours"), ("week", "7 days"), ("month", "30 days"), ("all", "All")]}}


def chart_payload():
    options = [
        {"xAxis": {"type": "category", "data": ["Mon", "Tue", "Wed", "Thu"]}, "yAxis": {"type": "value"}, "series": [{"name": "阅读", "type": "bar", "stack": "time", "data": [20, 45, None, 60]}, {"name": "运动", "type": "bar", "stack": "time", "data": [15, 20, 40, 30]}]},
        {"xAxis": {"type": "time"}, "yAxis": [{"type": "value", "name": "体重", "min": 40, "max": 100}, {"type": "value", "name": "配速", "inverse": True, "min": 0, "max": 20}], "series": [{"name": "体重", "type": "line", "data": [["2026-01-01", 60], ["2026-01-03", None], ["2026-01-10", 65]]}, {"name": "配速", "type": "line", "yAxisIndex": 1, "data": [["2026-01-01", 7], ["2026-01-03", 6], ["2026-01-10", 5]]}]},
        {"radar": {"indicator": [{"name": "阅读", "max": 100}, {"name": "运动", "max": 100}, {"name": "睡眠", "max": 100}]}, "series": [{"name": "Activity", "type": "radar", "data": [{"name": "今日", "value": [70, 40, 80]}, {"name": "目标", "value": [80, 60, 90]}]}]},
    ]
    return {"count": len(options), "charts": [{"id": f"fixture-{i}", "title": f"Synthetic chart {i + 1}", "description": "Native chart semantic smoke fixture", "empty": False, "error": None, "summary": [], "option": option} for i, option in enumerate(options)]}



def excel_fixture():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as book:
        book.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        book.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        book.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Synthetic" sheetId="1" r:id="rId1"/></sheets></workbook>')
        book.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        book.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Synthetic score</t></is></c><c r="B1"><v>25</v></c></row></sheetData></worksheet>')
    return output.getvalue()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *args):
        pass

    def read_body(self):
        # HttpClient JsonContent streams HTTP/1.1 requests with chunked transfer
        # encoding. A fixture that reads only Content-Length silently discards
        # those bodies and can make a native write test pass with wrong inputs.
        limit = 32 * 1024 * 1024
        encoding = self.headers.get("Transfer-Encoding", "").lower().strip()
        if encoding:
            if encoding != "chunked" or self.headers.get("Content-Length") is not None:
                raise ValueError("Ambiguous or unsupported request framing")
            chunks = bytearray()
            while True:
                line = self.rfile.readline(130)
                if len(line) > 128 or not line.endswith(b"\r\n"):
                    raise ValueError("Invalid chunk header")
                size = int(line.split(b";", 1)[0].strip(), 16)
                if size < 0 or len(chunks) + size > limit:
                    raise ValueError("Request exceeds fixture body limit")
                if size == 0:
                    trailer_size = 0
                    while True:
                        trailer = self.rfile.readline(8193)
                        trailer_size += len(trailer)
                        if trailer_size > 8192 or not trailer.endswith(b"\r\n"):
                            raise ValueError("Invalid chunk trailers")
                        if trailer == b"\r\n":
                            break
                    break
                data = self.rfile.read(size)
                if len(data) != size or self.rfile.read(2) != b"\r\n":
                    raise ValueError("Incomplete chunk body")
                chunks.extend(data)
            raw = bytes(chunks)
        else:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 <= length <= limit:
                raise ValueError("Request exceeds fixture body limit")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("Incomplete request body")
        if self.headers.get("Content-Type", "").startswith("application/json"):
            return json.loads(raw) if raw else {}
        return {}

    def respond(self, data, status=200, content_type="application/json"):
        payload = json.dumps(data, ensure_ascii=False).encode() if content_type == "application/json" else data
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        self.dispatch("GET")
    def do_POST(self):
        self.dispatch("POST")
    def do_PUT(self):
        self.dispatch("PUT")
    def do_DELETE(self):
        self.dispatch("DELETE")

    def dispatch(self, method):
        path = urlsplit(self.path).path
        s = self.server.state
        try:
            body = self.read_body() if method in {"POST", "PUT"} else {}
        except (ValueError, UnicodeError):
            self.close_connection = True
            return self.respond({"detail": "Invalid request framing or JSON"}, 400)
        # Never retain bodies or credentials; a smoke test may exercise writes.
        s["requests"].append({"method": method, "path": path})
        if path == "/__test__/reset" and method == "POST":
            self.server.state = state(body.get("onboarded", True))
            self.server.state["job_mode"] = body.get("job_mode", "success")
            return self.respond({"ok": True})
        if path == "/__test__/requests":
            return self.respond(s["requests"])
        if path == "/api/v1/capabilities":
            return self.respond({"api_version": "1.0", "service": "vantage", "transport": "loopback-http", "capabilities": ["settings", "onboarding", "action-plan-jobs", "action-plan-scheduler", "ndjson-events", "operation-catalog", "openapi"], "platform_owned": ["window", "tray", "login-startup", "file-picker", "camera-permission", "clipboard", "system-locale"], "contracts_url": "/openapi.json", "operations_url": "/api/v1/operations", "job_retention": "process-lifetime, bounded; saved results survive restart"})
        if path == "/api/v1/operations":
            return self.respond({"api_version": "1.0", "operations": []})
        if path == "/api/v1/settings":
            if method == "PUT":
                config = body.pop("provider_config", None)
                for key, value in body.items():
                    s["settings"]["settings"][key] = "********" if "api_key" in key and value else value
                if config:
                    for p in config.get("providers", {}).values():
                        if p.get("api_key"):
                            p["api_key"] = "********"
                    s["settings"]["provider"].update(config)
            return self.respond(s["settings"])
        if path == "/api/v1/settings/display-language":
            if method == "PUT":
                s["settings"]["settings"].update(body)
            return self.respond({"display_language": s["settings"]["settings"]["display_language"]})
        if path == "/api/v1/onboarding":
            st = s["settings"]["settings"]
            return self.respond({"completed": st["onboarding_completed"], "launchAtLogin": st["launch_at_login"], "displayLanguage": st["display_language"], "providerConfigured": True, "migrationCompleted": False, "legacyRoot": None})
        if path == "/api/v1/onboarding/complete":
            st = s["settings"]["settings"]
            st["onboarding_completed"] = True
            st["launch_at_login"] = body.get("launch_at_login", False)
            return self.respond({"completed": True, "launchAtLogin": st["launch_at_login"], "providerConfigured": True, "migration": {"imported": False, "completed": False, "sourcePath": None}, "settings": {k: st[k] for k in ("display_language", "theme", "theme_mode", "launch_at_login")}, "provider": {"selected_provider": "fixture", "providers": ["fixture"]}})
        if path == "/api/v1/action-plan/today":
            return self.respond(s["today"])
        if path == "/api/v1/action-plan/jobs":
            if method == "POST":
                if s["job"] and s["job"]["status"] in {"running", "queued", "cancelling"}:
                    return self.respond({**s["job"], "reused": True}, 202)
                s["job"] = job(body)
                s["events_reads"] = 0
                return self.respond(s["job"], 202)
            active = s["job"] if s["job"] and s["job"]["status"] not in {"succeeded", "failed", "cancelled"} else None
            return self.respond({"jobs": [s["job"]] if s["job"] else [], "active": active})
        if path.startswith("/api/v1/action-plan/jobs/"):
            j = s["job"]
            if not j or path.split("/")[5] != j["id"]:
                return self.respond({"detail": "Job not found"}, 404)
            if path.endswith("/cancel"):
                j["status"] = "cancelled"
                return self.respond(j)
            if path.endswith("/events"):
                s["events_reads"] += 1
                mode = s["job_mode"]
                events = [{"sequence": 1, "timestamp": STAMP, "log": 'STREAM_PLAN_CONTENT:"合成流式计划"'}]
                if mode == "disconnect" and s["events_reads"] == 1:
                    return self.respond((json.dumps(events[0]) + "\n").encode(), content_type="application/x-ndjson")
                if mode == "truncated" and s["events_reads"] == 1:
                    return self.respond(b'{"truncated":true,"cursor":2}\n', content_type="application/x-ndjson")
                if mode == "hold":
                    return self.respond((json.dumps({"sequence": 1, "timestamp": STAMP, "job_status": "running", "phase": "waiting"}) + "\n").encode(), content_type="application/x-ndjson")
                if mode == "failed":
                    j.update(status="failed", error={"code": "FIXTURE", "message": "Synthetic failure"})
                    events.append({"sequence": 3, "timestamp": STAMP, "error": "Synthetic failure", "error_code": "FIXTURE", "job_status": "failed"})
                elif mode == "cancelled":
                    j["status"] = "cancelled"
                    events.append({"sequence": 3, "timestamp": STAMP, "job_status": "cancelled"})
                else:
                    completed = copy.deepcopy(TODAY)
                    completed["id"] = "fixture-plan-" + uuid.uuid4().hex
                    completed["filename"] = completed["id"] + ".json"
                    completed["timestamp"] = time.time()
                    s["today"] = completed
                    j.update(status="succeeded", result=copy.deepcopy(completed), result_identity=completed["id"])
                    events.append({"sequence": 3, "timestamp": STAMP, "done": True, "job_status": "succeeded"})
                j["event_cursor"] = 3
                return self.respond("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events).encode(), content_type="application/x-ndjson")
            return self.respond(j)
        if path == "/api/v1/action-plan/scheduler":
            return self.respond({"running": True, "enabled": False, "startup_auto_generate": False, "onboarding_completed": True, "check_interval_minutes": 0, "last_check_at": None, "last_success_at": None, "last_error": None, "last_source_revision": "fixture-revision", "last_consumed_revision": "fixture-revision", "outcome": "disabled", "error": None, "date": "2026-01-01", "baseline_revision": "fixture-revision", "generated_revision": "fixture-revision"})
        if path == "/api/v1/action-plan/source-revision":
            return self.respond({"revision": "fixture-revision"})
        if path == "/api/v1/chat/context":
            if method == "DELETE":
                s["messages"] = [{"role": "assistant", "content": TODAY["plan"]["body"]}]
            return self.respond(context(s))
        if path == "/api/v1/chat":
            s["messages"].extend([{"role": "user", "content": body.get("message", "")}, {"role": "assistant", "content": "这是合成的原生聊天流响应。"}])
            events = [{"log": 'STREAM_THINKING:"测试思考"'}, {"log": 'STREAM_CONTENT:"这是合成的原生聊天流响应。"'}, {"done": True}]
            return self.respond("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events).encode(), content_type="application/x-ndjson")
        if path == "/api/v1/media/transcribe":
            return self.respond({"transcription": "合成语音转录"})
        if path in {"/api/v1/models/discover", "/api/v1/providers/models/discover"}:
            return self.respond({"models": ["fixture-model"], "route": "fixture", "base_url": "http://127.0.0.1:9/v1"})
        if path == "/api/v1/models":
            return self.respond({"models": ["fixture-model"], "providers": list(s["settings"]["provider"]["providers"].values()), "default_model": "fixture-model", "default_provider_route": "fixture", "model_options": [{"id": "fixture::fixture-model", "label": "Synthetic / fixture-model", "model": "fixture-model", "provider_route": "fixture", "reasoning_tiers": ["low", "medium", "high", "xhigh"], "default_reasoning_effort": "high", "is_default": True}]})
        if path == "/api/v1/system/status":
            return self.respond({"camera_online": False, "show_person_box": True, "camera_frame_available": False, "camera_frame_dark": False, "camera_frame_mean_luma": None, "paths": {"photo": False, "screenshot": False}, "media_roots_ready": {"photos": False, "screenshots": False}, "runtime": {"cwd_name": "fixture"}})
        if path == "/api/v1/system/statistics":
            return self.respond({"cpu_usage": 18.5, "memory_used_gb": 4.0, "memory_total_gb": 16.0, "memory_percent": 25, "disk_free_gb": 220.0, "storage_used_mb": 10, "storage_scan_truncated": False})
        if path == "/api/v1/health/sedentary":
            return self.respond({"status": "active", "duration_seconds": 900, "duration_minutes": 15, "detection_status": "present", "is_sitting": True, "away_duration_seconds": 0, "active_timer": "focus", "threshold_minutes": 60})
        if path == "/api/v1/system/air-quality":
            return self.respond({"aqi": None, "city": "Synthetic fixture", "status": "unavailable", "level": "Unavailable"})
        if path == "/api/v1/system/logs":
            return self.respond({"logs": ["[INFO] Synthetic backend ready", "[WARNING] Test data only; no hardware access"]})
        if path == "/api/v1/usage":
            return self.respond(usage_payload())
        if path == "/api/v1/projects/progress":
            return self.respond({"tasks": {"completed": [{"project": "原生客户端", "task": "实现共享协议", "status": "completed"}], "pending": [{"project": "原生客户端", "task": "验证操作系统集成", "status": "pending"}]}, "commits": [{"hash": "0123456", "date": "2026-01-01", "message": "Synthetic commit"}], "stats": {"total_tasks": 2, "completed_tasks": 1, "completion_rate": 0.5}})
        if path == "/api/v1/finance/balance-sheet":
            return self.respond({"source": {"path": "synthetic.xlsx", "sheet_count": 1, "updated_at": STAMP}, "summary": finance_summary(), "suggestions": ["合成财务建议"], "trend_points": [{"date": "2026-01-01", "balance": 950, "daily_average": 50, "period_spend": 50, "sheet": "Synthetic"}, {"date": "2026-01-02", "balance": 875, "daily_average": 62.5, "period_spend": 75, "sheet": "Synthetic"}], "forecast_points": [], "sheets": [{"name": "Synthetic", "columns": ["项目", "金额"], "rows": [["合成项目", 50]], "row_count": 1, "truncated": False}], "prompt_payload": {}})
        if "purchase-recommendations" in path:
            if path.endswith("/dismiss"):
                s["dismissed"].append({"id": max((item["id"] for item in s["dismissed"]), default=0) + 1, "cache_key": body.get("cache_key", ""), "group_key": body.get("group_key", ""), "created_at": STAMP, "estimated_price": body.get("item", {}).get("estimated_price", ""), **body.get("item", {})})
                return self.respond({"ok": True})
            if "/dismissed" in path:
                if method == "DELETE":
                    s["dismissed"] = [item for item in s["dismissed"] if item["id"] != int(path.rsplit("/", 1)[-1])] if path.rsplit("/", 1)[-1].isdigit() else []
                return self.respond({"ok": True, "items": s["dismissed"], "count": len(s["dismissed"])})
            return self.respond({"status": "ready", "cache_key": "fixture", "recommendation_groups": [{"key": "fixture", "title": "合成推荐", "items": [{"name": "测试用品", "category": "fixture", "estimated_price": "25", "reason": "仅供界面测试", "evidence": "Synthetic evidence", "duplicate_check": "No duplicate", "impulse_risk": "low", "recommendation_mode": "contextual"}]}], "request_config": {"model": "fixture-model", "provider_route": "fixture", "reasoning_effort": "high", "service_tier": None}, "recommendation_count_requested": 3, "recommendation_count_actual": 1})
        if path == "/api/v1/plots/data":
            return self.respond(chart_payload())
        if path == "/api/v1/plots/refresh":
            return self.respond({"status": "ready"})
        if path == "/api/v1/face/analyze":
            s["face_running"] = True
            return self.respond({"message": "Analysis started in background"})
        if path == "/api/v1/face/progress":
            return self.respond({"status": "done" if s["face_running"] else "idle", "percent": 100 if s["face_running"] else 0})
        if path == "/api/v1/face/live":
            return self.respond({"camera_online": False, "window_seconds": 60, "latest_score": None, "latest_datetime": "", "points": []})
        if path == "/api/v1/face/report":
            return self.respond(face_payload())
        if path == "/api/v1/face/export":
            return self.respond(excel_fixture(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if path == "/api/v1/camera/stream":
            frame = b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(JPEG)).encode() + b"\r\n\r\n" + JPEG + b"\r\n"
            return self.respond(frame * 3 + b"--frame--\r\n", content_type="multipart/x-mixed-replace; boundary=frame")
        if path == "/api/v1/media/latest":
            return self.respond({"photo": "/static/photos/synthetic-photo.png", "screenshot": "/static/screenshots/synthetic-screen.png", "photo_name": "synthetic-photo.png", "screenshot_name": "synthetic-screen.png", "latest_media_scan_truncated": False})
        if path == "/api/v1/camera/detection/toggle":
            return self.respond({"show_person_box": False})
        if path == "/api/v1/media/open-folder":
            if self.headers.get("X-Vantage-Intent") != "open-folder":
                return self.respond({"detail": "Missing explicit open-folder intent"}, 403)
            return self.respond({"status": "success"})
        if path.startswith(("/api/v1/media/", "/static/photos/", "/static/screenshots/", "/static/plots/")):
            return self.respond(PNG, content_type="image/png")
        return self.respond({"detail": "Unknown fixture endpoint"}, 404)


def start_fixture(port=0, onboarded=True):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.state = state(onboarded)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--ready-file")
    parser.add_argument("--onboarding-needed", action="store_true")
    args = parser.parse_args()
    server = start_fixture(args.port, not args.onboarding_needed)
    payload = {"base_url": f"http://127.0.0.1:{server.server_address[1]}", "pid": os.getpid()}
    if args.ready_file:
        Path(args.ready_file).write_text(json.dumps(payload), encoding="utf-8")
    print(json.dumps(payload), flush=True)
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    stopped.wait()
    server.shutdown()
    server.server_close()


if __name__ == "__main__":
    main()
