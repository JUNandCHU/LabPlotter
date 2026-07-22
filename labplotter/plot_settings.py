from __future__ import annotations

import tkinter as tk
from tkinter import colorchooser, font as tkfont, ttk

from .i18n import canonical, localize_widget_tree, manager as language_manager, tr


FONT_FAMILIES = (
    "Arial",
    "Calibri",
    "Times New Roman",
    "Malgun Gothic",
    "Noto Sans CJK KR",
    "DejaVu Sans",
)


class PlotSettingsWindow(tk.Toplevel):
    """Non-modal, reusable editor for one PlotPane's visual options."""

    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane
        self.title(tr("Graph settings"))
        self.geometry("760x700")
        self.minsize(650, 560)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.live = tk.BooleanVar(value=True)
        self._traces: list[tuple[tk.Variable, str]] = []

        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        ttk.Label(top, text="Graph settings", font=("Arial", 14, "bold")).pack(side="left")
        ttk.Checkbutton(top, text="Live preview", variable=self.live).pack(side="right", padx=(8, 0))
        ttk.Button(top, text="Apply", command=self.apply).pack(side="right")
        ttk.Button(top, text="Restore tab defaults", command=self.restore_defaults).pack(side="right", padx=(0, 6))

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        axes = ttk.Frame(notebook, padding=10)
        fonts = ttk.Frame(notebook, padding=10)
        notebook.add(axes, text=tr("Axes and lines"))
        notebook.add(fonts, text=tr("Fonts and colors"))
        self._build_axes(axes)
        self._build_fonts(fonts)
        self.extension = getattr(self.pane, "settings_extension", None)
        if self.extension is not None:
            extra = ttk.Frame(notebook, padding=10)
            notebook.add(extra, text=tr(self.extension.title))
            self.extension.build(extra)
        self._connect_live_preview()
        language_manager.subscribe(self.language_changed)
        localize_widget_tree(self)

    def _entry(self, parent, text: str, variable: tk.Variable, row: int, column: int = 0, width: int = 10):
        ttk.Label(parent, text=text).grid(row=row, column=column, sticky="e", padx=(4, 3), pady=3)
        widget = ttk.Entry(parent, textvariable=variable, width=width)
        widget.grid(row=row, column=column + 1, sticky="ew", pady=3)
        return widget

    def _build_axes(self, parent):
        labels = ttk.LabelFrame(parent, text="Axis labels and units", padding=8)
        labels.pack(fill="x")
        self._entry(labels, "X name", self.pane.vars["x_label"], 0, 0, 18)
        self._entry(labels, "Unit", self.pane.vars["x_unit"], 0, 2, 11)
        self._entry(labels, "Y name", self.pane.vars["y_label"], 1, 0, 18)
        self._entry(labels, "Unit", self.pane.vars["y_unit"], 1, 2, 11)
        labels.columnconfigure(1, weight=1)
        labels.columnconfigure(3, weight=1)

        ranges = ttk.LabelFrame(parent, text="Ranges and major ticks", padding=8)
        ranges.pack(fill="x", pady=8)
        fields = (
            ("X minimum", "x_min", 0, 0), ("X maximum", "x_max", 0, 2),
            ("Y minimum", "y_min", 1, 0), ("Y maximum", "y_max", 1, 2),
            ("X tick spacing", "x_tick", 2, 0), ("Y tick spacing", "y_tick", 2, 2),
        )
        for label, key, row, column in fields:
            self._entry(ranges, label, self.pane.vars[key], row, column)
        ranges.columnconfigure(1, weight=1)
        ranges.columnconfigure(3, weight=1)

        appearance = ttk.LabelFrame(parent, text="Frame and curves", padding=8)
        appearance.pack(fill="x")
        self._entry(appearance, "Curve width", self.pane.vars["line_width"], 0, 0)
        self._entry(appearance, "Tick width", self.pane.vars["tick_width"], 0, 2)
        self._entry(appearance, "Tick length", self.pane.vars["tick_length"], 1, 0)
        self._entry(appearance, "Frame width", self.pane.vars["spine_width"], 1, 2)
        ttk.Label(appearance, text="Background").grid(row=2, column=0, sticky="e", padx=(4, 3), pady=3)
        ttk.Combobox(
            appearance,
            textvariable=self.pane.vars["background"],
            values=("White", "Dark"),
            state="readonly",
            width=12,
        ).grid(row=2, column=1, sticky="w")
        ttk.Checkbutton(appearance, text="Reverse X", variable=self.pane.vars["reverse_x"]).grid(row=2, column=2, sticky="w")
        ttk.Checkbutton(appearance, text="Legend", variable=self.pane.vars["legend"]).grid(row=2, column=3, sticky="w")
        appearance.columnconfigure(1, weight=1)
        appearance.columnconfigure(3, weight=1)

    def _color_control(self, parent, label: str, key: str, row: int):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="e", padx=(4, 3), pady=3)
        entry = ttk.Entry(parent, textvariable=self.pane.vars[key], width=12)
        entry.grid(row=row, column=1, sticky="w")
        ttk.Button(parent, text="Choose…", command=lambda: self._choose_color(key)).grid(row=row, column=2, sticky="w", padx=4)

    def _font_group(self, parent, title: str, prefix: str):
        frame = ttk.LabelFrame(parent, text=title, padding=8)
        frame.pack(fill="x", pady=(0, 8))
        ttk.Label(frame, text="Font").grid(row=0, column=0, sticky="e", padx=(4, 3), pady=3)
        ttk.Combobox(frame, textvariable=self.pane.vars[f"{prefix}_font_family"], values=FONT_FAMILIES, width=24).grid(row=0, column=1, sticky="ew")
        ttk.Label(frame, text="Size").grid(row=0, column=2, sticky="e", padx=(8, 3))
        ttk.Entry(frame, textvariable=self.pane.vars[f"{prefix}_font_size"], width=8).grid(row=0, column=3, sticky="w")
        ttk.Checkbutton(frame, text="Bold", variable=self.pane.vars[f"{prefix}_bold"]).grid(row=0, column=4, sticky="w", padx=8)
        self._color_control(frame, "Color", f"{prefix}_color", 1)
        frame.columnconfigure(1, weight=1)

    def _build_fonts(self, parent):
        self._font_group(parent, "X-axis title", "x")
        self._font_group(parent, "Y-axis title", "y")
        self._font_group(parent, "Tick labels", "tick")
        self._font_group(parent, "Legend", "legend")
        ttk.Label(
            parent,
            text="When Korean text is present, LabPlotter automatically uses an installed Hangul-capable fallback font.",
            foreground="#555555",
            wraplength=620,
        ).pack(anchor="w", pady=(2, 0))

    def _build_annotations(self, parent):
        ttk.Label(
            parent,
            text="Choose a line or shape, then drag directly on the graph. Positions are kept relative to the graph frame.",
            foreground="#555555",
            wraplength=620,
        ).pack(anchor="w", pady=(0, 8))
        form = ttk.LabelFrame(parent, text="New annotation", padding=8)
        form.pack(fill="x")
        self.annotation_kind = tk.StringVar(value="Line")
        self.annotation_style = tk.StringVar(value="Solid")
        self.annotation_color = tk.StringVar(value="#C62828")
        self.annotation_width = tk.StringVar(value="2.0")
        ttk.Label(form, text="Type").grid(row=0, column=0, sticky="e", padx=3)
        ttk.Combobox(form, textvariable=self.annotation_kind, values=("Line", "Rectangle", "Ellipse", "Circle"), state="readonly", width=13).grid(row=0, column=1, sticky="w")
        ttk.Label(form, text="Style").grid(row=0, column=2, sticky="e", padx=(10, 3))
        ttk.Combobox(form, textvariable=self.annotation_style, values=("Solid", "Dashed", "Dotted", "Dash-dot"), state="readonly", width=13).grid(row=0, column=3, sticky="w")
        ttk.Label(form, text="Width").grid(row=1, column=0, sticky="e", padx=3, pady=4)
        ttk.Entry(form, textvariable=self.annotation_width, width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(form, text="Color").grid(row=1, column=2, sticky="e", padx=(10, 3))
        ttk.Entry(form, textvariable=self.annotation_color, width=12).grid(row=1, column=3, sticky="w")
        ttk.Button(form, text="Choose…", command=self._choose_annotation_color).grid(row=1, column=4, padx=4)
        ttk.Button(form, text="Draw on graph", command=self._begin_draw).grid(row=2, column=0, columnspan=5, sticky="ew", pady=(7, 0))

        list_frame = ttk.LabelFrame(parent, text="Placed annotations", padding=6)
        list_frame.pack(fill="both", expand=True, pady=8)
        default_font = tkfont.nametofont("TkDefaultFont")
        family, size = default_font.actual("family"), int(default_font.actual("size"))
        style = ttk.Style(self)
        style.configure("Annotations.Treeview", rowheight=max(34, int(default_font.metrics("linespace") * 1.8)), font=(family, size + 2))
        style.configure("Annotations.Treeview.Heading", font=(family, size + 2, "bold"), padding=(5, 7))
        self.annotation_tree = ttk.Treeview(list_frame, columns=("type", "style", "color"), show="headings", height=7, style="Annotations.Treeview")
        for key, label, width in (("type", "Type", 150), ("style", "Style", 140), ("color", "Color", 120)):
            self.annotation_tree.heading(key, text=label)
            self.annotation_tree.column(key, width=width, stretch=True)
        self.annotation_tree.pack(fill="both", expand=True)
        buttons = ttk.Frame(parent)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Remove selected", command=self._remove_annotations).pack(side="left")
        ttk.Button(buttons, text="Clear all", command=self._clear_annotations).pack(side="left", padx=5)
        self.draw_status = tk.StringVar(value="")
        ttk.Label(buttons, textvariable=self.draw_status, foreground="#0B5CAD").pack(side="right")
        self.refresh_annotations()

    def _choose_color(self, key: str):
        current = self.pane.vars[key].get() or "#000000"
        selected = colorchooser.askcolor(color=current, parent=self)[1]
        if selected:
            self.pane.vars[key].set(selected)

    def _choose_annotation_color(self):
        selected = colorchooser.askcolor(color=self.annotation_color.get(), parent=self)[1]
        if selected:
            self.annotation_color.set(selected)

    def _connect_live_preview(self):
        for variable in self.pane.vars.values():
            token = variable.trace_add("write", self._changed)
            self._traces.append((variable, token))
        if self.extension is not None:
            for variable in self.extension.variables():
                token = variable.trace_add("write", self._extension_changed)
                self._traces.append((variable, token))

    def _changed(self, *_args):
        if self.live.get():
            self.after_idle(self.pane.refresh)

    def _extension_changed(self, *_args):
        if self.live.get():
            self.after_idle(self.extension.apply)

    def apply(self):
        if self.extension is not None:
            self.extension.apply()
        self.pane.refresh()

    def restore_defaults(self):
        live = self.live.get()
        self.live.set(False)
        try:
            self.pane.restore_defaults()
            if self.extension is not None:
                self.extension.restore_defaults()
        finally:
            self.live.set(live)
        self.pane.refresh()

    def language_changed(self, old_language: str, new_language: str):
        if self.winfo_exists():
            localize_widget_tree(self, old_language, new_language)
            self.refresh_annotations()

    def _begin_draw(self):
        try:
            width = max(0.25, float(self.annotation_width.get()))
        except ValueError:
            width = 2.0
        self.draw_status.set(tr("Drag on the graph…"))
        self.pane.begin_annotation(
            canonical(self.annotation_kind.get()),
            canonical(self.annotation_style.get()),
            self.annotation_color.get() or "#C62828",
            width,
            self._annotation_added,
        )
        self.lift()

    def _annotation_added(self):
        self.draw_status.set(tr("Annotation added"))
        self.refresh_annotations()

    def refresh_annotations(self):
        if not hasattr(self, "annotation_tree"):
            return
        self.annotation_tree.delete(*self.annotation_tree.get_children())
        for item in self.pane.annotations:
            self.annotation_tree.insert("", "end", iid=item.uid, values=(tr(item.kind), tr(item.line_style), item.color))

    def _remove_annotations(self):
        selected = set(self.annotation_tree.selection())
        self.pane.annotations = [item for item in self.pane.annotations if item.uid not in selected]
        self.refresh_annotations()
        self.pane.refresh()

    def _clear_annotations(self):
        self.pane.annotations.clear()
        self.refresh_annotations()
        self.pane.refresh()

    def _close(self):
        self.pane.cancel_annotation()
        for variable, token in self._traces:
            try:
                variable.trace_remove("write", token)
            except tk.TclError:
                pass
        self.pane.settings_window = None
        self.destroy()


class AnnotationWindow(PlotSettingsWindow):
    """Direct graph annotation editor, kept separate from graph settings."""

    def __init__(self, pane):
        tk.Toplevel.__init__(self, pane)
        self.pane = pane
        self._traces = []
        self.title(tr("Lines and shapes"))
        self.geometry("760x650")
        self.minsize(650, 520)
        self.protocol("WM_DELETE_WINDOW", self._close)
        body = ttk.Frame(self, padding=10)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Lines and shapes", font=("Arial", 14, "bold")).pack(anchor="w", pady=(0, 8))
        self._build_annotations(body)
        language_manager.subscribe(self.language_changed)
        localize_widget_tree(self)

    def _close(self):
        self.pane.cancel_annotation()
        self.pane.annotation_window = None
        self.destroy()
