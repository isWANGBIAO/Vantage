def build_generation_metadata(*results: dict) -> dict:
    normalized_results = [result for result in results if result]
    latest_result = normalized_results[-1] if normalized_results else {}

    return {
        "model": latest_result.get("model"),
        "provider_route": latest_result.get("provider_route"),
        "requested_model": latest_result.get("requested_model"),
        "requested_provider_route": latest_result.get("requested_provider_route"),
        "fallback_used": bool(latest_result.get("fallback_used")),
        "reasoning_effort": latest_result.get("reasoning_effort") or "medium",
    }
