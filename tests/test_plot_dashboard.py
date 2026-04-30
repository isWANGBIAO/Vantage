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


if __name__ == "__main__":
    unittest.main()
