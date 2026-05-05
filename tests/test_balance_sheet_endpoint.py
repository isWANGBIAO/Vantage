import asyncio
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src import server


class BalanceSheetEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

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

    def test_sheet_payload_can_return_all_rows_without_truncation(self):
        frame = pd.DataFrame(
            {
                "Date": pd.date_range("2026-01-01", periods=205, freq="D"),
                "Value": list(range(205)),
            }
        )

        payload = server._sheet_to_payload(frame, max_rows=None)

        self.assertFalse(payload["truncated"])
        self.assertEqual(payload["row_count"], 205)
        self.assertEqual(len(payload["rows"]), 205)
        self.assertEqual(payload["rows"][0][0], "2026-01-01")
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
        self.assertEqual(payload["prompt_payload"]["file_name"], "Balance Sheet.xlsx")
        self.assertEqual(payload["prompt_payload"]["sheet_count"], 1)
        self.assertEqual(payload["prompt_payload"]["total_rows"], 1)
        self.assertEqual(payload["prompt_payload"]["sheets"][0]["rows"], [["2026-04-01", 100.0, 5000.0]])
        self.assertIn(list(fake_sheets["Summary"].columns)[1], payload["prompt_payload"]["sheets"][0]["non_null_counts"])

    def test_purchase_recommendations_uses_cache_for_same_balance_sheet_hash(self):
        route = next(
            (route for route in server.app.routes if route.path == "/api/balance_sheet/purchase_recommendations"),
            None,
        )

        fake_sheets = {"Asset": pd.DataFrame({"名称": ["护眼台灯"], "金额": [199.0]})}
        llm_payload = {
            "recommendation_groups": [
                {"key": "practical", "title": "实用补缺", "items": [{"name": f"p-{index}"} for index in range(4)]},
                {"key": "night_guard", "title": "夜间防冲动", "items": [{"name": f"n-{index}"} for index in range(4)]},
                {"key": "wishlist", "title": "愿望清单", "items": [{"name": f"w-{index}"} for index in range(4)]},
            ],
        }
        random_llm_payload = {
            "recommendation_groups": [
                {"key": "practical", "title": "实用补缺", "items": [{"name": f"rp-{index}"} for index in range(4)]},
                {"key": "night_guard", "title": "夜间防冲动", "items": [{"name": f"rn-{index}"} for index in range(4)]},
                {"key": "wishlist", "title": "愿望清单", "items": [{"name": f"rw-{index}"} for index in range(4)]},
            ],
        }

        with patch.object(server.Config, "get_cache_dir", return_value=Path(self.temp_dir.name)), patch.object(
            server.DataLoader, "resolve_data_path", return_value=Path("Balance Sheet.xlsx")
        ), patch.object(server.DataLoader, "load_excel_sheets", return_value=fake_sheets), patch.object(server.LLMClient, "chat", side_effect=[
            {"content": server.json.dumps(llm_payload, ensure_ascii=False), "usage": {"total_tokens": 50}, "model": "gpt-5.5"},
            {"content": server.json.dumps(random_llm_payload, ensure_ascii=False), "usage": {"total_tokens": 50}, "model": "gpt-5.5"},
        ]) as chat:
            first_payload = asyncio.run(route.endpoint())
            second_payload = asyncio.run(route.endpoint())

        self.assertFalse(first_payload["from_cache"])
        self.assertTrue(second_payload["from_cache"])
        self.assertEqual(first_payload["cache_key"], second_payload["cache_key"])
        self.assertEqual(chat.call_count, 2)
        self.assertEqual(first_payload["recommendation_mix"]["random"]["requested"], 6)
        self.assertEqual(first_payload["recommendation_mix"]["contextual"]["requested"], 6)

    def test_purchase_recommendation_dismissal_persists_and_deduplicates(self):
        dismiss_route = next(
            (
                route
                for route in server.app.routes
                if route.path == "/api/balance_sheet/purchase_recommendations/dismiss"
            ),
            None,
        )
        list_route = next(
            (
                route
                for route in server.app.routes
                if route.path == "/api/balance_sheet/purchase_recommendations/dismissed"
                and "GET" in getattr(route, "methods", set())
            ),
            None,
        )

        self.assertIsNotNone(dismiss_route)
        self.assertIsNotNone(list_route)

        request = server.PurchaseRecommendationDismissRequest(
            cache_key="sheet-hash",
            group_key="wishlist",
            item={
                "name": "电纸书阅读器",
                "category": "学习/阅读",
                "estimated_price": "900",
                "reason": "减少手机刷屏",
                "evidence": "历史多次买书",
                "duplicate_check": "没有 Kindle",
                "impulse_risk": "medium",
            },
        )

        with patch.object(server.Config, "get_history_dir", return_value=Path(self.temp_dir.name)):
            first = asyncio.run(dismiss_route.endpoint(request))
            second = asyncio.run(dismiss_route.endpoint(request))
            listed = asyncio.run(list_route.endpoint())

        self.assertTrue(first["ok"])
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(second["count"], 1)
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["items"][0]["name"], "电纸书阅读器")
        self.assertEqual(listed["items"][0]["group_key"], "wishlist")

    def test_purchase_recommendation_dismissals_can_be_cleared(self):
        dismiss_route = next(
            (
                route
                for route in server.app.routes
                if route.path == "/api/balance_sheet/purchase_recommendations/dismiss"
            ),
            None,
        )
        list_route = next(
            (
                route
                for route in server.app.routes
                if route.path == "/api/balance_sheet/purchase_recommendations/dismissed"
                and "GET" in getattr(route, "methods", set())
            ),
            None,
        )
        clear_route = next(
            (
                route
                for route in server.app.routes
                if route.path == "/api/balance_sheet/purchase_recommendations/dismissed"
                and "DELETE" in getattr(route, "methods", set())
            ),
            None,
        )

        request = server.PurchaseRecommendationDismissRequest(
            cache_key="sheet-hash",
            group_key="practical",
            item={"name": "升降桌", "category": "人体工学"},
        )

        with patch.object(server.Config, "get_history_dir", return_value=Path(self.temp_dir.name)):
            asyncio.run(dismiss_route.endpoint(request))
            before = asyncio.run(list_route.endpoint())
            cleared = asyncio.run(clear_route.endpoint())
            after = asyncio.run(list_route.endpoint())

        self.assertEqual(before["count"], 1)
        self.assertTrue(cleared["ok"])
        self.assertEqual(cleared["count"], 0)
        self.assertEqual(after["items"], [])

    def test_purchase_recommendations_use_total_count_context_and_model_params(self):
        fake_sheets = {"Asset": pd.DataFrame({"name": ["keyboard"], "amount": [399.0]})}
        llm_payload = {
            "recommendation_groups": [
                {"key": "practical", "title": "Practical", "items": [{"name": f"p-{index}"} for index in range(3)]},
                {"key": "night_guard", "title": "Night guard", "items": [{"name": f"n-{index}"} for index in range(3)]},
                {"key": "wishlist", "title": "Wishlist", "items": [{"name": f"w-{index}"} for index in range(3)]},
            ],
        }
        random_llm_payload = {
            "recommendation_groups": [
                {"key": "practical", "title": "Practical", "items": [{"name": f"rp-{index}"} for index in range(3)]},
                {"key": "night_guard", "title": "Night guard", "items": [{"name": f"rn-{index}"} for index in range(3)]},
                {"key": "wishlist", "title": "Wishlist", "items": [{"name": f"rw-{index}"} for index in range(3)]},
            ],
        }
        context_prompt = (
            "## Time Series Data (JSON)\n\n```json\n{\"rows\":[[\"2026-05-04\",\"sleep\"]]}\n```\n\n"
            "## Balance Sheet Data (JSON)\n\n```json\n{\"sheets\":[]}\n```\n\n# Goals\n\nReduce impulse shopping."
        )

        with patch.object(server.Config, "get_cache_dir", return_value=Path(self.temp_dir.name)), patch.object(
            server.DataLoader, "resolve_data_path", side_effect=lambda name: Path(name)
        ), patch.object(server.DataLoader, "load_excel_sheets", return_value=fake_sheets), patch.object(
            server.DataLoader, "construct_prompt", return_value=context_prompt
        ), patch.object(server.LLMClient, "chat", side_effect=[
            {"content": server.json.dumps(llm_payload, ensure_ascii=False), "usage": {"total_tokens": 123}, "model": "gpt-5.5"},
            {"content": server.json.dumps(random_llm_payload, ensure_ascii=False), "usage": {"total_tokens": 123}, "model": "gpt-5.5"},
        ]) as chat:
            payload = server._build_purchase_recommendations_payload(
                request_config={
                    "recommendation_count": 9,
                    "model": "gpt-5.5",
                    "provider_route": "custom",
                    "reasoning_effort": "xhigh",
                    "service_tier": "priority",
                }
            )

        self.assertNotIn("cover_image", payload)
        self.assertNotIn("image_model", payload)
        self.assertEqual(payload["request_config"]["recommendation_count"], 9)
        self.assertEqual(payload["recommendation_mix"]["random"]["requested"], 5)
        self.assertEqual(payload["recommendation_mix"]["contextual"]["requested"], 4)
        self.assertEqual(payload["context"]["time_xlsx_included"], True)
        self.assertEqual(payload["context"]["balance_sheet_included"], True)
        self.assertEqual(chat.call_count, 2)
        contextual_call = chat.call_args_list[0].kwargs
        random_call = chat.call_args_list[1].kwargs
        for call_kwargs in (contextual_call, random_call):
            self.assertEqual(call_kwargs["model"], "gpt-5.5")
            self.assertEqual(call_kwargs["provider_route"], "custom")
            self.assertEqual(call_kwargs["reasoning_effort"], "xhigh")
            self.assertEqual(call_kwargs["service_tier"], "priority")
        self.assertEqual(contextual_call["source"], "expense_purchase_recommendations_contextual")
        self.assertEqual(random_call["source"], "expense_purchase_recommendations_random")
        self.assertIn("Time Series Data (JSON)", contextual_call["messages"][1]["content"])
        self.assertIn("Balance Sheet Data (JSON)", contextual_call["messages"][1]["content"])
        self.assertIn("total of 4", contextual_call["messages"][1]["content"])
        self.assertNotIn("Time Series Data (JSON)", random_call["messages"][1]["content"])
        self.assertNotIn("Balance Sheet Data (JSON)", random_call["messages"][1]["content"])
        self.assertIn("total of 5", random_call["messages"][1]["content"])

    def test_purchase_recommendation_mix_uses_random_half_rounded_up(self):
        self.assertEqual(server._purchase_recommendation_mode_counts(12), {"random": 6, "contextual": 6})
        self.assertEqual(server._purchase_recommendation_mode_counts(7), {"random": 4, "contextual": 3})

    def test_purchase_recommendation_groups_are_trimmed_to_total_count(self):
        raw_groups = [
            {"key": "practical", "items": [{"name": f"p-{index}"} for index in range(4)]},
            {"key": "night_guard", "items": [{"name": f"n-{index}"} for index in range(4)]},
            {"key": "wishlist", "items": [{"name": f"w-{index}"} for index in range(4)]},
        ]

        groups = server._normalize_purchase_recommendation_groups(raw_groups, recommendation_count=7)

        self.assertEqual(sum(len(group["items"]) for group in groups), 7)
        self.assertTrue(all(len(group["items"]) >= 2 for group in groups))

    def test_purchase_recommendations_retry_when_model_underfills_requested_total(self):
        fake_sheets = {"Asset": pd.DataFrame({"name": ["keyboard"], "amount": [399.0]})}
        underfilled_payload = {
            "recommendation_groups": [
                {"key": "practical", "title": "Practical", "items": [{"name": "desk tray"}]},
                {"key": "night_guard", "title": "Night guard", "items": [{"name": "cooldown list"}]},
                {"key": "wishlist", "title": "Wishlist", "items": [{"name": "travel backpack"}]},
            ],
        }
        full_payload = {
            "recommendation_groups": [
                {"key": "practical", "title": "Practical", "items": [{"name": f"p-{index}"} for index in range(2)]},
                {"key": "night_guard", "title": "Night guard", "items": [{"name": f"n-{index}"} for index in range(2)]},
                {"key": "wishlist", "title": "Wishlist", "items": [{"name": f"w-{index}"} for index in range(2)]},
            ],
        }
        random_full_payload = {
            "recommendation_groups": [
                {"key": "practical", "title": "Practical", "items": [{"name": f"rp-{index}"} for index in range(2)]},
                {"key": "night_guard", "title": "Night guard", "items": [{"name": f"rn-{index}"} for index in range(2)]},
                {"key": "wishlist", "title": "Wishlist", "items": [{"name": f"rw-{index}"} for index in range(2)]},
            ],
        }
        random_full_payload = {
            "recommendation_groups": [
                {"key": "practical", "title": "Practical", "items": [{"name": f"rp-{index}"} for index in range(2)]},
                {"key": "night_guard", "title": "Night guard", "items": [{"name": f"rn-{index}"} for index in range(2)]},
                {"key": "wishlist", "title": "Wishlist", "items": [{"name": f"rw-{index}"} for index in range(2)]},
            ],
        }

        with patch.object(server.Config, "get_cache_dir", return_value=Path(self.temp_dir.name)), patch.object(
            server.Config, "get_history_dir", return_value=Path(self.temp_dir.name)
        ), patch.object(server.DataLoader, "resolve_data_path", side_effect=lambda name: Path(name)), patch.object(
            server.DataLoader, "load_excel_sheets", return_value=fake_sheets
        ), patch.object(
            server.DataLoader,
            "construct_prompt",
            return_value="## Time Series Data (JSON)\n{}\n\n## Balance Sheet Data (JSON)\n{}",
        ), patch.object(server.LLMClient, "chat", side_effect=[
            {"content": server.json.dumps(underfilled_payload), "usage": {"total_tokens": 30}, "model": "gpt-5.5"},
            {"content": server.json.dumps(full_payload), "usage": {"total_tokens": 60}, "model": "gpt-5.5"},
            {"content": server.json.dumps(random_full_payload), "usage": {"total_tokens": 60}, "model": "gpt-5.5"},
        ]) as chat:
            payload = server._build_purchase_recommendations_payload(request_config={"recommendation_count": 8})

        self.assertEqual(chat.call_count, 3)
        retry_messages = chat.call_args_list[1].kwargs["messages"]
        self.assertIn("only returned 3", retry_messages[-1]["content"])
        self.assertIn("exactly 4", retry_messages[-1]["content"])
        self.assertEqual(sum(len(group["items"]) for group in payload["recommendation_groups"]), 8)
        self.assertEqual(payload["recommendation_count_requested"], 8)
        self.assertEqual(payload["recommendation_count_actual"], 8)
        self.assertFalse(payload["recommendation_count_underfilled"])
        self.assertEqual(payload["generation_attempts"], 2)

    def test_purchase_recommendations_regenerate_underfilled_cache(self):
        fake_sheets = {"Asset": pd.DataFrame({"name": ["keyboard"], "amount": [399.0]})}
        underfilled_cached = {
            "status": "ready",
            "from_cache": False,
            "cache_key": "cached-underfilled",
            "request_config": {"recommendation_count": 6},
            "recommendation_groups": [
                {"key": "practical", "title": "Practical", "items": [{"name": "desk tray"}]},
                {"key": "night_guard", "title": "Night guard", "items": [{"name": "cooldown list"}]},
                {"key": "wishlist", "title": "Wishlist", "items": [{"name": "travel backpack"}]},
            ],
        }
        full_payload = {
            "recommendation_groups": [
                {"key": "practical", "title": "Practical", "items": [{"name": f"p-{index}"} for index in range(2)]},
                {"key": "night_guard", "title": "Night guard", "items": [{"name": f"n-{index}"} for index in range(2)]},
                {"key": "wishlist", "title": "Wishlist", "items": [{"name": f"w-{index}"} for index in range(2)]},
            ],
        }
        random_full_payload = {
            "recommendation_groups": [
                {"key": "practical", "title": "Practical", "items": [{"name": f"rp-{index}"} for index in range(2)]},
                {"key": "night_guard", "title": "Night guard", "items": [{"name": f"rn-{index}"} for index in range(2)]},
                {"key": "wishlist", "title": "Wishlist", "items": [{"name": f"rw-{index}"} for index in range(2)]},
            ],
        }

        with patch.object(server.Config, "get_cache_dir", return_value=Path(self.temp_dir.name)), patch.object(
            server.Config, "get_history_dir", return_value=Path(self.temp_dir.name)
        ), patch.object(server.DataLoader, "resolve_data_path", side_effect=lambda name: Path(name)), patch.object(
            server.DataLoader, "load_excel_sheets", return_value=fake_sheets
        ), patch.object(
            server.DataLoader,
            "construct_prompt",
            return_value="## Time Series Data (JSON)\n{}\n\n## Balance Sheet Data (JSON)\n{}",
        ), patch.object(server, "_load_purchase_recommendation_cache", return_value=underfilled_cached), patch.object(
            server.LLMClient,
            "chat",
            side_effect=[
                {"content": server.json.dumps(full_payload), "usage": {"total_tokens": 60}, "model": "gpt-5.5"},
                {"content": server.json.dumps(random_full_payload), "usage": {"total_tokens": 60}, "model": "gpt-5.5"},
            ],
        ) as chat:
            payload = server._build_purchase_recommendations_payload(request_config={"recommendation_count": 6})

        self.assertEqual(chat.call_count, 2)
        self.assertFalse(payload["from_cache"])
        self.assertEqual(sum(len(group["items"]) for group in payload["recommendation_groups"]), 6)
        self.assertFalse(payload["recommendation_count_underfilled"])

    def test_purchase_recommendation_prompt_uses_context_and_does_not_request_cover_prompt(self):
        messages = server._build_purchase_recommendation_messages(
            "## Time Series Data (JSON)\n\n```json\n{}\n```\n\n## Balance Sheet Data (JSON)\n\n```json\n{}\n```",
            recommendation_count=7,
            dismissed_items=[{"name": "restore-me", "category": "test"}],
        )

        user_prompt = messages[1]["content"]
        self.assertIn("Time Series Data (JSON)", user_prompt)
        self.assertIn("total of 7", user_prompt)
        self.assertIn("practical", user_prompt)
        self.assertIn("night_guard", user_prompt)
        self.assertIn("wishlist", user_prompt)
        self.assertIn("recommendation_mode", user_prompt)
        self.assertIn("contextual", user_prompt)
        self.assertIn("restore-me", user_prompt)
        self.assertIn("dismissed purchase recommendations", user_prompt)
        self.assertNotIn("cover_prompt", user_prompt)

    def test_random_purchase_recommendation_prompt_excludes_context_bundle(self):
        messages = server._build_purchase_random_recommendation_messages(
            dismissed_items=[{"name": "blocked thing", "category": "blocked category"}],
            recommendation_count=5,
            random_seed="seed-123",
        )

        user_prompt = messages[1]["content"]
        self.assertIn("total of 5", user_prompt)
        self.assertIn("seed-123", user_prompt)
        self.assertIn("blocked thing", user_prompt)
        self.assertIn("recommendation_mode", user_prompt)
        self.assertIn("random", user_prompt)
        self.assertNotIn("Time Series Data (JSON)", user_prompt)
        self.assertNotIn("Balance Sheet Data (JSON)", user_prompt)

    def test_purchase_recommendation_dismissal_filters_random_and_contextual_modes(self):
        groups = [
            {
                "key": "practical",
                "items": [
                    {"name": "blocked exact", "category": "tools", "recommendation_mode": "random"},
                    {"name": "fresh idea", "category": "blocked category", "recommendation_mode": "contextual"},
                    {"name": "safe idea", "category": "new", "recommendation_mode": "random"},
                ],
            }
        ]

        filtered = server._filter_dismissed_purchase_groups(
            groups,
            [
                {"name": "blocked exact", "category": "other"},
                {"name": "old item", "category": "blocked category"},
            ],
        )

        self.assertEqual([item["name"] for item in filtered[0]["items"]], ["safe idea"])

    def test_purchase_recommendation_dismissal_can_be_deleted_by_id(self):
        dismiss_route = next(route for route in server.app.routes if route.path == "/api/balance_sheet/purchase_recommendations/dismiss")
        delete_route = next(
            route
            for route in server.app.routes
            if route.path == "/api/balance_sheet/purchase_recommendations/dismissed/{item_id}"
            and "DELETE" in getattr(route, "methods", set())
        )
        list_route = next(
            route
            for route in server.app.routes
            if route.path == "/api/balance_sheet/purchase_recommendations/dismissed"
            and "GET" in getattr(route, "methods", set())
        )

        request = server.PurchaseRecommendationDismissRequest(
            cache_key="sheet-hash",
            group_key="wishlist",
            item={"name": "restore-me", "category": "test"},
        )

        with patch.object(server.Config, "get_history_dir", return_value=Path(self.temp_dir.name)):
            created = asyncio.run(dismiss_route.endpoint(request))
            item_id = created["item"]["id"]
            deleted = asyncio.run(delete_route.endpoint(item_id))
            listed = asyncio.run(list_route.endpoint())

        self.assertTrue(deleted["ok"])
        self.assertEqual(deleted["count"], 0)
        self.assertEqual(listed["items"], [])

    def test_purchase_recommendation_routes_build_off_event_loop(self):
        route = next(
            (route for route in server.app.routes if route.path == "/api/balance_sheet/purchase_recommendations"),
            None,
        )

        async def fake_to_thread(func, *args, **kwargs):
            return {"status": "ready", "func": func.__name__, "args": args, "kwargs": kwargs}

        with patch.object(server.asyncio, "to_thread", side_effect=fake_to_thread) as to_thread:
            payload = asyncio.run(route.endpoint())

        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["func"], "_build_purchase_recommendations_payload")
        self.assertEqual(payload["args"], ())
        self.assertEqual(payload["kwargs"]["force_regenerate"], False)
        self.assertEqual(payload["kwargs"]["request_config"]["recommendation_count"], 12)
        to_thread.assert_called_once()

    def test_purchase_recommendations_regenerate_bypasses_cache(self):
        route = next(
            (
                route
                for route in server.app.routes
                if route.path == "/api/balance_sheet/purchase_recommendations/regenerate"
            ),
            None,
        )

        self.assertIsNotNone(route)

        fake_sheets = {"Asset": pd.DataFrame({"名称": ["鼠标"], "金额": [129.0]})}
        llm_payload = {
            "recommendation_groups": [
                {"key": "practical", "title": "实用补缺", "items": [{"name": f"p-{index}"} for index in range(4)]},
                {"key": "night_guard", "title": "夜间防冲动", "items": [{"name": f"n-{index}"} for index in range(4)]},
                {"key": "wishlist", "title": "愿望清单", "items": [{"name": f"w-{index}"} for index in range(4)]},
            ],
        }
        random_llm_payload = {
            "recommendation_groups": [
                {"key": "practical", "title": "实用补缺", "items": [{"name": f"rp-{index}"} for index in range(4)]},
                {"key": "night_guard", "title": "夜间防冲动", "items": [{"name": f"rn-{index}"} for index in range(4)]},
                {"key": "wishlist", "title": "愿望清单", "items": [{"name": f"rw-{index}"} for index in range(4)]},
            ],
        }

        with patch.object(server.Config, "get_cache_dir", return_value=Path(self.temp_dir.name)), patch.object(
            server.DataLoader, "resolve_data_path", return_value=Path("Balance Sheet.xlsx")
        ), patch.object(server.DataLoader, "load_excel_sheets", return_value=fake_sheets), patch.object(server.LLMClient, "chat", side_effect=[
            {"content": server.json.dumps(llm_payload, ensure_ascii=False), "usage": {"total_tokens": 50}, "model": "gpt-5.5"},
            {"content": server.json.dumps(random_llm_payload, ensure_ascii=False), "usage": {"total_tokens": 50}, "model": "gpt-5.5"},
            {"content": server.json.dumps(llm_payload, ensure_ascii=False), "usage": {"total_tokens": 50}, "model": "gpt-5.5"},
            {"content": server.json.dumps(random_llm_payload, ensure_ascii=False), "usage": {"total_tokens": 50}, "model": "gpt-5.5"},
        ]) as chat:
            first_payload = asyncio.run(route.endpoint())
            second_payload = asyncio.run(route.endpoint())

        self.assertFalse(first_payload["from_cache"])
        self.assertFalse(second_payload["from_cache"])
        self.assertEqual(chat.call_count, 4)

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
        self.assertFalse(payload["sheets"][0]["truncated"])
        self.assertEqual(len(payload["sheets"][0]["rows"]), 240)
        self.assertEqual(payload["prompt_payload"]["total_rows"], 240)
        self.assertEqual(len(payload["prompt_payload"]["sheets"][0]["rows"]), 240)
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
