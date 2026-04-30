import asyncio
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src import server


class BalanceSheetEndpointTests(unittest.TestCase):
    def test_parse_required_flag_checks_optional_words_before_required_substrings(self):
        self.assertFalse(server._parse_required_flag("非必须"))
        self.assertFalse(server._parse_required_flag("不必须"))
        self.assertFalse(server._parse_required_flag("not required"))
        self.assertTrue(server._parse_required_flag("必须"))
        self.assertTrue(server._parse_required_flag("yes"))

    def test_find_first_column_prefers_exact_match_over_partial_match(self):
        columns = ["股票资产", "现金及现金等价物+股票", "期间支出", "日均支出"]

        selected = server._find_first_column(columns, ["现金及现金等价物+股票", "现金及现金等价物", "现金", "股票"])

        self.assertEqual(selected, "现金及现金等价物+股票")

    def test_sheet_payload_keeps_latest_rows_for_dated_sheets(self):
        frame = pd.DataFrame(
            {
                "日期": pd.date_range("2026-01-01", periods=205, freq="D"),
                "日均支出": list(range(205)),
            }
        )

        payload = server._sheet_to_payload(frame, max_rows=200)

        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["row_count"], 205)
        self.assertEqual(payload["rows"][0][0], "2026-01-06")
        self.assertEqual(payload["rows"][-1][0], "2026-07-24")

    def test_balance_sheet_route_is_registered_and_returns_payload(self):
        route = next((route for route in server.app.routes if route.path == "/api/balance_sheet"), None)

        self.assertIsNotNone(route)

        fake_sheets = {
            "Summary": pd.DataFrame(
                {
                    "日期": ["2026-04-01"],
                    "日均支出": [100.0],
                    "总资产": [5000.0],
                }
            )
        }

        with patch.object(server.DataLoader, "resolve_data_path", return_value=Path("Balance Sheet.xlsx")), patch.object(
            server.DataLoader, "load_excel_sheets", return_value=fake_sheets
        ):
            payload = asyncio.run(route.endpoint())

        self.assertEqual(payload["source"]["path"], "Balance Sheet.xlsx")
        self.assertEqual(payload["source"]["sheet_count"], 1)
        self.assertEqual(payload["summary"]["time_cost"]["daily_average"], 100.0)
        self.assertEqual(payload["summary"]["assets"]["total_assets"]["value"], 5000.0)
        self.assertEqual(payload["sheets"][0]["name"], "Summary")

    def test_balance_sheet_route_returns_full_trend_points_when_sheet_rows_are_truncated(self):
        route = next((route for route in server.app.routes if route.path == "/api/balance_sheet"), None)

        self.assertIsNotNone(route)

        expense_sheet = pd.DataFrame(
            {
                "日期": pd.date_range("2020-01-01", periods=240, freq="D"),
                "现金及现金等价物+股票": [1000 + index * 5 for index in range(240)],
                "日均支出": [50 + (index % 7) for index in range(240)],
                "期间支出": [80 + (index % 9) for index in range(240)],
            }
        )

        with patch.object(server.DataLoader, "resolve_data_path", return_value=Path("Balance Sheet.xlsx")), patch.object(
            server.DataLoader, "load_excel_sheets", return_value={"开销": expense_sheet}
        ):
            payload = asyncio.run(route.endpoint())

        self.assertEqual(payload["sheets"][0]["row_count"], 240)
        self.assertEqual(len(payload["sheets"][0]["rows"]), 200)
        self.assertEqual(len(payload["trend_points"]), 240)
        self.assertEqual(payload["trend_points"][0]["date"], "2020-01-01")
        self.assertEqual(payload["trend_points"][-1]["date"], "2020-08-27")
        self.assertEqual(payload["trend_points"][0]["balance"], 1000.0)
        self.assertEqual(payload["trend_points"][-1]["daily_average"], 51.0)

    def test_balance_sheet_summary_uses_actual_rows_and_exact_cash_total(self):
        expense_sheet = pd.DataFrame(
            {
                "日期": pd.to_datetime(["2026-04-30", "2026-05-31", "2029-06-30"]),
                "股票资产": [1089.10, None, None],
                "现金及现金等价物+股票": [58822.62, None, None],
                "实际/预测期末现金+股票": [58822.62, 61202.23, 149247.93],
                "期间支出": [3880.93, 5120.39, 5120.39],
                "预测/实际支出": [3880.93, 5120.39, 5120.39],
                "日均支出": [129.36, 165.17, 170.68],
                "记录类型": ["实际", "预测", "预测"],
                "固定收入": [None, 7500.0, 7500.0],
                "收入合计": [9972.0, 7500.0, 7500.0],
            }
        )

        summary = server._build_balance_summary({"开销": expense_sheet})
        trend_points = server._build_expense_trend_points({"开销": expense_sheet})

        self.assertEqual(summary["time_cost"]["latest_date"], "2026-04-30")
        self.assertEqual(summary["time_cost"]["daily_average"], 129.36)
        self.assertEqual(summary["assets"]["cash_and_stock"]["field"], "现金及现金等价物+股票")
        self.assertEqual(summary["assets"]["cash_and_stock"]["value"], 58822.62)
        self.assertEqual(len(trend_points), 1)
        self.assertEqual(trend_points[0]["date"], "2026-04-30")

    def test_balance_sheet_route_splits_actual_trend_from_forecast_points(self):
        route = next((route for route in server.app.routes if route.path == "/api/balance_sheet"), None)

        self.assertIsNotNone(route)

        expense_sheet = pd.DataFrame(
            {
                "日期": pd.to_datetime(["2026-04-30", "2026-05-31", "2026-06-30"]),
                "现金及现金等价物+股票": [58822.62, None, None],
                "实际/预测期末现金+股票": [58822.62, 61202.23, 63581.85],
                "期间支出": [3880.93, 5120.39, 5120.39],
                "预测/实际支出": [3880.93, 5120.39, 5120.39],
                "日均支出": [129.36, 165.17, 170.68],
                "记录类型": ["实际", "预测", "预测"],
                "固定收入": [None, 7500.0, 7500.0],
                "额外收入": [None, 0.0, 0.0],
                "收入合计": [9972.0, 7500.0, 7500.0],
                "净现金流": [6091.07, 2379.61, 2379.61],
            }
        )

        with patch.object(server.DataLoader, "resolve_data_path", return_value=Path("Balance Sheet.xlsx")), patch.object(
            server.DataLoader, "load_excel_sheets", return_value={"开销": expense_sheet}
        ):
            payload = asyncio.run(route.endpoint())

        self.assertEqual([point["date"] for point in payload["trend_points"]], ["2026-04-30"])
        self.assertEqual([point["date"] for point in payload["forecast_points"]], ["2026-05-31", "2026-06-30"])
        self.assertEqual(payload["forecast_points"][0]["fixed_income"], 7500.0)
        self.assertEqual(payload["forecast_points"][0]["planned_spend"], 3880.93)
        self.assertEqual(payload["forecast_points"][0]["net_cash_flow"], 3619.07)
        self.assertAlmostEqual(payload["forecast_points"][0]["projected_balance"], 62441.69)
        self.assertAlmostEqual(payload["forecast_points"][1]["projected_balance"], 66060.76)

    def test_balance_sheet_forecast_rolls_forward_from_latest_actual_income(self):
        expense_sheet = pd.DataFrame(
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
                    ]
                ),
                "支付宝资产": [12000.0, 18000.0, 24000.0, 30000.0, 50416.0, 57433.39, 0.0, 0.0],
                "银行卡资产": [0.0, 0.0, 0.0, 0.0, 1112.0, 157.33, 0.0, 0.0],
                "微信资产": [0.0, 0.0, 0.0, 0.0, 9.0, 142.8, 0.0, 0.0],
                "股票资产": [0.0, 0.0, 0.0, 0.0, 1194.0, 1089.1, 0.0, 0.0],
                "现金及现金等价物+股票": [12000.0, 18000.0, 24000.0, 30000.0, 52731.0, 58822.62, 0.0, 0.0],
                "收入工资": [0.0, 0.0, 0.0, 0.0, 9834.0, 9834.0, 9834.0, 30834.0],
                "期间收入": [0.0, 0.0, 0.0, 0.0, 9834.0, 9972.0, 9834.0, 30834.0],
                "期间支出": [1000.0, 2000.0, 3000.0, 4000.0, 5000.0, 6000.0, 68656.62, 30834.0],
                "日均支出": [33.33, 64.52, 96.77, 142.86, 161.29, 200.0, 2214.73, 1027.8],
                "记录类型": ["实际", "实际", "实际", "实际", "实际", "实际", "预测", "预测"],
            }
        )

        forecast_points = server._build_balance_forecast_points(
            {"开销": expense_sheet},
            as_of=date(2026, 5, 1),
        )

        self.assertEqual([point["date"] for point in forecast_points], ["2026-05-31", "2026-06-30"])
        self.assertEqual(forecast_points[0]["total_income"], 9834.0)
        self.assertEqual(forecast_points[0]["planned_spend"], 3500.0)
        self.assertEqual(forecast_points[0]["net_cash_flow"], 6334.0)
        self.assertAlmostEqual(forecast_points[0]["projected_balance"], 65156.62)
        self.assertEqual(forecast_points[1]["planned_spend"], 3500.0)
        self.assertEqual(forecast_points[1]["net_cash_flow"], 27334.0)
        self.assertAlmostEqual(forecast_points[1]["projected_balance"], 92490.62)


if __name__ == "__main__":
    unittest.main()
