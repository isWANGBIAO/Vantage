"""Running export quality regressions using only synthetic temporary exports."""

import json
from unittest.mock import patch

import pandas as pd
import pytest

from src.scripts import plot
from src.services import plot_dashboard as dashboard


BASE_UTC = pd.Timestamp("2001-01-02T12:00:00Z")
SOURCE_KINDS = ("mi", "zepp-master", "zepp-summary")


def _local_start(day=0):
    return (BASE_UTC + pd.Timedelta(days=day)).tz_convert("Asia/Shanghai").tz_localize(None)


def _write_export(root, kind, records):
    rows = []
    for day, record in enumerate(records):
        started = BASE_UTC + pd.Timedelta(days=day)
        distance = record["distance_m"]
        duration = record["duration_s"]
        # A plausible stored pace must not conceal an invalid total-duration ratio.
        native_pace = record.get("native_pace_min_per_km", 6)
        if kind == "mi":
            payload = {
                "start_time": int(started.timestamp()),
                "distance": distance,
                "duration": duration,
                "avg_pace": native_pace * 60,
            }
            for key in ("avg_hrm", "avg_cadence", "avg_stride"):
                if key in record:
                    payload[key] = record[key]
            rows.append({"Category": "running", "Time": int(started.timestamp()), "Value": json.dumps(payload)})
        elif kind == "zepp-master":
            rows.append({
                "summary_start_local": _local_start(day),
                "distance_km": distance / 1000 if distance is not None else None,
                "duration_seconds": duration,
                "avg_pace_min_per_km": native_pace,
                "detail_heart_rate_avg": record.get("avg_hrm"),
                "detail_cadence_avg": record.get("avg_cadence"),
            })
        else:
            rows.append({
                "type": 1,
                "startTime": started.strftime("%Y-%m-%d %H:%M:%S%z"),
                "distance(m)": distance,
                "sportTime(s)": duration,
                "avgPace(/meter)": native_pace * 60 / 1000,
            })

    if kind == "mi":
        folder = root / "mi_fiteness_data"
        filename = "synthetic_hlth_center_sport_record.csv"
    else:
        folder = root / "zepplift_data" / "SPORT"
        filename = "SPORT_running_master.csv" if kind == "zepp-master" else "SPORT_synthetic.csv"
    folder.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(folder / filename, index=False)


def _load_export(root, kind):
    loader = plot.load_mi_fitness_running_log_frame if kind == "mi" else plot.load_zepp_running_log_frame
    return loader(data_dir=root)


def _assert_source_exclusion(frame, expected_date):
    excluded = frame.attrs.get("source_excluded_rows", [])
    assert len(excluded) == 1
    item = excluded[0]
    assert pd.Timestamp(item["日期"]).normalize() == expected_date.normalize()
    assert isinstance(item["原文"], str) and item["原文"].strip()
    assert item["issues_by_chart"]["running-excluded"]


@pytest.mark.parametrize("kind", SOURCE_KINDS)
@pytest.mark.parametrize(
    ("distance", "duration"),
    [
        (0, 600),
        (-1, 600),
        (None, 600),
        (float("nan"), 600),
        (float("inf"), 600),
        (1000, 0),
        (1000, -1),
        (1000, None),
        (1000, float("nan")),
        (1000, float("inf")),
        (1000, 1801),
        (60, 240),
    ],
    ids=[
        "zero-distance", "negative-distance", "missing-distance", "nan-distance", "infinite-distance",
        "zero-duration", "negative-duration", "missing-duration", "nan-duration", "infinite-duration",
        "just-over-30-min-per-km", "tiny-distance-long-recording",
    ],
)
def test_invalid_export_measurements_are_excluded_with_auditable_reasons(tmp_path, kind, distance, duration):
    _write_export(tmp_path, kind, [{"distance_m": distance, "duration_s": duration}])

    result = _load_export(tmp_path, kind)

    assert result.empty
    _assert_source_exclusion(result, _local_start())


@pytest.mark.parametrize("kind", SOURCE_KINDS)
def test_source_filter_keeps_sprints_slow_activity_and_exact_pace_boundary(tmp_path, kind):
    _write_export(tmp_path, kind, [
        {"distance_m": 80, "duration_s": 16, "native_pace_min_per_km": 16 / 60 / 0.08},
        {"distance_m": 2000, "duration_s": 1800, "native_pace_min_per_km": 15},
        {"distance_m": 1000, "duration_s": 1800, "native_pace_min_per_km": 30},
        {"distance_m": 1000, "duration_s": 1801},
    ])

    result = _load_export(tmp_path, kind)

    assert result["日期"].tolist() == [_local_start(day) for day in range(3)]
    assert "跑步0.08公里" in result.iloc[0]["运动"]
    assert "配速15分00" in result.iloc[1]["运动"]
    assert "配速30分00" in result.iloc[2]["运动"]
    _assert_source_exclusion(result, _local_start(3))


def test_export_text_displays_native_stride_in_centimetres_with_available_metrics():
    text = plot._build_running_export_text(
        "Synthetic", distance_km=4, duration_seconds=1440, pace_min_per_km=6,
        heart_rate_bpm=145, cadence_spm=172, stride_cm=87,
    )

    assert "心率145" in text
    assert "步频172" in text
    assert "步幅87厘米" in text


def test_export_text_does_not_invent_missing_heart_rate_cadence_or_stride():
    text = plot._build_running_export_text(
        "Synthetic", distance_km=4, duration_seconds=1440, pace_min_per_km=6,
        heart_rate_bpm=None, cadence_spm=None, stride_cm=None,
    )

    assert "心率" not in text
    assert "步频" not in text
    assert "步幅" not in text


def test_mi_native_stride_survives_loading_and_metric_parsing(tmp_path):
    _write_export(tmp_path, "mi", [{
        "distance_m": 4000, "duration_s": 1440,
        "avg_hrm": 145, "avg_cadence": 172, "avg_stride": 87,
    }])

    frame = _load_export(tmp_path, "mi")
    metrics = plot.compute_running_metrics(frame)

    assert "心率145" in frame.iloc[0]["运动"]
    assert "步频172" in frame.iloc[0]["运动"]
    assert "步幅87厘米" in frame.iloc[0]["运动"]
    assert metrics.iloc[0]["stride_m"] == pytest.approx(0.87)
    assert metrics.iloc[0]["cadence_spm"] == 172


@pytest.mark.parametrize("kind", SOURCE_KINDS)
def test_missing_native_metrics_remain_absent_from_export_text(tmp_path, kind):
    _write_export(tmp_path, kind, [{"distance_m": 4000, "duration_s": 1440}])

    text = _load_export(tmp_path, kind).iloc[0]["运动"]

    assert "心率" not in text
    assert "步频" not in text
    assert "步幅" not in text


@pytest.mark.parametrize("kind", ("zepp-master", "zepp-summary"))
def test_zepp_missing_summary_metrics_use_matching_reasonable_detail_samples(tmp_path, kind):
    _write_export(tmp_path, kind, [{"distance_m": 4000, "duration_s": 1440}])
    details = tmp_path / "zepplift_data" / "SPORT" / "details"
    details.mkdir()
    detail_name = f"Workout--{_local_start():%Y-%m-%d--%H-%M-%S}.csv"
    pd.DataFrame({
        "heart_rate": [0, -5, 120, 160, 400, None],
        "cadence": [0, -5, 150, 170, 500, None],
    }).to_csv(details / detail_name, index=False)
    # A different activity's file must not supply values to this activity.
    other_name = f"Workout--{_local_start(1):%Y-%m-%d--%H-%M-%S}.csv"
    pd.DataFrame({"heart_rate": [200], "cadence": [200]}).to_csv(details / other_name, index=False)

    frame = _load_export(tmp_path, kind)
    text = frame.iloc[0]["运动"]

    assert "心率140" in text
    assert "步频160" in text
    assert "步频320" not in text
    assert "心率200" not in text
    assert "步幅" not in text


def test_zepp_master_native_summary_metrics_are_not_doubled(tmp_path):
    _write_export(tmp_path, "zepp-master", [{
        "distance_m": 4000, "duration_s": 1440, "avg_hrm": 142, "avg_cadence": 162,
    }])

    text = _load_export(tmp_path, "zepp-master").iloc[0]["运动"]

    assert "心率142" in text
    assert "步频162" in text
    assert "步频324" not in text
    assert "步幅" not in text


def _source_exclusion(day, marker):
    return {
        "日期": _local_start(day),
        "原文": marker,
        "issues_by_chart": {"running-excluded": ["合成导出记录的距离或时长无效"]},
    }


def _running_frame(day=0, empty=False):
    if empty:
        return pd.DataFrame(columns=["日期", "运动"])
    return pd.DataFrame({
        "日期": [_local_start(day)],
        "运动": ["Synthetic 跑步4.00公里，用时24分，配速6分00，心率140，步频160，步幅87厘米"],
    })


@pytest.mark.parametrize(("mi_empty", "zepp_empty"), [(False, False), (True, False), (False, True), (True, True)])
def test_combining_app_sources_retains_exclusions_even_from_empty_sources(mi_empty, zepp_empty):
    mi = _running_frame(day=2, empty=mi_empty)
    zepp = _running_frame(day=0, empty=zepp_empty)
    mi.attrs["source_excluded_rows"] = [_source_exclusion(3, "synthetic-mi-exclusion")]
    zepp.attrs["source_excluded_rows"] = [_source_exclusion(1, "synthetic-zepp-exclusion")]

    with patch.object(plot, "load_mi_fitness_running_log_frame", return_value=mi), patch.object(
        plot, "load_zepp_running_log_frame", return_value=zepp,
    ):
        result = plot.load_app_running_log_frame()

    assert len(result) == int(not mi_empty) + int(not zepp_empty)
    excluded = result.attrs.get("source_excluded_rows", [])
    assert {item["原文"] for item in excluded} == {"synthetic-mi-exclusion", "synthetic-zepp-exclusion"}


@pytest.mark.parametrize(
    ("app_empty", "manual_day", "expected_source"),
    [
        (False, None, "app_exports"),
        (False, -1, "app_exports"),
        (False, 2, "app_exports_plus_time_xlsx"),
        (True, 2, "time_xlsx"),
        (True, None, "time_xlsx"),
    ],
    ids=["app-only", "manual-before-app", "manual-tail", "manual-fallback", "all-excluded"],
)
def test_preferred_metrics_preserve_source_exclusion_warnings_in_every_return_branch(app_empty, manual_day, expected_source):
    app = _running_frame(empty=app_empty)
    marker = "synthetic-source-exclusion"
    app.attrs["source_excluded_rows"] = [_source_exclusion(1, marker)]
    manual = _running_frame(day=manual_day) if manual_day is not None else _running_frame(empty=True)

    with patch.object(plot, "load_app_running_log_frame", return_value=app):
        result = plot.compute_preferred_running_metrics(manual)

    assert result.attrs["running_source"] == expected_source
    excluded = result.attrs.get("excluded_rows", [])
    assert any(item["原文"] == marker and item["issues_by_chart"]["running-excluded"] for item in excluded)


def test_preferred_metrics_keep_source_and_existing_manual_chart_exclusions_together():
    app = _running_frame()
    marker = "synthetic-source-exclusion"
    app.attrs["source_excluded_rows"] = [_source_exclusion(1, marker)]
    manual_text = "Synthetic 跑步0.40公里，用时2分，配速5分00，心率145"
    manual = pd.DataFrame({"日期": [_local_start(2)], "运动": [manual_text]})

    with patch.object(plot, "load_app_running_log_frame", return_value=app):
        result = plot.compute_preferred_running_metrics(manual)

    assert result.attrs["running_source"] == "app_exports_plus_time_xlsx"
    excluded = result.attrs.get("excluded_rows", [])
    assert {item["原文"] for item in excluded} == {marker, manual_text}
    assert all(item["issues_by_chart"]["running-excluded"] for item in excluded)


def test_walking_gait_metrics_do_not_turn_a_walk_into_a_run():
    assert not plot._looks_like_running_text("散步4公里，用时60分，步频100，步幅70，心率85")
    assert not plot._looks_like_running_text("步行3公里，配速12分00，心率90")
    assert plot._looks_like_running_text("走路热身；跑3公里，用时20分，步频170")


def _preferred_app_metrics(app):
    with patch.object(plot, "load_app_running_log_frame", return_value=app):
        return plot.compute_preferred_running_metrics(_running_frame(empty=True))


def test_app_cadence_is_displayed_without_inventing_a_missing_native_stride():
    app = pd.DataFrame({
        "日期": [_local_start()],
        "运动": ["Zepp 跑步4.00公里，用时24分，配速6分00，心率140，步频160步/分"],
    })

    metrics = _preferred_app_metrics(app)
    chart = dashboard._build_running_form_dashboard_chart(metrics)

    assert metrics.iloc[0]["cadence_spm"] == 160
    assert pd.isna(metrics.iloc[0]["stride_m"])
    assert len(metrics.attrs["dashboard_frames"]["running-form"]) == 1
    cadence = next(series for series in chart["option"]["series"] if "Cadence" in series["name"])
    assert cadence["data"] == [[_local_start().strftime("%Y-%m-%d"), 160]]
    for series in chart["option"]["series"]:
        if "Stride" in series["name"]:
            assert all(point[1] is None for point in series["data"])


def test_app_stride_chart_has_a_gap_where_the_native_stride_is_missing():
    app = pd.DataFrame({
        "日期": [_local_start(), _local_start(1)],
        "运动": [
            "Mi Fitness 跑步4.00公里，用时24分，配速6分00，心率140，步频160步/分，步幅87厘米",
            "Mi Fitness 跑步4.00公里，用时24分，配速6分00，心率140，步频160步/分",
        ],
    })

    metrics = _preferred_app_metrics(app)
    chart = dashboard._build_running_form_dashboard_chart(metrics)

    assert metrics.iloc[0]["stride_m"] == pytest.approx(0.87)
    assert pd.isna(metrics.iloc[1]["stride_m"])
    stride = next(series for series in chart["option"]["series"] if "Stride" in series["name"])
    assert stride["data"] == [[_local_start().strftime("%Y-%m-%d"), 0.87], [_local_start(1).strftime("%Y-%m-%d"), None]]
    assert stride.get("connectNulls", False) is False
    cadence = next(series for series in chart["option"]["series"] if "Cadence" in series["name"])
    assert cadence["data"] == [[_local_start().strftime("%Y-%m-%d"), 160], [_local_start(1).strftime("%Y-%m-%d"), 160]]


def test_app_native_stride_does_not_invent_a_missing_native_cadence():
    app = pd.DataFrame({
        "日期": [_local_start()],
        "运动": ["Mi Fitness 跑步4.00公里，用时24分，配速6分00，心率140，步幅87厘米"],
    })

    metrics = _preferred_app_metrics(app)

    assert pd.isna(metrics.iloc[0]["cadence_spm"])
    assert metrics.iloc[0]["stride_m"] == pytest.approx(0.87)


@pytest.mark.parametrize(
    ("manual_text", "metric", "expected"),
    [
        ("跑步4.00公里，用时24分，配速6分00，心率140，步频160", "stride_m", 4000 / 24 / 160),
        ("跑步4.00公里，用时24分，配速6分00，心率140，步幅100厘米", "cadence_spm", 4000 / 24),
    ],
    ids=["manual-stride-inference", "manual-cadence-inference"],
)
def test_manual_records_keep_the_existing_optional_gait_inference(manual_text, metric, expected):
    manual = pd.DataFrame({"日期": [_local_start()], "运动": [manual_text]})

    metrics = plot.compute_running_metrics(manual)

    assert metrics.iloc[0][metric] == pytest.approx(expected)

