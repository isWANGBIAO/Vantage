"""Synthetic boundary tests for source snapshots, prompt records and calendars."""

import json
import os
import re
import shutil
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from src.utils.data_loader import DataLoader


def construct(tmp_path, frame, budget=None):
    prompt = tmp_path / "Prompt_Personal_Info.md"
    prompt.write_text("Synthetic instructions", encoding="utf-8")
    source = tmp_path / "Time.xlsx"
    source.write_bytes(b"placeholder")
    with patch.object(DataLoader, "load_excel_data", return_value=frame), patch.object(DataLoader, "resolve_data_path", side_effect=lambda filename, **_: tmp_path / filename), patch.object(DataLoader, "get_balance_sheet_data_summary", return_value=""), patch.object(DataLoader, "get_future_planned_rows", return_value="Future: none"), patch.object(DataLoader, "_build_calendar_info", return_value="Synthetic calendar"):
        return DataLoader.construct_prompt(prompt, source, start_date="earliest", prompt_token_budget=budget)


def block(text, title):
    prefix = f"## {title}\n\n```json\n"
    return json.loads(text.split(prefix, 1)[1].split("\n```", 1)[0])


def test_snapshot_names_do_not_collide_when_clock_is_identical(tmp_path):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 1, 0, 0, 0, 123456)

    first = tmp_path / "first.xlsx"
    second = tmp_path / "second.xlsx"
    first.write_bytes(b"first synthetic source")
    second.write_bytes(b"second synthetic source")
    snapshots = []
    try:
        with patch("src.utils.data_loader.datetime", Clock):
            snapshots.append(DataLoader._safe_copy_excel(first))
            snapshots.append(DataLoader._safe_copy_excel(second))
        assert snapshots[0] != snapshots[1]
        assert snapshots[0].read_bytes() == first.read_bytes()
        snapshots[0].unlink()
        assert snapshots[1].read_bytes() == second.read_bytes()
    finally:
        for snapshot in snapshots:
            snapshot.unlink(missing_ok=True)


def test_snapshot_janitor_cannot_remove_an_in_progress_copy_with_old_source_mtime(tmp_path):
    source = tmp_path / "old-source.xlsx"
    source.write_bytes(b"synthetic old workbook")
    os.utime(source, (1, 1))
    copy_bytes = shutil.copyfile
    removed = []

    def copy_then_janitor(src, dst, **kwargs):
        copy_bytes(src, dst)
        shutil.copystat(src, dst)
        removed.append(DataLoader.cleanup_stale_excel_snapshots())

    def powershell_copy(arguments, **kwargs):
        destination = re.search(r"-Destination '([^']+)'", arguments[-1])[1]
        copy_then_janitor(source, destination)

    snapshot = None
    try:
        with patch("src.utils.data_loader.tempfile.gettempdir", return_value=str(tmp_path)), patch("src.utils.data_loader.subprocess.run", side_effect=powershell_copy), patch("shutil.copyfile", side_effect=copy_then_janitor):
            snapshot = DataLoader._safe_copy_excel(source)
        assert removed == [0]
        assert snapshot.read_bytes() == source.read_bytes()
    finally:
        if snapshot is not None:
            snapshot.unlink(missing_ok=True)


def test_single_selected_prompt_row_is_still_in_the_actual_data_blocks(tmp_path):
    today = datetime.now().date()
    text = construct(tmp_path, pd.DataFrame({"日期": [pd.Timestamp(today)], "metric": [42]}))
    history = block(text, "Time Series Data (JSON)")
    current = block(text, "Current Day")
    assert history["included_row_count"] == 1
    assert history["rows"] + [current["current_day"]] == [[str(today), 42]]


def test_omitted_old_long_value_cannot_reenter_through_latest_values(tmp_path):
    today = datetime.now().date()
    frame = pd.DataFrame({"日期": [pd.Timestamp(today - timedelta(days=2)), pd.Timestamp(today - timedelta(days=1)), pd.Timestamp(today)], "note": ["long " * 6000, None, None], "metric": [1, 2, 3]})
    with pytest.raises(ValueError, match="budget"):
        construct(tmp_path, frame, budget=1500)


def test_nonfinite_workbook_numbers_produce_strict_json_and_nulls():
    sheets = {"Assets": pd.DataFrame({"Name": ["A", "B", "C"], "Amount": [float("inf"), float("-inf"), 0]})}
    payload = DataLoader.build_balance_sheet_prompt_payload_from_sheets(sheets)
    json.dumps(payload, allow_nan=False)
    assert [row[1] for row in payload["sheets"][0]["rows"]] == [None, None, 0]


def test_excel_mixed_iso_date_formats_load_without_a_columnwide_format_guess(tmp_path):
    source = tmp_path / "mixed.xlsx"
    pd.DataFrame({"日期": ["2026-01-01", "2026-01-02T13:14:15"], "metric": [1, 2]}).to_excel(source, index=False)
    frame = DataLoader.load_excel_data(source)
    assert frame["日期"].dt.strftime("%Y-%m-%d").tolist() == ["2026-01-01", "2026-01-02"]


@pytest.mark.parametrize("text,expected", [("30分", 0.5), ("7.5小时", 7.5), ("7小时30分", 7.5), ("-2小时", None)])
def test_duration_parser_does_not_drop_decimal_sign_or_minute_only_input(text, expected):
    assert DataLoader._duration_text_to_hours(text) == expected


@pytest.mark.parametrize("today,eve", [(date(2026, 1, 28), date(2026, 2, 16)), (date(2024, 1, 20), date(2024, 2, 9))])
def test_new_year_eve_is_exactly_one_day_before_next_lunar_new_year(today, eve):
    pytest.importorskip("zhdate")
    festivals = DataLoader._get_upcoming_festivals(today, days=30)
    assert [(name, day) for name, day, _ in festivals if name == "除夕"] == [("除夕", eve)]
