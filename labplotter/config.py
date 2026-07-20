from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "LabPlotter"


def data_dir() -> Path:
    override = os.environ.get("LABPLOTTER_DATA_DIR")
    if override:
        path = Path(override)
    elif os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        path = root / APP_NAME
    else:
        path = Path.home() / ".local" / "share" / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    return data_dir() / "particle_library.sqlite3"


def profiles_path() -> Path:
    return data_dir() / "format_profiles.json"


def settings_path() -> Path:
    return data_dir() / "settings.json"
