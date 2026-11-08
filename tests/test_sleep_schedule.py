"""Synthetic calendar data only; no private workbook or installed app is read."""

from datetime import date, datetime, timedelta
import json

import pandas as pd
import pytest

from src.services.sleep_schedule import build_sleep_schedule_payload
from src.services import plot_dashboard


def observation(day, bedtime=25.0, wake=33.0):
    return {"date": day, "bedtime_hour": bedtime, "wake_hour": wake}


def week(start, *, bedtime=25.0, wake=33.0, count=7):
    start = date.fromisoformat(start)
    return [observation(start + timedelta(days=i), bedtime, wake) for i in range(count)]


def test_complete_calendar_week_preserves_daily_observations_and_weekly_median():
    records = week("2026-11-02")
    records[0].update(bedtime_hour=27.0, wake_hour=35.0)
    result = build_sleep_schedule_payload(records)
    assert result["version"] == 1
    assert result["latest_date"] == "2026-11-08"
    assert result["duplicate_day_count"] == 0
    assert result["daily"][0] == observation("2026-11-02", 27.0, 35.0)
    assert result["weeks"] == [{
        "start": "2026-11-02", "end": "2026-11-08", "record_count": 7,
        "bedtime_hour": 25.0, "wake_hour": 33.0, "partial": False,
    }]


def test_even_sample_count_uses_middle_pair_not_average_of_all_values():
    records = [observation(f"2026-11-0{i + 2}", bed, bed + 8) for i, bed in enumerate([24, 25, 25, 31])]
    result = build_sleep_schedule_payload(records)
    assert result["weeks"][0]["bedtime_hour"] == 25
    assert result["weeks"][0]["wake_hour"] == 33
    assert result["weeks"][0]["record_count"] == 4


def test_cross_year_monday_week_is_not_split_at_month_or_year_boundary():
    result = build_sleep_schedule_payload(week("2025-12-29", count=10))
    assert [(q["start"], q["end"], q["record_count"], q["partial"]) for q in result["weeks"]] == [
        ("2025-12-29", "2026-01-04", 7, False),
        ("2026-01-05", "2026-01-07", 3, True),
    ]
    assert result["weeks"][1]["bedtime_hour"] is None
    assert result["weeks"][1]["wake_hour"] is None


def test_first_and_last_partially_observed_calendar_weeks_are_flagged():
    result = build_sleep_schedule_payload(week("2026-10-29", count=10))
    assert result["weeks"][0] == {
        "start": "2026-10-26", "end": "2026-11-01", "record_count": 4,
        "bedtime_hour": 25.0, "wake_hour": 33.0, "partial": True,
    }
    assert result["weeks"][1]["start"] == "2026-11-02"
    assert result["weeks"][1]["end"] == "2026-11-07"
    assert result["weeks"][1]["record_count"] == 6
    assert result["weeks"][1]["partial"] is True


def test_sunday_is_current_week_end_and_monday_starts_a_new_week():
    result = build_sleep_schedule_payload([observation("2026-11-01"), observation("2026-11-02")])
    assert [q["start"] for q in result["weeks"]] == ["2026-10-26", "2026-11-02"]
    assert result["weeks"][0]["end"] == "2026-11-01"
    assert result["weeks"][1]["end"] == "2026-11-02"


def test_missing_days_are_null_and_missing_calendar_weeks_remain_explicit_gaps():
    records = week("2026-10-12") + week("2026-10-26")
    result = build_sleep_schedule_payload(records)
    assert len(result["daily"]) == 21
    assert result["daily"][7] == observation("2026-10-19", None, None)
    assert result["weeks"][1] == {
        "start": "2026-10-19", "end": "2026-10-25", "record_count": 0,
        "bedtime_hour": None, "wake_hour": None, "partial": False,
    }
    assert all(row["bedtime_hour"] is None for row in result["daily"][7:14])


def test_three_distinct_days_do_not_become_a_trustworthy_week():
    result = build_sleep_schedule_payload([
        observation("2026-11-02"), observation("2026-11-04"), observation("2026-11-08"),
    ])
    assert result["weeks"][0]["record_count"] == 3
    assert result["weeks"][0]["bedtime_hour"] is None
    assert result["weeks"][0]["wake_hour"] is None


def test_duplicate_dates_use_last_valid_input_and_cannot_satisfy_minimum_days():
    records = [
        observation("2026-11-02", 24, 32),
        observation("2026-11-03", 25, 33),
        observation("2026-11-02", 26, 34),
        observation("2026-11-04", 25, 33),
        observation("2026-11-02", 27, 35),
        observation("2026-11-02", None, None),
    ]
    result = build_sleep_schedule_payload(records)
    assert result["duplicate_day_count"] == 1
    assert result["daily"][0]["bedtime_hour"] == 27
    assert result["weeks"][0]["record_count"] == 3
    assert result["weeks"][0]["bedtime_hour"] is None


def test_unordered_input_is_sorted_by_date_without_changing_last_valid_duplicate_order():
    result = build_sleep_schedule_payload([
        observation("2026-11-05"), observation("2026-11-03"),
        observation("2026-11-02"), observation("2026-11-04"),
    ])
    assert [row["date"] for row in result["daily"]] == [f"2026-11-0{i}" for i in range(2, 6)]
    assert result["weeks"][0]["bedtime_hour"] == 25


def test_cross_midnight_unwrapped_hours_do_not_average_to_noon():
    records = [observation(f"2026-11-0{i + 2}", bed, 32) for i, bed in enumerate([23.5, 24.5, 23.5, 24.5])]
    result = build_sleep_schedule_payload(records)
    assert result["weeks"][0]["bedtime_hour"] == 24
    assert result["weeks"][0]["wake_hour"] == 32


def test_later_earlier_and_unchanged_weeks_keep_the_true_direction_and_minute_precision():
    result = build_sleep_schedule_payload(
        week("2026-10-05", bedtime=25, wake=33)
        + week("2026-10-12", bedtime=25.5, wake=33.25)
        + week("2026-10-19", bedtime=24.75, wake=32.5)
        + week("2026-10-26", bedtime=24.75, wake=32.5)
    )
    weeks = result["weeks"]
    assert [(q["bedtime_hour"] - weeks[0]["bedtime_hour"]) * 60 for q in weeks] == [0, 30, -15, -15]
    assert [(q["wake_hour"] - weeks[0]["wake_hour"]) * 60 for q in weeks] == [0, 15, -30, -30]


@pytest.mark.parametrize("day", [None, "", "not-a-date", "2026-02-30", "2026-11-02junk", 20261102, pd.NaT])
def test_invalid_dates_are_ignored_without_creating_phantom_days(day):
    result = build_sleep_schedule_payload([observation(day)])
    assert result["latest_date"] is None
    assert result["daily"] == []
    assert result["weeks"] == []


@pytest.mark.parametrize("bed,wake", [
    (None, 33), (25, None), (True, 33), (25, False),
    (float("nan"), 33), (25, float("inf")), (25, float("-inf")),
    ("25", 33), (25, "33"), (-1, 33), (36, 40), (25, 24), (25, 25), (25, 44),
])
def test_invalid_or_non_primary_numeric_values_do_not_create_zero_or_nonfinite_output(bed, wake):
    result = build_sleep_schedule_payload([observation("2026-11-02", bed, wake)])
    assert result["daily"] == []
    json.dumps(result, allow_nan=False)


def test_empty_and_non_mapping_input_are_safe_and_input_is_not_mutated():
    records = [None, "invalid", observation("2026-11-02")]
    before = repr(records)
    result = build_sleep_schedule_payload(records)
    assert repr(records) == before
    assert len(result["daily"]) == 1
    assert build_sleep_schedule_payload([])["weeks"] == []


def test_date_and_datetime_inputs_are_calendar_dates_without_timezone_conversion():
    result = build_sleep_schedule_payload([
        observation(date(2026, 11, 2)), observation(datetime(2026, 11, 3, 23, 59)),
        observation(pd.Timestamp("2026-11-04")), observation("2026-11-05"),
    ])
    assert [row["date"] for row in result["daily"]] == [f"2026-11-0{i}" for i in range(2, 6)]


def test_pathological_multi_millennial_range_is_rejected_not_silently_truncated():
    with pytest.raises(ValueError, match="100-year"):
        build_sleep_schedule_payload([observation("0001-01-01"), observation("9999-12-31")])


def test_final_partial_week_at_date_max_does_not_overflow():
    result = build_sleep_schedule_payload([observation(date.max)])
    assert result["daily"][0]["date"] == "9999-12-31"
    assert result["weeks"][0]["partial"] is True


def test_chart_integration_adds_metadata_without_changing_legacy_series_or_summary():
    frame = pd.DataFrame({
        "日期": pd.date_range("2026-11-02", periods=7),
        "起床时间": ["23.30-7.30"] * 7,
    })
    chart = plot_dashboard._build_sleep_schedule_dashboard_chart(frame)
    assert chart["sleep_schedule"]["version"] == 1
    assert chart["sleep_schedule"]["weeks"][0]["bedtime_hour"] == 23.5
    assert chart["sleep_schedule"]["weeks"][0]["wake_hour"] == 31.5
    assert [series["name"] for series in chart["option"]["series"]] == ["入睡时间", "起床时间"]
    assert chart["option"]["series"][0]["data"][0] == ["2026-11-02", 23.5]
    assert {item["label"]: item["value"] for item in chart["summary"]}["样本天数"] == "7"
    json.dumps(chart, allow_nan=False)


def test_chart_integration_duplicate_order_is_stable_after_sorting():
    frame = pd.DataFrame({
        "日期": pd.to_datetime(["2026-11-03", "2026-11-02", "2026-11-02", "2026-11-04", "2026-11-05"]),
        "起床时间": ["1.00-9.00", "1.00-9.00", "2.00-10.00", "1.00-9.00", "1.00-9.00"],
    })
    chart = plot_dashboard._build_sleep_schedule_dashboard_chart(frame)
    assert chart["sleep_schedule"]["daily"][0]["bedtime_hour"] == 26
    assert chart["sleep_schedule"]["duplicate_day_count"] == 1
    assert chart["sleep_schedule"]["weeks"][0]["record_count"] == 4
