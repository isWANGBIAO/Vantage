"""Real parser/chart boundary regressions; all records and exports synthetic."""

import ast
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src.scripts import plot
from src.services import plot_dashboard as dashboard


def test_time_suffix_means_are_invariant_to_workbook_row_order():
    frame = pd.DataFrame({"日期": pd.date_range("2026-01-01", periods=3), "睡眠时间": ["6小时", "8小时", "10小时"], "手机屏幕\n使用时间": ["2小时"] * 3})
    result = dashboard._compute_time_trend_payload(frame)
    expected = dict(zip(result["sleep_df"]["日期"], result["y1"]))
    for order in [frame.iloc[::-1], frame.iloc[[1, 0, 2]]]:
        result = dashboard._compute_time_trend_payload(order)
        assert dict(zip(result["sleep_df"]["日期"], result["y1"])) == expected


def test_undated_body_measurements_do_not_become_latest_or_enter_averages():
    frame = pd.DataFrame({"日期": [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02"), pd.NaT], "体重": [60, 65, 70], "体脂率": [18, 20, 22]})
    chart = dashboard._build_weight_bodyfat_dashboard_chart(frame)
    summary = {item["label"]: item["value"] for item in chart["summary"]}
    assert summary["最新体重"] == "65.0 kg"
    assert summary["平均体重"] == "62.5 kg"
    assert summary["最新体脂率"] == "20.0 %"
    assert all(point[0] is not None for series in chart["option"]["series"] for point in series["data"])


def test_missing_middle_heart_rate_remains_a_line_gap():
    frame = pd.DataFrame({"日期": pd.date_range("2026-01-01", periods=3), "pace_min_per_km": [5, 5, 5], "distance_km": [5, 5, 5], "duration_min": [25] * 3, "heart_rate_bpm": [140, None, 150]})
    chart = dashboard._build_running_dashboard_chart(frame)
    heart = next(series for series in chart["option"]["series"] if "Heart Rate" in series["name"])
    assert heart["data"] == [["2026-01-01", 140], ["2026-01-02", None], ["2026-01-03", 150]]
    assert heart.get("connectNulls", False) is False


def test_bad_date_in_warning_cannot_destroy_five_valid_time_charts():
    frame = pd.DataFrame({"日期": [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02"), "pending date"], "睡眠时间": ["7小时", "8小时", "27小时"], "手机屏幕\n使用时间": ["2小时"] * 3, "体重": [60, 62, None], "体脂率": [18, 19, None]})
    with patch.object(plot, "load_time_data", return_value=frame), patch.object(plot, "compute_preferred_running_metrics", side_effect=ValueError("Synthetic unavailable")), patch.object(dashboard, "_build_balance_dashboard_chart", return_value={}):
        payload = dashboard.build_plot_dashboard_data()
    charts = {chart["id"]: chart for chart in payload["charts"] if chart}
    assert all(not charts[name].get("empty") for name in dashboard.TIME_WARNING_CHART_IDS)
    assert "pending date" in str(payload["warnings"])


def test_mi_export_discovery_ignores_filename_ids_and_isolates_nonobject_json(tmp_path, capsys):
    folder = tmp_path / "mi_fiteness_data"
    folder.mkdir()
    rows = [{"Category": "running", "Time": 1770000000, "Value": json.dumps(value)} for value in [[], 1, True, None]]
    valid = {"start_time": 1770000000, "distance": 5000, "duration": 1800, "avg_hrm": 140}
    rows.append({"Category": "running", "Time": 1770000000, "Value": json.dumps(valid)})
    pd.DataFrame(rows).to_csv(folder / "20261022_123_MiFitness_hlth_center_sport_record.csv", index=False)
    result = plot.load_mi_fitness_running_log_frame(data_dir=tmp_path)
    assert len(result) == 1
    assert "心率140" in result.iloc[0]["运动"]
    diagnostics = capsys.readouterr().out
    assert "20261022_123_MiFitness_hlth_center_sport_record.csv:2" in diagnostics
    assert "expected JSON object" in diagnostics


def test_legacy_named_mi_export_nonobject_rows_cannot_abort_good_rows(tmp_path):
    folder = tmp_path / "mi_fiteness_data"
    folder.mkdir()
    valid = {"start_time": 1770000000, "distance": 5000, "duration": 1800}
    pd.DataFrame({"Category": ["running", "running"], "Time": [1770000000] * 2, "Value": ["[]", json.dumps(valid)]}).to_csv(folder / "20260416_881116692_MiFitness_hlth_center_sport_record.csv", index=False)
    assert len(plot.load_mi_fitness_running_log_frame(data_dir=tmp_path)) == 1


def test_zepp_export_discovery_ignores_historical_numeric_filename(tmp_path):
    folder = tmp_path / "zepplift_data" / "SPORT"
    folder.mkdir(parents=True)
    pd.DataFrame({"type": [1], "startTime": [1770000000000], "distance(m)": [5000], "sportTime(s)": [1800], "calories(kcal)": [300]}).to_csv(folder / "SPORT_9999999999999.csv", index=False)
    assert len(plot.load_zepp_running_log_frame(data_dir=tmp_path)) == 1


def test_multiple_export_copies_are_deduplicated_and_bad_csv_isolated(tmp_path):
    folder = tmp_path / "mi_fiteness_data"
    folder.mkdir()
    valid = {"start_time": 1770000000, "distance": 5000, "duration": 1800}
    rows = pd.DataFrame({"Category": ["running"], "Time": [1770000000], "Value": [json.dumps(valid)]})
    for prefix in ["20261021", "20261022"]:
        rows.to_csv(folder / f"{prefix}_123_MiFitness_hlth_center_sport_record.csv", index=False)
    (folder / "20261023_broken_hlth_center_sport_record.csv").write_bytes(b"\xff\xff")
    assert len(plot.load_mi_fitness_running_log_frame(data_dir=tmp_path)) == 1


def test_chart_duration_parsing_uses_the_same_strict_data_loader_contract():
    assert plot.time_to_hour("30分") == 0.5
    assert plot.time_to_hour("7.5小时") == 7.5
    assert plot.time_to_hour("-2小时") is None


def test_undated_measurements_emit_a_visible_dashboard_warning():
    frame = pd.DataFrame({"日期": ["2026-01-01", None], "体重": [60, 70], "体脂率": [18, 22], "睡眠时间": ["7小时"] * 2, "手机屏幕\n使用时间": ["2小时"] * 2})
    with patch.object(plot, "load_time_data", return_value=frame), patch.object(plot, "compute_preferred_running_metrics", side_effect=ValueError("Synthetic unavailable")), patch.object(dashboard, "_build_balance_dashboard_chart", return_value={}):
        payload = dashboard.build_plot_dashboard_data()
    warning = next(item for item in payload["warnings"] if item["id"] == "undated-body-measurements")
    assert warning["chart_ids"] == ["weight-bodyfat"]
    assert "1" in warning["message"]
    assert "跳过" in warning["message"]


def test_food_next_day_association_joins_calendar_days_not_exploded_rows():
    # Execute the actual pure statistic function without importing optional LLM
    # SDK/tokenizer packages or invoking any classifier/provider.
    source = Path(__file__).resolve().parents[1] / "src" / "AI_Prediction" / "analyzer.py"
    module = ast.parse(source.read_text(encoding="utf-8"))
    function = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "statistical_analysis")
    namespace = {"pd": pd}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    for foods in [["A", "B", "C", "D"], ["B", "A", "D", "C"]]:
        frame = pd.DataFrame({"日期": ["2026-01-01"] * 2 + ["2026-01-02"] * 2, "食物餐厅": foods, "拉稀次数": [0, 0, 1, 1]})
        with patch.object(pd.DataFrame, "to_csv"):
            result = namespace["statistical_analysis"](frame).set_index("食物餐厅")
        assert result.loc["A", "当日及次日拉稀次数"] == 1
        assert result.loc["B", "当日及次日拉稀次数"] == 1
