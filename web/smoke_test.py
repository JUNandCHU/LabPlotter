from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


def main() -> None:
    app_path = Path(__file__).with_name("streamlit_app.py")
    app = AppTest.from_file(str(app_path), default_timeout=30).run()
    if app.exception:
        raise RuntimeError("; ".join(str(item.value) for item in app.exception))
    titles = [item.value for item in app.title]
    if titles != ["LabPlotter Web 0.8.2"]:
        raise RuntimeError(f"Unexpected title: {titles}")
    labels = [item.label for item in app.tabs]
    expected = ["FTIR", "NanoDrop UV–Vis", "ssNMR", "ZetaSizer", "TEM", "Custom format"]
    if labels != expected:
        raise RuntimeError(f"Unexpected tabs: {labels}")


if __name__ == "__main__":
    main()
