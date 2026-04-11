import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src import server


class BalanceSheetEndpointTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
