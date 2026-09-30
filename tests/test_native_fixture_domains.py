"""Keep synthetic native UI smoke data faithful to the current domain API.

These tests contact only the in-process synthetic fixture. They do not import
the production application, read user records, invoke models, or open devices.
Nonempty representative data is intentional: an empty page cannot demonstrate
that a native client understands the real payload or renders its contents.
"""

import json
import urllib.error
import urllib.request

import pytest

from src.native.testing.fixture_backend import start_fixture


@pytest.fixture(scope="module")
def fixture_server():
    server = start_fixture()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture
def fixture_request(fixture_server):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(path, method="GET", body=None, raw=False, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            fixture_server + path, data=data, method=method,
            headers={**({"Content-Type": "application/json"} if data else {}), **(headers or {})},
        )
        with opener.open(req, timeout=3) as response:
            payload = response.read()
            return (response.headers.get_content_type(), payload) if raw else json.loads(payload)

    call("/__test__/reset", "POST", {})
    return call


def require_keys(value, keys, source):
    assert isinstance(value, dict), f"{source}: expected an object, got {value!r}"
    missing = set(keys) - value.keys()
    assert not missing, f"Fixture diverges from {source}: missing {sorted(missing)}"


def test_finance_summary_matches_nested_metrics(fixture_request):
    # src/backend/finance_data.py:_build_balance_summary / _find_metric
    payload = fixture_request("/api/v1/finance/balance-sheet")
    summary = payload["summary"]
    require_keys(summary, {"time_cost", "assets", "budget"}, "finance_data._build_balance_summary")
    require_keys(summary["time_cost"], {"daily_average", "monthly_total", "per_minute", "per_day_month", "latest_date", "source"}, "finance_data time_cost")
    require_keys(summary["assets"], {"fixed_assets", "current_assets", "total_assets", "liabilities", "equity", "cash_and_stock"}, "finance_data assets")
    metrics = [metric for metric in summary["assets"].values() if metric is not None]
    assert metrics, "Include a nonempty asset metric so native nested-value rendering is exercised"
    for metric in metrics:
        require_keys(metric, {"value", "field", "sheet"}, "finance_data._find_metric")
        assert isinstance(metric["value"], (int, float))
    require_keys(summary["budget"], {"sheet", "monthly_required", "monthly_optional", "required_count", "optional_count", "source_column"}, "finance_data._build_budget_summary")


def test_finance_rows_and_trend_use_actual_fields(fixture_request):
    payload = fixture_request("/api/v1/finance/balance-sheet")
    assert payload["sheets"], "The fixture must exercise workbook tabs and rows"
    assert payload["source"]["sheet_count"] == len(payload["sheets"])
    for sheet in payload["sheets"]:
        require_keys(sheet, {"name", "columns", "rows", "row_count", "truncated"}, "finance_data._sheet_to_payload")
        assert sheet["rows"] and sheet["columns"]
        assert all(len(row) == len(sheet["columns"]) for row in sheet["rows"])
        assert sheet["row_count"] >= len(sheet["rows"])
    assert payload["trend_points"], "The fixture must exercise the financial trend"
    for point in payload["trend_points"]:
        require_keys(point, {"date", "balance", "daily_average", "period_spend", "sheet"}, "finance_data._build_expense_trend_points")
        assert "expense" not in point, "expense is not the canonical finance trend field"


def test_purchase_recommendations_use_canonical_groups_and_items(fixture_request):
    payload = fixture_request("/api/v1/finance/purchase-recommendations")
    require_keys(payload, {"status", "cache_key", "recommendation_groups", "request_config", "recommendation_count_requested", "recommendation_count_actual"}, "finance_recommendations._build_purchase_recommendations_payload")
    assert "groups" not in payload, "A fixture-only alias masks a real client contract error"
    items = []
    for group in payload["recommendation_groups"]:
        require_keys(group, {"key", "title", "items"}, "purchase recommendation group")
        items.extend(group["items"])
    assert items, "The fixture must render actionable purchase recommendation cards"
    assert payload["recommendation_count_actual"] == len(items)
    for item in items:
        require_keys(item, {"name", "category", "estimated_price", "reason", "evidence", "duplicate_check", "impulse_risk", "recommendation_mode"}, "finance_recommendations._normalize_purchase_item")
        assert isinstance(item["estimated_price"], str)
        assert item["recommendation_mode"] in {"contextual", "random"}


def test_purchase_restore_one_preserves_other_dismissals(fixture_request):
    # UI refreshes the dismissed collection after each action. Restoring one
    # must not clear every item, even if the native screen only shows one row.
    for name in ("Synthetic first", "Synthetic second"):
        response = fixture_request("/api/v1/finance/purchase-recommendations/dismiss", "POST", {
            "cache_key": "fixture", "group_key": "health", "item": {"name": name},
        })
        assert response["ok"] is True
    dismissed = fixture_request("/api/v1/finance/purchase-recommendations/dismissed")
    assert dismissed["count"] == len(dismissed["items"]) == 2
    first, second = dismissed["items"]
    assert first["id"] != second["id"]
    for item in (first, second):
        require_keys(item, {"id", "cache_key", "group_key", "name", "created_at", "estimated_price"}, "finance_recommendations._dismissed_purchase_row_to_item")
    fixture_request(f"/api/v1/finance/purchase-recommendations/dismissed/{first['id']}", "DELETE")
    remaining = fixture_request("/api/v1/finance/purchase-recommendations/dismissed")
    assert [item["id"] for item in remaining["items"]] == [second["id"]]
    fixture_request("/api/v1/finance/purchase-recommendations/dismissed", "DELETE")
    assert fixture_request("/api/v1/finance/purchase-recommendations/dismissed")["items"] == []


def test_usage_summary_matches_recorder_dashboard(fixture_request):
    # src/services/model_call_recorder.py:get_usage_dashboard_snapshot
    payload = fixture_request("/api/v1/usage")
    require_keys(payload, {"summary", "by_source", "by_day", "sessions", "recent_calls", "speed_series"}, "model_call_recorder.get_usage_dashboard_snapshot")
    summary = payload["summary"]
    require_keys(summary, {
        "session_count", "completed_call_count", "failed_call_count", "prompt_tokens", "completion_tokens", "total_tokens",
        "prompt_cache_hit_tokens", "prompt_cache_miss_tokens", "prompt_cache_hit_rate", "completion_reasoning_tokens",
        "total_duration", "average_duration", "average_tokens_per_call", "average_tokens_per_second", "output_tokens_per_second",
        "earliest_call_at", "latest_call_at",
    }, "model_call_recorder summary")
    assert summary["total_tokens"] == summary["prompt_tokens"] + summary["completion_tokens"]
    assert summary["total_duration"] > 0
    assert summary["average_tokens_per_second"] == pytest.approx(summary["total_tokens"] / summary["total_duration"])
    assert summary["output_tokens_per_second"] == pytest.approx(summary["completion_tokens"] / summary["total_duration"])
    recorded = summary["prompt_cache_hit_tokens"] + summary["prompt_cache_miss_tokens"]
    assert summary["prompt_cache_hit_rate"] == pytest.approx(summary["prompt_cache_hit_tokens"] / recorded * 100), "Cache-hit rates use percentage units (0–100), not a 0–1 fraction"


@pytest.mark.parametrize(("collection", "identity"), [
    ("by_source", "source"), ("by_day", "date"), ("sessions", "session_id"),
    ("recent_calls", "call_id"), ("speed_series", "call_id"),
])
def test_usage_has_representative_grouped_rows(fixture_request, collection, identity):
    payload = fixture_request("/api/v1/usage")
    assert payload.get(collection), f"Include a nonempty {collection} fixture to exercise the native table/chart"
    for row in payload[collection]:
        require_keys(row, {identity, "prompt_tokens", "completion_tokens", "total_tokens", "average_tokens_per_second", "output_tokens_per_second"}, f"model_call_recorder {collection}")
        if collection == "speed_series":
            require_keys(row, {"created_at", "model", "duration"}, "model_call_recorder speed_series")


def test_sedentary_fixture_matches_focus_presence_state(fixture_request):
    # src/backend/health.py:get_sedentary_stats active snapshot branch
    payload = fixture_request("/api/v1/health/sedentary")
    require_keys(payload, {"status", "detection_status", "is_sitting", "duration_minutes", "duration_seconds", "away_duration_seconds", "active_timer", "threshold_minutes"}, "health.get_sedentary_stats")
    assert payload["status"] == "active"
    assert payload["detection_status"] in {"present", "absent", "unknown", "stale"}
    assert payload["active_timer"] in {"focus", "away", "none"}
    assert payload["duration_minutes"] == int(payload["duration_seconds"] // 60)
    assert isinstance(payload["is_sitting"], bool)


def test_face_report_contains_real_trend_and_extreme_image_shapes(fixture_request):
    # The public adapter intentionally differs from pipeline's cached report.
    # src/utils/face_report_cache.py:build_face_report_response
    payload = fixture_request("/api/v1/face/report")
    require_keys(payload, {"heaviest", "lightest", "trend_plot", "trend_views"}, "face_report_cache.build_face_report_response")
    for kind in ("heaviest", "lightest"):
        require_keys(payload[kind], {"url", "date", "score"}, f"face report {kind}")
        assert payload[kind]["url"].startswith(("/static/", "/api/v1/media/image?"))
        assert isinstance(payload[kind]["score"], (int, float))
    assert payload["trend_plot"].startswith("/static/plots/")
    for window in ("day", "week", "month", "all"):
        view = payload["trend_views"][window]
        require_keys(view, {"label", "points"}, "face report trend view")
        assert view["points"], "Nonempty trend points are required for visual smoke coverage"
        for point in view["points"]:
            require_keys(point, {"timestamp", "datetime", "score"}, "face_analysis_pipeline._trend_points_from_df")


def test_media_fixture_exercises_backend_relative_image_downloads(fixture_request):
    payload = fixture_request("/api/v1/media/latest")
    require_keys(payload, {"photo_name", "screenshot_name", "latest_media_scan_truncated"}, "media.get_latest_images")
    for key in ("photo", "screenshot"):
        path = payload[key]
        assert isinstance(path, str) and path.startswith("/"), f"Include a synthetic {key} image rather than testing only empty placeholders"
        assert path.startswith("/static/photos/" if key == "photo" else "/static/screenshots/"), "The real latest-media endpoint returns static mount URLs"
        content_type, data = fixture_request(path, raw=True)
        assert content_type.startswith("image/") and len(data) > 8


def test_media_folder_fixture_enforces_local_action_intent(fixture_request):
    with pytest.raises(urllib.error.HTTPError) as failure:
        fixture_request("/api/v1/media/open-folder", "POST", {"type": "photo"})
    assert failure.value.code == 403
    result = fixture_request("/api/v1/media/open-folder", "POST", {"type": "photo"}, headers={"X-Vantage-Intent": "open-folder"})
    assert result["status"] == "success"


def test_face_analysis_fixture_uses_actual_progress_states(fixture_request):
    fixture_request("/api/v1/face/analyze", "POST", {})
    progress = fixture_request("/api/v1/face/progress")
    assert progress["status"] in {"analyzing", "building_report", "done", "running", "idle", "error"}, "analyze_face.py emits analyzing/building_report/done, not processing/completed"
    if progress["percent"] >= 100:
        assert progress["status"] == "done"


def test_chart_fixture_exercises_current_production_data_semantics(fixture_request):
    # Production plot_dashboard.py emits category/time coordinates, null gaps,
    # stack groups, several Y axes, and radar vector data. A simple line alone
    # cannot reveal native renderers that silently collapse those semantics.
    payload = fixture_request("/api/v1/plots/data")
    charts = payload["charts"]
    assert charts
    series = [series for chart in charts for series in chart["option"].get("series", [])]
    assert {"line", "bar", "radar"} <= {series["type"] for series in series}
    assert any(series.get("stack") for series in series), "Include production-style stacked bars"
    assert any(series.get("yAxisIndex", 0) > 0 for series in series), "Include multiple independently scaled Y axes"
    assert any(isinstance(chart["option"].get("yAxis"), list) for chart in charts)
    data = [item for series in series for item in series.get("data", [])]
    assert any(item is None or (isinstance(item, list) and len(item) > 1 and item[1] is None) for item in data), "Include a missing-data gap"
    assert any(isinstance(item, list) and len(item) == 2 and isinstance(item[0], str) for item in data), "Include time-based [date, value] coordinates"
    for chart in charts:
        for entry in chart["option"].get("series", []):
            if entry["type"] == "radar":
                indicators = chart["option"]["radar"]["indicator"]
                assert indicators
                assert all(len(item["value"]) == len(indicators) for item in entry["data"])
