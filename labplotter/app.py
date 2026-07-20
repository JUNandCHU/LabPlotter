from __future__ import annotations

import ctypes
import os
import sys
import traceback
import tkinter as tk
from tkinter import messagebox


def main() -> None:
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    from .ui import LabPlotterApp
    from .config import data_dir
    from .i18n import tr
    log_path = data_dir() / "labplotter_error.log"
    try:
        app = LabPlotterApp()
    except Exception as exc:
        detail = traceback.format_exc()
        log_path.write_text(detail, encoding="utf-8")
        print(detail, file=sys.stderr)
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(tr("LabPlotter startup error"), f"{exc}\n\n{tr('Error log:')}\n{log_path}", parent=root)
            root.destroy()
        except Exception:
            pass
        raise SystemExit(1)

    def report_callback_exception(exc_type, exc_value, exc_tb):
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log_path.write_text(detail, encoding="utf-8")
        messagebox.showerror(tr("LabPlotter error"), f"{exc_value}\n\n{tr('Error log:')}\n{log_path}")
        print(detail, file=sys.stderr)

    app.report_callback_exception = report_callback_exception
    app.mainloop()


if __name__ == "__main__":
    main()
