import json
import os
from pathlib import Path

from src.core.config import Config

MEDIA_PATHS_FILE_NAME = "media-paths.json"
MEDIA_PATHS_VERSION = 1
DEFAULT_D_DRIVE_ROOT = r"D:\WANGBIAO"
PHOTO_DIR_NAME = "本机照片"
PICTURE_DIR_CANDIDATES = ("Pictures", "图片")
SCREENSHOT_DIR_CANDIDATES = ("Screenshots", "屏幕截图")


def get_media_paths_settings_file(config_dir: str | Path | None = None) -> Path:
    resolved_config_dir = Path(config_dir) if config_dir else Path(Config.get_config_dir())
    resolved_config_dir.mkdir(parents=True, exist_ok=True)
    return resolved_config_dir / MEDIA_PATHS_FILE_NAME


def _normalize_media_path(path_value: str | Path) -> str:
    return str(Path(path_value).expanduser())


def load_media_paths_settings(settings_file: str | Path | None = None) -> dict | None:
    resolved_settings_file = Path(settings_file) if settings_file else get_media_paths_settings_file()
    if not resolved_settings_file.exists():
        return None

    try:
        payload = json.loads(resolved_settings_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None

    if not isinstance(payload, dict):
        return None

    photos_path = payload.get("photos_path")
    screenshots_path = payload.get("screenshots_path")
    if not isinstance(photos_path, str) or not photos_path.strip():
        return None
    if not isinstance(screenshots_path, str) or not screenshots_path.strip():
        return None

    return {
        "version": int(payload.get("version") or MEDIA_PATHS_VERSION),
        "photos_path": _normalize_media_path(photos_path),
        "screenshots_path": _normalize_media_path(screenshots_path),
    }


def save_media_paths_settings(
    photos_path: str | Path,
    screenshots_path: str | Path,
    settings_file: str | Path | None = None,
) -> Path:
    resolved_settings_file = Path(settings_file) if settings_file else get_media_paths_settings_file()
    resolved_settings_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": MEDIA_PATHS_VERSION,
        "photos_path": _normalize_media_path(photos_path),
        "screenshots_path": _normalize_media_path(screenshots_path),
    }
    resolved_settings_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return resolved_settings_file


def _ensure_media_directories(
    photos_path: str | Path,
    screenshots_path: str | Path,
    makedirs_fn=os.makedirs,
) -> tuple[str, str]:
    resolved_photos_path = _normalize_media_path(photos_path)
    resolved_screenshots_path = _normalize_media_path(screenshots_path)
    makedirs_fn(resolved_photos_path, exist_ok=True)
    makedirs_fn(resolved_screenshots_path, exist_ok=True)
    return resolved_photos_path, resolved_screenshots_path


def detect_preferred_media_paths(
    *,
    d_drive_root: str = DEFAULT_D_DRIVE_ROOT,
    user_home: str | None = None,
    onedrive_env: str | None = None,
    onedrive_consumer_env: str | None = None,
    exists_fn=os.path.exists,
    makedirs_fn=os.makedirs,
) -> tuple[str, str]:
    resolved_user_home = user_home or os.path.expanduser("~")
    resolved_onedrive_env = onedrive_env if onedrive_env is not None else os.environ.get("OneDrive")
    resolved_onedrive_consumer = (
        onedrive_consumer_env
        if onedrive_consumer_env is not None
        else os.environ.get("OneDriveConsumer")
    )

    roots_to_check: list[str] = []
    if d_drive_root and exists_fn(d_drive_root):
        roots_to_check.append(d_drive_root)
    if resolved_onedrive_env:
        roots_to_check.append(resolved_onedrive_env)
    if resolved_onedrive_consumer:
        roots_to_check.append(resolved_onedrive_consumer)
    roots_to_check.append(os.path.join(resolved_user_home, "OneDrive"))
    roots_to_check.append(resolved_user_home)

    for root in roots_to_check:
        for picture_dir in PICTURE_DIR_CANDIDATES:
            picture_root = os.path.join(root, picture_dir)
            photos_path = os.path.join(picture_root, PHOTO_DIR_NAME)
            if not exists_fn(photos_path):
                continue
            for screenshot_dir_name in SCREENSHOT_DIR_CANDIDATES:
                screenshots_path = os.path.join(picture_root, screenshot_dir_name)
                if exists_fn(screenshots_path):
                    return _ensure_media_directories(photos_path, screenshots_path, makedirs_fn=makedirs_fn)

    default_root = roots_to_check[0] if roots_to_check else (resolved_onedrive_env or os.path.join(resolved_user_home, "OneDrive"))
    pictures_path = os.path.join(default_root, "Pictures")
    if not exists_fn(pictures_path):
        pictures_path = os.path.join(default_root, "图片")

    screenshots_path = os.path.join(pictures_path, "Screenshots")
    if not exists_fn(screenshots_path):
        screenshots_path = os.path.join(pictures_path, "屏幕截图")

    photos_path = os.path.join(pictures_path, PHOTO_DIR_NAME)
    return _ensure_media_directories(photos_path, screenshots_path, makedirs_fn=makedirs_fn)


def resolve_media_storage_paths(
    *,
    settings_file: str | Path | None = None,
    d_drive_root: str = DEFAULT_D_DRIVE_ROOT,
    user_home: str | None = None,
    onedrive_env: str | None = None,
    onedrive_consumer_env: str | None = None,
    exists_fn=os.path.exists,
    makedirs_fn=os.makedirs,
) -> tuple[str, str]:
    resolved_settings_file = Path(settings_file) if settings_file else get_media_paths_settings_file()
    persisted = load_media_paths_settings(resolved_settings_file)
    if persisted:
        try:
            return _ensure_media_directories(
                persisted["photos_path"],
                persisted["screenshots_path"],
                makedirs_fn=makedirs_fn,
            )
        except OSError:
            pass

    photos_path, screenshots_path = detect_preferred_media_paths(
        d_drive_root=d_drive_root,
        user_home=user_home,
        onedrive_env=onedrive_env,
        onedrive_consumer_env=onedrive_consumer_env,
        exists_fn=exists_fn,
        makedirs_fn=makedirs_fn,
    )
    save_media_paths_settings(
        photos_path,
        screenshots_path,
        settings_file=resolved_settings_file,
    )
    return photos_path, screenshots_path
