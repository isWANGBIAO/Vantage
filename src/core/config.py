import os
import sys
from pathlib import Path


class Config:
    APP_NAME = "Vantage"
    DEV_APP_NAME = "Vantage-dev"

    @staticmethod
    def get_project_root():
        """Dynamically find project root by looking for .env or requirements.txt."""
        explicit_root = os.environ.get("VANTAGE_PROJECT_ROOT")
        if explicit_root:
            return Path(explicit_root).expanduser().resolve()

        if getattr(sys, "frozen", False):
            meipass_root = getattr(sys, "_MEIPASS", None)
            if meipass_root:
                return Path(meipass_root).resolve()
            return Path(sys.executable).resolve().parent

        current = Path(__file__).resolve().parent
        for _ in range(5):
            if (current / ".env").exists() or (current / "requirements.txt").exists():
                return current
            current = current.parent
        return Path.cwd()

    @staticmethod
    def get_app_mode():
        explicit_mode = os.environ.get("VANTAGE_APP_MODE")
        if explicit_mode:
            return explicit_mode
        return "development"

    @staticmethod
    def _get_default_user_data_dir(app_name):
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / app_name

        if sys.platform == "win32":
            return Path.home() / "AppData" / "Local" / app_name

        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / app_name

        return Path.home() / ".local" / "share" / app_name

    @staticmethod
    def _get_default_packaged_data_dir():
        return Config._get_default_user_data_dir(Config.APP_NAME)

    @staticmethod
    def get_data_dir():
        explicit_path = os.environ.get("VANTAGE_DATA_DIR")
        if explicit_path:
            data_dir = Path(explicit_path).expanduser().resolve()
        elif Config.get_app_mode() == "packaged":
            data_dir = Config._get_default_packaged_data_dir()
        else:
            data_dir = Config.get_project_root()

        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir

    @staticmethod
    def _resolve_runtime_dir(explicit_env_var, default_name):
        explicit_path = os.environ.get(explicit_env_var)
        if explicit_path:
            resolved = Path(explicit_path).expanduser().resolve()
        else:
            resolved = Config.get_data_dir() / default_name

        resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    @staticmethod
    def _resolve_history_dir():
        explicit_path = os.environ.get("VANTAGE_HISTORY_DIR")
        if explicit_path:
            resolved = Path(explicit_path).expanduser().resolve()
        elif os.environ.get("VANTAGE_DATA_DIR") or Config.get_app_mode() == "packaged":
            resolved = Config.get_data_dir() / "history"
        else:
            resolved = Config._get_default_user_data_dir(Config.DEV_APP_NAME) / "history"

        resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    @staticmethod
    def load_env():
        """Load environment variables from .env file."""
        root = Config.get_project_root()
        env_path = root / ".env"
        if not env_path.exists():
            return

        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key and key not in os.environ:
                val = value.strip()
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                os.environ[key] = val

    @staticmethod
    def get(key, default=None):
        return os.environ.get(key, default)

    @staticmethod
    def get_config_dir():
        return Config._resolve_runtime_dir("VANTAGE_CONFIG_DIR", "config")

    @staticmethod
    def get_history_dir():
        return Config._resolve_history_dir()

    @staticmethod
    def get_logs_dir():
        return Config._resolve_runtime_dir("VANTAGE_LOG_DIR", "logs")

    @staticmethod
    def get_plot_dir():
        return Config._resolve_runtime_dir("VANTAGE_PLOT_DIR", "plot_outputs")

    @staticmethod
    def get_cache_dir():
        return Config._resolve_runtime_dir("VANTAGE_CACHE_DIR", "cache")

    @staticmethod
    def get_runtime_dir():
        return Config._resolve_runtime_dir("VANTAGE_RUNTIME_DIR", "runtime")

    @staticmethod
    def get_migration_dir():
        return Config._resolve_runtime_dir("VANTAGE_MIGRATION_DIR", "migration")

    @staticmethod
    def get_runtime_paths():
        return {
            "app_mode": Config.get_app_mode(),
            "data_dir": Config.get_data_dir(),
            "config_dir": Config.get_config_dir(),
            "history_dir": Config.get_history_dir(),
            "log_dir": Config.get_logs_dir(),
            "plot_dir": Config.get_plot_dir(),
            "cache_dir": Config.get_cache_dir(),
            "runtime_dir": Config.get_runtime_dir(),
            "migration_dir": Config.get_migration_dir(),
        }

    @staticmethod
    def build_runtime_environment():
        runtime_paths = Config.get_runtime_paths()
        return {
            "VANTAGE_APP_MODE": runtime_paths["app_mode"],
            "VANTAGE_DATA_DIR": str(runtime_paths["data_dir"]),
            "VANTAGE_CONFIG_DIR": str(runtime_paths["config_dir"]),
            "VANTAGE_HISTORY_DIR": str(runtime_paths["history_dir"]),
            "VANTAGE_LOG_DIR": str(runtime_paths["log_dir"]),
            "VANTAGE_PLOT_DIR": str(runtime_paths["plot_dir"]),
            "VANTAGE_CACHE_DIR": str(runtime_paths["cache_dir"]),
            "VANTAGE_RUNTIME_DIR": str(runtime_paths["runtime_dir"]),
            "VANTAGE_MIGRATION_DIR": str(runtime_paths["migration_dir"]),
        }
