"""Missing optional running measurements are normal; all fixtures are synthetic."""

from copy import deepcopy
from unittest.mock import patch

import pandas as pd
import pytest

from src.services import plot_dashboard as dashboard


def _metrics(heart_rates, recorded=None):
    normalized = [value if value is not None and 40 <= value <= 230 else None for value in heart_rates]
    return pd.DataFrame({
        "日期": pd.date_range("2001-01-02", periods=len(heart_rates)),
        "心率": heart_rates if recorded is None else recorded,
        "pace_min_per_km": [6.0] * len(heart_rates),
        "pace_mmss": ["6:00"] * len(heart_rates),
        "distance_km": [4.0] * len(heart_rates),
        "duration_min": [24.0] * len(heart_rates),
        "duration_mmss": ["24:00"] * len(heart_rates),
        "heart_rate_bpm": normalized,
        "cadence_spm": [160.0] * len(heart_rates),
        "stride_m": [0.87] * len(heart_rates),
        "HRC_m_per_beat": [4000 / 24 / value if value else None for value in normalized],
    })


def _warning_row(issues_by_chart, text="合成跑步4公里，用时24分，心率无"):
    return {"日期": pd.Timestamp("2001-01-02"), "原文": text, "issues_by_chart": issues_by_chart}


@pytest.mark.parametrize(
    "issues_by_chart",
    [
        {"running": ["缺少 心率"], "running-hrc": ["缺少 心率", "缺少 HRC"]},
        {"running": ["心率异常值 0"], "running-hrc": ["心率异常值 0", "缺少 HRC"]},
        {"running": ["心率异常值 0.0bpm"], "running-hrc": ["缺少HRC"]},
        {"running-form": ["缺少 步频", "缺少 步幅"]},
        {"running-form": ["步频异常值 0", "步幅异常值 0"]},
        {"running": "缺少 心率", "running-hrc": ["  缺少   hrc  "]},
        {"running": [], "running-form": [], "running-hrc": []},
    ],
    ids=["missing-hr", "zero-hr", "zero-hr-with-unit", "missing-gait", "zero-gait", "legacy-spacing", "empty-groups"],
)
def test_legacy_optional_measurement_issues_do_not_produce_warnings(issues_by_chart):
    rows = [_warning_row(issues_by_chart)]
    original = deepcopy(rows)

    assert dashboard._build_running_data_warnings(rows) == []
    assert rows == original


def test_filtering_missing_heart_rate_preserves_actual_distance_and_duration_issues():
    rows = [_warning_row({
        "running": ["缺少 心率", "缺少 距离"],
        "running-form": ["缺少 步频", "缺少 步幅", "缺少 用时"],
        "running-hrc": ["缺少 心率", "缺少 HRC", "缺少 用时/配速"],
        "running-excluded": ["里程必须大于0"],
    })]

    warnings = dashboard._build_running_data_warnings(rows)

    assert len(warnings) == 4
    details = "\n".join(detail for warning in warnings for detail in warning["details"])
    assert "缺少 距离" in details
    assert "缺少 用时" in details
    assert "里程必须大于0" in details
    assert "缺少 心率" not in details
    assert "缺少 HRC" not in details
    assert "缺少 步频" not in details
    assert "缺少 步幅" not in details
    assert all("Time.xlsx「记录」页的运动原文" in warning["message"] for warning in warnings)
    assert all("导出文件" not in warning["message"] for warning in warnings)


@pytest.mark.parametrize("heart_rate", [30, 300])
def test_explicit_nonzero_heart_rate_anomalies_still_produce_warnings(heart_rate):
    issue = f"心率异常值 {heart_rate}"
    warnings = dashboard._build_running_data_warnings([_warning_row({
        "running": [issue], "running-hrc": [issue, "缺少 HRC"],
    })])

    assert {warning["id"] for warning in warnings} == {"running-missing-main", "running-missing-hrc"}
    assert all(issue in warning["details"][0] for warning in warnings)
    assert all("缺少 HRC" not in warning["details"][0] for warning in warnings)


def test_optional_gaps_do_not_inflate_the_warning_details_count():
    missing = [_warning_row({"running": ["缺少 心率"]}) for _ in range(10)]
    invalid = [_warning_row({"running": ["缺少 距离"]}) for _ in range(8)]

    warning = dashboard._build_running_data_warnings(missing + invalid)[0]

    assert len(warning["details"]) == 7
    assert warning["details"][-1] == "其余 2 条异常记录已省略，请核对 Time.xlsx「记录」页的运动原文。"


def test_all_missing_heart_rates_leave_running_and_gait_visible_and_hrc_normally_empty():
    metrics = _metrics([None, 0, None], recorded=[None, 0, "无"])
    # An older upstream response may provide an empty HRC-specific view.
    metrics.attrs["dashboard_frames"] = {"running": metrics.copy(), "running-hrc": metrics.iloc[:0].copy()}

    running = dashboard._build_running_dashboard_chart(metrics)
    form = dashboard._build_running_form_dashboard_chart(metrics)
    hrc = dashboard._build_running_hrc_dashboard_chart(metrics)

    assert running["empty"] is False
    assert form["empty"] is False
    assert any("距离" in series["name"] for series in running["option"]["series"])
    assert {series["name"] for series in form["option"]["series"]} == {
        "用时 Duration (min)", "步频 Cadence (spm)", "步幅 Stride (m)",
    }
    assert hrc["empty"] is True
    assert hrc["error"] is None
    assert "暂无心率数据" in hrc["message"]


def test_hrc_skips_missing_and_zero_heart_rates_but_keeps_recorded_samples():
    metrics = _metrics([150, 0, None, 160])
    # Reproduce a legacy numeric zero rather than assuming upstream normalized it.
    metrics.loc[1, ["heart_rate_bpm", "HRC_m_per_beat"]] = 0

    chart = dashboard._build_running_hrc_dashboard_chart(metrics)

    assert chart["empty"] is False
    points = chart["option"]["series"][0]["data"]
    assert [point[0] for point in points] == ["2001-01-02", "2001-01-05"]
    assert all(point[1] > 0 for point in points)


def test_recorded_invalid_heart_rate_is_not_relabelled_as_normal_missing_data():
    chart = dashboard._safe_chart(
        "running-hrc", "HRC", "synthetic",
        lambda: dashboard._build_running_hrc_dashboard_chart(_metrics([300])),
    )

    assert chart["empty"] is True
    assert chart["error"]
    assert "暂无心率数据" not in chart.get("message", "")


def test_source_read_failure_still_uses_the_error_state():
    def unreadable_source():
        raise OSError("synthetic Time source unavailable")

    chart = dashboard._safe_chart("running-hrc", "HRC", "synthetic", unreadable_source)

    assert chart["empty"] is True
    assert chart["error"] == "synthetic Time source unavailable"


def test_dashboard_suppresses_legacy_missing_hr_warnings_without_hiding_running_charts():
    metrics = _metrics([None, 0])
    metrics.attrs["invalid_rows"] = [_warning_row({
        "running": ["缺少 心率"], "running-hrc": ["缺少 心率", "缺少 HRC"],
    })]
    time = pd.DataFrame({
        "日期": pd.date_range("2001-01-02", periods=2),
        "睡眠时间": ["7小时", "8小时"], "手机屏幕\n使用时间": ["2小时", "3小时"],
    })
    with patch.object(dashboard.plot_module, "load_time_data", return_value=time), patch.object(
        dashboard.plot_module, "compute_preferred_running_metrics", return_value=metrics,
    ), patch.object(dashboard, "_build_balance_dashboard_chart", return_value={}):
        payload = dashboard.build_plot_dashboard_data()

    charts = {chart["id"]: chart for chart in payload["charts"] if chart}
    assert not any(warning["id"].startswith("running-") for warning in payload["warnings"])
    assert charts["running"]["empty"] is False
    assert charts["running-form"]["empty"] is False
    assert charts["running-hrc"]["empty"] is True
    assert charts["running-hrc"]["error"] is None


def test_form_summary_counts_calculated_strides_among_the_displayed_runs():
    metrics = _metrics([None, 150, None, 160])
    metrics["stride_source"] = ["calculated", "recorded", "calculated", "missing"]
    metrics.loc[3, "stride_m"] = None

    chart = dashboard._build_running_form_dashboard_chart(metrics)

    summary = {item["label"]: item["value"] for item in chart["summary"]}
    assert summary["计算/估算步幅"] == "2次"
    assert "平均步幅" in summary


def test_form_summary_does_not_claim_recorded_or_hidden_strides_were_calculated():
    metrics = _metrics([150, 160])
    metrics["stride_source"] = ["recorded", "calculated"]
    metrics.attrs["dashboard_frames"] = {"running-form": metrics.iloc[:1].copy()}

    chart = dashboard._build_running_form_dashboard_chart(metrics)

    assert "计算/估算步幅" not in {item["label"] for item in chart["summary"]}
