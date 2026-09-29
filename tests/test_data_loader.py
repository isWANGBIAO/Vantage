import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src.utils.data_loader import DataLoader


def extract_json_block(content, heading):
    marker = f"## {heading}\n\n```json\n"
    start = content.index(marker) + len(marker)
    end = content.index("\n```", start)
    return json.loads(content[start:end])


def extract_current_day_block(content):
    """当天那行与派生汇总现在独立成段，见 construct_prompt。"""
    return extract_json_block(content, "Current Day")


class DataLoaderFuturePlansTests(unittest.TestCase):
    def test_construct_prompt_truncates_time_rows_by_explicit_token_budget(self):
        today = datetime.now().date()
        df = pd.DataFrame(
            [
                {"日期": pd.Timestamp(today - timedelta(days=2)), "metric": "old" * 20},
                {"日期": pd.Timestamp(today - timedelta(days=1)), "metric": "recent" * 20},
                {"日期": pd.Timestamp(today), "metric": "latest" * 20},
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            prompt_path = temp_path / "Prompt_Personal_Info.md"
            excel_path = temp_path / "Time.xlsx"
            prompt_path.write_text("personal info", encoding="utf-8")
            excel_path.write_text("placeholder", encoding="utf-8")

            with patch.object(DataLoader, "load_excel_data", return_value=df), patch.object(
                DataLoader, "get_balance_sheet_data_summary", return_value=""
            ), patch.object(
                DataLoader, "get_future_planned_rows", return_value="## Future Planned Items\n\n- none\n"
            ), patch.object(
                DataLoader,
                "resolve_data_path",
                side_effect=lambda filename, **_: temp_path / filename,
            ):
                combined = DataLoader.construct_prompt(
                    prompt_path,
                    excel_path,
                    days=90,
                    prompt_token_budget=80,
                )

        payload = extract_json_block(combined, "Time Series Data (JSON)")
        self.assertTrue(payload["truncated"])
        self.assertLessEqual(payload["estimated_tokens"], 80)
        self.assertGreater(payload["omitted_row_count"], 0)

    def test_get_future_planned_rows_only_includes_future_non_empty_rows(self):
        today = datetime.now().date()
        df = pd.DataFrame(
            [
                {
                    "日期": pd.Timestamp(today - timedelta(days=1)),
                    "周几": "周五",
                    "工作": "昨天的事",
                    "运动": None,
                },
                {
                    "日期": pd.Timestamp(today + timedelta(days=1)),
                    "周几": "周日",
                    "工作": None,
                    "运动": None,
                },
                {
                    "日期": pd.Timestamp(today + timedelta(days=2)),
                    "周几": "周一",
                    "工作": "去宁波",
                    "运动": None,
                },
                {
                    "日期": pd.Timestamp(today + timedelta(days=3)),
                    "周几": "周二",
                    "工作": "博士论文开题答辩",
                    "运动": "恢复跑步",
                },
            ]
        )

        with patch.object(DataLoader, "load_excel_data", return_value=df):
            future_rows = DataLoader.get_future_planned_rows(Path("Time.xlsx"))

        self.assertIn("去宁波", future_rows)
        self.assertIn("博士论文开题答辩", future_rows)
        self.assertIn("恢复跑步", future_rows)
        self.assertNotIn("昨天的事", future_rows)
        self.assertNotIn(str(today + timedelta(days=1)), future_rows)

    def test_construct_prompt_appends_future_plans_summary(self):
        today = datetime.now().date()
        df = pd.DataFrame(
            [
                {
                    "日期": pd.Timestamp(today - timedelta(days=1)),
                    "体重": 63.5,
                    "工作": "写代码",
                },
                {
                    "日期": pd.Timestamp(today),
                    "体重": 63.0,
                    "工作": "继续写代码",
                },
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            prompt_path = temp_path / "Prompt_Personal_Info.md"
            excel_path = temp_path / "Time.xlsx"
            prompt_path.write_text("personal info", encoding="utf-8")
            excel_path.write_text("placeholder", encoding="utf-8")

            def fake_resolve_data_path(filename, user_home=None, onedrive_env=None):
                return temp_path / filename

            with patch.object(DataLoader, "load_excel_data", return_value=df), patch.object(
                DataLoader,
                "resolve_data_path",
                side_effect=fake_resolve_data_path,
            ), patch.object(
                DataLoader,
                "get_future_planned_rows",
                return_value="## Future Planned Items\n\n- 2026-06-16（周二）: 工作: 去宁波\n",
            ):
                combined = DataLoader.construct_prompt(prompt_path, excel_path, days=90)

        self.assertIn("# Future Planned Items", combined)
        self.assertIn("2026-06-16（周二）: 工作: 去宁波", combined)

    def test_construct_prompt_keeps_markdown_sections_and_embeds_compact_json_timeseries(self):
        today = datetime.now().date()
        df = pd.DataFrame(
            [
                {
                    "\u65e5\u671f": pd.Timestamp(today - timedelta(days=1)),
                    "Days": 100,
                    "\u5468\u51e0": "\u5468\u516d",
                    "\u4f53\u91cd": 63.5,
                    "\u5de5\u4f5c": "\u5199\u4ee3\u7801",
                },
                {
                    "\u65e5\u671f": pd.Timestamp(today),
                    "Days": 101,
                    "\u5468\u51e0": "\u5468\u65e5",
                    "\u4f53\u91cd": 63.0,
                    "\u5de5\u4f5c": "\u7ee7\u7eed\u5199\u4ee3\u7801",
                },
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            prompt_path = temp_path / "Prompt_Personal_Info.md"
            excel_path = temp_path / "Time.xlsx"
            prompt_path.write_text("personal info", encoding="utf-8")
            excel_path.write_text("placeholder", encoding="utf-8")
            (temp_path / "Prompt_Project_Management.md").write_text("project context", encoding="utf-8")
            (temp_path / "Prompt_Goals.md").write_text("goal text", encoding="utf-8")

            def fake_resolve_data_path(filename, user_home=None, onedrive_env=None):
                return temp_path / filename

            with patch.object(DataLoader, "load_excel_data", return_value=df), patch.object(
                DataLoader,
                "resolve_data_path",
                side_effect=fake_resolve_data_path,
            ), patch.object(
                DataLoader,
                "get_future_planned_rows",
                return_value="## Future Planned Items\n\n- 2026-06-16: lab visit\n",
            ):
                combined = DataLoader.construct_prompt(prompt_path, excel_path, days=90)

        self.assertIn("personal info", combined)
        self.assertIn("## Time Series Data (JSON)", combined)
        self.assertIn("# Future Planned Items", combined)
        self.assertIn("# Project Management Context", combined)
        self.assertIn("project context", combined)
        self.assertIn("# Goals", combined)
        self.assertIn("goal text", combined)

        marker = "## Time Series Data (JSON)\n\n```json\n"
        start = combined.index(marker) + len(marker)
        end = combined.index("\n```", start)
        payload = json.loads(combined[start:end])

        self.assertEqual(payload["days_requested"], 90)
        self.assertEqual(
            payload["date_range"],
            {
                "start": str(today - timedelta(days=90)),
                "end": str(today),
            },
        )
        self.assertEqual(payload["total_days"], 91)
        self.assertEqual(payload["days_with_data"], 2)
        self.assertEqual(
            payload["column_meta"],
            {
                "\u4f53\u91cd": {"unit": "kg"},
            },
        )
        self.assertEqual(
            payload["columns"],
            ["date", "Days", "\u5468\u51e0", "\u4f53\u91cd", "\u5de5\u4f5c"],
        )
        # 稳定块只含历史行；当天那行与派生汇总在 Current Day 段。
        self.assertEqual(
            payload["rows"],
            [
                [str(today - timedelta(days=1)), 100, "\u5468\u516d", 63.5, "\u5199\u4ee3\u7801"],
            ],
        )
        current_day = extract_current_day_block(combined)
        self.assertEqual(
            current_day["current_day"],
            [str(today), 101, "\u5468\u65e5", 63.0, "\u7ee7\u7eed\u5199\u4ee3\u7801"],
        )
        self.assertEqual(
            current_day["non_null_counts"],
            {
                "Days": 2,
                "\u5468\u51e0": 2,
                "\u4f53\u91cd": 2,
                "\u5de5\u4f5c": 2,
            },
        )
        self.assertEqual(
            current_day["latest_values"],
            {
                "Days": {"date": str(today), "value": 101},
                "\u5468\u51e0": {"date": str(today), "value": "\u5468\u65e5"},
                "\u4f53\u91cd": {"date": str(today), "value": 63.0},
                "\u5de5\u4f5c": {"date": str(today), "value": "\u7ee7\u7eed\u5199\u4ee3\u7801"},
            },
        )

    def test_construct_prompt_can_use_fixed_start_date_for_append_only_cache_prefix(self):
        today = datetime.now().date()
        df = pd.DataFrame(
            [
                {
                    "\u65e5\u671f": pd.Timestamp("2023-12-31"),
                    "metric": "before fixed start",
                },
                {
                    "\u65e5\u671f": pd.Timestamp("2024-01-01"),
                    "metric": "stable first row",
                },
                {
                    "\u65e5\u671f": pd.Timestamp(today),
                    "metric": "latest row",
                },
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            prompt_path = temp_path / "Prompt_Personal_Info.md"
            excel_path = temp_path / "Time.xlsx"
            prompt_path.write_text("personal info", encoding="utf-8")
            excel_path.write_text("placeholder", encoding="utf-8")

            def fake_resolve_data_path(filename, user_home=None, onedrive_env=None):
                return temp_path / filename

            with patch.object(DataLoader, "load_excel_data", return_value=df), patch.object(
                DataLoader,
                "resolve_data_path",
                side_effect=fake_resolve_data_path,
            ), patch.object(
                DataLoader,
                "get_future_planned_rows",
                return_value="## Future Planned Items\n\n- none\n",
            ):
                combined = DataLoader.construct_prompt(
                    prompt_path,
                    excel_path,
                    days=1,
                    start_date="2024-01-01",
                )

        marker = "## Time Series Data (JSON)\n\n```json\n"
        start = combined.index(marker) + len(marker)
        end = combined.index("\n```", start)
        payload = json.loads(combined[start:end])

        self.assertEqual(payload["date_range"]["start"], "2024-01-01")
        self.assertEqual(payload["rows"][0], ["2024-01-01", "stable first row"])
        self.assertEqual(extract_current_day_block(combined)["current_day"], [str(today), "latest row"])
        self.assertNotIn("before fixed start", json.dumps(payload, ensure_ascii=False))

    def test_construct_prompt_with_earliest_start_date_includes_full_history(self):
        today = datetime.now().date()
        df = pd.DataFrame(
            [
                {
                    "\u65e5\u671f": pd.Timestamp("2020-05-03"),
                    "metric": "first recorded row",
                },
                {
                    "\u65e5\u671f": pd.Timestamp(today),
                    "metric": "latest row",
                },
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            prompt_path = temp_path / "Prompt_Personal_Info.md"
            excel_path = temp_path / "Time.xlsx"
            prompt_path.write_text("personal info", encoding="utf-8")
            excel_path.write_text("placeholder", encoding="utf-8")

            with patch.object(DataLoader, "load_excel_data", return_value=df), patch.object(
                DataLoader,
                "get_future_planned_rows",
                return_value="## Future Planned Items\n\n- none\n",
            ), patch.object(
                DataLoader,
                "get_balance_sheet_data_summary",
                return_value="",
            ):
                combined = DataLoader.construct_prompt(
                    prompt_path,
                    excel_path,
                    days=90,
                    start_date="earliest",
                )

        payload = extract_json_block(combined, "Time Series Data (JSON)")
        self.assertEqual(payload["window_strategy"], "full_history")
        self.assertEqual(payload["date_range"]["start"], "2020-05-03")
        self.assertEqual(payload["rows"][0], ["2020-05-03", "first recorded row"])
        # 当天那行已拆到 Current Day 段，稳定块只到昨天为止。
        self.assertEqual(extract_current_day_block(combined)["current_day"], [str(today), "latest row"])
        self.assertNotEqual(payload["rows"][-1][0], str(today))

    def test_construct_prompt_places_time_json_rows_before_editable_prompts(self):
        today = datetime.now().date()
        df = pd.DataFrame(
            [
                {
                    "\u65e5\u671f": pd.Timestamp(today - timedelta(days=2)),
                    "metric": 1,
                },
                {
                    "\u65e5\u671f": pd.Timestamp(today - timedelta(days=1)),
                    "metric": 2,
                },
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            prompt_path = temp_path / "Prompt_Personal_Info.md"
            excel_path = temp_path / "Time.xlsx"
            prompt_path.write_text("editable personal prompt", encoding="utf-8")
            excel_path.write_text("placeholder", encoding="utf-8")
            (temp_path / "Prompt_Project_Management.md").write_text("editable project prompt", encoding="utf-8")

            def fake_resolve_data_path(filename, user_home=None, onedrive_env=None):
                return temp_path / filename

            with patch.object(DataLoader, "load_excel_data", return_value=df), patch.object(
                DataLoader,
                "resolve_data_path",
                side_effect=fake_resolve_data_path,
            ), patch.object(
                DataLoader,
                "get_future_planned_rows",
                return_value="## Future Planned Items\n\n- none\n",
            ):
                combined = DataLoader.construct_prompt(prompt_path, excel_path, days=90)

        time_marker = "## Time Series Data (JSON)"
        self.assertLess(combined.index(time_marker), combined.index("editable personal prompt"))
        self.assertLess(combined.index(time_marker), combined.index("editable project prompt"))

        json_start = combined.index("```json\n", combined.index(time_marker)) + len("```json\n")
        json_end = combined.index("\n```", json_start)
        first_key_order = list(json.loads(combined[json_start:json_end]).keys())[:2]
        self.assertEqual(first_key_order, ["columns", "rows"])

    def test_construct_prompt_places_balance_sheet_json_after_time_json(self):
        today = datetime.now().date()
        time_df = pd.DataFrame(
            [
                {
                    "\u65e5\u671f": pd.Timestamp(today),
                    "metric": 1,
                },
            ]
        )
        balance_sheets = {
            "Assets": pd.DataFrame(
                [
                    {"Account": "Cash", "Amount": 1000},
                    {"Account": None, "Amount": None},
                    {"Account": "Stock", "Amount": 2000},
                ]
            ),
            "Budget": pd.DataFrame(
                [
                    {"Category": "Food", "Monthly": 1500},
                    {"Category": "Transport", "Monthly": 300},
                ]
            ),
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            prompt_path = temp_path / "Prompt_Personal_Info.md"
            excel_path = temp_path / "Time.xlsx"
            balance_path = temp_path / "Balance Sheet.xlsx"
            prompt_path.write_text("editable personal prompt", encoding="utf-8")
            excel_path.write_text("placeholder", encoding="utf-8")
            balance_path.write_text("placeholder", encoding="utf-8")

            def fake_resolve_data_path(filename, user_home=None, onedrive_env=None):
                return temp_path / filename

            with patch.object(DataLoader, "load_excel_data", return_value=time_df), patch.object(
                DataLoader,
                "load_excel_sheets",
                return_value=balance_sheets,
            ), patch.object(
                DataLoader,
                "resolve_data_path",
                side_effect=fake_resolve_data_path,
            ), patch.object(
                DataLoader,
                "get_future_planned_rows",
                return_value="## Future Planned Items\n\n- none\n",
            ):
                combined = DataLoader.construct_prompt(prompt_path, excel_path, days=90)

        self.assertLess(
            combined.index("## Time Series Data (JSON)"),
            combined.index("## Balance Sheet Data (JSON)"),
        )
        self.assertLess(
            combined.index("## Balance Sheet Data (JSON)"),
            combined.index("## Future Planned Items"),
        )
        self.assertLess(combined.index("## Balance Sheet Data (JSON)"), combined.index("editable personal prompt"))

        payload = extract_json_block(combined, "Balance Sheet Data (JSON)")
        self.assertEqual(payload["file_name"], "Balance Sheet.xlsx")
        self.assertEqual(payload["sheet_count"], 2)
        self.assertEqual(payload["total_rows"], 4)
        self.assertEqual(
            payload["sheets"],
            [
                {
                    "name": "Assets",
                    "columns": ["Account", "Amount"],
                    "rows": [["Cash", 1000], ["Stock", 2000]],
                    "row_count": 2,
                    "non_null_counts": {"Account": 2, "Amount": 2},
                },
                {
                    "name": "Budget",
                    "columns": ["Category", "Monthly"],
                    "rows": [["Food", 1500], ["Transport", 300]],
                    "row_count": 2,
                    "non_null_counts": {"Category": 2, "Monthly": 2},
                },
            ],
        )

    def test_construct_prompt_can_limit_balance_sheet_rows_per_sheet(self):
        today = datetime.now().date()
        time_df = pd.DataFrame(
            [
                {
                    "\u65e5\u671f": pd.Timestamp(today),
                    "metric": 1,
                },
            ]
        )
        balance_sheets = {
            "Assets": pd.DataFrame(
                [
                    {"Account": "Cash", "Amount": 1000},
                    {"Account": "Brokerage", "Amount": 2000},
                    {"Account": "Savings", "Amount": 3000},
                ]
            ),
            "Budget": pd.DataFrame(
                [
                    {"Category": "Food", "Monthly": 1500},
                    {"Category": "Transport", "Monthly": 300},
                ]
            ),
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            prompt_path = temp_path / "Prompt_Personal_Info.md"
            excel_path = temp_path / "Time.xlsx"
            balance_path = temp_path / "Balance Sheet.xlsx"
            prompt_path.write_text("editable personal prompt", encoding="utf-8")
            excel_path.write_text("placeholder", encoding="utf-8")
            balance_path.write_text("placeholder", encoding="utf-8")

            def fake_resolve_data_path(filename, user_home=None, onedrive_env=None):
                return temp_path / filename

            with patch.object(DataLoader, "load_excel_data", return_value=time_df), patch.object(
                DataLoader,
                "load_excel_sheets",
                return_value=balance_sheets,
            ), patch.object(
                DataLoader,
                "resolve_data_path",
                side_effect=fake_resolve_data_path,
            ), patch.object(
                DataLoader,
                "get_future_planned_rows",
                return_value="## Future Planned Items\n\n- none\n",
            ):
                combined = DataLoader.construct_prompt(
                    prompt_path,
                    excel_path,
                    days=90,
                    balance_sheet_row_limit_per_sheet=1,
                )

        payload = extract_json_block(combined, "Balance Sheet Data (JSON)")

        self.assertEqual(payload["total_rows"], 5)
        self.assertEqual(payload["total_included_rows"], 2)
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["sheets"][0]["row_count"], 3)
        self.assertEqual(payload["sheets"][0]["included_row_count"], 1)
        self.assertEqual(payload["sheets"][0]["omitted_row_count"], 2)
        self.assertEqual(payload["sheets"][0]["rows"], [["Savings", 3000]])
        self.assertEqual(payload["sheets"][1]["rows"], [["Transport", 300]])

    def test_balance_sheet_prompt_payload_drops_wide_empty_columns(self):
        sheets = {
            "Asset": pd.DataFrame(
                {
                    "Date": [pd.Timestamp("2026-06-01"), pd.Timestamp("2026-06-02")],
                    "Name": ["Laptop", "Monitor"],
                    "Amount": [8000, 1200],
                    "Empty Header": [None, None],
                    "Column 16384": [None, None],
                }
            )
        }

        payload = DataLoader.build_balance_sheet_prompt_payload_from_sheets(sheets)

        self.assertEqual(payload["total_rows"], 2)
        self.assertEqual(payload["sheets"][0]["columns"], ["Date", "Name", "Amount"])
        self.assertEqual(
            payload["sheets"][0]["rows"],
            [["2026-06-01", "Laptop", 8000], ["2026-06-02", "Monitor", 1200]],
        )
        self.assertEqual(payload["sheets"][0]["non_null_counts"], {"Date": 2, "Name": 2, "Amount": 2})

    def test_construct_prompt_keeps_runtime_clock_out_of_the_timeseries_json(self):
        """分钟精度的时间戳不能待在可缓存的数据块内部。"""
        real_datetime = datetime
        today = real_datetime.now().date()
        df = pd.DataFrame(
            [
                {"\u65e5\u671f": pd.Timestamp(today - timedelta(days=2)), "metric": 1},
                {"\u65e5\u671f": pd.Timestamp(today - timedelta(days=1)), "metric": 2},
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            prompt_path = temp_path / "Prompt_Personal_Info.md"
            excel_path = temp_path / "Time.xlsx"
            balance_path = temp_path / "Balance Sheet.xlsx"
            prompt_path.write_text("editable personal prompt", encoding="utf-8")
            excel_path.write_text("placeholder", encoding="utf-8")
            balance_path.write_text("placeholder", encoding="utf-8")

            def fake_resolve_data_path(filename, user_home=None, onedrive_env=None):
                return temp_path / filename

            def build():
                with patch.object(DataLoader, "load_excel_data", return_value=df), patch.object(
                    DataLoader,
                    "load_excel_sheets",
                    return_value={"Assets": pd.DataFrame([{"Account": "Cash", "Amount": 1000}])},
                ), patch.object(
                    DataLoader,
                    "resolve_data_path",
                    side_effect=fake_resolve_data_path,
                ), patch.object(
                    DataLoader,
                    "get_future_planned_rows",
                    return_value="## Future Planned Items\n\n- none\n",
                ):
                    return DataLoader.construct_prompt(prompt_path, excel_path, days=90)

            combined = build()

            # 时钟前进不得改动可缓存的数据块。
            noon = real_datetime(2026, 5, 1, 12, 0)
            with patch.object(DataLoader, "_build_calendar_info", return_value="calendar"), patch(
                "src.utils.data_loader.datetime", wraps=real_datetime
            ) as fake_datetime:
                fake_datetime.now.return_value = noon
                first = build()
                fake_datetime.now.return_value = noon + timedelta(minutes=1)
                second = build()

        time_payload = extract_json_block(combined, "Time Series Data (JSON)")

        # 时间戳不能放在承载时间序列的 payload 里。
        self.assertNotIn("current_time", time_payload)

        # 但它仍要送达模型，且必须排在昂贵数据与可编辑 prompt 之后，
        # 这样分钟跳变只作废这一小段，不会连带作废它们。
        self.assertIn("## Runtime Context", combined)
        runtime_index = combined.index("## Runtime Context")
        balance_end = combined.index("\n```", combined.index("## Balance Sheet Data (JSON)"))
        self.assertGreater(runtime_index, balance_end)
        self.assertGreater(runtime_index, combined.index("editable personal prompt"))
        self.assertGreater(runtime_index, combined.index("## Current Day"))
        # 排在最后：时钟之后不再有稳定内容。
        self.assertEqual(combined[runtime_index:].count("## "), 1)

        first_json = extract_json_block(first, "Time Series Data (JSON)")
        second_json = extract_json_block(second, "Time Series Data (JSON)")
        self.assertEqual(first_json, second_json)

        # 整串 prompt 确实变了（时间戳在起作用），但只是数据之后的那一小段。
        self.assertNotEqual(
            DataLoader.build_prompt_cache_metadata(first)["full_prompt_hash"],
            DataLoader.build_prompt_cache_metadata(second)["full_prompt_hash"],
        )
        prefix_end = first.index("## Runtime Context")
        self.assertEqual(first[:prefix_end], second[:prefix_end])

    def test_construct_prompt_keeps_the_mutable_day_out_of_the_timeseries_json(self):
        """当天那行整天都在变，不能和 89 行历史数据挤在同一个 JSON 里。"""
        today = datetime.now().date()
        frame = pd.DataFrame(
            [
                {"\u65e5\u671f": pd.Timestamp(today - timedelta(days=2)), "metric": 1},
                {"\u65e5\u671f": pd.Timestamp(today - timedelta(days=1)), "metric": 2},
                {"\u65e5\u671f": pd.Timestamp(today), "metric": 3},
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            prompt_path = temp_path / "Prompt_Personal_Info.md"
            excel_path = temp_path / "Time.xlsx"
            prompt_path.write_text("editable personal prompt", encoding="utf-8")
            excel_path.write_text("placeholder", encoding="utf-8")

            def fake_resolve_data_path(filename, user_home=None, onedrive_env=None):
                return temp_path / filename

            def build(df):
                with patch.object(DataLoader, "load_excel_data", return_value=df), patch.object(
                    DataLoader,
                    "resolve_data_path",
                    side_effect=fake_resolve_data_path,
                ), patch.object(
                    DataLoader,
                    "get_future_planned_rows",
                    return_value="## Future Planned Items\n\n- none\n",
                ):
                    return DataLoader.construct_prompt(prompt_path, excel_path, days=90)

            baseline = build(frame)
            payload = extract_json_block(baseline, "Time Series Data (JSON)")
            rows = payload["rows"]

            # 稳定块只保留到昨天。
            self.assertEqual([row[0] for row in rows], [
                str(today - timedelta(days=2)),
                str(today - timedelta(days=1)),
            ])
            self.assertNotIn("latest_values", payload)
            self.assertNotIn("non_null_counts", payload)

            # 当天那行与派生汇总仍要送达模型，且排在稳定块之后。
            self.assertIn(str(today), baseline)
            self.assertIn("## Current Day", baseline)
            self.assertGreater(baseline.index("## Current Day"), baseline.index("## Time Series Data (JSON)"))

            # 改当天那一格：稳定块必须逐字节不变。
            edited = frame.copy()
            edited.loc[edited["\u65e5\u671f"] == pd.Timestamp(today), "metric"] = 99
            after = build(edited)

            self.assertEqual(
                extract_json_block(baseline, "Time Series Data (JSON)"),
                extract_json_block(after, "Time Series Data (JSON)"),
            )
            stable_prefix = baseline[:baseline.index("## Current Day")]
            self.assertEqual(stable_prefix, after[:after.index("## Current Day")])
            self.assertNotEqual(baseline, after)

            # 改历史行则必须仍然改变稳定块。
            edited_history = frame.copy()
            edited_history.loc[
                edited_history["\u65e5\u671f"] == pd.Timestamp(today - timedelta(days=1)), "metric"
            ] = 77
            self.assertNotEqual(
                extract_json_block(baseline, "Time Series Data (JSON)"),
                extract_json_block(build(edited_history), "Time Series Data (JSON)"),
            )

    def test_prompt_cache_metadata_ignores_editable_prompt_changes_for_time_rows(self):
        first_prompt = (
            "## Time Series Data (JSON)\n\n```json\n"
            '{"columns":["date","metric"],"rows":[["2026-04-26",1],["2026-04-27",2]],"latest_values":{"metric":2}}\n'
            "```\n\neditable prompt A"
        )
        second_prompt = first_prompt.replace("editable prompt A", "editable prompt B")

        first_metadata = DataLoader.build_prompt_cache_metadata(first_prompt)
        second_metadata = DataLoader.build_prompt_cache_metadata(second_prompt)

        self.assertEqual(first_metadata["time_json_rows_hash"], second_metadata["time_json_rows_hash"])
        self.assertNotEqual(first_metadata["full_prompt_hash"], second_metadata["full_prompt_hash"])

    def test_prompt_cache_metadata_records_balance_sheet_hash(self):
        prompt = (
            "## Time Series Data (JSON)\n\n```json\n"
            '{"columns":["date","metric"],"rows":[["2026-04-26",1],["2026-04-27",2]]}\n'
            "```\n\n"
            "## Balance Sheet Data (JSON)\n\n```json\n"
            '{"file_name":"Balance Sheet.xlsx","sheet_count":1,"total_rows":1,'
            '"sheets":[{"name":"Assets","columns":["Account","Amount"],"rows":[["Cash",1000]],'
            '"row_count":1,"non_null_counts":{"Account":1,"Amount":1}}]}\n'
            "```\n\neditable prompt"
        )

        metadata = DataLoader.build_prompt_cache_metadata(prompt)

        self.assertEqual(metadata["cache_layout"], "system_time_json_balance_json_then_prompts")
        self.assertIn("balance_sheet_full_hash", metadata)
        self.assertEqual(metadata["balance_sheet_sheet_count"], 1)
        self.assertEqual(metadata["balance_sheet_row_count"], 1)

    def test_prompt_cache_metadata_treats_latest_row_as_dynamic_tail(self):
        first_prompt = (
            "## Time Series Data (JSON)\n\n```json\n"
            '{"columns":["date","metric"],"rows":[["2026-04-26",1],["2026-04-27",2]],"latest_values":{"metric":2}}\n'
            "```\n\neditable prompt"
        )
        second_prompt = first_prompt.replace('["2026-04-27",2]', '["2026-04-27",3]')

        first_metadata = DataLoader.build_prompt_cache_metadata(first_prompt)
        second_metadata = DataLoader.build_prompt_cache_metadata(second_prompt)

        self.assertEqual(first_metadata["time_json_rows_hash"], second_metadata["time_json_rows_hash"])
        self.assertNotEqual(first_metadata["time_json_all_rows_hash"], second_metadata["time_json_all_rows_hash"])

    def test_stable_prefix_survives_edits_to_future_planned_rows(self):
        """编辑 Time.xlsx 的未来行，不得改动时间序列 JSON 块内的任何字节。

        `estimated_tokens` 由 tokenizer 量出，曾把 `## Future Planned Items`
        和分钟级时钟一起算进去；那个数字又被写进最靠前的时间序列 JSON，于是
        用户每加一条未来计划，都会让整块历史数据前缀在 72% 处断掉并白跑
        27% 的 prompt 缓存。这里锁住"只量不可变内容"这个不变式。
        """
        today = datetime.now().date()
        df = pd.DataFrame(
            [
                {"日期": pd.Timestamp(today - timedelta(days=1)), "工作": "历史"},
                {"日期": pd.Timestamp(today), "工作": "今天"},
            ]
        )
        plans = "## Future Planned Items\n\n- 2026-09-22（周二）: 工作: qq\n"
        # 余额表带日期派生列（已使用天数 / 日均使用成本），每天都会变，所以它
        # 同样不能被量进那个前导数字里。这里的变体必须换成长度不同的值，否则
        # 按字符计数的替身 tokenizer 量不出差异，用例会假通过。
        balance = '## Balance Sheet Data (JSON)\n\n```json\n{"days_used":162}\n```'
        balance_next_day = '## Balance Sheet Data (JSON)\n\n```json\n{"days_used":1162}\n```'

        def build(future_planned_rows, balance_sheet_summary):
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                prompt_path = temp_path / "Prompt_Personal_Info.md"
                excel_path = temp_path / "Time.xlsx"
                prompt_path.write_text("personal info", encoding="utf-8")
                excel_path.write_text("placeholder", encoding="utf-8")

                with patch.object(DataLoader, "load_excel_data", return_value=df), patch.object(
                    DataLoader, "get_balance_sheet_data_summary", return_value=balance_sheet_summary
                ), patch.object(
                    DataLoader, "get_future_planned_rows", return_value=future_planned_rows
                ), patch.object(
                    # 用字符长度代替真实 tokenizer：单调、与 tiktoken 的具体分词
                    # 无关，所以在小 fixture 上也必然随内容变化（真实 tiktoken 在
                    # 短串上可能给出相同计数，让这个用例假通过）。
                    sys.modules["src.utils.data_loader"],
                    "estimate_tokens",
                    side_effect=lambda text, _tokenizer=None: len(text),
                ), patch.object(
                    DataLoader,
                    "resolve_data_path",
                    side_effect=lambda filename, **_: temp_path / filename,
                ):
                    return DataLoader.construct_prompt(prompt_path, excel_path, days=90)

        def payload_of(prompt):
            # 从 JSON 正文反推块结束位置：本文件其它 docstring 里也出现过同一个
            # 标记，用 index 找标记会命中错误的那个 ``\n``` ``。
            marker = "## Time Series Data (JSON)\n\n```json\n"
            payload_start = prompt.index(marker) + len(marker)
            payload_end = prompt.index("\n```", payload_start)
            return json.loads(prompt[payload_start:payload_end]), payload_end + len("\n```")

        first = build(plans, balance)
        first_payload, first_end = payload_of(first)

        def assert_prefix_survives(second, label):
            self.assertNotEqual(first, second)
            second_payload, _ = payload_of(second)

            # 前导数字本身必须逐字节不变——它就印在时间序列 JSON 里。
            self.assertEqual(
                first_payload["estimated_tokens"],
                second_payload["estimated_tokens"],
                f"{label}改变了时间序列 JSON 里的 estimated_tokens，"
                "会让整个可缓存前缀作废",
            )

            # 首个差异必须出现在可缓存前缀之后；一旦落进前缀里，它后面的所有
            # token 都会失去缓存，这正是 75% 命中的成因。
            shared = min(len(first), len(second))
            first_difference = next(
                (index for index in range(shared) if first[index] != second[index]), shared
            )
            self.assertGreaterEqual(
                first_difference,
                first_end,
                f"{label}改动了时间序列 JSON 块，"
                f"可缓存前缀在第 {first_difference} 字节处被作废（前缀长 {first_end} 字节）",
            )

        # 用户在两次调用之间往 Time.xlsx 里追加了一条未来计划
        assert_prefix_survives(
            build(plans + "- 2026-09-23（周三）: 工作: 答辩\n", balance),
            "编辑 Time.xlsx 的未来计划行",
        )
        # 或者余额表里的日期派生列翻了一天
        assert_prefix_survives(build(plans, balance_next_day), "余额表的日期派生列")

    def test_construct_prompt_normalizes_sleep_and_screen_time_to_hour_floats(self):
        today = datetime.now().date()
        df = pd.DataFrame(
            [
                {
                    "\u65e5\u671f": pd.Timestamp(today - timedelta(days=1)),
                    "\u7761\u7720\u65f6\u95f4": "8\u5c0f\u65f633\u5206",
                    "\u624b\u673a\u5c4f\u5e55\n\u4f7f\u7528\u65f6\u95f4": "4\u5c0f\u65f612\u5206",
                },
                {
                    "\u65e5\u671f": pd.Timestamp(today),
                    "\u7761\u7720\u65f6\u95f4": "7\u5c0f\u65f606\u5206",
                    "\u624b\u673a\u5c4f\u5e55\n\u4f7f\u7528\u65f6\u95f4": "3\u5c0f\u65f648\u5206",
                },
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            prompt_path = temp_path / "Prompt_Personal_Info.md"
            excel_path = temp_path / "Time.xlsx"
            prompt_path.write_text("personal info", encoding="utf-8")
            excel_path.write_text("placeholder", encoding="utf-8")

            def fake_resolve_data_path(filename, user_home=None, onedrive_env=None):
                return temp_path / filename

            with patch.object(DataLoader, "load_excel_data", return_value=df), patch.object(
                DataLoader,
                "resolve_data_path",
                side_effect=fake_resolve_data_path,
            ), patch.object(
                DataLoader,
                "get_future_planned_rows",
                return_value="## Future Planned Items\n\n- none\n",
            ):
                combined = DataLoader.construct_prompt(prompt_path, excel_path, days=90)

        marker = "## Time Series Data (JSON)\n\n```json\n"
        start = combined.index(marker) + len(marker)
        end = combined.index("\n```", start)
        payload = json.loads(combined[start:end])

        self.assertEqual(
            payload["column_meta"],
            {
                "\u7761\u7720\u65f6\u95f4": {"unit": "hour"},
                "\u624b\u673a\u5c4f\u5e55 \u4f7f\u7528\u65f6\u95f4": {"unit": "hour"},
            },
        )
        self.assertEqual(
            payload["rows"],
            [
                [str(today - timedelta(days=1)), 8.55, 4.2],
            ],
        )
        current_day = extract_current_day_block(combined)
        self.assertEqual(current_day["current_day"], [str(today), 7.1, 3.8])
        self.assertEqual(
            current_day["latest_values"],
            {
                "\u7761\u7720\u65f6\u95f4": {"date": str(today), "value": 7.1},
                "\u624b\u673a\u5c4f\u5e55 \u4f7f\u7528\u65f6\u95f4": {"date": str(today), "value": 3.8},
            },
        )


class DataLoaderSnapshotCleanupTests(unittest.TestCase):
    def test_cleanup_removes_only_stale_snapshots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stale = temp_path / "temp_read_111111.xlsx"
            fresh = temp_path / "temp_read_222222.xlsx"
            unrelated = temp_path / "keep_me.xlsx"
            for path in (stale, fresh, unrelated):
                path.write_bytes(b"data")

            old = datetime.now().timestamp() - (DataLoader.STALE_SNAPSHOT_AGE_SECONDS + 60)
            os.utime(stale, (old, old))

            with patch.object(tempfile, "gettempdir", return_value=temp_dir):
                removed = DataLoader.cleanup_stale_excel_snapshots()

            self.assertEqual(removed, 1)
            self.assertFalse(stale.exists())
            # 正在使用的新快照不能被删掉。
            self.assertTrue(fresh.exists())
            # 不匹配命名规则的文件一律不动。
            self.assertTrue(unrelated.exists())

    def test_cleanup_tolerates_a_missing_temp_directory(self):
        with patch.object(tempfile, "gettempdir", return_value=str(Path(tempfile.gettempdir()) / "does-not-exist-xyz")):
            self.assertEqual(DataLoader.cleanup_stale_excel_snapshots(), 0)


class DataLoaderPastSevenDaysTests(unittest.TestCase):
    def test_get_past_seven_days_rows_only_includes_previous_seven_days(self):
        today = datetime.now().date()
        df = pd.DataFrame(
            [
                {
                    "日期": pd.Timestamp(today - timedelta(days=8)),
                    "周几": "周一",
                    "工作": "超出窗口",
                    "运动": "老训练",
                },
                {
                    "日期": pd.Timestamp(today - timedelta(days=7)),
                    "周几": "周二",
                    "工作": "七天前任务",
                    "运动": "背部训练",
                },
                {
                    "日期": pd.Timestamp(today - timedelta(days=3)),
                    "周几": "周六",
                    "工作": None,
                    "运动": "腿部训练",
                    "睡眠时间": "7小时20分",
                },
                {
                    "日期": pd.Timestamp(today - timedelta(days=1)),
                    "周几": "周一",
                    "工作": "昨天任务",
                    "运动": None,
                    "健康情况": "轻微酸痛",
                },
                {
                    "日期": pd.Timestamp(today),
                    "周几": "周二",
                    "工作": "今天任务",
                    "运动": "今天训练",
                },
            ]
        )

        with patch.object(DataLoader, "load_excel_data", return_value=df):
            past_rows = DataLoader.get_past_seven_days_rows(Path("Time.xlsx"))

        self.assertIn("## Past 7 Days Data Records", past_rows)
        self.assertIn("七天前任务", past_rows)
        self.assertIn("背部训练", past_rows)
        self.assertIn("腿部训练", past_rows)
        self.assertIn("7小时20分", past_rows)
        self.assertIn("昨天任务", past_rows)
        self.assertIn("轻微酸痛", past_rows)
        self.assertNotIn("超出窗口", past_rows)
        self.assertNotIn("老训练", past_rows)
        self.assertNotIn("今天任务", past_rows)
        self.assertNotIn("今天训练", past_rows)


if __name__ == "__main__":
    unittest.main()
