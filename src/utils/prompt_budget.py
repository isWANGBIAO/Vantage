"""Shared token-budget resolution and deterministic row selection helpers."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable
from typing import Any


def estimate_tokens(text: str, tokenizer: Callable[[str], int] | None = None) -> int:
    """Estimate tokens conservatively for text sent to a model."""
    if tokenizer is not None:
        try:
            return max(1, int(tokenizer(text)))
        except (TypeError, ValueError, RuntimeError):
            pass

    return max(1, math.ceil(len(str(text)) / 3))


def resolve_prompt_budget(
    *,
    context_window_tokens: int | None,
    output_reserve_tokens: int,
    protocol_overhead_tokens: int,
    global_ceiling_tokens: int,
) -> dict[str, Any]:
    """Return the usable input budget and the source of the selected ceiling."""
    try:
        normalized_global = max(1, int(global_ceiling_tokens))
    except (TypeError, ValueError):
        normalized_global = 250_000

    try:
        normalized_context = int(context_window_tokens) if context_window_tokens else None
    except (TypeError, ValueError):
        normalized_context = None

    if normalized_context and normalized_context > 0:
        ceiling = min(normalized_global, normalized_context)
        source = "provider_model"
    else:
        ceiling = normalized_global
        source = "fallback_global_ceiling"

    reserve = max(0, int(output_reserve_tokens or 0))
    overhead = max(0, int(protocol_overhead_tokens or 0))
    return {
        "context_window_tokens": normalized_context,
        "ceiling_tokens": ceiling,
        "output_reserve_tokens": reserve,
        "protocol_overhead_tokens": overhead,
        "input_budget_tokens": max(1, ceiling - reserve - overhead),
        "source": source,
    }


def select_rows_by_budget(
    rows: Iterable[dict[str, Any]],
    *,
    budget_tokens: int,
    tokenizer: Callable[[str], int] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select complete rows in priority/date order without exceeding a budget."""
    candidates = []
    for index, row in enumerate(rows):
        candidate = dict(row)
        priority = candidate.pop("priority", 1_000_000)
        date_value = str(candidate.get("date") or candidate.get("日期") or "")
        serialized = json.dumps(candidate, ensure_ascii=False, separators=(",", ":"), default=str)
        candidates.append((int(priority), date_value, index, candidate, estimate_tokens(serialized, tokenizer)))

    candidates.sort(key=lambda item: (item[0], -_date_sort_key(item[1]), item[2]))
    remaining = max(0, int(budget_tokens))
    selected = []
    estimated_tokens = 0

    for _, _, _, candidate, row_tokens in candidates:
        if row_tokens > remaining:
            continue
        selected.append(candidate)
        remaining -= row_tokens
        estimated_tokens += row_tokens

    return selected, {
        "budget_tokens": max(0, int(budget_tokens)),
        "estimated_tokens": estimated_tokens,
        "included_row_count": len(selected),
        "omitted_row_count": len(candidates) - len(selected),
        "selection_strategy": "priority_then_newest_first",
    }


def _date_sort_key(value: str) -> int:
    """Provide a stable sortable value without making date parsing mandatory."""
    digits = "".join(char for char in value if char.isdigit())
    try:
        return int(digits or 0)
    except ValueError:
        return 0
