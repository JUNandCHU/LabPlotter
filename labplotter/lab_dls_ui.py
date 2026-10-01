"""Desktop Lab DLS workspace: left-side data list, two plots and live measurement controls."""
from __future__ import annotations

from dataclasses import asdict
import math
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, simpledialog, ttk

from matplotlib.colors import is_color_like

from .config import SettingsStore
from .i18n import canonical, localize_widget_tree, tr
from .lab_dls import (AVERAGING_NOTE, STATISTICS_NOTE, parse_dls_csv, statistics_csv, statistics_rows)
from .lab_dls_library import DLSLibrary
from .lab_dls_plot import DLSStyle, MeanLabelDrag, dls_plot_options, draw_dls, plot_series


def dls_tree_style(parent):
    font = tkfont.nametofont("TkDefaultFont")
    style = ttk.Style(parent)
    style.configure("LabDLS.Treeview", font=font, rowheight=max(30, font.metrics("linespace") + 12))
    style.configure("LabDLS.Treeview.Heading", font=font, padding=(5, 7))
    return "LabDLS.Treeview"


def scroll_tree(parent, columns, height=5, selectmode="extended"):
    box = ttk.Frame(parent)
    box.rowconfigure(0, weight=1); box.columnconfigure(0, weight=1)
    tree = ttk.Treeview(box, columns=[c[0] for c in columns], show="headings", height=height,
                        selectmode=selectmode, style=dls_tree_style(parent))
    for key, label, width in columns:
        tree.heading(key, text=tr(label)); tree.column(key, width=width, minwidth=60, stretch=True)
    vs = ttk.Scrollbar(box, command=tree.yview)
    hs = ttk.Scrollbar(box, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
    tree.grid(row=0, column=0, sticky="nsew"); vs.grid(row=0, column=1, sticky="ns")
    hs.grid(row=1, column=0, sticky="ew")
    return box, tree


class DLSResults(ttk.Frame):
    """Native per-row checkbuttons; collapsible per-particle overlay summaries."""
    def __init__(self, parent, show_particle=True, on_measurement_changed=None):
        super().__init__(parent)
        self.show_particle = show_particle
        self.on_measurement_changed = on_measurement_changed
        self.checks, self.check_vars = {}, {}
        self._check_job = None
        columns = (("measurement", "Measurement", 170), ("mean_radius", "Mean R (nm)", 92),
                   ("mean_diameter", "Mean D (nm)", 92), ("pd_percent", "%PD", 75))
        if show_particle:
            columns = (("expand", "+ / -", 45), ("particle", "Particle", 135)) + columns
        else:
            columns = (("hidden", "Hide", 62), ("excluded", "Exclude", 68)) + columns
        box, self.tree = scroll_tree(self, columns, height=4, selectmode="browse")
        if show_particle:
            self.tree.column("expand", width=45, minwidth=40, stretch=False)
            self.tree.bind("<Button-1>", self._expand_click)
            self.tree.bind("<Return>", self._expand_key)
            self.tree.bind("<space>", self._expand_key)
        else:
            for col in ("hidden", "excluded"):
                self.tree.column(col, minwidth=55, stretch=False)
            scrollbars = [w for w in box.winfo_children() if isinstance(w, ttk.Scrollbar)]
            vs = next(w for w in scrollbars if str(w.cget("orient"))=="vertical")
            hs = next(w for w in scrollbars if str(w.cget("orient"))=="horizontal")
            self.tree.configure(yscrollcommand=lambda a,b: (vs.set(a,b), self._schedule_checks()),
                                xscrollcommand=lambda a,b: (hs.set(a,b), self._schedule_checks()))
            for event in ("<Configure>", "<ButtonRelease-1>", "<B1-Motion>", "<<TreeviewSelect>>"):
                self.tree.bind(event, self._schedule_checks, add=True)
        self.tree.tag_configure("excluded", foreground="#858585")
        box.pack(fill="both", expand=True)
        note = "Averages use included measurements. Hide only affects individual curves." if not show_particle else "Particle averages; expand + for individual measurements."
        ttk.Label(self, text=tr(note), wraplength=530).pack(anchor="w", pady=3)
        self.rows = []
        self.bind("<Destroy>", self._destroy_checks, add=True)

    def _destroy_checks(self, event):
        if event.widget is self and self._check_job is not None:
            self.after_cancel(self._check_job); self._check_job = None

    def _schedule_checks(self, _event=None):
        if self._check_job is None:
            self._check_job = self.after_idle(self._place_checks)

    def _place_checks(self):
        self._check_job = None
        for (iid, col), button in self.checks.items():
            bounds = self.tree.bbox(iid, col)
            if bounds and bounds[0]>=0 and bounds[0]+bounds[2]<=self.tree.winfo_width():
                x,y,w,h = bounds
                button.place(x=x+(w-24)//2, y=y+1, width=24, height=h-2)
            else:
                button.place_forget()

    def _expand_click(self, event):
        iid = self.tree.identify_row(event.y)
        if self.tree.identify_column(event.x)=="#1" and iid and self.tree.parent(iid)=="":
            self.toggle_particle(iid)
            return "break"

    def _expand_key(self, _event):
        selected = self.tree.selection()
        if selected and self.tree.parent(selected[0])=="":
            self.toggle_particle(selected[0])
        return "break"

    def toggle_particle(self, iid):
        opened = not bool(self.tree.item(iid, "open"))
        self.tree.item(iid, open=opened)
        self.tree.set(iid, "expand", "-" if opened else "+")

    def update_particles(self, particles, representative=False):
        opened = {iid for iid in self.tree.get_children() if self.tree.item(iid,"open")}
        yview = self.tree.yview()
        self.rows = statistics_rows(particles, representative)
        for button in self.checks.values():
            button.destroy()
        self.checks.clear(); self.check_vars.clear()
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(self.rows):
            uid, kind = row["particle_uid"], row["kind"]
            label = tr("Average (n={n})", n=row["included_count"]) if kind=="average" else tr(row["measurement"])
            if row["excluded"]:
                label += " " + tr("[excluded]")
            values = [label, *["N/A" if row[k] is None else f"{row[k]:.4f}" for k in ("mean_radius","mean_diameter","pd_percent")]]
            tags = ("excluded",) if row["excluded"] else ()
            if self.show_particle:
                # One arithmetic mean per particle at the top level. Raw
                # measurement rows remain available under a collapsed parent.
                if kind=="representative":
                    continue
                if kind=="average":
                    self.tree.insert("", "end", iid=uid, values=["-" if uid in opened else "+", row["particle"], *values], open=uid in opened)
                else:
                    self.tree.insert(uid, "end", iid=f"{uid}:{row['measurement_index']}", values=["", "", *values], tags=tags)
            else:
                iid = f"row-{index}"
                self.tree.insert("", "end", iid=iid, values=["", "", *values], tags=tags)
                if kind=="measurement":
                    mi = row["measurement_index"]
                    for col in ("hidden", "excluded"):
                        var = tk.BooleanVar(value=row[col]); self.check_vars[(mi,col)] = var
                        button = ttk.Checkbutton(self.tree, variable=var,
                            command=lambda u=uid, i=mi, c=col, v=var: self.on_measurement_changed(u,i,c,v.get()))
                        self.checks[(iid,col)] = button
        if yview:
            self.tree.yview_moveto(yview[0])
        if not self.show_particle:
            self._schedule_checks()


class DLSSettings:
    title = "Lab DLS annotations"

    def __init__(self, owner, key, pane):
        self.owner, self.key, self.pane = owner, key, pane
        self.default = DLSStyle(show_lines=key=="selected", show_labels=key=="selected")
        raw = owner.settings.get("lab_dls_style_" + key, {})
        try:
            self.style = DLSStyle(**{**asdict(self.default), **raw})
        except TypeError:
            self.style = DLSStyle(**asdict(self.default))
        self.vars = {k: (tk.BooleanVar(value=v) if isinstance(v, bool) else tk.StringVar(value=str(v)))
                     for k, v in asdict(self.style).items()}
        self.colors = owner.settings.get("lab_dls_colors_" + key, {})

    def build(self, parent):
        for text, key in (("Show mean-radius lines", "show_lines"), ("Show mean R labels", "show_labels"),
                          ("Logarithmic radius axis", "log_x"), ("Bold mean R labels", "bold")):
            ttk.Checkbutton(parent, text=tr(text), variable=self.vars[key]).pack(anchor="w", pady=3)
        form = ttk.Frame(parent); form.pack(fill="x", pady=8)
        fields = (("Mean line style", "line_style"), ("Mean line width", "line_width"),
                  ("Mean R font size", "font_size"), ("Mean R font family", "font_family"),
                  ("Annotation opacity (0–1)", "alpha"), ("Decimal places", "decimals"),
                  ("Annotation color (blank = curve)", "color"))
        for row, (label, key) in enumerate(fields):
            ttk.Label(form, text=tr(label)).grid(row=row, column=0, sticky="w", padx=4, pady=4)
            if key == "line_style":
                widget = ttk.Combobox(form, textvariable=self.vars[key], values=("--", "-", ":", "-."), state="readonly", width=18)
            else:
                widget = ttk.Entry(form, textvariable=self.vars[key], width=22)
            widget.grid(row=row, column=1, sticky="ew", padx=4, pady=4)
        ttk.Button(parent, text=tr("Reset mean R label positions"), command=self.owner.drags[self.key].reset).pack(anchor="w", pady=5)
        ttk.Label(parent, text=tr("Drag mean R labels directly on the plot. Copy graph includes the visible labels."), wraplength=550).pack(anchor="w", pady=5)
        self.error = ttk.Label(parent, foreground="#A00000", wraplength=550); self.error.pack(anchor="w")
    def variables(self):
        return list(self.vars.values())

    def apply(self):
        values = {k: v.get() for k, v in self.vars.items()}
        try:
            for k in ("line_width", "font_size", "alpha"):
                values[k] = float(values[k])
                if not math.isfinite(values[k]):
                    raise ValueError()
            values["decimals"] = int(values["decimals"])
            if not (0 < values["line_width"] <= 20 and 4 <= values["font_size"] <= 72 and
                    0 <= values["alpha"] <= 1 and 0 <= values["decimals"] <= 8):
                raise ValueError()
            if values["color"] and not is_color_like(values["color"]):
                raise ValueError()
        except (ValueError, TypeError):
            if hasattr(self, "error") and self.error.winfo_exists():
                self.error.configure(text=tr("Enter valid colors, line width 0–20, font size 4–72, opacity 0–1 and decimals 0–8."))
            return
        if hasattr(self, "error") and self.error.winfo_exists():
            self.error.configure(text="")
        self.style = DLSStyle(**values)
        self.owner.settings.set("lab_dls_style_" + self.key, values)
        self.owner.settings.set("lab_dls_colors_" + self.key, self.colors)
        self.pane.refresh()

    def restore_defaults(self):
        for k, v in asdict(self.default).items():
            self.vars[k].set(v)
        self.colors.clear()
        self.apply()
        self.owner.drags[self.key].reset()


class DLSLibraryWindow(tk.Toplevel):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner, self.library = owner, owner.library
        self.title(tr("Lab DLS library")); self.geometry("850x500")
        actions = ttk.Frame(self, padding=8); actions.pack(fill="x")
        for i, (label, command) in enumerate((("Load into data list", self.load), ("Rename…", self.rename),
                ("Delete from library…", self.delete), ("Move up", lambda: self.move(-1)), ("Move down", lambda: self.move(1)))):
            ttk.Button(actions, text=tr(label), command=command).grid(row=i//3, column=i%3, sticky="ew", padx=3, pady=3)
        box, self.tree = scroll_tree(self, (("name", "Particle", 360), ("source", "Source", 390)))
        box.pack(fill="both", expand=True, padx=8, pady=8)
        self.tree.bind("<Double-1>", lambda _: self.load()); self.refresh()

    def refresh(self, selected=None):
        self.tree.delete(*self.tree.get_children())
        for row in self.library.entries():
            self.tree.insert("", "end", iid=row["uid"], values=(row["name"], Path(row["source"]).name))
        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected); self.tree.see(selected)

    def load(self):
        self.owner.add_particles([self.library.load(uid) for uid in self.tree.selection()])

    def rename(self):
        ids = self.tree.selection()
        if len(ids) == 1:
            value = simpledialog.askstring(tr("Rename…"), tr("Particle name"), initialvalue=self.tree.item(ids[0], "values")[0], parent=self)
            if value and value.strip():
                self.library.rename(ids[0], value); self.refresh(ids[0])

    def delete(self):
        ids = self.tree.selection()
        if ids and messagebox.askyesno(tr("Delete from library…"), tr("Delete saved particles? The current data list is kept."), parent=self):
            self.library.delete(ids); self.refresh()

    def move(self, offset):
        ids = self.tree.selection()
        if len(ids) == 1:
            self.library.move(ids[0], offset); self.refresh(ids[0])


class LabDLSTab(ttk.Frame):
    def __init__(self, parent, library=None, settings=None):
        from .ui import PlotPane
        super().__init__(parent)
        self.library = library or DLSLibrary()
        self.settings = settings or SettingsStore()
        self.particles = {}
        self.overlay_ids = []
        self.current_uid = None
        self.library_window = None
        self.all_measurements = tk.BooleanVar(value=False)
        self.average_selected = tk.BooleanVar(value=False)
        self.quick_controls = {}
        self.status = tk.StringVar()
        self.panes, self.results, self.drags, self.extensions, self.notices = {}, {}, {}, {}, {}
        workspace = ttk.Panedwindow(self, orient="horizontal"); workspace.pack(fill="both", expand=True)
        graphs = ttk.Panedwindow(workspace, orient="horizontal")
        controls = ttk.Frame(workspace, padding=6, width=310)
        workspace.add(controls, weight=1); workspace.add(graphs, weight=4)
        self.workspace, self.controls = workspace, controls
        self._initial_layout_complete = False
        def initialize_layout(_event=None):
            if not self._initial_layout_complete and workspace.winfo_width() > 800:
                workspace.sashpos(0, 300)
                self._initial_layout_complete = True
        workspace.bind("<Configure>", initialize_layout)
        for key, title in (("selected", "Selected particle"), ("overlay", "Particle overlay")):
            panel = ttk.LabelFrame(graphs, text=tr(title), padding=4); graphs.add(panel, weight=1)
            split = ttk.Panedwindow(panel, orient="vertical"); split.pack(fill="both", expand=True)
            top = ttk.Frame(split); bottom = ttk.LabelFrame(split, text=tr("Distribution results"), padding=3)
            split.add(top, weight=4); split.add(bottom, weight=1)
            pane = PlotPane(top, lambda ax, opts, k=key: self._draw(k, ax, opts), dls_plot_options(),
                            compact=True, draggable_legend=True, export_current_view=True)
            pane.pack(fill="both", expand=True); self.panes[key] = pane
            self.extensions[key] = pane.settings_extension = DLSSettings(self, key, pane)
            positions = self.settings.get("lab_dls_positions_" + key, {})
            self.drags[key] = MeanLabelDrag(pane, positions, lambda values, k=key: self.settings.set("lab_dls_positions_" + k, values))
            actions = ttk.Frame(bottom); actions.pack(fill="x")
            for label, command in (("Fit Y axis", lambda k=key: self.fit_y(k)),
                                   ("Calculation method…", self.show_method), ("Export results…", lambda k=key: self.export_results(k))):
                ttk.Button(actions, text=tr(label), command=command).pack(side="left", padx=2)
            quick = ttk.Frame(bottom); quick.pack(fill="x", pady=3)
            extension = self.extensions[key]
            self.quick_controls[key] = {}
            for i, (label, field) in enumerate((("Mean R labels", "show_labels"), ("Mean lines", "show_lines"))):
                button = ttk.Checkbutton(quick, text=tr(label), variable=extension.vars[field], command=extension.apply)
                button.grid(row=0, column=i, sticky="w", padx=2)
                self.quick_controls[key][field] = button
            reset = ttk.Button(quick, text=tr("Reset mean R label positions"), command=self.drags[key].reset)
            reset.grid(row=2, column=0, columnspan=2, sticky="w", padx=2, pady=2)
            self.quick_controls[key]["reset"] = reset
            if key=="selected":
                button = ttk.Checkbutton(quick, text=tr("Average distribution only"), variable=self.average_selected, command=self.refresh_selected)
                button.grid(row=1, column=0, columnspan=2, sticky="w", padx=2)
                self.quick_controls[key]["average"] = button
            self.notices[key] = ttk.Label(bottom, wraplength=430, foreground="#875000")
            self.notices[key].pack(fill="x")
            self.results[key] = DLSResults(bottom, show_particle=key=="overlay", on_measurement_changed=self.set_measurement_state); self.results[key].pack(fill="both", expand=True)
        self.plot = self.panes["selected"]
        self.plot_panes = tuple(self.panes.values())
        ttk.Button(controls, text=tr("Import Lab DLS CSV…"), command=self.import_dialog).pack(fill="x", pady=2)
        ttk.Button(controls, text=tr("Open Lab DLS library…"), command=self.open_library).pack(fill="x", pady=2)
        ttk.Label(controls, text=tr("Loaded particles")).pack(anchor="w", pady=(8, 3))
        box, self.tree = scroll_tree(controls, (("name", "Particle", 285),), height=6)
        box.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.select)
        buttons = ttk.Frame(controls); buttons.pack(fill="x", pady=3)
        for i, (label, command) in enumerate((("Rename…", self.rename), ("Save to library", self.save), ("Remove from data list", self.remove))):
            ttk.Button(buttons, text=tr(label), command=command).grid(row=i, column=0, sticky="ew", pady=2)
        buttons.columnconfigure(0, weight=1)
        ttk.Button(controls, text=tr("Register graph overlay"), command=self.register_overlay).pack(fill="x", pady=(10, 3))
        ttk.Checkbutton(controls, text=tr("Show all measurements in overlay"), variable=self.all_measurements,
                        command=self.refresh_overlay, style="LabDLS.TCheckbutton").pack(anchor="w", pady=4)
        ttk.Style(self).configure("LabDLS.TCheckbutton", wraplength=285)
        ttk.Label(controls, text=tr("Registered overlay particles")).pack(anchor="w", pady=(5, 3))
        box, self.overlay_tree = scroll_tree(controls, (("name", "Particle", 285),), height=4)
        box.pack(fill="both", expand=True)
        ttk.Button(controls, text=tr("Remove from overlay"), command=self.remove_overlay).pack(fill="x", pady=3)
        ttk.Label(controls, textvariable=self.status, wraplength=290).pack(fill="x", pady=5)
        localize_widget_tree(self)

    def displayed(self, key):
        if key == "selected":
            return [self.particles[self.current_uid]] if self.current_uid in self.particles else []
        return [self.particles[uid] for uid in self.overlay_ids if uid in self.particles]

    def curves(self, key):
        return plot_series(self.displayed(key), overlay=key=="overlay", all_measurements=self.all_measurements.get(), average=key=="selected" and self.average_selected.get())

    def _draw(self, key, axis, options):
        curves, errors = self.curves(key)
        extension = self.extensions[key]
        labels = draw_dls(axis, options, curves, extension.style, self.drags[key].positions, extension.colors,
                          lambda: self.settings.set("lab_dls_colors_" + key, extension.colors))
        self.drags[key].set_artists(labels)
        if not curves:
            text = "No visible measurements. Check Hide / Exclude." if self.displayed(key) else ("Register particles with the overlay button." if key=="overlay" else "Import a CSV and select a particle.")
            axis.text(.5, .45, tr(text),
                      transform=axis.transAxes, ha="center", va="center", wrap=True)
        ymax = options.y_max
        clipped = ymax is not None and any(float(c[2].intensity.max()) > ymax for c in curves)
        notice = "\n".join(errors)
        if clipped:
            notice = (notice + "\n" if notice else "") + tr("Peaks exceed the Y range. Use Fit Y axis to see the full curves.")
        self.notices[key].configure(text=notice)

    def _refresh(self):
        self.refresh_selected(); self.refresh_overlay()

    def refresh_selected(self):
        self.plot.refresh(); self.results["selected"].update_particles(self.displayed("selected"), representative=self.average_selected.get())

    def refresh_overlay(self):
        selection = self.overlay_tree.selection()
        self.overlay_tree.delete(*self.overlay_tree.get_children())
        for p in self.displayed("overlay"):
            self.overlay_tree.insert("", "end", iid=p.uid, values=(p.name,))
        self.overlay_tree.selection_set([uid for uid in selection if self.overlay_tree.exists(uid)])
        self.panes["overlay"].refresh()
        self.results["overlay"].update_particles(self.displayed("overlay"), representative=not self.all_measurements.get())

    def add_particles(self, particles):
        for p in particles:
            self.particles[p.uid] = p
            if self.tree.exists(p.uid):
                self.tree.item(p.uid, values=(p.name,))
            else:
                self.tree.insert("", "end", iid=p.uid, values=(p.name,))
        if particles:
            self.current_uid = particles[-1].uid
            self.tree.selection_set(self.current_uid); self.tree.focus(self.current_uid); self.tree.see(self.current_uid)
        self._refresh()

    def import_dialog(self):
        self.add_paths(filedialog.askopenfilenames(parent=self, filetypes=(("Lab DLS CSV", "*.csv"),)))

    def add_paths(self, paths):
        particles, errors = [], []
        for path in paths:
            try:
                particles.append(parse_dls_csv(path))
            except (ValueError, OSError) as exc:
                errors.append(f"{Path(path).name}: {exc}")
        self.add_particles(particles)
        self.status.set(tr("Imported {n} particles.", n=len(particles)))
        if errors:
            messagebox.showerror(tr("Lab DLS import"), "\n".join(errors), parent=self)

    def select(self, _event=None):
        selected = self.tree.selection()
        self.current_uid = (self.tree.focus() if self.tree.focus() in selected else selected[0]) if selected else None
        self.refresh_selected()

    def rename(self):
        selected = self.tree.selection()
        if len(selected) == 1:
            p = self.particles[selected[0]]
            value = simpledialog.askstring(tr("Rename…"), tr("Particle name"), initialvalue=p.name, parent=self)
            if value and value.strip():
                p.name = value.strip(); self.tree.item(p.uid, values=(p.name,)); self._refresh()

    def save(self):
        selected = self.tree.selection()
        try:
            for uid in selected:
                self.library.save(self.particles[uid])
            if self.library_window and self.library_window.winfo_exists():
                self.library_window.refresh()
            self.status.set(tr("Saved {n} particles to Lab DLS library.", n=len(selected)))
        except (ValueError, OSError) as exc:
            messagebox.showerror(tr("Lab DLS library"), str(exc), parent=self)

    def remove(self):
        for uid in self.tree.selection():
            self.particles.pop(uid, None); self.tree.delete(uid)
            if uid in self.overlay_ids:
                self.overlay_ids.remove(uid)
        ids = self.tree.get_children()
        self.current_uid = ids[0] if ids else None
        if self.current_uid:
            self.tree.selection_set(self.current_uid); self.tree.focus(self.current_uid)
        self._refresh()

    def set_measurement_state(self, uid, index, field, value):
        if field not in ("hidden", "excluded"):
            raise ValueError("Unknown measurement setting")
        setattr(self.particles[uid].measurements[index], field, bool(value))
        self._refresh()

    def register_overlay(self):
        for uid in self.tree.selection():
            if uid not in self.overlay_ids:
                self.overlay_ids.append(uid)
        self.refresh_overlay()

    def remove_overlay(self):
        selected = set(self.overlay_tree.selection())
        self.overlay_ids = [uid for uid in self.overlay_ids if uid not in selected]
        self.refresh_overlay()

    def open_library(self):
        if self.library_window and self.library_window.winfo_exists():
            self.library_window.refresh(); self.library_window.lift()
        else:
            self.library_window = DLSLibraryWindow(self)

    def fit_y(self, key):
        curves, _ = self.curves(key)
        pane = self.panes[key]
        pane.vars["y_min"].set("0")
        pane.vars["y_max"].set(str(max([1, *[float(c[2].intensity.max()) * 1.12 for c in curves]])))
        pane.refresh()

    def show_method(self):
        messagebox.showinfo(tr("Calculation method"), tr(STATISTICS_NOTE) + "\n\n" + tr(AVERAGING_NOTE), parent=self)

    def export_results(self, key):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", initialfile="Lab_DLS_results.csv", filetypes=(("CSV", "*.csv"),))
        if path:
            Path(path).write_text(statistics_csv(self.displayed(key), (key=="overlay" and not self.all_measurements.get()) or (key=="selected" and self.average_selected.get())), encoding="utf-8-sig")
