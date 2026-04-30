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
                "日期": pd.to_datetime(["2026-04-30", "2026-05-31", "2026-06-30"]),
                "支付宝资产": [57433.39, None, None],
                "银行卡资产": [157.33, None, None],
                "微信资产": [142.80, None, None],
                "股票资产": [1089.10, None, None],
                "现金及现金等价物+股票": [58822.62, 0.0, 0.0],
                "收入工资": [9834.0, 9834.0, 9834.0],
                "期间收入": [9972.0, 9834.0, 9834.0],
                "期间支出": [3880.93, 68656.62, 9834.0],
                "日均支出": [129.36, 2214.73, 327.8],
                "记录类型": ["实际", "预测", "预测"],
            }
        )

        with patch.object(plot_dashboard.plot_module, "load_balance_sheet", return_value=data_frame):
            chart = plot_dashboard._build_balance_dashboard_chart()

        self.assertEqual(chart["summary"][0]["value"], "¥58,823")
        self.assertEqual(chart["summary"][1]["value"], "¥129/天")

        cash_series = next(item for item in chart["option"]["series"] if item["name"] == "现金及现金等价物+股票")
        forecast_series = next(item for item in chart["option"]["series"] if item["name"] == "预测期末现金+股票")

        self.assertEqual([point[0] for point in cash_series["data"]], ["2026-04-30"])
        self.assertEqual([point[0] for point in forecast_series["data"]], ["2026-04-30", "2026-05-31", "2026-06-30"])
        self.assertEqual([point[1] for point in forecast_series["data"]], [58823.0, 68657.0, 78491.0])
        self.assertEqual(forecast_series["lineStyle"]["type"], "dashed")
        self.assertTrue(all(zoom["start"] == 0 for zoom in chart["option"]["dataZoom"]))
        self.assertTrue(all(zoom["end"] == 100 for zoom in chart["option"]["dataZoom"]))


if __name__ == "__main__":
    unittest.main()
