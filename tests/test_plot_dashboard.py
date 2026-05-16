import unittest
from unittest.mock import patch

import pandas as pd

from src.services import plot_dashboard


class SleepScheduleDashboardTests(unittest.TestCase):
    def test_parse_primary_sleep_session_supports_sleep_wake_text(self):
        self.assertTrue(
            hasattr(plot_dashboard, "_parse_primary_sleep_session"),
            "expected _parse_primary_sleep_session() helper to exist",
        )

        parsed = plot_dashboard._parse_primary_sleep_session("22.28睡，10.40起")

        self.assertIsNotNone(parsed)
        self.assertAlmostEqual(parsed["bedtime_hour"], 22 + 28 / 60, places=4)
        self.assertAlmostEqual(parsed["wake_hour"], 10 + 40 / 60, places=4)

    def test_parse_primary_sleep_session_uses_first_segment_for_multi_sleep_rows(self):
        self.assertTrue(
            hasattr(plot_dashboard, "_parse_primary_sleep_session"),
            "expected _parse_primary_sleep_session() helper to exist",
        )

        parsed = plot_dashboard._parse_primary_sleep_session("2.45-7.49；12.25-14.57")

        self.assertIsNotNone(parsed)
        self.assertAlmostEqual(parsed["bedtime_hour"], 2 + 45 / 60, places=4)
        self.assertAlmostEqual(parsed["wake_hour"], 7 + 49 / 60, places=4)

    def test_sleep_schedule_chart_contains_bedtime_and_wake_series(self):
        self.assertTrue(
            hasattr(plot_dashboard, "_build_sleep_schedule_dashboard_chart"),
            "expected _build_sleep_schedule_dashboard_chart() helper to exist",
        )

        data_frame = pd.DataFrame(
            {
                "日期": pd.to_datetime(["2026-04-19", "2026-04-20"]),
                "起床时间": ["22.28睡，10.40起", "0.55-9.15"],
                "睡眠时间": ["12小时12分", "8小时20分"],
            }
        )

        chart = plot_dashboard._build_sleep_schedule_dashboard_chart(data_frame)

        self.assertEqual(chart["id"], "sleep-schedule")
        self.assertFalse(chart["empty"])
        self.assertEqual(
            [series["name"] for series in chart["option"]["series"]],
            ["入睡时间", "起床时间"],
        )
        self.assertEqual(chart["option"]["xAxis"]["type"], "time")
        self.assertEqual(chart["option"]["yAxis"]["type"], "value")
        self.assertEqual(chart["option"]["series"][0]["data"][0][0], "2026-04-19")
        self.assertAlmostEqual(chart["option"]["series"][0]["data"][0][1], 22 + 28 / 60, places=4)
        self.assertAlmostEqual(chart["option"]["series"][1]["data"][0][1], 24 + 10 + 40 / 60, places=4)

    def test_balance_dashboard_splits_actual_assets_from_forecast_path(self):
        data_frame = pd.DataFrame(
            {
                "日期": pd.to_datetime(
                    [
                        "2025-11-30",
                        "2025-12-31",
                        "2026-01-31",
                        "2026-02-28",
                        "2026-03-31",
                        "2026-04-30",
                        "2026-05-31",
                        "2026-06-30",
                        "2026-07-31",
                    ]
                ),
                "支付宝资产": [10000.0, 20000.0, 30000.0, 40000.0, 50416.0, 57433.39, None, None, None],
                "银行卡资产": [0.0, 0.0, 0.0, 0.0, 1112.0, 157.33, None, None, None],
                "微信资产": [0.0, 0.0, 0.0, 0.0, 9.0, 142.80, None, None, None],
                "股票资产": [0.0, 0.0, 0.0, 0.0, 1194.0, 1089.10, None, None, None],
                "现金及现金等价物+股票": [10000.0, 20000.0, 30000.0, 40000.0, 52731.0, 58822.62, 0.0, 0.0, 0.0],
                "收入工资": [0.0, 0.0, 0.0, 0.0, 9834.0, 9834.0, 9834.0, 30834.0, 6000.0],
                "期间收入": [0.0, 0.0, 0.0, 0.0, 9834.0, 9972.0, 9834.0, 30834.0, 6000.0],
                "期间支出": [1000.0, 2000.0, 3000.0, 4000.0, 5000.0, 6000.0, 68656.62, 30834.0, 6000.0],
                "日均支出": [33.33, 64.52, 96.77, 142.86, 161.29, 200.0, 2214.73, 1027.8, 193.5],
                "记录类型": ["实际", "实际", "实际", "实际", "实际", "实际", "预测", "预测", "预测"],
            }
        )

        with patch.object(plot_dashboard.plot_module, "load_balance_sheet", return_value=data_frame):
            chart = plot_dashboard._build_balance_dashboard_chart()

        self.assertEqual(chart["summary"][0]["value"], "¥58,823")
        self.assertEqual(chart["summary"][1]["value"], "¥200/天")

        cash_series = next(item for item in chart["option"]["series"] if item["name"] == "现金及现金等价物+股票")
        forecast_series = next(item for item in chart["option"]["series"] if item["name"] == "预测期末现金+股票")

        self.assertEqual(
            [point[0] for point in cash_series["data"]],
            ["2025-11-30", "2025-12-31", "2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"],
        )
        self.assertEqual(
            [point["value"][0] for point in forecast_series["data"]],
            ["2026-04-30", "2026-05-31", "2026-06-30", "2026-07-31"],
        )
        self.assertEqual([point["value"][1] for point in forecast_series["data"]], [58823.0, 65157.0, 92491.0, 94991.0])
        self.assertEqual([point.get("monthlyIncome") for point in forecast_series["data"]], [None, 9834.0, 30834.0, 6000.0])
        self.assertNotIn("step", forecast_series)
        self.assertTrue(forecast_series["smooth"])
        self.assertFalse(forecast_series["showSymbol"])
        self.assertEqual(forecast_series["lineStyle"]["type"], "dashed")
        self.assertTrue(all(zoom["start"] == 0 for zoom in chart["option"]["dataZoom"]))
        self.assertTrue(all(zoom["end"] == 100 for zoom in chart["option"]["dataZoom"]))

    def test_hhh_parser_handles_compact_markers_and_ignores_time_ranges(self):
        self.assertEqual(plot_dashboard._extract_hhh_values_for_dashboard("10.40-1"), [-1.0])
        self.assertEqual(
            plot_dashboard._extract_hhh_values_for_dashboard(
                "9.50 \u64b8\u4e0d\u51fa\u6765\uff1b14.45\u81ea\u5df1\u770b\u7247\u4e24\u5206\u949f-1\uff1b"
            ),
            [-1.0],
        )
        self.assertEqual(
            plot_dashboard._extract_hhh_values_for_dashboard(
                "\u65e9\u4e0a-1\uff1b20.47-22.42 \u548c\u9676\u4e9a\u4e39 +1"
            ),
            [-1.0, 1.0],
        )
        self.assertEqual(plot_dashboard._extract_hhh_values_for_dashboard("20.47-22.42"), [])

    def test_hhh_frequency_chart_keeps_mixed_same_day_events(self):
        data_frame = pd.DataFrame(
            {
                "\u65e5\u671f": pd.to_datetime(["2026-03-24", "2026-05-02", "2026-05-14"]),
                "HHH": [
                    "\u65e9\u4e0a-1\uff1b20.47-22.42 \u548c\u9676\u4e9a\u4e39 +1",
                    "9.50 \u64b8\u4e0d\u51fa\u6765\uff1b14.45\u81ea\u5df1\u770b\u7247\u4e24\u5206\u949f-1\uff1b",
                    "10.40-1",
                ],
            }
        )

        chart = plot_dashboard._build_hhh_frequency_dashboard_chart(data_frame)

        intercourse_series = next(item for item in chart["option"]["series"] if item["name"] == "\u6027\u751f\u6d3b")
        masturbation_series = next(item for item in chart["option"]["series"] if item["name"] == "\u81ea\u6170")

        self.assertEqual(intercourse_series["data"], [["2026-03-24", 1.0]])
        self.assertEqual(
            masturbation_series["data"],
            [["2026-03-24", 1.0], ["2026-05-02", 1.0], ["2026-05-14", 1.0]],
        )
        self.assertEqual(chart["summary"][0]["value"], "1")
        self.assertEqual(chart["summary"][1]["value"], "3")

    def test_hhh_interval_chart_uses_event_dates_and_independent_axes(self):
        data_frame = pd.DataFrame(
            {
                "\u65e5\u671f": pd.to_datetime(
                    [
                        "2025-06-01",
                        "2025-06-03",
                        "2025-06-04",
                        "2026-03-04",
                        "2026-03-05",
                        "2026-03-08",
                    ]
                ),
                "HHH": ["+1", "-1", "-1", "+1", "-1", "-1"],
            }
        )

        chart = plot_dashboard._build_hhh_interval_dashboard_chart(data_frame)

        self.assertEqual(chart["option"]["xAxis"]["type"], "time")
        self.assertNotIn("name", chart["option"]["xAxis"])
        self.assertEqual(len(chart["option"]["yAxis"]), 2)

        intercourse_series = next(item for item in chart["option"]["series"] if item["name"] == "\u6027\u751f\u6d3b\u95f4\u9694\uff08\u5929\uff09")
        masturbation_series = next(item for item in chart["option"]["series"] if item["name"] == "\u81ea\u6170\u95f4\u9694\uff08\u5929\uff09")

        self.assertEqual(intercourse_series["yAxisIndex"], 0)
        self.assertEqual(masturbation_series["yAxisIndex"], 1)
        self.assertEqual(intercourse_series["data"], [["2026-03-04", 276.0]])
        self.assertEqual(
            masturbation_series["data"],
            [["2025-06-04", 1.0], ["2026-03-05", 274.0], ["2026-03-08", 3.0]],
        )


if __name__ == "__main__":
    unittest.main()
