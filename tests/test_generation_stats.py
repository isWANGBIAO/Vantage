import unittest

from src.utils.generation_stats import build_generation_metadata


class GenerationStatsTests(unittest.TestCase):
    def test_build_generation_metadata_defaults_reasoning_effort_to_medium(self):
        metadata = build_generation_metadata(
            {
                "model": "gpt-5.2",
                "provider_route": "cliproxyapi_primary",
            },
        )

        self.assertEqual(metadata["reasoning_effort"], "medium")

    def test_build_generation_metadata_keeps_reasoning_effort_from_latest_result(self):
        metadata = build_generation_metadata(
            {
                "model": "gpt-5.2",
                "provider_route": "cliproxyapi_primary",
                "reasoning_effort": "high",
            },
            {
                "model": "gemini-3.1-pro-high",
                "provider_route": "cliproxyapi_secondary",
                "reasoning_effort": "xhigh",
            },
        )

        self.assertEqual(metadata["reasoning_effort"], "xhigh")

    def test_build_generation_metadata_prefers_latest_result_model(self):
        metadata = build_generation_metadata(
            {
                "model": "gpt-5.2",
                "provider_route": "cliproxyapi_primary",
                "reasoning_effort": "medium",
            },
            {
                "model": "gemini-3.1-pro-high",
                "provider_route": "cliproxyapi_secondary",
                "reasoning_effort": "xhigh",
            },
        )

        self.assertEqual(metadata["model"], "gemini-3.1-pro-high")
        self.assertEqual(metadata["provider_route"], "cliproxyapi_secondary")
        self.assertEqual(metadata["reasoning_effort"], "xhigh")
