import json

from src.utils.prompt_budget import (
    estimate_tokens,
    resolve_prompt_budget,
    select_rows_by_budget,
)


def test_resolve_prompt_budget_uses_provider_limit_before_global_fallback():
    resolved = resolve_prompt_budget(
        context_window_tokens=100_000,
        output_reserve_tokens=20_000,
        protocol_overhead_tokens=2_000,
        global_ceiling_tokens=250_000,
    )

    assert resolved["input_budget_tokens"] == 78_000
    assert resolved["source"] == "provider_model"


def test_resolve_prompt_budget_uses_250k_only_when_provider_limit_is_missing():
    resolved = resolve_prompt_budget(
        context_window_tokens=None,
        output_reserve_tokens=20_000,
        protocol_overhead_tokens=2_000,
        global_ceiling_tokens=250_000,
    )

    assert resolved["input_budget_tokens"] == 228_000
    assert resolved["source"] == "fallback_global_ceiling"


def test_select_rows_keeps_priority_rows_and_newest_rows_without_exceeding_budget():
    rows = [
        {"date": "2026-09-01", "value": "old", "priority": 2},
        {"date": "2026-09-07", "value": "recent", "priority": 1},
        {"date": "2026-09-08", "value": "latest", "priority": 0},
    ]
    budget = estimate_tokens(json.dumps(rows[2], ensure_ascii=False, separators=(",", ":")))

    selected, metadata = select_rows_by_budget(rows, budget_tokens=budget)

    assert selected == [{"date": "2026-09-08", "value": "latest"}]
    assert metadata["included_row_count"] == 1
    assert metadata["omitted_row_count"] == 2
    assert metadata["estimated_tokens"] <= budget


def test_select_rows_is_deterministic_and_does_not_mutate_input():
    rows = [
        {"date": "2026-09-06", "value": "b", "priority": 1},
        {"date": "2026-09-07", "value": "a", "priority": 1},
    ]
    original = [dict(row) for row in rows]
    selected_one, _ = select_rows_by_budget(rows, budget_tokens=10_000)
    selected_two, _ = select_rows_by_budget(rows, budget_tokens=10_000)

    assert selected_one == selected_two
    assert rows == original
