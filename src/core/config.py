import os
import sys
from pathlib import Path

class Config:
    @staticmethod
    def get_project_root():
        """Dynamically find project root by looking for .env or requirements.txt"""
        current = Path(__file__).resolve().parent
        for _ in range(5):
            if (current / ".env").exists() or (current / "requirements.txt").exists():
                return current
            current = current.parent
        return Path.cwd()

    @staticmethod
    def load_env():
        """Load environment variables from .env file"""
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
    def get_history_dir():
        root = Config.get_project_root()
        history_dir = root / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        return history_dir
