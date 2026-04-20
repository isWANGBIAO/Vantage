import unittest

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


if __name__ == "__main__":
    unittest.main()
