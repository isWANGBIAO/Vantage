import os
from datetime import datetime
from unittest.mock import patch

from src.utils.data_loader import DataLoader


def test_personal_system_prompt_takes_precedence_and_is_reread(tmp_path):
    bundled = tmp_path / "bundled"
    personal = tmp_path / "personal"
    bundled.mkdir()
    personal.mkdir()
    (bundled / "Prompt_System.md").write_text("bundled instructions", encoding="utf-8")
    source = personal / "Prompt_System.md"
    source.write_text("personal first", encoding="utf-8")

    with patch.dict("os.environ", {"AI_DATA_ROOT": str(personal)}), patch(
        "src.utils.data_loader.Config.get_project_root", return_value=bundled
    ), patch.object(DataLoader, "_build_calendar_info", return_value="calendar"):
        assert DataLoader.get_system_prompt_content() == "personal first"
        source.write_text("personal changed", encoding="utf-8")
        assert DataLoader.get_system_prompt_content() == "personal changed"


def test_explicit_ai_data_root_precedes_data_root_and_bundled_prompt(tmp_path):
    ai_root, data_root, bundled = (tmp_path / name for name in ("ai", "data", "bundled"))
    for root in (ai_root, data_root, bundled):
        root.mkdir()
        (root / "Prompt_System.md").write_text(root.name, encoding="utf-8")

    with patch.dict(os.environ, {"AI_DATA_ROOT": str(ai_root), "DATA_ROOT": str(data_root)}), patch(
        "src.utils.data_loader.Config.get_project_root", return_value=bundled
    ):
        assert DataLoader.get_system_prompt_content() == "ai"

    with patch.dict(os.environ, {"DATA_ROOT": str(data_root)}, clear=True), patch(
        "src.utils.data_loader.Config.get_project_root", return_value=bundled
    ):
        assert DataLoader.get_system_prompt_content() == "data"


def test_missing_or_empty_system_prompt_uses_time_and_calendar_fallback(tmp_path):
    source = tmp_path / "Prompt_System.md"
    with patch.object(DataLoader, "resolve_data_path", return_value=source), patch.object(
        DataLoader, "_build_calendar_info", return_value="calendar-marker"
    ):
        missing = DataLoader.get_system_prompt_content()
        source.write_text("  \n", encoding="utf-8")
        empty = DataLoader.get_system_prompt_content()

    for content in (missing, empty):
        assert content.startswith("Context: Current Date and Time is ")
        assert content.endswith("Calendar: calendar-marker")


def test_system_prompt_replaces_time_and_calendar_placeholders(tmp_path):
    source = tmp_path / "Prompt_System.md"
    source.write_text("Now {current_time}; {当前时间}; {calendar_info}", encoding="utf-8")

    class FixedDatetime:
        @staticmethod
        def now():
            return datetime(2026, 10, 12, 9, 30)

    with patch.object(DataLoader, "resolve_data_path", return_value=source), patch.object(
        DataLoader, "_build_calendar_info", return_value="calendar-marker"
    ), patch("src.utils.data_loader.datetime", FixedDatetime):
        assert DataLoader.get_system_prompt_content() == (
            "Now 2026-10-12 09:30; 2026-10-12 09:30; calendar-marker"
        )
