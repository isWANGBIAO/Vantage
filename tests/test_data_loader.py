import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src.utils.data_loader import DataLoader


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
