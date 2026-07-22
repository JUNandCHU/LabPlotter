from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import tkinter as tk
from copy import deepcopy
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont
from typing import Callable

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.colors import is_color_like, to_hex
from matplotlib.figure import Figure
from matplotlib.patches import Ellipse, Rectangle
from PIL import Image, ImageTk

from . import __version__
from .clipboard import copy_png_to_clipboard
from .config import SettingsStore
from .i18n import canonical, language, localize_widget_tree, manager as language_manager, set_language, tr, translate_value
from .models import Spectrum
from .nmr import parse_bruker_zip, process_bruker_1d
from .ocr import OCRTable, run_table_ocr
from .parsers import (
    detect_builtin_kind,
    parse_ftir_file,
    parse_generic_with_profile,
    parse_nanodrop_file,
    parse_zetasizer_workbook,
    workbook_preview,
    workbook_signature,
)
from .plot_settings import AnnotationWindow, PlotSettingsWindow
from .plotting import AnnotationSpec, PlotOptions, apply_origin_style, figure_png_bytes, font_family_for_text
from .processing import ftir_peak_indices, mean_curve, process_ftir
from .storage import FormatProfileStore, ParticleLibrary, default_particle_label


FTIR_RANGES = (
    ("O–H stretch (often broad)", "3200–3600 cm^-1"),
    ("N–H stretch", "3300–3500 cm^-1"),
    ("=C–H / aromatic C–H stretch", "3000–3100 cm^-1"),
    ("sp3 C–H stretch", "2850–2960 cm^-1"),
    ("C≡N / C≡C region", "2100–2260 cm^-1"),
    ("C=O stretch", "1650–1750 cm^-1"),
    ("Aromatic C=C region", "1450–1600 cm^-1"),
    ("C–N stretch (context dependent)", "1020–1350 cm^-1"),
    ("C–O stretch", "1000–1300 cm^-1"),
    ("Aromatic C–H out-of-plane", "650–900 cm^-1"),
)

BASELINE_METHODS = (
    "Linear endpoints (diagonal)",
    "Rubberband (convex hull)",
    "Modified polynomial (ModPoly)",
    "AsLS (asymmetric least squares)",
    "arPLS (asymmetrically reweighted PLS)",
    "airPLS (adaptive reweighted PLS)",
)

BASELINE_HELP = {
    "Linear endpoints (diagonal)": "The median values in the first and last 3% of the spectrum are joined by a straight line. This is closest to manually selecting both ends for a diagonal baseline in Origin. It is transparent and stable for nearly linear drift, but biased when a real band occurs at either end.",
    "Rubberband (convex hull)": "A piecewise-linear baseline follows the upper convex hull for transmittance or the lower hull for absorbance. It is useful for a broad, slowly varying background, but noise or very broad bands may be mistaken for the baseline.",
    "Modified polynomial (ModPoly)": "A polynomial is fitted repeatedly while points on the peak or band side are clipped automatically. The polynomial order controls curvature; 2–4 is usually reasonable. A high order can follow and remove real broad bands.",
    "AsLS (asymmetric least squares)": "A Whittaker smoother with asymmetric weights estimates the baseline. Larger λ produces a smoother baseline, while p controls peak/baseline asymmetry. Strong broad bands can be overcorrected depending on λ and p.",
    "arPLS (asymmetrically reweighted PLS)": "Weights are adjusted iteratively from the negative-residual distribution. Unlike AsLS, p does not need to be selected directly and λ is the main control. It adapts relatively automatically to curved backgrounds.",
    "airPLS (adaptive reweighted PLS)": "Adaptive PLS gives progressively larger weights to residuals below the baseline. Peak positions are not required and λ controls smoothness. It can help with complex backgrounds but may be aggressive for some spectra.",
}


SERIES_PALETTE = (
    "#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD",
    "#8C564B", "#E377C2", "#7F7F7F", "#BCBD22", "#17BECF",
)

ZETA_COLOR_DEFAULTS = {
    "dls_curve": {"scope": "individual", "global_color": "#1F77B4", "colors": {}},
    "zeta_curve": {"scope": "individual", "global_color": "#1F77B4", "colors": {}},
    "dls_bar": {"scope": "all", "global_color": "#4C78A8", "colors": {}},
    "zeta_bar": {"scope": "all", "global_color": "#F58518", "colors": {}},
}


def _float_or_none(value: str) -> float | None:
    try:
        return float(value.strip()) if value.strip() else None
    except ValueError:
        return None


def normalized_color(value: str, fallback: str) -> str:
    """Return a Matplotlib-compatible color in canonical hex form."""
    candidate = str(value).strip()
    if not is_color_like(candidate):
        candidate = fallback
    return to_hex(candidate, keep_alpha=False).upper()


def resolve_series_color(configuration: dict, particle: str, index: int, default_color: str) -> str:
    """Resolve an all-series or per-particle ZetaSizer color choice."""
    if configuration.get("scope") == "all":
        return normalized_color(configuration.get("global_color", ""), default_color)
    stored = configuration.get("colors", {})
    fallback = SERIES_PALETTE[index % len(SERIES_PALETTE)]
    return normalized_color(stored.get(particle, "") if isinstance(stored, dict) else "", fallback)


class TreeColumnWidthState:
    """Persist manually resized Treeview columns in the user settings file."""

    GROUP = "tree_column_widths"

    def __init__(self, tree: ttk.Treeview, store: SettingsStore, key: str, columns: tuple[str, ...]):
        self.tree = tree
        self.store = store
        self.key = key
        self.columns = columns
        self._pending = None
        self.restore()
        self.tree.after_idle(self.restore)
        self.tree.bind("<ButtonRelease-1>", self._schedule_save, add=True)
        self.tree.bind("<Destroy>", self._destroyed, add=True)

    def restore(self):
        if not self.tree.winfo_exists():
            return
        group = self.store.get(self.GROUP, {})
        saved = group.get(self.key, {}) if isinstance(group, dict) else {}
        if not isinstance(saved, dict):
            return
        for column in self.columns:
            try:
                width = int(saved.get(column, 0))
                if 40 <= width <= 4000:
                    self.tree.column(column, width=width)
            except (TypeError, ValueError, tk.TclError):
                continue

    def _schedule_save(self, _event=None):
        if self._pending is not None:
            self.tree.after_cancel(self._pending)
        self._pending = self.tree.after(180, self.save)

    def save(self):
        self._pending = None
        if not self.tree.winfo_exists():
            return
        try:
            widths = {column: int(self.tree.column(column, "width")) for column in self.columns}
            group = self.store.get(self.GROUP, {})
            if not isinstance(group, dict):
                group = {}
            group[self.key] = widths
            self.store.set(self.GROUP, group)
        except (OSError, tk.TclError, TypeError, ValueError):
            pass

    def _destroyed(self, event=None):
        if event is None or event.widget is self.tree:
            self.save()


class HoverTooltip:
    def __init__(self, widget, text_provider: Callable[[], str], delay: int = 350):
        self.widget = widget
        self.text_provider = text_provider
        self.delay = delay
        self._job = None
        self._window = None
        widget.bind("<Enter>", self._schedule, add=True)
        widget.bind("<Leave>", self.hide, add=True)

    def _schedule(self, _event=None):
        self.hide()
        self._job = self.widget.after(self.delay, self.show)

    def show(self):
        self._job = None
        text = self.text_provider()
        if not text:
            return
        self._window = tk.Toplevel(self.widget)
        self._window.wm_overrideredirect(True)
        self._window.wm_geometry(f"+{self.widget.winfo_pointerx() + 14}+{self.widget.winfo_pointery() + 12}")
        label = tk.Label(self._window, text=text, justify="left", wraplength=440, background="#fffbe6", relief="solid", borderwidth=1, padx=9, pady=7)
        label.pack()

    def hide(self, _event=None):
        if self._job:
            self.widget.after_cancel(self._job)
            self._job = None
        if self._window:
            self._window.destroy()
            self._window = None


class LocalizedNavigationToolbar(NavigationToolbar2Tk):
    def __init__(self, canvas, window, pack_toolbar=False):
        self.toolitems = tuple(
            (tr(text), tr(tooltip), image, method)
            for text, tooltip, image, method in NavigationToolbar2Tk.toolitems
        )
        super().__init__(canvas, window, pack_toolbar=pack_toolbar)


class PlotPane(ttk.Frame):
    def __init__(self, parent, draw_callback: Callable, options: PlotOptions, compact: bool = False):
        super().__init__(parent)
        self.draw_callback = draw_callback
        self.options = options
        self.default_options = deepcopy(options)
        self.figure = Figure(figsize=(8.5, 6.2), dpi=100)
        self.axis = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, master=self)
        self.action_frame = ttk.Frame(self)
        actions = (
            ("Graph settings…", self.open_settings),
            ("Lines and shapes…", self.open_annotations),
            ("Save graph…", lambda: self.save_figure(False)),
            ("Save + annotations…", lambda: self.save_figure(True)),
            ("Copy graph", lambda: self.copy_image(False)),
            ("Copy + annotations", lambda: self.copy_image(True)),
        )
        if compact:
            for index, (text, command) in enumerate(actions):
                row, column = divmod(index, 3)
                ttk.Button(self.action_frame, text=text, command=command).grid(row=row, column=column, sticky="ew", padx=2, pady=2)
            for column in range(3):
                self.action_frame.columnconfigure(column, weight=1)
        else:
            for text, command in actions:
                ttk.Button(self.action_frame, text=text, command=command).pack(side="left", padx=2)
        self.action_frame.pack(fill="x", pady=(0, 2))
        self.toolbar_frame = ttk.Frame(self)
        self.toolbar_frame.pack(fill="x")
        self.toolbar = None
        self.settings_window = None
        self.settings_extension = None
        self.annotation_window = None
        self.annotations: list[AnnotationSpec] = []
        self.annotation_artists = []
        self.overlay_artists = []
        self._pending_annotation = None
        self._drawing_start = None
        self._rebuild_toolbar()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.vars = {
            "x_label": tk.StringVar(value=tr(options.x_label)),
            "x_unit": tk.StringVar(value=options.x_unit),
            "y_label": tk.StringVar(value=tr(options.y_label)),
            "y_unit": tk.StringVar(value=options.y_unit),
            "tick_font_family": tk.StringVar(value=options.tick_font_family),
            "tick_font_size": tk.StringVar(value=str(options.tick_font_size)),
            "tick_bold": tk.BooleanVar(value=options.tick_bold),
            "tick_color": tk.StringVar(value=options.tick_color),
            "x_font_family": tk.StringVar(value=options.x_font_family),
            "x_font_size": tk.StringVar(value=str(options.x_font_size)),
            "x_bold": tk.BooleanVar(value=options.x_bold),
            "x_color": tk.StringVar(value=options.x_color),
            "y_font_family": tk.StringVar(value=options.y_font_family),
            "y_font_size": tk.StringVar(value=str(options.y_font_size)),
            "y_bold": tk.BooleanVar(value=options.y_bold),
            "y_color": tk.StringVar(value=options.y_color),
            "legend_font_family": tk.StringVar(value=options.legend_font_family),
            "legend_font_size": tk.StringVar(value=str(options.legend_font_size)),
            "legend_bold": tk.BooleanVar(value=options.legend_bold),
            "legend_color": tk.StringVar(value=options.legend_color),
            "line_width": tk.StringVar(value=str(options.line_width)),
            "tick_width": tk.StringVar(value=str(options.tick_width)),
            "tick_length": tk.StringVar(value=str(options.tick_length)),
            "spine_width": tk.StringVar(value=str(options.spine_width)),
            "reverse_x": tk.BooleanVar(value=options.reverse_x),
            "legend": tk.BooleanVar(value=options.legend),
            "background": tk.StringVar(value=options.background),
            "x_min": tk.StringVar(value="" if options.x_min is None else str(options.x_min)),
            "x_max": tk.StringVar(value="" if options.x_max is None else str(options.x_max)),
            "y_min": tk.StringVar(value="" if options.y_min is None else str(options.y_min)),
            "y_max": tk.StringVar(value="" if options.y_max is None else str(options.y_max)),
            "x_tick": tk.StringVar(value="" if options.x_tick is None else str(options.x_tick)),
            "y_tick": tk.StringVar(value="" if options.y_tick is None else str(options.y_tick)),
        }
        self.canvas.mpl_connect("button_press_event", self._annotation_press)
        self.canvas.mpl_connect("button_release_event", self._annotation_release)

    def _rebuild_toolbar(self):
        if self.toolbar is not None:
            self.toolbar.destroy()
        self.toolbar = LocalizedNavigationToolbar(self.canvas, self.toolbar_frame, pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(side="left")

    def set_labels(self, x_name: str, x_unit: str, y_name: str, y_unit: str):
        for key, value in (("x_label", x_name), ("x_unit", x_unit), ("y_label", y_name), ("y_unit", y_unit)):
            self.vars[key].set(tr(value) if key.endswith("label") else value)

    def language_changed(self, old_language: str, new_language: str):
        for key in ("x_label", "y_label"):
            self.vars[key].set(translate_value(self.vars[key].get(), old_language, new_language))
        self._rebuild_toolbar()
        self.refresh()

    def _read_options(self):
        for key in (
            "x_label", "x_unit", "y_label", "y_unit",
            "tick_font_family", "x_font_family", "y_font_family", "legend_font_family",
            "tick_color", "x_color", "y_color", "legend_color",
        ):
            setattr(self.options, key, self.vars[key].get())
        self.options.background = canonical(self.vars["background"].get())
        self.options.line_width = _float_or_none(self.vars["line_width"].get()) or 2.0
        self.options.tick_width = _float_or_none(self.vars["tick_width"].get()) or 1.5
        self.options.tick_length = _float_or_none(self.vars["tick_length"].get()) or 6.0
        self.options.spine_width = _float_or_none(self.vars["spine_width"].get()) or 1.5
        for key, default in (("tick_font_size", 12.0), ("x_font_size", 13.0), ("y_font_size", 13.0), ("legend_font_size", 11.0)):
            setattr(self.options, key, _float_or_none(self.vars[key].get()) or default)
        self.options.font_size = self.options.tick_font_size
        self.options.reverse_x = self.vars["reverse_x"].get()
        for key in ("tick_bold", "x_bold", "y_bold", "legend_bold"):
            setattr(self.options, key, self.vars[key].get())
        self.options.legend = self.vars["legend"].get()
        for key in ("x_min", "x_max", "y_min", "y_max", "x_tick", "y_tick"):
            setattr(self.options, key, _float_or_none(self.vars[key].get()))

    def refresh(self):
        self._read_options()
        self.axis.clear()
        self.overlay_artists = []
        try:
            self.draw_callback(self.axis, self.options)
            apply_origin_style(self.figure, self.axis, self.options)
            handles, labels = self.axis.get_legend_handles_labels()
            if self.options.legend and handles:
                legend = self.axis.legend(frameon=False, fontsize=self.options.legend_font_size)
                ink = "#E8E8E8" if self.options.background == "Dark" else "black"
                for text in legend.get_texts():
                    text.set_color(self.options.legend_color or ink)
                    text.set_fontfamily(font_family_for_text(self.options.legend_font_family or "Arial", text.get_text()))
                    text.set_fontweight("bold" if self.options.legend_bold else "normal")
            self.figure.tight_layout()
            self._render_annotations()
            self.canvas.draw_idle()
        except Exception as exc:
            messagebox.showerror(tr("Plot error"), str(exc), parent=self)

    def register_overlay(self, artist):
        """Register an automatic label that follows annotation export visibility."""
        self.overlay_artists.append(artist)
        return artist

    def open_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            self.settings_window.focus_force()
            return
        self.settings_window = PlotSettingsWindow(self)

    def open_annotations(self):
        if self.annotation_window and self.annotation_window.winfo_exists():
            self.annotation_window.lift()
            self.annotation_window.focus_force()
            return
        self.annotation_window = AnnotationWindow(self)

    def restore_defaults(self):
        self.options = deepcopy(self.default_options)
        values = {
            "x_label": tr(self.options.x_label), "x_unit": self.options.x_unit,
            "y_label": tr(self.options.y_label), "y_unit": self.options.y_unit,
            "tick_font_family": self.options.tick_font_family, "tick_font_size": str(self.options.tick_font_size),
            "tick_bold": self.options.tick_bold, "tick_color": self.options.tick_color,
            "x_font_family": self.options.x_font_family, "x_font_size": str(self.options.x_font_size),
            "x_bold": self.options.x_bold, "x_color": self.options.x_color,
            "y_font_family": self.options.y_font_family, "y_font_size": str(self.options.y_font_size),
            "y_bold": self.options.y_bold, "y_color": self.options.y_color,
            "legend_font_family": self.options.legend_font_family, "legend_font_size": str(self.options.legend_font_size),
            "legend_bold": self.options.legend_bold, "legend_color": self.options.legend_color,
            "line_width": str(self.options.line_width), "tick_width": str(self.options.tick_width),
            "tick_length": str(self.options.tick_length), "spine_width": str(self.options.spine_width),
            "reverse_x": self.options.reverse_x, "legend": self.options.legend,
            "background": tr(self.options.background),
            "x_min": "" if self.options.x_min is None else str(self.options.x_min),
            "x_max": "" if self.options.x_max is None else str(self.options.x_max),
            "y_min": "" if self.options.y_min is None else str(self.options.y_min),
            "y_max": "" if self.options.y_max is None else str(self.options.y_max),
            "x_tick": "" if self.options.x_tick is None else str(self.options.x_tick),
            "y_tick": "" if self.options.y_tick is None else str(self.options.y_tick),
        }
        for key, value in values.items():
            self.vars[key].set(value)

    def begin_annotation(self, kind: str, line_style: str, color: str, line_width: float, callback: Callable | None = None):
        self._pending_annotation = (kind, line_style, color, line_width, callback)
        self._drawing_start = None
        self.canvas.get_tk_widget().configure(cursor="crosshair")

    def cancel_annotation(self):
        self._pending_annotation = None
        self._drawing_start = None
        try:
            self.canvas.get_tk_widget().configure(cursor="")
        except tk.TclError:
            pass

    def _annotation_press(self, event):
        if self._pending_annotation and event.inaxes is self.axis:
            x, y = self.axis.transAxes.inverted().transform((event.x, event.y))
            self._drawing_start = (float(x), float(y))

    def _annotation_release(self, event):
        if not self._pending_annotation or self._drawing_start is None or event.inaxes is not self.axis:
            return
        x, y = self.axis.transAxes.inverted().transform((event.x, event.y))
        x1, y1 = self._drawing_start
        if abs(x - x1) + abs(y - y1) < 0.005:
            return
        kind, style, color, width, callback = self._pending_annotation
        self.annotations.append(AnnotationSpec(kind, (x1, y1, float(x), float(y)), style, color, width))
        self.cancel_annotation()
        self.refresh()
        if callback:
            callback()

    def _render_annotations(self):
        self.annotation_artists = []
        style_map = {"Solid": "-", "Dashed": "--", "Dotted": ":", "Dash-dot": "-."}
        bbox = self.axis.get_window_extent()
        for item in self.annotations:
            x1, y1, x2, y2 = item.coordinates
            line_style = style_map.get(canonical(item.line_style), "-")
            if canonical(item.kind) == "Line":
                artist, = self.axis.plot((x1, x2), (y1, y2), transform=self.axis.transAxes, color=item.color, linewidth=item.line_width, linestyle=line_style, clip_on=False)
            else:
                kind = canonical(item.kind)
                if kind == "Circle":
                    radius_px = ((x2 - x1) ** 2 * bbox.width ** 2 + (y2 - y1) ** 2 * bbox.height ** 2) ** 0.5
                    width, height = 2 * radius_px / max(1.0, bbox.width), 2 * radius_px / max(1.0, bbox.height)
                    artist = Ellipse((x1, y1), width, height, transform=self.axis.transAxes, fill=False, edgecolor=item.color, linewidth=item.line_width, linestyle=line_style, clip_on=False)
                else:
                    left, bottom = min(x1, x2), min(y1, y2)
                    width, height = abs(x2 - x1), abs(y2 - y1)
                    patch_class = Rectangle if kind == "Rectangle" else Ellipse
                    if patch_class is Rectangle:
                        artist = Rectangle((left, bottom), width, height, transform=self.axis.transAxes, fill=False, edgecolor=item.color, linewidth=item.line_width, linestyle=line_style, clip_on=False)
                    else:
                        artist = Ellipse(((x1 + x2) / 2, (y1 + y2) / 2), width, height, transform=self.axis.transAxes, fill=False, edgecolor=item.color, linewidth=item.line_width, linestyle=line_style, clip_on=False)
                self.axis.add_patch(artist)
            self.annotation_artists.append(artist)

    def _with_annotation_visibility(self, visible: bool, callback: Callable):
        artists = [*self.annotation_artists, *self.overlay_artists]
        previous = [artist.get_visible() for artist in artists]
        try:
            for artist in artists:
                artist.set_visible(visible)
            self.canvas.draw()
            return callback()
        finally:
            for artist, state in zip(artists, previous):
                artist.set_visible(state)
            self.canvas.draw_idle()

    def copy_image(self, include_annotations: bool = False):
        try:
            data = self._with_annotation_visibility(include_annotations, lambda: figure_png_bytes(self.figure, dpi=300))
            copy_png_to_clipboard(data)
            messagebox.showinfo(tr("Copied"), tr("A 300 dpi image is now on the clipboard."), parent=self)
        except Exception as exc:
            messagebox.showerror(tr("Clipboard"), str(exc), parent=self)

    def save_figure(self, include_annotations: bool = False):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".png", filetypes=((tr("PNG image"), "*.png"), (tr("SVG vector"), "*.svg"), (tr("PDF vector"), "*.pdf")))
        if path:
            try:
                self._with_annotation_visibility(include_annotations, lambda: self.figure.savefig(path, dpi=300, bbox_inches="tight"))
            except Exception as exc:
                messagebox.showerror(tr("Save error"), str(exc), parent=self)


class SpectrumTree(ttk.Frame):
    def __init__(self, parent, on_change: Callable):
        super().__init__(parent)
        self.on_change = on_change
        self.spectra: list[Spectrum] = []
        default_font = tkfont.nametofont("TkDefaultFont")
        row_height = max(30, int(default_font.metrics("linespace") * 1.65))
        style = ttk.Style(self)
        style.configure("LabPlotter.Treeview", rowheight=row_height, padding=(3, 3))
        style.configure("LabPlotter.Treeview.Heading", font=(default_font.actual("family"), default_font.actual("size"), "bold"))
        self.tree = ttk.Treeview(self, columns=("visible", "name", "source"), show="headings", selectmode="extended", height=10, style="LabPlotter.Treeview")
        self.tree.heading("visible", text="Plot")
        self.tree.heading("name", text="Series name")
        self.tree.heading("source", text="Source")
        self.tree.column("visible", width=58, anchor="center", stretch=False)
        self.tree.column("name", width=250)
        self.tree.column("source", width=220)
        vertical = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", self._double_click)

    def add(self, spectra: list[Spectrum]):
        self.spectra.extend(spectra)
        self.refresh()
        self.on_change()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for spectrum in self.spectra:
            self.tree.insert("", "end", iid=spectrum.uid, values=("✓" if spectrum.visible else "", spectrum.name, Path(spectrum.source).name))

    def _double_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        spectrum = next((s for s in self.spectra if s.uid == item), None)
        if not spectrum:
            return
        if self.tree.identify_column(event.x) == "#1":
            spectrum.visible = not spectrum.visible
        else:
            name = simpledialog.askstring(tr("Rename series"), tr("Series name"), initialvalue=spectrum.name, parent=self)
            if name:
                spectrum.name = name.strip()
        self.refresh()
        self.on_change()

    def remove_selected(self):
        selected = set(self.tree.selection())
        self.spectra = [s for s in self.spectra if s.uid not in selected]
        self.refresh()
        self.on_change()

    def color_selected(self):
        selected = set(self.tree.selection())
        if not selected:
            return
        color = colorchooser.askcolor(parent=self, title=tr("Choose line color"))[1]
        if color:
            for spectrum in self.spectra:
                if spectrum.uid in selected:
                    spectrum.metadata["color"] = color
            self.on_change()

    def visible(self) -> list[Spectrum]:
        return [s for s in self.spectra if s.visible]


class FTIRTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        controls = ttk.Frame(paned, padding=7)
        controls.configure(width=560)
        graph = ttk.Frame(paned, padding=5)
        paned.add(controls, weight=0)
        paned.add(graph, weight=1)

        row = ttk.Frame(controls)
        ttk.Button(row, text="Add FTIR files…", command=self.add_dialog).pack(side="left")
        ttk.Button(row, text="Remove", command=lambda: self.tree.remove_selected()).pack(side="left", padx=4)
        ttk.Button(row, text="Color…", command=lambda: self.tree.color_selected()).pack(side="left")
        row.pack(fill="x", pady=(0, 5))
        self.tree = SpectrumTree(controls, self._refresh)
        self.tree.pack(fill="both", expand=True)

        process = ttk.LabelFrame(controls, text="FTIR processing", padding=6)
        process.pack(fill="x", pady=7)
        self.baseline = tk.BooleanVar(value=False)
        self.baseline_method = tk.StringVar(value="Linear endpoints (diagonal)")
        self.orientation = tk.StringVar(value="Transmittance (downward bands)")
        self.lam = tk.StringVar(value="1e8")
        self.p = tk.StringVar(value="0.01")
        self.poly_order = tk.StringVar(value="2")
        self.normalization = tk.BooleanVar(value=False)
        self.normalization_mode = tk.StringVar(value="Min-max (0–1)")
        self.peaks = tk.BooleanVar(value=False)
        self.prominence = tk.StringVar(value="0.03")
        ttk.Checkbutton(process, text="Baseline correction", variable=self.baseline, command=self._refresh).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(process, text="Method").grid(row=1, column=0, sticky="w")
        method_box = ttk.Combobox(process, textvariable=self.baseline_method, state="readonly", width=32, values=BASELINE_METHODS)
        method_box.grid(row=1, column=1, sticky="ew", pady=2)
        method_box.bind("<<ComboboxSelected>>", lambda _: self._refresh())
        help_box = tk.Label(process, text="?", width=2, relief="solid", borderwidth=1, background="#eef3f8", cursor="hand2")
        help_box.grid(row=1, column=2, padx=(5, 0))
        HoverTooltip(help_box, lambda: tr(BASELINE_HELP.get(canonical(self.baseline_method.get()), "")))
        ttk.Label(process, text="Spectrum").grid(row=2, column=0, sticky="w")
        orientation_box = ttk.Combobox(process, textvariable=self.orientation, state="readonly", width=32, values=("Transmittance (downward bands)", "Absorbance (upward peaks)"))
        orientation_box.grid(row=2, column=1, sticky="ew")
        orientation_box.bind("<<ComboboxSelected>>", lambda _: self._orientation_changed())
        orientation_help = tk.Label(process, text="?", width=2, relief="solid", borderwidth=1, background="#eef3f8", cursor="hand2")
        orientation_help.grid(row=2, column=2, padx=(5, 0))
        HoverTooltip(orientation_help, lambda: tr("Transmittance has downward bands, so an upper baseline is estimated and corrected as T/baseline × 100. Absorbance has upward peaks, so a lower baseline is estimated and subtracted."))
        ttk.Label(process, text="Smoothness λ").grid(row=3, column=0, sticky="w")
        ttk.Entry(process, textvariable=self.lam, width=10).grid(row=3, column=1, sticky="e")
        ttk.Label(process, text="Asymmetry p").grid(row=4, column=0, sticky="w")
        ttk.Entry(process, textvariable=self.p, width=10).grid(row=4, column=1, sticky="e")
        ttk.Label(process, text="Polynomial order").grid(row=5, column=0, sticky="w")
        ttk.Entry(process, textvariable=self.poly_order, width=10).grid(row=5, column=1, sticky="e")
        ttk.Checkbutton(process, text="Normalization", variable=self.normalization, command=self._refresh).grid(row=6, column=0, columnspan=3, sticky="w", pady=(5, 0))
        normalization_box = ttk.Combobox(process, textvariable=self.normalization_mode, state="readonly", values=("Min-max (0–1)", "Maximum = 1", "Vector (L2)"), width=32)
        normalization_box.grid(row=7, column=0, columnspan=3, sticky="ew")
        normalization_box.bind("<<ComboboxSelected>>", lambda _: self._refresh())
        ttk.Checkbutton(process, text="Mark peaks", variable=self.peaks, command=self._refresh).grid(row=8, column=0, sticky="w", pady=(5, 0))
        ttk.Entry(process, textvariable=self.prominence, width=8).grid(row=8, column=1, sticky="e")
        ttk.Button(process, text="Apply processing", command=self._refresh).grid(row=9, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        ttk.Button(process, text="Common FTIR range reference…", command=self.show_range_library).grid(row=10, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        process.columnconfigure(1, weight=1)

        options = PlotOptions("Wavenumber", "cm^-1", "Transmittance", "%", line_width=2.0, reverse_x=True)
        self.plot = PlotPane(graph, self._draw, options)
        self.plot.pack(fill="both", expand=True)
        self._cache: dict[tuple, np.ndarray] = {}

    def add_dialog(self):
        paths = filedialog.askopenfilenames(parent=self, filetypes=((tr("FTIR data"), "*.csv *.txt *.tsv *.xlsx"), (tr("All files"), "*.*")))
        self.add_paths(paths)

    def add_paths(self, paths):
        loaded = []
        for path in paths:
            try:
                loaded.append(parse_ftir_file(path))
            except Exception as exc:
                messagebox.showerror(tr("FTIR import"), f"{Path(path).name}\n{exc}", parent=self)
        if loaded:
            self.tree.add(loaded)

    def _processed(self, spectrum: Spectrum) -> np.ndarray:
        try:
            lam, p, poly_order = float(self.lam.get()), float(self.p.get()), int(self.poly_order.get())
        except ValueError:
            lam, p, poly_order = 1e8, 0.01, 2
        method = canonical(self.baseline_method.get())
        orientation = canonical(self.orientation.get())
        normalization_mode = canonical(self.normalization_mode.get())
        key = (spectrum.uid, self.baseline.get(), method, orientation, lam, p, poly_order, self.normalization.get(), normalization_mode)
        if key not in self._cache:
            self._cache[key] = process_ftir(
                spectrum.x, spectrum.y, self.baseline.get(), method, orientation,
                lam, p, poly_order, self.normalization.get(), normalization_mode
            )
        return self._cache[key]

    def _draw(self, axis, options):
        for spectrum in self.tree.visible():
            y = self._processed(spectrum)
            kwargs = {"color": spectrum.metadata["color"]} if spectrum.metadata.get("color") else {}
            line, = axis.plot(spectrum.x, y, label=spectrum.name, linewidth=options.line_width, **kwargs)
            if self.peaks.get():
                try:
                    fraction = float(self.prominence.get())
                except ValueError:
                    fraction = 0.03
                for index in ftir_peak_indices(y, fraction, troughs=canonical(self.orientation.get()).startswith("Transmittance")):
                    axis.annotate(f"{spectrum.x[index]:.0f}", (spectrum.x[index], y[index]), xytext=(0, -15), textcoords="offset points", ha="center", va="top", fontsize=max(7, options.font_size - 3), color=line.get_color(), rotation=90)
        if not self.tree.visible():
            axis.text(0.5, 0.5, tr("Add one or more FTIR files"), ha="center", va="center", transform=axis.transAxes)

    def _refresh(self):
        if hasattr(self, "plot"):
            self.plot.refresh()

    def _orientation_changed(self):
        if canonical(self.orientation.get()).startswith("Transmittance"):
            self.plot.set_labels("Wavenumber", "cm^-1", "Transmittance", "%")
        else:
            self.plot.set_labels("Wavenumber", "cm^-1", "Absorbance", "")
        self._refresh()

    def show_range_library(self):
        top = tk.Toplevel(self)
        top.title(tr("Common FTIR ranges · reference only"))
        top.geometry("820x520")
        top.minsize(650, 400)
        ttk.Label(top, text=tr("Ranges overlap and do not constitute a unique functional-group assignment."), foreground="#555555", padding=8).pack(anchor="w")
        default_font = tkfont.nametofont("TkDefaultFont")
        style = ttk.Style(top)
        style.configure("FTIRReference.Treeview", rowheight=max(32, int(default_font.metrics("linespace") * 1.7)), padding=(3, 3))
        body = ttk.Frame(top, padding=(8, 0, 8, 8))
        body.pack(fill="both", expand=True)
        tree = ttk.Treeview(body, columns=("group", "range"), show="headings", height=len(FTIR_RANGES), style="FTIRReference.Treeview")
        tree.heading("group", text=tr("Candidate vibration / group"))
        tree.heading("range", text=tr("Approximate range"))
        tree.column("group", width=430); tree.column("range", width=260)
        for group, value in FTIR_RANGES:
            tree.insert("", "end", values=(tr(group), value))
        vertical = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vertical.set)
        tree.pack(side="left", fill="both", expand=True)
        vertical.pack(side="right", fill="y")


class NanoDropTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        controls, graph = ttk.Frame(paned, padding=7), ttk.Frame(paned, padding=5)
        paned.add(controls, weight=0); paned.add(graph, weight=1)
        row = ttk.Frame(controls)
        ttk.Button(row, text="Add NanoDrop file…", command=self.add_dialog).pack(side="left")
        ttk.Button(row, text="Remove", command=lambda: self.tree.remove_selected()).pack(side="left", padx=4)
        ttk.Button(row, text="Color…", command=lambda: self.tree.color_selected()).pack(side="left")
        row.pack(fill="x", pady=(0, 5))
        self.tree = SpectrumTree(controls, self._refresh)
        self.tree.pack(fill="both", expand=True)
        self.show_blank = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="Plot one Blank spectrum", variable=self.show_blank, command=self._toggle_blank).pack(anchor="w", pady=6)
        ttk.Label(controls, text="Double-click Plot to show/hide a curve.\nDouble-click a name to rename it.", foreground="#555555").pack(anchor="w")
        self.plot = PlotPane(graph, self._draw, PlotOptions("Wavelength", "nm", "Absorbance", "", line_width=2.0))
        self.plot.pack(fill="both", expand=True)

    def add_dialog(self):
        paths = filedialog.askopenfilenames(parent=self, filetypes=((tr("NanoDrop exports"), "*.xml *.xlsx"), (tr("All files"), "*.*")))
        self.add_paths(paths)

    def add_paths(self, paths):
        loaded = []
        for path in paths:
            try:
                loaded.extend(parse_nanodrop_file(path))
            except Exception as exc:
                messagebox.showerror(tr("NanoDrop import"), f"{Path(path).name}\n{exc}", parent=self)
        if loaded:
            self.tree.add(loaded)
            self._toggle_blank()

    def _toggle_blank(self):
        blanks = [s for s in self.tree.spectra if s.metadata.get("blank")]
        for item in blanks:
            item.visible = False
        if self.show_blank.get() and blanks:
            blanks[0].visible = True
        self.tree.refresh()
        self._refresh()

    def _draw(self, axis, options):
        for spectrum in self.tree.visible():
            kwargs = {"color": "#777777", "linestyle": "--"} if spectrum.metadata.get("blank") else {}
            if spectrum.metadata.get("color"):
                kwargs["color"] = spectrum.metadata["color"]
            axis.plot(spectrum.x, spectrum.y, label=spectrum.name, linewidth=options.line_width, **kwargs)
        if not self.tree.visible():
            axis.text(0.5, 0.5, tr("Add a NanoDrop XML/XLSX export"), ha="center", va="center", transform=axis.transAxes)

    def _refresh(self):
        if hasattr(self, "plot"):
            self.plot.refresh()


class SSNMRTab(ttk.Frame):
    PHASE_MODES = (
        "Automatic phase",
        "Saved TopSpin phase",
        "Magnitude (phase independent)",
        "No phase correction",
    )

    def __init__(self, parent):
        super().__init__(parent)
        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        controls, graph = ttk.Frame(paned, padding=7), ttk.Frame(paned, padding=5)
        controls.configure(width=570)
        paned.add(controls, weight=0); paned.add(graph, weight=1)
        row = ttk.Frame(controls)
        ttk.Button(row, text="Add Bruker ZIP…", command=self.add_dialog).pack(side="left")
        ttk.Button(row, text="Remove", command=lambda: self.tree.remove_selected()).pack(side="left", padx=4)
        ttk.Button(row, text="Color…", command=lambda: self.tree.color_selected()).pack(side="left")
        row.pack(fill="x", pady=(0, 5))
        self.tree = SpectrumTree(controls, self._refresh)
        self.tree.pack(fill="both", expand=True)
        ttk.Label(
            controls,
            text="All supported 1D FIDs are listed. When 13C data are present, carbon spectra are shown by default and other nuclei remain hidden.",
            foreground="#555555",
            wraplength=520,
        ).pack(anchor="w", pady=(5, 0))

        process = ttk.LabelFrame(controls, text="ssNMR processing", padding=6)
        process.pack(fill="x", pady=7)
        self.saved_window = tk.BooleanVar(value=True)
        self.phase_mode = tk.StringVar(value="Automatic phase")
        self.extra_lb = tk.StringVar(value="0")
        self.phase0 = tk.StringVar(value="0")
        self.phase1 = tk.StringVar(value="0")
        self.baseline = tk.BooleanVar(value=False)
        self.normalization = tk.BooleanVar(value=True)
        self.vertical_offset = tk.StringVar(value="0")
        self.peaks = tk.BooleanVar(value=False)
        self.prominence = tk.StringVar(value="0.05")
        ttk.Checkbutton(process, text="Use saved TopSpin window function", variable=self.saved_window, command=self._refresh).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(process, text="Phase mode").grid(row=1, column=0, sticky="w")
        phase_box = ttk.Combobox(process, textvariable=self.phase_mode, values=self.PHASE_MODES, state="readonly", width=31)
        phase_box.grid(row=1, column=1, sticky="ew", pady=2)
        phase_box.bind("<<ComboboxSelected>>", lambda _: self._refresh())
        phase_help = tk.Label(process, text="?", width=2, relief="solid", borderwidth=1, background="#eef3f8", cursor="hand2")
        phase_help.grid(row=1, column=2, padx=(5, 0))
        HoverTooltip(phase_help, lambda: tr("Automatic phase minimizes dispersive/negative signal in the expected nucleus range. Saved TopSpin phase uses PHC0/PHC1 from procs. Magnitude is phase-independent but broadens line shapes."))
        fields = (
            ("Additional line broadening (Hz)", self.extra_lb, 2),
            ("P0 adjustment (degrees)", self.phase0, 3),
            ("P1 adjustment (degrees)", self.phase1, 4),
            ("Vertical offset", self.vertical_offset, 5),
        )
        for label, variable, row_number in fields:
            ttk.Label(process, text=label).grid(row=row_number, column=0, sticky="w")
            ttk.Entry(process, textvariable=variable, width=12).grid(row=row_number, column=1, sticky="e", pady=1)
        ttk.Checkbutton(process, text="Linear edge baseline", variable=self.baseline, command=self._refresh).grid(row=6, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(process, text="Normalize each spectrum", variable=self.normalization, command=self._refresh).grid(row=7, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(process, text="Mark peaks", variable=self.peaks, command=self._refresh).grid(row=8, column=0, sticky="w")
        ttk.Entry(process, textvariable=self.prominence, width=10).grid(row=8, column=1, sticky="e")
        ttk.Button(process, text="Apply processing", command=self._refresh).grid(row=9, column=0, columnspan=3, sticky="ew", pady=(5, 0))
        ttk.Button(process, text="View acquisition details…", command=self.view_details).grid(row=10, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        process.columnconfigure(1, weight=1)

        options = PlotOptions("Chemical shift", "ppm", "Intensity", "a.u.", line_width=2.0, reverse_x=True, x_min=-20.0, x_max=250.0, x_tick=50.0)
        self.plot = PlotPane(graph, self._draw, options)
        self.plot.pack(fill="both", expand=True)
        self._cache: dict[tuple, np.ndarray] = {}

    def add_dialog(self):
        paths = filedialog.askopenfilenames(parent=self, filetypes=((tr("Bruker/TopSpin ZIP"), "*.zip"), (tr("All files"), "*.*")))
        self.add_paths(paths)

    def add_paths(self, paths):
        loaded: list[Spectrum] = []
        skipped: list[str] = []
        for path in paths:
            try:
                spectra, omitted = parse_bruker_zip(path)
                loaded.extend(spectra)
                skipped.extend(f"{Path(path).name}: {item}" for item in omitted)
            except Exception as exc:
                messagebox.showerror(tr("ssNMR import"), f"{Path(path).name}\n{exc}", parent=self)
        if loaded:
            self.tree.add(loaded)
            carbon_count = sum(item.metadata.get("nucleus") == "13C" for item in loaded)
            text = tr("Imported {count} one-dimensional spectra; {carbon} are 13C spectra.", count=len(loaded), carbon=carbon_count)
            if skipped:
                text += "\n\n" + tr("Skipped:") + "\n" + "\n".join(skipped)
            messagebox.showinfo(tr("ssNMR import"), text, parent=self)

    @staticmethod
    def _float(variable: tk.StringVar, default: float = 0.0) -> float:
        try:
            return float(variable.get())
        except ValueError:
            return default

    def _processed(self, spectrum: Spectrum) -> np.ndarray:
        mode = canonical(self.phase_mode.get())
        extra_lb = self._float(self.extra_lb)
        phase0, phase1 = self._float(self.phase0), self._float(self.phase1)
        key = (spectrum.uid, self.saved_window.get(), mode, extra_lb, phase0, phase1, self.baseline.get(), self.normalization.get())
        if key not in self._cache:
            metadata = spectrum.metadata
            _x, values = process_bruker_1d(
                metadata["raw_fid"], metadata["acquisition"], metadata["processing"],
                use_saved_window=self.saved_window.get(), phase_mode=mode,
                extra_line_broadening=extra_lb, phase0=phase0, phase1=phase1,
                baseline=self.baseline.get(), normalize=self.normalization.get(),
            )
            self._cache[key] = values
        return self._cache[key]

    def _draw(self, axis, options):
        visible = self.tree.visible()
        offset = self._float(self.vertical_offset)
        for curve_index, spectrum in enumerate(visible):
            values = self._processed(spectrum) + curve_index * offset
            kwargs = {"color": spectrum.metadata["color"]} if spectrum.metadata.get("color") else {}
            line, = axis.plot(spectrum.x, values, label=spectrum.name, linewidth=options.line_width, **kwargs)
            if self.peaks.get():
                prominence = max(0.0, self._float(self.prominence, 0.05))
                for index in ftir_peak_indices(values, prominence, troughs=False):
                    axis.annotate(f"{spectrum.x[index]:.1f}", (spectrum.x[index], values[index]), xytext=(0, 8), textcoords="offset points", ha="center", va="bottom", fontsize=max(7, options.font_size - 3), color=line.get_color(), rotation=90)
        if not visible:
            axis.text(0.5, 0.5, tr("Add a Bruker ssNMR ZIP archive"), ha="center", va="center", transform=axis.transAxes)

    def view_details(self):
        selected = list(self.tree.tree.selection())
        if len(selected) != 1:
            messagebox.showinfo(tr("Acquisition details"), tr("Select exactly one spectrum."), parent=self)
            return
        spectrum = next(item for item in self.tree.spectra if item.uid == selected[0])
        metadata = spectrum.metadata
        acquisition, processing = metadata["acquisition"], metadata["processing"]
        lines = (
            f"{tr('Experiment')}: {metadata.get('experiment', '')}",
            f"{tr('Nucleus')}: {metadata.get('nucleus', '')}",
            f"{tr('Pulse program')}: {metadata.get('pulse_program', '')}",
            f"{tr('Title')}: {metadata.get('title', '')}",
            f"{tr('Scans')}: {metadata.get('ns', '')}",
            f"{tr('MAS rate')}: {metadata.get('mas_hz', 0) / 1000:g} kHz",
            f"{tr('Spectral width')}: {float(acquisition.get('SW_h', 0)):g} Hz",
            f"{tr('Saved line broadening')}: {float(processing.get('LB', 0)):g} Hz",
            f"PHC0 / PHC1: {processing.get('PHC0', 0)} / {processing.get('PHC1', 0)}",
            f"{tr('Group delay')}: {acquisition.get('GRPDLY', 0)}",
        )
        messagebox.showinfo(tr("Acquisition details"), "\n".join(lines), parent=self)

    def _refresh(self):
        if hasattr(self, "plot"):
            self.plot.refresh()


class ZoomImageViewer(ttk.Frame):
    def __init__(self, parent, image: Image.Image):
        super().__init__(parent)
        self.original = image.copy().convert("RGBA")
        self.photo = None
        self.zoom = tk.StringVar(value="100%")
        controls = ttk.Frame(self)
        controls.pack(fill="x", pady=(0, 5))
        ttk.Label(controls, text=tr("Embedded source image: {width} × {height} px", width=image.width, height=image.height)).pack(side="left")
        ttk.Button(controls, text="Fit window", command=self.fit_window).pack(side="right")
        box = ttk.Combobox(controls, textvariable=self.zoom, values=("50%", "75%", "100%", "125%", "150%", "200%", "300%"), state="readonly", width=7)
        box.pack(side="right", padx=5)
        box.bind("<<ComboboxSelected>>", lambda _event: self.render())
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, background="#666666", highlightthickness=0)
        vertical = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        horizontal = ttk.Scrollbar(body, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        self.canvas.bind("<Control-MouseWheel>", self._wheel_zoom)
        self.after_idle(self.render)

    def _scale(self) -> float:
        try:
            return max(0.1, float(self.zoom.get().rstrip("%")) / 100.0)
        except ValueError:
            return 1.0

    def render(self):
        scale = self._scale()
        size = (max(1, round(self.original.width * scale)), max(1, round(self.original.height * scale)))
        image = self.original if size == self.original.size else self.original.resize(size, Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(image)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.canvas.configure(scrollregion=(0, 0, size[0], size[1]))

    def fit_window(self):
        width = max(1, self.canvas.winfo_width() - 8)
        height = max(1, self.canvas.winfo_height() - 8)
        scale = min(width / self.original.width, height / self.original.height)
        self.zoom.set(f"{max(10, min(400, round(scale * 100)))}%")
        self.render()

    def _wheel_zoom(self, event):
        current = self._scale() * 100
        current *= 1.15 if event.delta > 0 else 1 / 1.15
        self.zoom.set(f"{max(10, min(400, round(current)))}%")
        self.render()


class OCRReviewPane(ttk.Frame):
    """Side-by-side source image and editable, explicitly reviewed OCR table."""

    def __init__(self, parent, library: ParticleLibrary, particle: str, kind: str, replicate: int, raw: bytes, on_saved: Callable):
        super().__init__(parent, padding=8)
        self.library = library
        self.particle = particle
        self.kind = kind
        self.replicate = replicate
        self.raw = raw
        self.on_saved = on_saved
        self.columns: tuple[str, ...] = ()
        self.confidence: list[list[float | None]] = []
        self.engine = ""
        self.cell_vars: list[list[tk.StringVar]] = []

        title = ttk.Frame(self)
        title.pack(fill="x", pady=(0, 7))
        ttk.Label(title, text=tr("OCR reading · {kind} measurement {number}", kind=kind, number=replicate), font=("Arial", 13, "bold")).pack(side="left")
        self.status = tk.StringVar(value=tr("Not reviewed"))
        ttk.Label(title, textvariable=self.status, foreground="#8A4B08").pack(side="right")

        split = ttk.Panedwindow(self, orient="horizontal")
        split.pack(fill="both", expand=True)
        source = ttk.LabelFrame(split, text=tr("Original result image"), padding=6)
        editor = ttk.LabelFrame(split, text=tr("Editable OCR result"), padding=6)
        split.add(source, weight=1)
        split.add(editor, weight=1)
        ZoomImageViewer(source, Image.open(BytesIO(raw))).pack(fill="both", expand=True)

        ttk.Label(
            editor,
            text=tr("OCR is a draft. Compare every value with the source image; low-confidence cells are highlighted."),
            foreground="#7A3E00",
            wraplength=600,
        ).pack(fill="x", pady=(0, 6))
        table_shell = ttk.Frame(editor)
        table_shell.pack(fill="both", expand=True)
        self.table_canvas = tk.Canvas(table_shell, background="white", highlightthickness=0)
        vbar = ttk.Scrollbar(table_shell, orient="vertical", command=self.table_canvas.yview)
        hbar = ttk.Scrollbar(table_shell, orient="horizontal", command=self.table_canvas.xview)
        self.table_canvas.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        self.table_canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        table_shell.rowconfigure(0, weight=1)
        table_shell.columnconfigure(0, weight=1)
        self.table = tk.Frame(self.table_canvas, background="white")
        self.table_window = self.table_canvas.create_window((0, 0), window=self.table, anchor="nw")
        self.table.bind("<Configure>", lambda _event: self.table_canvas.configure(scrollregion=self.table_canvas.bbox("all")))
        self.table_canvas.bind("<Configure>", self._resize_table)

        buttons = ttk.Frame(editor)
        buttons.pack(fill="x", pady=(7, 0))
        self.run_button = ttk.Button(buttons, text=tr("Run OCR again"), command=self.run_ocr)
        self.run_button.pack(side="left")
        ttk.Button(buttons, text=tr("Add row"), command=self.add_row).pack(side="left", padx=4)
        ttk.Button(buttons, text=tr("Remove last row"), command=self.remove_last_row).pack(side="left")
        ttk.Button(buttons, text=tr("Save reviewed result to library"), command=self.save_reviewed).pack(side="right")

        saved = self.library.ocr_result(particle, kind, replicate)
        if saved and saved.get("status") != "failed":
            self.set_table(OCRTable(tuple(saved["columns"]), saved["rows"], saved["confidence"], [], saved["engine"]))
            self.status.set(tr("Reviewed and saved") if saved.get("status") == "reviewed" else tr("Auto OCR draft · review required"))
        else:
            self.after_idle(self.run_ocr)

    def _resize_table(self, event):
        requested = self.table.winfo_reqwidth()
        self.table_canvas.itemconfigure(self.table_window, width=max(requested, event.width))

    def set_table(self, result: OCRTable):
        for child in self.table.winfo_children():
            child.destroy()
        self.columns = tuple(result.columns)
        self.confidence = result.confidence
        self.engine = result.engine
        self.cell_vars = []
        default_font = tkfont.nametofont("TkDefaultFont")
        family = default_font.actual("family")
        size = int(default_font.actual("size")) + 1
        for column, label in enumerate(self.columns):
            tk.Label(self.table, text=tr(label), font=(family, size, "bold"), background="#E7EEF6", relief="solid", borderwidth=1, padx=6, pady=6).grid(row=0, column=column, sticky="nsew")
            self.table.columnconfigure(column, weight=3 if column == 0 else 1, minsize=115 if column else 270)
        for row_index, values in enumerate(result.rows):
            variables: list[tk.StringVar] = []
            for column in range(len(self.columns)):
                value = values[column] if column < len(values) else ""
                variable = tk.StringVar(value=value)
                score = result.confidence[row_index][column] if row_index < len(result.confidence) and column < len(result.confidence[row_index]) else None
                background = "#FFF1A8" if score is not None and score < 0.85 else "white"
                tk.Entry(self.table, textvariable=variable, font=(family, size), background=background, relief="solid", borderwidth=1).grid(row=row_index + 1, column=column, sticky="nsew", ipady=5)
                variables.append(variable)
            self.cell_vars.append(variables)
        self.status.set(tr("OCR draft · review required"))

    def run_ocr(self):
        self.run_button.configure(state="disabled")
        self.status.set(tr("Running local OCR…"))

        def worker():
            try:
                result = run_table_ocr(self.raw)
                self.after(0, lambda: self._ocr_finished(result, None))
            except Exception as exc:
                self.after(0, lambda: self._ocr_finished(None, exc))

        threading.Thread(target=worker, daemon=True).start()

    def _ocr_finished(self, result: OCRTable | None, error: Exception | None):
        if not self.winfo_exists():
            return
        self.run_button.configure(state="normal")
        if error:
            self.status.set(tr("OCR failed"))
            messagebox.showerror(tr("OCR failed"), str(error), parent=self.winfo_toplevel())
            return
        self.set_table(result)

    def add_row(self):
        rows = self.values()
        rows.append([""] * len(self.columns))
        confidence = [*self.confidence, [None] * len(self.columns)]
        self.set_table(OCRTable(self.columns, rows, confidence, [], self.engine))

    def remove_last_row(self):
        rows = self.values()
        if rows:
            rows.pop()
            confidence = self.confidence[: len(rows)]
            self.set_table(OCRTable(self.columns, rows, confidence, [], self.engine))

    def values(self) -> list[list[str]]:
        return [[variable.get().strip() for variable in row] for row in self.cell_vars]

    def save_reviewed(self):
        if not self.cell_vars or not messagebox.askyesno(
            tr("Confirm reviewed OCR"),
            tr("Have you compared the editable result with the source image? Save this reviewed table to the particle library?"),
            parent=self.winfo_toplevel(),
        ):
            return
        rows = self.values()
        self.library.save_ocr_result(self.particle, self.kind, self.replicate, self.columns, rows, self.confidence, self.engine, reviewed=True)
        self.status.set(tr("Reviewed and saved"))
        self.on_saved()
        messagebox.showinfo(tr("OCR saved"), tr("Reviewed OCR result saved to the particle library."), parent=self.winfo_toplevel())


class SeriesColorSettingsExtension:
    """Color controls shared by ZetaSizer distribution and batch plots."""

    title = "Series colors"

    def __init__(self, owner, plot_key: str, item_kind: str):
        self.owner = owner
        self.plot_key = plot_key
        self.item_kind = item_kind
        state = owner.color_settings[plot_key]
        scope_text = "One color for all" if state["scope"] == "all" else "Set colors by particle"
        self.color_scope = tk.StringVar(value=tr(scope_text))
        self.global_color = tk.StringVar(value=state["global_color"])
        self.color_vars: dict[str, tk.StringVar] = {}

    def build_colors(self, parent):
        self.color_vars = {}
        frame = ttk.LabelFrame(parent, text=tr("Curve and bar colors"), padding=8)
        frame.pack(fill="x", pady=(0, 8))
        ttk.Label(frame, text=tr("Color mode")).grid(row=0, column=0, sticky="e", padx=(4, 3), pady=3)
        ttk.Combobox(
            frame,
            textvariable=self.color_scope,
            values=(tr("One color for all"), tr("Set colors by particle")),
            state="readonly",
            width=24,
        ).grid(row=0, column=1, columnspan=2, sticky="w", pady=3)
        ttk.Label(frame, text=tr("Color for all {items}", items=tr(self.item_kind))).grid(row=1, column=0, sticky="e", padx=(4, 3), pady=3)
        ttk.Entry(frame, textvariable=self.global_color, width=14).grid(row=1, column=1, sticky="w", pady=3)
        ttk.Button(frame, text=tr("Choose…"), command=lambda: self._choose_color(self.global_color)).grid(row=1, column=2, sticky="w", padx=4)
        frame.columnconfigure(1, weight=1)

        individual = ttk.LabelFrame(parent, text=tr("Individual particle colors"), padding=8)
        individual.pack(fill="both", expand=True, pady=(0, 8))
        ttk.Label(individual, text=tr("Particle"), font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Label(individual, text=tr("Color"), font=("TkDefaultFont", 9, "bold")).grid(row=0, column=1, sticky="w", padx=4, pady=4)
        names = self.owner.active_names()
        if not names:
            ttk.Label(individual, text=tr("Add particles to the plots to set individual colors."), foreground="#555555").grid(
                row=1, column=0, columnspan=3, sticky="w", padx=4, pady=5
            )
        for index, name in enumerate(names, start=1):
            variable = tk.StringVar(value=self.owner.series_color(self.plot_key, name, index - 1))
            self.color_vars[name] = variable
            ttk.Label(individual, text=name).grid(row=index, column=0, sticky="w", padx=4, pady=3)
            ttk.Entry(individual, textvariable=variable, width=14).grid(row=index, column=1, sticky="w", padx=4, pady=3)
            ttk.Button(individual, text=tr("Choose…"), command=lambda item=variable: self._choose_color(item)).grid(row=index, column=2, sticky="w", padx=4, pady=3)
        individual.columnconfigure(0, weight=1)

    @staticmethod
    def _choose_color(variable: tk.StringVar):
        selected = colorchooser.askcolor(color=variable.get() or "#1F77B4")[1]
        if selected:
            variable.set(selected.upper())

    def _store_colors(self):
        state = self.owner.color_settings[self.plot_key]
        state["scope"] = "all" if canonical(self.color_scope.get()) == "One color for all" else "individual"
        default = ZETA_COLOR_DEFAULTS[self.plot_key]["global_color"]
        state["global_color"] = normalized_color(self.global_color.get(), default)
        colors = state.setdefault("colors", {})
        for index, (name, variable) in enumerate(self.color_vars.items()):
            colors[name] = normalized_color(variable.get(), SERIES_PALETTE[index % len(SERIES_PALETTE)])
        self.global_color.set(state["global_color"])
        self.owner.save_color_settings()

    def apply(self):
        self._store_colors()
        self.owner._refresh()

    def variables(self):
        return [self.color_scope, self.global_color, *self.color_vars.values()]

    def restore_colors(self):
        self.owner.color_settings[self.plot_key] = deepcopy(ZETA_COLOR_DEFAULTS[self.plot_key])
        default = self.owner.color_settings[self.plot_key]
        self.color_scope.set(tr("One color for all") if default["scope"] == "all" else tr("Set colors by particle"))
        self.global_color.set(default["global_color"])
        for index, (name, variable) in enumerate(self.color_vars.items()):
            variable.set(self.owner.series_color(self.plot_key, name, index))
        self.owner.save_color_settings()

    def restore_defaults(self):
        self.restore_colors()


class BatchSettingsExtension(SeriesColorSettingsExtension):
    """Instrument-specific controls embedded in a bar chart's settings window."""

    title = "Batch comparison"

    def __init__(self, owner, kind: str):
        super().__init__(owner, f"{kind.casefold()}_bar", "bars")
        self.kind = kind
        self.statistic = tk.StringVar(value="Mean")
        self.error_bars = tk.BooleanVar(value=True)
        self.error_type = tk.StringVar(value="SD")
        self.label_vars: dict[str, tk.StringVar] = {}

    def build(self, parent):
        self.label_vars = {}
        self.build_colors(parent)
        options = ttk.LabelFrame(parent, text=tr("Summary and error bars"), padding=8)
        options.pack(fill="x")
        ttk.Label(options, text=tr("Central value")).grid(row=0, column=0, sticky="e", padx=4)
        ttk.Combobox(options, textvariable=self.statistic, values=(tr("Mean"), tr("Median")), state="readonly", width=14).grid(row=0, column=1, sticky="w")
        ttk.Checkbutton(options, text=tr("Show error bars"), variable=self.error_bars).grid(row=0, column=2, sticky="w", padx=12)
        ttk.Combobox(options, textvariable=self.error_type, values=("SD", "SEM"), state="readonly", width=8).grid(row=0, column=3, sticky="w")

        labels = ttk.LabelFrame(parent, text=tr("Editable batch names"), padding=8)
        labels.pack(fill="both", expand=True, pady=(8, 0))
        ttk.Label(labels, text=tr("Source particle"), font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Label(labels, text=tr("Batch name on X-axis"), font=("TkDefaultFont", 9, "bold")).grid(row=0, column=1, sticky="w", padx=4, pady=4)
        rows = {row["name"]: row for row in self.owner.library.particles()}
        for index, name in enumerate(self.owner.active_names(), start=1):
            value = rows.get(name, {}).get("plot_label") or default_particle_label(name)
            variable = tk.StringVar(value=value)
            self.label_vars[name] = variable
            ttk.Label(labels, text=name).grid(row=index, column=0, sticky="w", padx=4, pady=3)
            ttk.Entry(labels, textvariable=variable, width=28).grid(row=index, column=1, sticky="ew", padx=4, pady=3)
        labels.columnconfigure(1, weight=1)
        ttk.Button(parent, text=tr("Reset batch names to automatic JM labels"), command=self.reset_labels).pack(anchor="e", pady=(7, 0))

    def apply(self):
        for name, variable in self.label_vars.items():
            self.owner.library.set_plot_label(name, variable.get())
        self._store_colors()
        self.owner.refresh_active()

    def variables(self):
        return [*super().variables(), self.statistic, self.error_bars, self.error_type, *self.label_vars.values()]

    def reset_labels(self):
        names = list(self.label_vars)
        self.owner.library.reset_plot_labels(names)
        for name, variable in self.label_vars.items():
            variable.set(default_particle_label(name))

    def restore_defaults(self):
        self.restore_colors()
        self.statistic.set(tr("Mean"))
        self.error_bars.set(True)
        self.error_type.set("SD")
        self.reset_labels()


class ParticleLibraryWindow(tk.Toplevel):
    SORT_OPTIONS = {
        "Name A–Z": ("name", False), "Name Z–A": ("name", True),
        "Recently updated": ("updated_at", True), "DLS count (high first)": ("dls_count", True),
        "Zeta count (high first)": ("zeta_count", True), "OCR reviewed (high first)": ("ocr_reviewed", True),
        "Source A–Z": ("source_files", False),
    }

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.library = owner.library
        self.settings_store = owner.settings_store
        self.title(tr("ZetaSizer particle library"))
        self.geometry("1400x820")
        self.minsize(980, 620)
        self.protocol("WM_DELETE_WINDOW", self._close)

        toolbar = ttk.Frame(self, padding=8)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text=tr("Add selected to plots"), command=self.add_selected).pack(side="left")
        ttk.Button(toolbar, text=tr("View result tables…"), command=self.view_tables).pack(side="left", padx=5)
        ttk.Button(toolbar, text=tr("Edit batch name…"), command=self.edit_label).pack(side="left")
        ttk.Button(toolbar, text=tr("Delete selected…"), command=self.delete_selected).pack(side="left", padx=5)
        ttk.Button(toolbar, text=tr("Refresh library"), command=self.refresh).pack(side="right")
        self.sort_choice = tk.StringVar(value=tr("Name A–Z"))
        sort_box = ttk.Combobox(toolbar, textvariable=self.sort_choice, values=tuple(tr(value) for value in self.SORT_OPTIONS), state="readonly", width=25)
        sort_box.pack(side="right", padx=5)
        sort_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        ttk.Label(toolbar, text=tr("Sort by")).pack(side="right")

        vertical = ttk.Panedwindow(self, orient="vertical")
        vertical.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        upper, lower = ttk.Frame(vertical), ttk.Frame(vertical)
        vertical.add(upper, weight=3); vertical.add(lower, weight=2)
        columns = ("name", "batch", "zavg", "zetaavg", "dls", "zeta", "ocr", "source")
        self.tree = ttk.Treeview(upper, columns=columns, show="headings", selectmode="extended", style="ParticleLibrary.Treeview")
        definitions = (
            ("name", "Particle", 220), ("batch", "Batch", 100), ("zavg", "Z-average", 100),
            ("zetaavg", "Average zeta", 110), ("dls", "DLS n", 70), ("zeta", "Zeta n", 70),
            ("ocr", "OCR status", 160), ("source", "Source", 300),
        )
        for key, label, width in definitions:
            self.tree.heading(key, text=tr(label))
            self.tree.column(key, width=width, minwidth=65, stretch=key in {"name", "source"})
        self._column_widths = TreeColumnWidthState(self.tree, self.settings_store, "zetasizer_library", columns)
        ybar = ttk.Scrollbar(upper, orient="vertical", command=self.tree.yview)
        xbar = ttk.Scrollbar(upper, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew"); ybar.grid(row=0, column=1, sticky="ns"); xbar.grid(row=1, column=0, sticky="ew")
        upper.rowconfigure(0, weight=1); upper.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.refresh_details())
        self.tree.bind("<Double-1>", lambda _event: self.edit_label())

        details = ttk.Notebook(lower)
        details.pack(fill="both", expand=True)
        measure_frame, ocr_frame = ttk.Frame(details), ttk.Frame(details)
        details.add(measure_frame, text=tr("Measurements and sources")); details.add(ocr_frame, text=tr("Stored OCR data"))
        self.measure_tree = self._detail_tree(measure_frame, ("kind", "rep", "sheet", "cell", "source", "ocr"),
            (("kind", "Data", 80), ("rep", "Replicate", 75), ("sheet", "Sheet", 180), ("cell", "Cell", 90), ("source", "Source", 300), ("ocr", "OCR status", 130)))
        self.ocr_tree = self._detail_tree(ocr_frame, ("kind", "rep", "status", "field", "mean", "engine"),
            (("kind", "Data", 80), ("rep", "Replicate", 75), ("status", "Status", 100), ("field", "OCR field", 300), ("mean", "Mean", 100), ("engine", "Engine", 200)))
        localize_widget_tree(self)
        self.refresh()

    @staticmethod
    def _detail_tree(parent, columns, definitions):
        tree = ttk.Treeview(parent, columns=columns, show="headings", style="ParticleLibrary.Treeview")
        for key, label, width in definitions:
            tree.heading(key, text=tr(label)); tree.column(key, width=width, minwidth=60, stretch=key in {"sheet", "source", "field"})
        ybar = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        xbar = ttk.Scrollbar(parent, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        tree.grid(row=0, column=0, sticky="nsew"); ybar.grid(row=0, column=1, sticky="ns"); xbar.grid(row=1, column=0, sticky="ew")
        parent.rowconfigure(0, weight=1); parent.columnconfigure(0, weight=1)
        return tree

    @staticmethod
    def _display_number(value, unit=""):
        return "—" if value is None else f"{value:.4g}{unit}"

    def _sort_values(self):
        return self.SORT_OPTIONS.get(canonical(self.sort_choice.get()), ("name", False))

    def refresh(self, selected=()):
        keep = set(selected) or set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        sort_by, descending = self._sort_values()
        for row in self.library.particles(sort_by, descending):
            status = f"{row['ocr_auto']} {tr('auto')} · {row['ocr_reviewed']} {tr('reviewed')}"
            if row["ocr_failed"]:
                status += f" · {row['ocr_failed']} {tr('failed')}"
            values = (row["name"], row["plot_label"], self._display_number(row.get("dls_z_mean"), " nm"),
                      self._display_number(row.get("zeta_average_mean"), " mV"), row["dls_count"], row["zeta_count"], status, row["source_files"] or "")
            self.tree.insert("", "end", iid=row["name"], values=values)
            if row["name"] in keep:
                self.tree.selection_add(row["name"])
        self.refresh_details()

    def refresh_details(self):
        self.measure_tree.delete(*self.measure_tree.get_children())
        self.ocr_tree.delete(*self.ocr_tree.get_children())
        selected = list(self.tree.selection())
        if len(selected) != 1:
            return
        particle = selected[0]
        for index, row in enumerate(self.library.measurement_records(particle)):
            self.measure_tree.insert("", "end", iid=f"m{index}", values=(row["kind"], row["replicate"], row["sheet_name"], row["cell_number"], row["source_file"], row["ocr_status"]))
        for item in self.library.ocr_results(particle):
            columns = [str(value).casefold() for value in item["columns"]]
            mean_index = next((index for index, value in enumerate(columns) if "mean" in value), 1)
            if not item["rows"]:
                self.ocr_tree.insert("", "end", values=(item["kind"], item["replicate"], item["status"], item.get("error_text") or "—", "", item["engine"]))
            for row in item["rows"]:
                self.ocr_tree.insert("", "end", values=(item["kind"], item["replicate"], item["status"], row[0] if row else "", row[mean_index] if mean_index < len(row) else "", item["engine"]))

    def add_selected(self):
        names = list(self.tree.selection())
        if names:
            self.owner.add_particle_names(names)

    def view_tables(self):
        selected = list(self.tree.selection())
        if len(selected) != 1:
            messagebox.showinfo(tr("Result tables"), tr("Select exactly one particle."), parent=self)
            return
        self.owner.view_tables_for(selected[0], parent=self)

    def edit_label(self):
        selected = list(self.tree.selection())
        if len(selected) != 1:
            return
        row = next((value for value in self.library.particles() if value["name"] == selected[0]), None)
        value = simpledialog.askstring(tr("Edit batch name"), tr("Batch name on X-axis"), initialvalue=row["plot_label"] if row else default_particle_label(selected[0]), parent=self)
        if value is not None:
            self.library.set_plot_label(selected[0], value)
            self.refresh(selected)
            self.owner.refresh_active()

    def delete_selected(self):
        selected = list(self.tree.selection())
        if not selected:
            return
        if messagebox.askyesno(tr("Delete particles"), tr("Delete {count} selected particles and all of their stored measurements? This cannot be undone.", count=len(selected)), parent=self):
            self.library.delete_particles(selected)
            self.owner.active_particles = [name for name in self.owner.active_particles if name not in selected]
            self.owner.refresh_active(); self.refresh()

    def _close(self):
        self._column_widths.save()
        self.owner.library_window = None
        self.destroy()


class ZetaTab(ttk.Frame):
    def __init__(self, parent, library: ParticleLibrary):
        super().__init__(parent)
        self.library = library
        self.settings_store = SettingsStore()
        self.color_settings = self._load_color_settings()
        self.active_particles: list[str] = []
        self.library_window = None
        self.mode = tk.StringVar(value="Mean ± SD")
        self.log_x = tk.BooleanVar(value=True)
        self.peak_labels = tk.BooleanVar(value=True)
        self.multi_peak_labels = tk.BooleanVar(value=False)

        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        controls, graph = ttk.Frame(paned, padding=8, width=430), ttk.Frame(paned, padding=5)
        paned.add(controls, weight=1); paned.add(graph, weight=4)
        ttk.Button(controls, text="Import ZetaSizer workbook…", command=self.import_dialog).pack(fill="x")
        ttk.Button(controls, text="Open particle library…", command=self.open_library).pack(fill="x", pady=(5, 0))
        ttk.Label(controls, text="Particles included in the four plots", foreground="#555555").pack(anchor="w", pady=(9, 3))

        default_font = tkfont.nametofont("TkDefaultFont")
        style = ttk.Style(self)
        style.configure("ParticleLibrary.Treeview", rowheight=max(34, int(default_font.metrics("linespace") * 1.8)), padding=(4, 4))
        style.configure("ParticleLibrary.Treeview.Heading", font=(default_font.actual("family"), default_font.actual("size"), "bold"), padding=(4, 6))
        tree_frame = ttk.Frame(controls)
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_frame, columns=("name", "zavg", "zeta"), show="headings", selectmode="extended", style="ParticleLibrary.Treeview")
        for key, label, width in (("name", "Particle", 220), ("zavg", "Z-average", 105), ("zeta", "Average zeta", 110)):
            self.tree.heading(key, text=tr(label)); self.tree.column(key, width=width, minwidth=75, stretch=key == "name")
        self._column_widths = TreeColumnWidthState(self.tree, self.settings_store, "zetasizer_plot_selection", ("name", "zavg", "zeta"))
        ybar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        xbar = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew"); ybar.grid(row=0, column=1, sticky="ns"); xbar.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1); tree_frame.columnconfigure(0, weight=1)
        ttk.Button(controls, text="Add from library…", command=self.open_library).pack(fill="x", pady=(6, 0))
        ttk.Button(controls, text="Remove selected from plots", command=self.remove_from_plots).pack(fill="x", pady=(4, 0))

        settings = ttk.LabelFrame(controls, text="Comparison", padding=6)
        settings.pack(fill="x", pady=(8, 0))
        ttk.Label(settings, text="Display").grid(row=0, column=0, sticky="w")
        mode_box = ttk.Combobox(settings, textvariable=self.mode, values=("Mean ± SD", "Mean + replicates", "Replicates only"), state="readonly", width=21)
        mode_box.grid(row=0, column=1, sticky="ew"); mode_box.bind("<<ComboboxSelected>>", lambda _event: self._refresh())
        ttk.Checkbutton(settings, text="Log X for DLS", variable=self.log_x, command=self._refresh).grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(settings, text="Peak value labels", variable=self.peak_labels, command=self._refresh).grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(settings, text="Allow labels for multiple particles", variable=self.multi_peak_labels, command=self._refresh).grid(row=3, column=0, columnspan=2, sticky="w")
        settings.columnconfigure(1, weight=1)

        dashboard = ttk.Panedwindow(graph, orient="vertical")
        dashboard.pack(fill="both", expand=True)
        upper, lower = ttk.Panedwindow(dashboard, orient="horizontal"), ttk.Panedwindow(dashboard, orient="horizontal")
        dashboard.add(upper, weight=1); dashboard.add(lower, weight=1)
        frames = [ttk.LabelFrame(upper, text=tr("DLS distribution"), padding=3), ttk.LabelFrame(upper, text=tr("Zeta distribution"), padding=3),
                  ttk.LabelFrame(lower, text=tr("Batch vs DLS Z-average"), padding=3), ttk.LabelFrame(lower, text=tr("Batch vs average zeta potential"), padding=3)]
        upper.add(frames[0], weight=1); upper.add(frames[1], weight=1); lower.add(frames[2], weight=1); lower.add(frames[3], weight=1)
        self.dls_plot = PlotPane(frames[0], lambda axis, options: self._draw_kind("DLS", axis, options), PlotOptions("Particle diameter", "nm", "Intensity", "%", line_width=2.2), compact=True)
        self.zeta_plot = PlotPane(frames[1], lambda axis, options: self._draw_kind("Zeta", axis, options), PlotOptions("Zeta potential", "mV", "Total counts", "kcps", line_width=2.2), compact=True)
        self.dls_bar_plot = PlotPane(frames[2], lambda axis, options: self._draw_batch("DLS", axis, options), PlotOptions("Batch", "", "Z-average", "nm", line_width=1.5, legend=False), compact=True)
        self.zeta_bar_plot = PlotPane(frames[3], lambda axis, options: self._draw_batch("Zeta", axis, options), PlotOptions("Batch", "", "Average zeta potential", "mV", line_width=1.5, legend=False), compact=True)
        self.dls_curve_settings = SeriesColorSettingsExtension(self, "dls_curve", "curves")
        self.zeta_curve_settings = SeriesColorSettingsExtension(self, "zeta_curve", "curves")
        self.dls_batch_settings = BatchSettingsExtension(self, "DLS")
        self.zeta_batch_settings = BatchSettingsExtension(self, "Zeta")
        self.dls_plot.settings_extension = self.dls_curve_settings
        self.zeta_plot.settings_extension = self.zeta_curve_settings
        self.dls_bar_plot.settings_extension = self.dls_batch_settings
        self.zeta_bar_plot.settings_extension = self.zeta_batch_settings
        for frame, plot in zip(frames, (self.dls_plot, self.zeta_plot, self.dls_bar_plot, self.zeta_bar_plot)):
            plot.pack(fill="both", expand=True)
        self.plot = self.dls_plot
        self.plot_panes = (self.dls_plot, self.zeta_plot, self.dls_bar_plot, self.zeta_bar_plot)
        self.refresh_active()

    def _load_color_settings(self):
        saved = self.settings_store.get("zetasizer_colors", {})
        saved = saved if isinstance(saved, dict) else {}
        result = {}
        for key, defaults in ZETA_COLOR_DEFAULTS.items():
            value = saved.get(key, {})
            value = value if isinstance(value, dict) else {}
            scope = value.get("scope") if value.get("scope") in {"all", "individual"} else defaults["scope"]
            colors = value.get("colors", {}) if isinstance(value.get("colors"), dict) else {}
            result[key] = {
                "scope": scope,
                "global_color": normalized_color(value.get("global_color", ""), defaults["global_color"]),
                "colors": {
                    str(name): normalized_color(color, SERIES_PALETTE[index % len(SERIES_PALETTE)])
                    for index, (name, color) in enumerate(colors.items())
                },
            }
        return result

    def save_color_settings(self):
        try:
            self.settings_store.set("zetasizer_colors", self.color_settings)
        except OSError:
            pass

    def series_color(self, plot_key: str, particle: str, index: int) -> str:
        defaults = ZETA_COLOR_DEFAULTS[plot_key]
        return resolve_series_color(self.color_settings[plot_key], particle, index, defaults["global_color"])

    @staticmethod
    def _display_number(value, unit=""):
        return "—" if value is None else f"{value:.4g}{unit}"

    def active_names(self):
        return [name for name in self.active_particles if name in set(self.tree.get_children())]

    def add_particle_names(self, names):
        for name in names:
            if name not in self.active_particles:
                self.active_particles.append(name)
        self.refresh_active()

    def remove_from_plots(self):
        selected = set(self.tree.selection())
        self.active_particles = [name for name in self.active_particles if name not in selected]
        self.refresh_active()

    def open_library(self):
        if self.library_window and self.library_window.winfo_exists():
            self.library_window.lift(); self.library_window.focus_force(); return
        self.library_window = ParticleLibraryWindow(self)

    def refresh_active(self):
        rows = {row["name"]: row for row in self.library.particles()}
        self.active_particles = [name for name in self.active_particles if name in rows]
        self.tree.delete(*self.tree.get_children())
        for name in self.active_particles:
            row = rows[name]
            self.tree.insert("", "end", iid=name, values=(name, self._display_number(row.get("dls_z_mean"), " nm"), self._display_number(row.get("zeta_average_mean"), " mV")))
        if self.library_window and self.library_window.winfo_exists():
            self.library_window.refresh()
        self._refresh()

    def refresh_library(self, select=()):
        """Compatibility entry point used by OCR panes and older smart-import code."""
        if select:
            self.add_particle_names(select)
        else:
            self.refresh_active()

    def import_dialog(self):
        self.add_paths(filedialog.askopenfilenames(parent=self, filetypes=((tr("ZetaSizer Excel"), "*.xlsx *.xlsm"), (tr("All files"), "*.*"))))

    def add_paths(self, paths):
        paths = tuple(paths)
        if not paths:
            return
        progress = tk.Toplevel(self)
        progress.title(tr("Importing and reading result tables")); progress.transient(self.winfo_toplevel()); progress.resizable(False, False)
        body = ttk.Frame(progress, padding=16); body.pack(fill="both", expand=True)
        status = tk.StringVar(value=tr("Reading workbook data…"))
        ttk.Label(body, textvariable=status, wraplength=430).pack(anchor="w")
        bar = ttk.Progressbar(body, mode="indeterminate", length=430); bar.pack(fill="x", pady=(10, 0)); bar.start(10)
        progress.protocol("WM_DELETE_WINDOW", lambda: None)

        def worker():
            imported, particles, ocr_count, errors = 0, set(), 0, []
            for path in paths:
                try:
                    measurements = parse_zetasizer_workbook(path)
                    imported += self.library.import_measurements(measurements)
                    particles.update(item.particle_name for item in measurements)
                    for item in measurements:
                        if not item.result_png:
                            continue
                        try:
                            result = run_table_ocr(item.result_png)
                            self.library.save_ocr_result(item.particle_name, item.kind, item.replicate, result.columns, result.rows, result.confidence, result.engine, reviewed=False)
                            ocr_count += 1
                        except Exception as exc:
                            self.library.save_ocr_failure(item.particle_name, item.kind, item.replicate, str(exc))
                            errors.append(f"{item.particle_name} · {item.kind} M{item.replicate}: {exc}")
                except Exception as exc:
                    errors.append(f"{Path(path).name}: {exc}")
            self.after(0, lambda: finished(imported, particles, ocr_count, errors))

        def finished(imported, particles, ocr_count, errors):
            if progress.winfo_exists():
                progress.destroy()
            if imported:
                self.add_particle_names(sorted(particles))
                message = tr("Stored {curves} replicate curves for {particles} particles and automatically read {tables} result tables.", curves=imported, particles=len(particles), tables=ocr_count)
                if errors:
                    message += "\n\n" + tr("Some OCR readings need review:") + "\n" + "\n".join(errors[:8])
                messagebox.showinfo(tr("Imported"), message, parent=self)
            elif errors:
                messagebox.showerror(tr("ZetaSizer import"), "\n".join(errors), parent=self)

        threading.Thread(target=worker, daemon=True).start()

    def _draw_kind(self, kind: str, axis, options):
        names = self.active_names()
        mode = canonical(self.mode.get())
        data = self.library.measurements(names, kind)
        plot_key = f"{kind.casefold()}_curve"
        pane = self.dls_plot if kind == "DLS" else self.zeta_plot
        show_peaks = self.peak_labels.get() and (len(names) == 1 or self.multi_peak_labels.get())
        for color_index, name in enumerate(names):
            items = data.get(name, [])
            if not items:
                continue
            color = self.series_color(plot_key, name, color_index)
            curves = [(item["x"], item["y"]) for item in items]
            if mode in {"Mean + replicates", "Replicates only"}:
                for item in items:
                    label = f"{name} {tr('rep {number}', number=item['replicate'])}"
                    axis.plot(item["x"], item["y"], color=color, alpha=0.28 if mode == "Mean + replicates" else 0.75, linewidth=max(0.8, options.line_width * 0.65), label=label if mode == "Replicates only" else "_nolegend_")
            x, mean, sd = mean_curve(curves)
            if mode != "Replicates only":
                axis.plot(x, mean, color=color, linewidth=options.line_width, label=name)
                if mode == "Mean ± SD":
                    axis.fill_between(x, mean - sd, mean + sd, color=color, alpha=0.18, linewidth=0)
            if show_peaks and mean.size:
                index = int(np.nanargmax(mean))
                unit = "nm" if kind == "DLS" else "mV"
                artist = axis.annotate(f"{x[index]:.4g} {unit}", (x[index], mean[index]), xytext=(7, 10), textcoords="offset points", color=color,
                                       fontsize=max(7, options.tick_font_size - 2), fontweight="bold", arrowprops={"arrowstyle": "-", "color": color, "linewidth": 1.0})
                pane.register_overlay(artist)
        if kind == "DLS" and self.log_x.get():
            axis.set_xscale("log")
        if not names:
            axis.text(0.5, 0.5, tr("Add particles from the library"), ha="center", va="center", transform=axis.transAxes)

    def _draw_batch(self, kind: str, axis, options):
        names = self.active_names()
        rows = {row["name"]: row for row in self.library.particles()}
        extension = self.dls_batch_settings if kind == "DLS" else self.zeta_batch_settings
        prefix = "dls_z" if kind == "DLS" else "zeta_average"
        statistic = canonical(extension.statistic.get()).casefold()
        values, errors, labels, particles = [], [], [], []
        for name in names:
            row = rows.get(name, {})
            value = row.get(f"{prefix}_median" if statistic == "median" else f"{prefix}_mean")
            if value is None:
                continue
            particles.append(name); labels.append(row.get("plot_label") or default_particle_label(name)); values.append(value)
            errors.append(row.get(f"{prefix}_{canonical(extension.error_type.get()).casefold()}") or 0.0)
        if values:
            x = np.arange(len(values))
            plot_key = f"{kind.casefold()}_bar"
            colors = [self.series_color(plot_key, name, index) for index, name in enumerate(particles)]
            axis.bar(x, values, color=colors, edgecolor="black", linewidth=0.7,
                     yerr=errors if extension.error_bars.get() else None, capsize=4)
            axis.set_xticks(x, labels, rotation=30, ha="right")
        else:
            axis.text(0.5, 0.5, tr("Automatic OCR values will appear here"), ha="center", va="center", transform=axis.transAxes)

    def view_tables(self):
        selected = list(self.tree.selection())
        if len(selected) != 1:
            messagebox.showinfo(tr("Result tables"), tr("Select exactly one particle."), parent=self)
            return
        self.view_tables_for(selected[0])

    def view_tables_for(self, particle: str, parent=None):
        top = tk.Toplevel(parent or self)
        top.title(tr("{particle} · result tables", particle=particle)); top.geometry("1400x840"); top.minsize(980, 650)
        top.rowconfigure(0, weight=1); top.columnconfigure(0, weight=1)
        notebook = ttk.Notebook(top); notebook.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        review_tabs: dict[tuple[str, int], OCRReviewPane] = {}

        def open_ocr(kind: str, measurements: ttk.Notebook):
            replicate = measurements.index("current") + 1
            raw = self.library.result_image(particle, kind, replicate)
            if not raw:
                messagebox.showinfo(tr("OCR reading"), tr("No embedded table image"), parent=top); return
            key = (kind, replicate)
            if key in review_tabs and review_tabs[key].winfo_exists():
                notebook.select(review_tabs[key]); return
            frame = OCRReviewPane(notebook, self.library, particle, kind, replicate, raw, self.refresh_active)
            review_tabs[key] = frame; notebook.add(frame, text=tr("{kind}_OCR M{number}", kind=kind, number=replicate)); notebook.select(frame)

        for kind in ("DLS", "Zeta"):
            kind_frame = ttk.Frame(notebook); kind_frame.rowconfigure(0, weight=1); kind_frame.columnconfigure(0, weight=1)
            notebook.add(kind_frame, text=tr(kind))
            measurements = ttk.Notebook(kind_frame); measurements.grid(row=0, column=0, sticky="nsew")
            for replicate in (1, 2, 3):
                frame = ttk.Frame(measurements, padding=8); measurements.add(frame, text=tr("Measurement {number}", number=replicate))
                raw = self.library.result_image(particle, kind, replicate)
                if raw:
                    ZoomImageViewer(frame, Image.open(BytesIO(raw))).pack(fill="both", expand=True)
                else:
                    ttk.Label(frame, text=tr("No embedded table image")).pack(padx=30, pady=30)
            footer = ttk.Frame(kind_frame, padding=(7, 9)); footer.grid(row=1, column=0, sticky="ew")
            ttk.Label(footer, text=tr("Automatic OCR is stored on import. Open the selected measurement to review or correct it."), foreground="#555555").pack(side="left")
            ttk.Button(footer, text=tr("Review current OCR…"), command=lambda value=kind, tabs=measurements: open_ocr(value, tabs)).pack(side="right")
        localize_widget_tree(top)

    def _refresh(self):
        for plot in getattr(self, "plot_panes", ()):
            plot.refresh()


class MappingDialog(tk.Toplevel):
    def __init__(self, parent, path: str, store: FormatProfileStore):
        super().__init__(parent)
        self.title(tr("Map a new Excel format"))
        self.transient(parent)
        self.grab_set()
        self.path = path
        self.store = store
        self.previews = workbook_preview(path)
        self.result = None
        form = ttk.Frame(self, padding=8)
        form.pack(fill="x")
        self.name = tk.StringVar(value=tr("{name} format", name=Path(path).stem))
        self.sheet = tk.StringVar(value=next(iter(self.previews)))
        self.header = tk.StringVar(value="1")
        self.start = tk.StringVar(value="2")
        self.x_col = tk.StringVar(value="A")
        self.y_cols = tk.StringVar(value="B")
        fields = (("Custom format name", self.name), ("Sheet", self.sheet), ("Header row", self.header), ("Data starts at row", self.start), ("X column", self.x_col), ("Y column(s), comma separated", self.y_cols))
        for row, (label, var) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="e", padx=4, pady=2)
            if label == "Sheet":
                widget = ttk.Combobox(form, textvariable=var, values=tuple(self.previews), state="readonly")
                widget.bind("<<ComboboxSelected>>", lambda _: self.update_preview())
            else:
                widget = ttk.Entry(form, textvariable=var)
            widget.grid(row=row, column=1, sticky="ew", pady=2)
        form.columnconfigure(1, weight=1)
        self.preview_frame = ttk.Frame(self, padding=8)
        self.preview_frame.pack(fill="both", expand=True)
        buttons = ttk.Frame(self, padding=8)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Save format and import", command=self.save).pack(side="right", padx=5)
        buttons.pack(fill="x")
        self.update_preview()
        self.geometry("900x520")
        localize_widget_tree(self)

    def update_preview(self):
        for child in self.preview_frame.winfo_children():
            child.destroy()
        rows = self.previews.get(self.sheet.get(), [])[:30]
        width = min(12, max((len(row) for row in rows), default=1))
        columns = tuple(str(i + 1) for i in range(width))
        tree = ttk.Treeview(self.preview_frame, columns=columns, show="headings")
        for idx, col in enumerate(columns):
            name = ""
            n = idx + 1
            while n:
                n, rem = divmod(n - 1, 26)
                name = chr(65 + rem) + name
            tree.heading(col, text=name); tree.column(col, width=100, stretch=True)
        for row in rows:
            tree.insert("", "end", values=["" if v is None else str(v) for v in row[:width]])
        tree.pack(fill="both", expand=True)

    def save(self):
        try:
            profile = {
                "name": self.name.get().strip(), "sheet": self.sheet.get(),
                "header_row": int(self.header.get()), "data_start_row": int(self.start.get()),
                "x_column": self.x_col.get().strip(),
                "y_columns": [v.strip() for v in self.y_cols.get().split(",") if v.strip()],
                "extension": Path(self.path).suffix.lower(),
                "sheet_index": list(self.previews).index(self.sheet.get()),
                "signature": workbook_signature(self.path),
            }
            if not profile["name"] or not profile["y_columns"]:
                raise ValueError(tr("A name and at least one Y column are required."))
            self.store.save_profile(profile)
            self.result = profile
            self.destroy()
        except Exception as exc:
            messagebox.showerror(tr("Format mapping"), str(exc), parent=self)


class GenericTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.store = FormatProfileStore()
        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        controls, graph = ttk.Frame(paned, padding=7), ttk.Frame(paned, padding=5)
        paned.add(controls, weight=0); paned.add(graph, weight=1)
        self.profile = tk.StringVar()
        ttk.Label(controls, text="Saved format").pack(anchor="w")
        self.profile_box = ttk.Combobox(controls, textvariable=self.profile, state="readonly", width=34)
        self.profile_box.pack(fill="x", pady=(0, 5))
        ttk.Button(controls, text="Import using selected format…", command=self.import_known).pack(fill="x")
        ttk.Button(controls, text="Map a new format…", command=self.map_new).pack(fill="x", pady=4)
        ttk.Button(controls, text="Remove selected curves", command=lambda: self.tree.remove_selected()).pack(fill="x")
        ttk.Button(controls, text="Set selected curve color…", command=lambda: self.tree.color_selected()).pack(fill="x", pady=(4, 0))
        self.tree = SpectrumTree(controls, self._refresh)
        self.tree.pack(fill="both", expand=True, pady=6)
        ttk.Label(controls, text="Unknown workbooks open a preview where you\nchoose the sheet, header, X and Y columns.", foreground="#555555").pack(anchor="w")
        self.plot = PlotPane(graph, self._draw, PlotOptions("X", "", "Y", "", line_width=2.0))
        self.plot.pack(fill="both", expand=True)
        self.refresh_profiles()

    def refresh_profiles(self):
        names = [p.get("name", "") for p in self.store.load()]
        self.profile_box.configure(values=names)
        if names and self.profile.get() not in names:
            self.profile.set(names[0])

    def _choose_files(self):
        return filedialog.askopenfilenames(parent=self, filetypes=((tr("Data workbooks"), "*.xlsx *.xlsm *.xml *.csv *.tsv *.txt"), (tr("All files"), "*.*")))

    def import_known(self):
        profile = next((p for p in self.store.load() if p.get("name") == self.profile.get()), None)
        if not profile:
            messagebox.showinfo(tr("Custom format"), tr("Create a format mapping first."), parent=self)
            return
        self.add_paths(self._choose_files(), profile)

    def map_new(self, path=None):
        if not path:
            paths = self._choose_files()
            path = paths[0] if paths else None
        if not path:
            return
        dialog = MappingDialog(self, path, self.store)
        self.wait_window(dialog)
        if dialog.result:
            self.refresh_profiles(); self.profile.set(dialog.result["name"])
            self.add_paths([path], dialog.result)

    def auto_import(self, path):
        signature = workbook_signature(path)
        profile = next((p for p in self.store.load() if p.get("signature") == signature), None)
        if profile:
            self.profile.set(profile["name"])
            self.add_paths([path], profile)
        else:
            messagebox.showinfo(tr("New or unrecognized format"), tr("{name} does not match a saved format.\nPlease map its sheet and data columns once.", name=Path(path).name), parent=self)
            self.map_new(path)

    def add_paths(self, paths, profile):
        loaded = []
        for path in paths:
            try:
                loaded.extend(parse_generic_with_profile(path, profile))
            except Exception as exc:
                messagebox.showerror(tr("Custom import"), f"{Path(path).name}\n{exc}", parent=self)
        if loaded:
            self.tree.add(loaded)

    def _draw(self, axis, options):
        for spectrum in self.tree.visible():
            kwargs = {"color": spectrum.metadata["color"]} if spectrum.metadata.get("color") else {}
            axis.plot(spectrum.x, spectrum.y, linewidth=options.line_width, label=spectrum.name, **kwargs)
        if not self.tree.visible():
            axis.text(0.5, 0.5, tr("Create or select a custom format, then import data"), ha="center", va="center", transform=axis.transAxes)

    def _refresh(self):
        if hasattr(self, "plot"):
            self.plot.refresh()


class UpdateCenter(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title(tr("LabPlotter Update Center"))
        self.transient(parent)
        self.resizable(False, False)
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="LabPlotter Update Center", font=("Arial", 15, "bold")).pack(anchor="w")
        ttk.Label(body, text=tr("Installed version: {version}", version=__version__), padding=(0, 5, 0, 12)).pack(anchor="w")
        ttk.Label(
            body,
            text=tr("Apply a verified .labpatch file without replacing the application folder or its local Python environment. The app closes during the update and restarts automatically."),
            wraplength=480,
            foreground="#555555",
        ).pack(anchor="w", pady=(0, 12))
        ttk.Button(body, text="Apply .labpatch…", command=self._apply).pack(fill="x", pady=3)
        ttk.Button(body, text="Rollback latest update…", command=self._rollback).pack(fill="x", pady=3)
        backup_count = self._backup_count()
        ttk.Label(body, text=tr("Available rollback backups: {count}", count=backup_count), foreground="#555555", padding=(0, 8, 0, 0)).pack(anchor="w")
        localize_widget_tree(self)

    def _backup_count(self) -> int:
        root = Path(__file__).resolve().parents[1] / ".updates" / "backups"
        count = 0
        for path in root.glob("*/backup_manifest.json") if root.exists() else ():
            try:
                import json
                if json.loads(path.read_text(encoding="utf-8")).get("status") == "applied":
                    count += 1
            except Exception:
                pass
        return count

    def _apply(self):
        path = filedialog.askopenfilename(parent=self, title=tr("Select LabPlotter patch"), filetypes=((tr("LabPlotter patch"), "*.labpatch"),))
        if path and messagebox.askyesno(tr("Apply update"), tr("LabPlotter will close, apply the patch, validate it, and restart. Continue?"), parent=self):
            self.destroy()
            self.parent.start_updater(["--patch", path])

    def _rollback(self):
        if not self._backup_count():
            messagebox.showinfo(tr("Rollback"), tr("No applied update backup is available."), parent=self)
            return
        if messagebox.askyesno(tr("Rollback"), tr("Restore the version from immediately before the latest update? LabPlotter will close and restart."), parent=self):
            self.destroy()
            self.parent.start_updater(["--rollback", "latest"])


class ContactDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title(tr("Contact and feedback"))
        self.transient(parent)
        self.resizable(False, False)
        body = ttk.Frame(self, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="LabPlotter", font=("Arial", 16, "bold")).pack(anchor="w")
        ttk.Label(body, text="Jun Min Moon", font=("Arial", 12, "bold"), padding=(0, 12, 0, 2)).pack(anchor="w")
        email = tk.StringVar(value="moonkeving@gmail.com")
        row = ttk.Frame(body)
        row.pack(fill="x")
        entry = ttk.Entry(row, textvariable=email, width=34, state="readonly")
        entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Copy email", command=lambda: self._copy_email(email.get())).pack(side="left", padx=(6, 0))
        ttk.Label(
            body,
            text="Feedback, bug reports, and requests for new instrument formats are welcome.",
            foreground="#555555",
            wraplength=410,
            padding=(0, 12, 0, 0),
        ).pack(anchor="w")
        localize_widget_tree(self)

    def _copy_email(self, email: str):
        self.clipboard_clear()
        self.clipboard_append(email)
        self.update()
        messagebox.showinfo(tr("Copied"), tr("Email address copied."), parent=self)


class LabPlotterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LabPlotter · local scientific data workbench")
        self.geometry("1450x900")
        self.minsize(1100, 700)
        self._set_theme()
        top = ttk.Frame(self, padding=(8, 6))
        ttk.Label(top, text=f"LabPlotter {__version__}", font=("Arial", 16, "bold")).pack(side="left")
        ttk.Button(top, text="Smart Import…", command=self.smart_import).pack(side="right")
        ttk.Button(top, text="Updates…", command=lambda: UpdateCenter(self)).pack(side="right", padx=5)
        ttk.Button(top, text="Contact…", command=lambda: ContactDialog(self)).pack(side="right")
        self.language_var = tk.StringVar(value="한국어" if language() == "ko" else "English")
        self.language_box = ttk.Combobox(top, textvariable=self.language_var, values=("English", "한국어"), state="readonly", width=9)
        self.language_box.pack(side="right", padx=(4, 0))
        self.language_box.bind("<<ComboboxSelected>>", self._select_language)
        ttk.Label(top, text="Language").pack(side="right", padx=(8, 0))
        top.pack(fill="x")
        self.notebook = ttk.Notebook(self, style="LabPlotter.TNotebook")
        self.ftir = FTIRTab(self.notebook)
        self.nano = NanoDropTab(self.notebook)
        self.nmr = SSNMRTab(self.notebook)
        self.zeta = ZetaTab(self.notebook, ParticleLibrary())
        self.generic = GenericTab(self.notebook)
        self.notebook.add(self.ftir, text="FTIR")
        self.notebook.add(self.nano, text="NanoDrop UV–Vis")
        self.notebook.add(self.nmr, text="ssNMR")
        self.notebook.add(self.zeta, text="ZetaSizer library")
        self.notebook.add(self.generic, text="Custom formats")
        self.notebook.enable_traversal()
        self.notebook.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        language_manager.subscribe(self._language_changed)
        if language() != "en":
            self._language_changed("en", language())
        self.after(150, self._initial_draw)

    def _select_language(self, _event=None):
        set_language("ko" if self.language_var.get() == "한국어" else "en")

    def _language_changed(self, old_language: str, new_language: str):
        localize_widget_tree(self, old_language, new_language)
        self.language_var.set("한국어" if new_language == "ko" else "English")
        for tab in (self.ftir, self.nano, self.nmr, self.zeta, self.generic):
            for plot in getattr(tab, "plot_panes", (tab.plot,)):
                plot.language_changed(old_language, new_language)

    def _set_theme(self):
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        default_font = tkfont.nametofont("TkDefaultFont")
        family, size = default_font.actual("family"), int(default_font.actual("size"))
        style.configure("LabPlotter.TNotebook", borderwidth=0, tabmargins=(2, 3, 2, 0), background="#E9EDF2")
        style.configure(
            "LabPlotter.TNotebook.Tab",
            padding=(18, 10),
            font=(family, max(10, size + 1), "bold"),
            borderwidth=1,
            background="#E3E8EE",
            foreground="#25313C",
        )
        style.map(
            "LabPlotter.TNotebook.Tab",
            background=[("selected", "#0B5CAD"), ("active", "#D2E5F7"), ("!selected", "#E3E8EE")],
            foreground=[("selected", "#FFFFFF"), ("active", "#0B3D66"), ("!selected", "#25313C")],
            expand=[("selected", (1, 1, 1, 0))],
        )

    def _initial_draw(self):
        for tab in (self.ftir, self.nano, self.nmr, self.zeta, self.generic):
            tab._refresh()

    def smart_import(self):
        paths = filedialog.askopenfilenames(parent=self, filetypes=((tr("Lab data"), "*.csv *.txt *.tsv *.xml *.xlsx *.xlsm *.zip"), (tr("All files"), "*.*")))
        for path in paths:
            try:
                kind = detect_builtin_kind(path)
                if kind == "FTIR":
                    self.ftir.add_paths([path]); self.notebook.select(self.ftir)
                elif kind == "NanoDrop":
                    self.nano.add_paths([path]); self.notebook.select(self.nano)
                elif kind == "ssNMR":
                    self.nmr.add_paths([path]); self.notebook.select(self.nmr)
                elif kind == "ZetaSizer":
                    self.zeta.add_paths([path])
                    self.notebook.select(self.zeta)
                else:
                    self.generic.auto_import(path); self.notebook.select(self.generic)
            except Exception as exc:
                messagebox.showerror(tr("Smart Import"), f"{Path(path).name}\n{exc}", parent=self)

    def start_updater(self, arguments: list[str]):
        app_root = Path(__file__).resolve().parents[1]
        updater = app_root / "updater.py"
        if not updater.exists():
            messagebox.showerror(tr("Update Manager"), tr("updater.py is missing from the application folder."), parent=self)
            return
        command = [sys.executable, str(updater), "--app-root", str(app_root), "--pid", str(os.getpid()), *arguments]
        try:
            subprocess.Popen(command, cwd=app_root)
        except Exception as exc:
            messagebox.showerror(tr("Update Manager"), str(exc), parent=self)
            return
        self.after(150, self.destroy)
