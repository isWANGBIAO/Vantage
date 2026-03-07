def build_generation_metadata(*results: dict) -> dict:
    normalized_results = [result for result in results if result]
    latest_result = normalized_results[-1] if normalized_results else {}

    return {
        "model": latest_result.get("model"),
        "provider_route": latest_result.get("provider_route"),
        "reasoning_effort": latest_result.get("reasoning_effort") or "medium",
    }
