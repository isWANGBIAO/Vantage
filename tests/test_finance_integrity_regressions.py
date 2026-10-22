"""Synthetic regression contracts for financial chronology and numeric meaning."""

import unittest
from datetime import date, datetime
from unittest.mock import patch

import pandas as pd

from src.backend import finance_data as finance


class FinanceIntegrityTests(unittest.TestCase):
    def test_undated_money_columns_are_not_interpreted_as_epoch_dates(self):
        frame = pd.DataFrame({"现金余额": [300, 100, 200]})
        self.assertIsNone(finance._find_date_column(frame))
        self.assertEqual(finance._find_metric_from_columns(frame, ["现金余额"])["value"], 200)

    def test_backend_budget_period_matches_real_calendar_including_leap_year(self):
        frame = pd.DataFrame({"项目": ["Synthetic"], "是否必须": ["非必需"], "每日": [10]})
        for year, month, days in [(2025, 2, 28), (2024, 2, 29), (2026, 4, 30), (2026, 10, 31)]:
            class Clock(datetime):
                @classmethod
                def now(cls, tz=None, year=year, month=month):
                    return cls(year, month, 2)

            with self.subTest(year=year, month=month), patch.object(finance, "datetime", Clock):
                budget = finance._build_budget_summary({"Budget": frame})
                self.assertEqual(budget["days_in_month"], days)
                self.assertEqual(budget["period_start"], f"{year}-{month:02d}-01")
                self.assertEqual(budget["monthly_optional"], days * 10)

    def test_latest_summary_is_chronological_not_physical_order(self):
        frame = pd.DataFrame({"日期": ["2025/2/1", "2025/10/1"], "实际消费": [100, 200], "日均消费": [10, 20], "总资产": [1000, 2000]})
        for order in [frame, frame.iloc[::-1]]:
            with self.subTest(order=list(order.index)):
                summary = finance._build_balance_summary({"开销": order})
                self.assertEqual(summary["time_cost"]["monthly_total"], 200)
                self.assertEqual(summary["time_cost"]["daily_average"], 20)
                self.assertEqual(summary["assets"]["total_assets"]["value"], 2000)

    def test_latest_value_reports_its_own_date_when_newer_values_are_missing(self):
        frame = pd.DataFrame({"日期": ["2025-01-01", "2025-01-02"], "日均消费": [10, None]})
        cost = finance._build_balance_summary({"开销": frame})["time_cost"]
        self.assertEqual(cost["daily_average"], 10)
        self.assertEqual(cost["latest_date"], "2025-01-01")
        self.assertEqual(cost["source"]["daily_average"]["date"], "2025-01-01")

    def test_named_compact_date_strings_are_dates_not_money(self):
        frame = pd.DataFrame({"日期": ["20250102", "20250101"], "日均消费": [20, 10]})
        cost = finance._build_balance_summary({"开销": frame})["time_cost"]
        self.assertEqual(cost["daily_average"], 20)
        self.assertEqual(cost["latest_date"], "2025-01-02")

    def test_forecasts_are_never_promoted_to_actual_summary(self):
        frame = pd.DataFrame({"日期": ["2099-01-01"], "记录类型": ["预测"], "实际消费": [300], "日均消费": [10], "现金及现金等价物+股票": [9000]})
        summary = finance._build_balance_summary({"开销": frame})
        self.assertIsNone(summary["time_cost"]["monthly_total"])
        self.assertIsNone(summary["assets"]["cash_and_stock"])

    def test_forecast_running_balance_uses_parsed_dates(self):
        frame = pd.DataFrame({"日期": ["2025/12/1", "2026/10/1", "2026/2/1"], "记录类型": ["实际", "预测", "预测"], "现金及现金等价物+股票": [100, None, None], "收入合计": [None, 20, 10], "计划支出": [None, 0, 0]})
        points = finance._build_balance_forecast_points({"开销": frame}, as_of=date(2026, 1, 1))
        self.assertEqual([(p["date"], p["projected_balance"]) for p in points], [("2026-02-01", 110), ("2026-10-01", 130)])

    def test_plot_forecast_uses_the_same_chronological_cumulative_order(self):
        from src.scripts.plot import build_balance_sheet_forecast_series

        frame = pd.DataFrame({"日期": ["2025/12/1", "2026/10/1", "2026/2/1"], "记录类型": ["实际", "预测", "预测"], "现金及现金等价物+股票": [100, None, None], "收入合计": [None, 20, 10], "计划支出": [None, 0, 0]})
        result = build_balance_sheet_forecast_series(frame, as_of=date(2026, 1, 1))
        self.assertEqual(result["projected_balance"].tolist(), [110, 130])

    def test_money_parser_preserves_sign_and_exponent(self):
        for text, expected in [("1e3", 1000), ("−1,200.50", -1200.5), ("(1,200)", -1200), ("￥1,200元", 1200), ("-1.2e-3", -0.0012)]:
            with self.subTest(text=text):
                self.assertEqual(finance._coerce_number(text), expected)
        for text in ["2026-04-01", "abc123", "1.2.3", "1e9999", "--2", "not a number"]:
            with self.subTest(invalid=text):
                self.assertIsNone(finance._coerce_number(text))

    def test_optional_synonyms_do_not_match_required_substring(self):
        for text in ["非必需", "不必需", "非必须", "不必须"]:
            self.assertIs(finance._parse_required_flag(text), False)

    def test_row_metrics_prefer_exact_total_over_partial_label(self):
        frame = pd.DataFrame({"项目": ["流动负债", "负债合计"], "金额": [100, 250]})
        self.assertEqual(finance._find_metric_from_rows(frame, ["负债合计", "负债"])["value"], 250)


if __name__ == "__main__":
    unittest.main()
