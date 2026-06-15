import json
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


class DataLoaderFuturePlansTests(unittest.TestCase):
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
        self.assertEqual(
            payload["rows"],
            [
                [str(today - timedelta(days=1)), 100, "\u5468\u516d", 63.5, "\u5199\u4ee3\u7801"],
                [str(today), 101, "\u5468\u65e5", 63.0, "\u7ee7\u7eed\u5199\u4ee3\u7801"],
            ],
        )
        self.assertEqual(
            payload["non_null_counts"],
            {
                "Days": 2,
                "\u5468\u51e0": 2,
                "\u4f53\u91cd": 2,
                "\u5de5\u4f5c": 2,
            },
        )
        self.assertEqual(
            payload["latest_values"],
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
        self.assertEqual(payload["rows"][-1], [str(today), "latest row"])
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
        self.assertEqual(payload["rows"][-1], [str(today), "latest row"])

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
                [str(today), 7.1, 3.8],
            ],
        )
        self.assertEqual(
            payload["latest_values"],
            {
                "\u7761\u7720\u65f6\u95f4": {"date": str(today), "value": 7.1},
                "\u624b\u673a\u5c4f\u5e55 \u4f7f\u7528\u65f6\u95f4": {"date": str(today), "value": 3.8},
            },
        )


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
