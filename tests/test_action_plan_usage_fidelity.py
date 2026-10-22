"""Synthetic partial-usage contracts across retry and per-round statistics."""

from types import SimpleNamespace

import pytest

from src.scripts import run_prompt
from src.services.model_call_recorder import normalize_usage


def test_retry_sum_keeps_partial_counters_unknown_without_losing_known_output():
    responses = iter([
        {"content": "", "usage": {"completion_tokens": 5}, "duration": 2},
        {"content": "complete body", "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}, "duration": 2},
    ])
    result, content = run_prompt.run_action_plan_round(
        client=SimpleNamespace(chat=lambda *_, **__: next(responses)),
        messages=[{"role": "user", "content": "synthetic"}], section="analysis",
        model_override=None, provider_route=None, service_tier=None,
        emit_start_before_first_attempt=False, emit=lambda _: None,
    )
    assert content == "complete body"
    assert result["attempts"] == 2
    assert result["usage"]["prompt_tokens"] is None
    assert result["usage"]["total_tokens"] is None
    assert result["usage"]["completion_tokens"] == 10
    stats = run_prompt.build_action_plan_request_stats("analysis", result)
    assert stats["usage_complete"] is False
    assert stats["prompt_tokens"] is None
    assert stats["completion_tokens"] == 10
    assert stats["completion_tokens_per_second"] == 2.5
    assert stats["total_tokens_per_second"] is None


@pytest.mark.parametrize("field", ["prompt_cache_hit_tokens", "prompt_cache_miss_tokens", "completion_reasoning_tokens"])
@pytest.mark.parametrize("value", [True, -1, 2.5, float("inf"), "bad"])
def test_optional_token_counters_use_the_same_strict_normalizer(field, value):
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, field: value}
    normalized = normalize_usage(usage)
    assert normalized[field] is None
    stats = run_prompt.build_action_plan_request_stats("analysis", {"usage": usage, "duration": 2})
    assert stats[field] is None
    assert stats["usage_complete"] is True
