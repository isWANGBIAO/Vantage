import os
from pathlib import Path
from unittest.mock import patch

from src.core.config import Config


def test_runtime_paths_default_to_local_appdata_in_packaged_mode(tmp_path):
    local_appdata = tmp_path / "LocalAppData"

    with patch.dict(
        os.environ,
        {
            "VANTAGE_APP_MODE": "packaged",
            "LOCALAPPDATA": str(local_appdata),
        },
        clear=True,
    ):
        paths = Config.get_runtime_paths()

    assert paths["app_mode"] == "packaged"
    assert paths["data_dir"] == local_appdata / "Vantage"
    assert paths["config_dir"] == local_appdata / "Vantage" / "config"
    assert paths["history_dir"] == local_appdata / "Vantage" / "history"
    assert paths["log_dir"] == local_appdata / "Vantage" / "logs"
    assert paths["plot_dir"] == local_appdata / "Vantage" / "plot_outputs"
    assert paths["cache_dir"] == local_appdata / "Vantage" / "cache"
    assert paths["runtime_dir"] == local_appdata / "Vantage" / "runtime"
    assert paths["migration_dir"] == local_appdata / "Vantage" / "migration"


def test_runtime_paths_fall_back_to_project_root_in_development_mode(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()

    with patch.dict(os.environ, {}, clear=True), patch.object(
        Config,
        "get_project_root",
        return_value=project_root,
    ):
        paths = Config.get_runtime_paths()

    assert paths["app_mode"] == "development"
    assert paths["data_dir"] == project_root
    assert paths["config_dir"] == project_root / "config"
    assert paths["history_dir"] == project_root / "history"
    assert paths["log_dir"] == project_root / "logs"
    assert paths["plot_dir"] == project_root / "plot_outputs"
    assert paths["cache_dir"] == project_root / "cache"
    assert paths["runtime_dir"] == project_root / "runtime"
    assert paths["migration_dir"] == project_root / "migration"


def test_build_runtime_environment_exposes_stringified_directory_contract(tmp_path):
    paths = {
        "app_mode": "packaged",
        "data_dir": tmp_path / "data",
        "config_dir": tmp_path / "data" / "config",
        "history_dir": tmp_path / "data" / "history",
        "log_dir": tmp_path / "data" / "logs",
        "plot_dir": tmp_path / "data" / "plot_outputs",
        "cache_dir": tmp_path / "data" / "cache",
        "runtime_dir": tmp_path / "data" / "runtime",
        "migration_dir": tmp_path / "data" / "migration",
    }

    with patch.object(Config, "get_runtime_paths", return_value=paths):
        env = Config.build_runtime_environment()

    assert env == {
        "VANTAGE_APP_MODE": "packaged",
        "VANTAGE_DATA_DIR": str(paths["data_dir"]),
        "VANTAGE_CONFIG_DIR": str(paths["config_dir"]),
        "VANTAGE_HISTORY_DIR": str(paths["history_dir"]),
        "VANTAGE_LOG_DIR": str(paths["log_dir"]),
        "VANTAGE_PLOT_DIR": str(paths["plot_dir"]),
        "VANTAGE_CACHE_DIR": str(paths["cache_dir"]),
        "VANTAGE_RUNTIME_DIR": str(paths["runtime_dir"]),
        "VANTAGE_MIGRATION_DIR": str(paths["migration_dir"]),
    }
