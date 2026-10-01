"""Scrollable, font-sized editor for a plot's actual data curves."""
import tkinter as tk
from tkinter import colorchooser, ttk

from matplotlib.colors import is_color_like, to_hex

from .i18n import tr


class CurveColorEditor:
    def __init__(self, window, parent):
        self.window, self.pane = window, window.pane
        self.variables, self.swatches, self.entries = {}, {}, {}
        self.dirty, self.resets = set(), set()
        self.signature = None
        self.syncing = False
        ttk.Label(parent, text=tr("Choose a color for each curve. Related labels and bands follow the curve color."),
                  wraplength=600).pack(anchor="w", pady=(0, 8))
        ttk.Button(parent, text=tr("Restore default curve colors"), command=self.reset_all).pack(anchor="w", pady=4)
        self.error = ttk.Label(parent, foreground="#A00000", wraplength=600)
        self.error.pack(anchor="w")
        self.rows = ttk.Frame(parent)
        self.rows.pack(fill="both", expand=True)
        self.refresh()

    def refresh(self):
        entries = getattr(self.pane.axis, "_labplotter_color_series", {})
        signature = tuple((key, entry.label) for key, entry in entries.items())
        self.syncing = True
        try:
            if signature != self.signature:
                pending = {key: var.get() for key, var in self.variables.items() if key in self.dirty}
                for child in self.rows.winfo_children():
                    child.destroy()
                self.variables.clear(); self.swatches.clear()
                self.signature = signature
                if not entries:
                    ttk.Label(self.rows, text=tr("Plot data to edit its curve colors."), wraplength=580).grid(sticky="w", pady=8)
                for row, (key, entry) in enumerate(entries.items()):
                    var = tk.StringVar(master=self.rows, value=pending.get(key, entry.color))
                    self.variables[key] = var
                    # Natural widget heights and padding track system font/DPI.
                    ttk.Label(self.rows, text=entry.label, wraplength=300).grid(row=row, column=0, sticky="w", padx=4, pady=6)
                    swatch = tk.Label(self.rows, width=3, background=entry.color, relief="sunken")
                    swatch.grid(row=row, column=1, padx=4, pady=6)
                    self.swatches[key] = swatch
                    ttk.Entry(self.rows, textvariable=var, width=11).grid(row=row, column=2, padx=4, pady=6)
                    ttk.Button(self.rows, text=tr("Choose…"), command=lambda k=key: self.choose(k)).grid(row=row, column=3, padx=4, pady=6)
                    ttk.Button(self.rows, text=tr("Default"), command=lambda k=key: self.reset(k)).grid(row=row, column=4, padx=4, pady=6)
                    var.trace_add("write", lambda *_args, k=key: self.changed(k))
                self.rows.columnconfigure(0, weight=1)
                self.dirty.intersection_update(entries)
                self.resets.intersection_update(entries)
            self.entries = dict(entries)
            for key, entry in entries.items():
                if key not in self.dirty:
                    self.variables[key].set(entry.color)
                value = self.variables[key].get()
                if is_color_like(value):
                    self.swatches[key].configure(background=to_hex(value))
        finally:
            self.syncing = False

    def changed(self, key):
        if self.syncing:
            return
        self.dirty.add(key); self.resets.discard(key)
        if self.window.live.get() and self.apply():
            self.pane.refresh_curve_colors()

    def choose(self, key):
        value = self.variables[key].get()
        color = colorchooser.askcolor(color=to_hex(value) if is_color_like(value) else self.entries[key].color,
                                     parent=self.window, title=tr("Choose line color"))[1]
        if color:
            self.variables[key].set(color)

    def reset(self, key):
        self.syncing = True
        self.variables[key].set(self.entries[key].default)
        self.syncing = False
        self.dirty.add(key); self.resets.add(key)
        if self.window.live.get() and self.apply():
            self.pane.refresh_curve_colors()

    def reset_all(self):
        for key in self.entries:
            self.syncing = True
            self.variables[key].set(self.entries[key].default)
            self.syncing = False
            self.dirty.add(key); self.resets.add(key)
        if self.window.live.get() and self.apply():
            self.pane.refresh_curve_colors()

    def apply(self):
        if any(not is_color_like(self.variables[key].get()) for key in self.dirty):
            self.error.configure(text=tr("Enter a valid color, for example #C00000, or use Choose…."))
            return False
        self.error.configure(text="")
        for key in self.dirty:
            self.entries[key].set(None if key in self.resets else self.variables[key].get())
        self.dirty.clear(); self.resets.clear()
        return True

    def discard(self):
        self.dirty.clear(); self.resets.clear()
