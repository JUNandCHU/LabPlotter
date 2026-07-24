from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any


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


class SettingsStore:
    """Small JSON preference store shared by UI features.

    Settings live outside the application directory, so column layouts and
    other user choices survive both application upgrades and rollbacks.
    Every write reloads the document first so the language preference managed
    by :mod:`labplotter.i18n` is preserved.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else settings_path()

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def get(self, key: str, default: Any = None) -> Any:
        return deepcopy(self.load().get(key, default))

    def set(self, key: str, value: Any) -> None:
        document = self.load()
        document[str(key)] = deepcopy(value)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.tmp")
        temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self.path)
