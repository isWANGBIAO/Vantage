from __future__ import annotations

import re
from pathlib import Path

from src.cli import command_path_for_operation
from src.services.automation_catalog import OPERATIONS


ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / ".agents" / "skills" / "vantage" / "SKILL.md"
MEMORY_PATH = ROOT / "docs" / "vantage-project-memory.md"


def _read_required(path: Path) -> str:
    assert path.is_file(), f"Required Vantage project guidance is missing: {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8")


def test_vantage_skill_has_discoverable_metadata_and_project_memory_entrypoint():
    skill = _read_required(SKILL_PATH)

    assert skill.startswith("---\n")
    frontmatter = skill.split("---", maxsplit=2)[1]
    assert re.search(r"(?m)^name:\s*vantage\s*$", frontmatter)
    assert re.search(r"(?m)^description:\s*.+", frontmatter)
    assert "docs/vantage-project-memory.md" in skill
    assert "AGENTS.md" in skill


def test_vantage_skill_routes_operations_through_cli_mcp_and_visual_ui():
    skill = _read_required(SKILL_PATH).lower()

    for required in (
        "vantage mcp",
        "--input-json -",
        "--format json",
        "system.status.read",
        "settings.update",
        "action_plan.generate",
        "action_plan.today.read",
        "computer use",
    ):
        assert required.lower() in skill, f"Skill is missing required workflow guidance: {required}"


def test_vantage_skill_gives_each_desktop_only_operation_a_computer_use_route():
    skill = _read_required(SKILL_PATH).lower()

    assert "settings.open_path" in skill
    assert "设置 → 数据与日志 → 配置/历史/日志 → 打开" in skill
    assert "system.locale.read" in skill
    assert "设置 → 通用 → 系统区域设置" in skill
    assert "window.title_bar_theme.update" in skill
    assert "设置 → 通用 → 主题" in skill
    assert "onboarding.legacy_root.pick" in skill
    assert "首次运行引导 → 迁移数据 → 选择文件夹" in skill
    assert "只可被 cli/mcp 发现" in skill
    assert "调用会返回不可用" in skill


def test_project_memory_contains_catalog_cli_mcp_parity_for_every_operation():
    memory = _read_required(MEMORY_PATH)

    for operation in OPERATIONS:
        cli_command = " ".join(("vantage", *command_path_for_operation(operation)))
        assert operation.name in memory, f"Project memory omits MCP operation {operation.name}"
        assert cli_command in memory, f"Project memory omits CLI command {cli_command}"


def test_project_memory_documents_source_truth_and_sensitive_data_boundaries():
    memory = _read_required(MEMORY_PATH)
    normalized = memory.lower()

    for required in ("source code", "tests", "runtime", "mcp", "cli"):
        assert required in normalized
    assert "api key" in normalized or "api-key" in normalized
    assert "write-only" in normalized
    assert not re.search(r"[A-Za-z]:\\Users\\[^\\\s]+", memory)
    assert not re.search(r"\bsk-[A-Za-z0-9_-]{12,}\b", memory)


def test_project_memory_marks_desktop_only_commands_as_discovery_only():
    memory = _read_required(MEMORY_PATH)

    for operation_name in (
        "settings.open_path",
        "system.locale.read",
        "window.title_bar_theme.update",
        "onboarding.legacy_root.pick",
    ):
        row = next(line for line in memory.splitlines() if operation_name in line)
        assert "仅发现，不可调用" in row
        assert "可见 UI" in row
