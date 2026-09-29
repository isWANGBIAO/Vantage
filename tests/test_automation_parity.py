from __future__ import annotations

import asyncio
from pathlib import Path

from mcp import Client

from src import cli
from src.core import user_config
from src.mcp_server import create_mcp_server
from src.services.automation_catalog import OPERATIONS, get_operation
from src.services.vantage_client import DEFAULT_BACKEND_BASE_URL


ROOT = Path(__file__).resolve().parents[1]
MEMORY_PATH = ROOT / "docs" / "vantage-project-memory.md"
SKILL_PATH = ROOT / ".agents" / "skills" / "vantage" / "SKILL.md"
ACTION_PLAN_INTERVAL_MAX = 35_791


def _cli_operations(node, prefix=()):
    if node.operation is not None:
        yield node.operation.name, prefix
    for name, child in node.children.items():
        yield from _cli_operations(child, (*prefix, name))


def test_catalog_operations_have_one_matching_cli_mcp_and_memory_entry():
    cli_paths = dict(_cli_operations(cli._command_tree()))
    assert set(cli_paths) == {operation.name for operation in OPERATIONS}

    async def list_tool_schemas():
        async with Client(create_mcp_server()) as client:
            result = await client.list_tools()
        return {tool.name: (tool.description, tool.input_schema) for tool in result.tools}

    mcp_tools = asyncio.run(list_tool_schemas())
    assert set(mcp_tools) == {operation.name for operation in OPERATIONS}

    memory = MEMORY_PATH.read_text(encoding="utf-8")
    skill = SKILL_PATH.read_text(encoding="utf-8")
    assert "docs/vantage-project-memory.md" in skill
    for operation in OPERATIONS:
        expected_cli = tuple(segment.replace("_", "-") for segment in operation.name.split("."))
        assert cli_paths[operation.name] == expected_cli
        assert mcp_tools[operation.name] == (
            operation.description,
            operation.input_schema,
        )
        memory_rows = [
            line for line in memory.splitlines()
            if "|" in line and operation.name in line
        ]
        assert any(
            " ".join(("vantage", *cli_paths[operation.name])) in row
            for row in memory_rows
        ), f"Project memory has no parity row for {operation.name}"


def test_operations_use_the_configured_loopback_backend_boundary():
    assert DEFAULT_BACKEND_BASE_URL == "http://127.0.0.1:8000"
    unavailable = {operation.name for operation in OPERATIONS if not operation.dispatchable}
    assert unavailable == {
        "settings.open_path",
        "system.locale.read",
        "window.title_bar_theme.update",
        "onboarding.legacy_root.pick",
    }
    assert all(get_operation(name).unavailable_reason for name in unavailable)


def test_onboarding_catalog_requires_an_explicit_setup_choice():
    schema = get_operation("onboarding.complete").input_schema
    assert schema["required"] == ["skip_chat_setup"]
    assert schema["properties"]["skip_chat_setup"]["type"] == "boolean"
    assert schema["oneOf"][0]["properties"]["skip_chat_setup"]["enum"] == [True]
    assert schema["oneOf"][1]["properties"]["skip_chat_setup"]["enum"] == [False]
    assert schema["oneOf"][1]["required"] == ["selected_provider"]


def test_action_plan_interval_limit_matches_catalog_storage_and_frontend_sanitizers():
    max_minutes = getattr(user_config, "MAX_ACTION_PLAN_CHECK_INTERVAL_MINUTES", None)
    assert max_minutes == ACTION_PLAN_INTERVAL_MAX

    interval_schema = get_operation("settings.update").input_schema["properties"][
        "action_plan_check_interval_minutes"
    ]
    assert interval_schema["minimum"] == 0
    assert interval_schema["maximum"] == max_minutes
    assert user_config._sanitize_settings(
        {"action_plan_check_interval_minutes": max_minutes}
    )["action_plan_check_interval_minutes"] == max_minutes
    assert user_config._sanitize_settings(
        {"action_plan_check_interval_minutes": max_minutes + 1}
    )["action_plan_check_interval_minutes"] == 60

    settings_state = (ROOT / "src/webapp/src/utils/settingsState.js").read_text(
        encoding="utf-8"
    )
    onboarding_config = (ROOT / "src/webapp/src/utils/onboardingConfig.cjs").read_text(
        encoding="utf-8"
    )
    action_plan = (ROOT / "src/webapp/src/components/ActionPlan.jsx").read_text(
        encoding="utf-8"
    )
    shared_limits = (ROOT / "src/webapp/src/utils/automationLimits.cjs").read_text(
        encoding="utf-8"
    )
    assert "35_791" in shared_limits
    for source in (settings_state, onboarding_config, action_plan):
        assert "MAX_ACTION_PLAN_CHECK_INTERVAL_MINUTES" in source
    assert "max={MAX_ACTION_PLAN_CHECK_INTERVAL_MINUTES}" in action_plan
