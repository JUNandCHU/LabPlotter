"""Desktop C/H workspace and the quantitative complex 1H workflow."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, font as tkfont
from tkinter.scrolledtext import ScrolledText

import numpy as np
from .i18n import tr, localize_widget_tree
from .hnmr import (HNMRSettings, QuantSettings, common_settings, infer_identity,
                   parse_hnmr_ascii, prepare_spectra, preview_spectrum, quant_defaults,
                   quantify, result_csv)
from .hnmr_library import (HNMRLibrary, HNMRParameterLibrary, PARAMETER_FIELDS,
                           export_hnmr_library, import_hnmr_library, validate_parameters)
from .nmr_ui import SSNMRTab, nmr_tree_style, save_text
from .plotting import PlotOptions, SERIES_PALETTE
from .curve_colors import curve_color


def _tree(parent, columns, height=8, selectmode="extended"):
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=height,
                        selectmode=selectmode, style=nmr_tree_style(parent))
    for key, label, width in columns:
        width = max(width, tkfont.nametofont("TkDefaultFont").measure(tr(label))+28)
        tree.heading(key, text=tr(label)); tree.column(key, width=width, minwidth=60, stretch=key == columns[0][0])
    sy = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    sx = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
    tree.grid(row=0, column=0, sticky="nsew"); sy.grid(row=0, column=1, sticky="ns"); sx.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1); frame.columnconfigure(0, weight=1)
    return frame, tree


class Fields(ttk.Frame):
    """Short, labeled forms; nullable numbers remain blank, never guessed."""
    def __init__(self, parent, specs, values):
        super().__init__(parent, padding=10)
        self.specs, self.vars, self.widgets = specs, {}, {}
        self.canvas = tk.Canvas(self, highlightthickness=0, width=650, height=min(480, len(specs)*48))
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True); scrollbar.pack(side="right", fill="y")
        body = ttk.Frame(self.canvas)
        window = self.canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(window, width=event.width))
        body.columnconfigure(1, weight=1)
        for i, (key, label, kind) in enumerate(specs):
            value = values.get(key)
            var = tk.BooleanVar(value=bool(value)) if kind == "bool" else tk.StringVar(value="" if value is None else str(value))
            self.vars[key] = var
            ttk.Label(body, text=tr(label), wraplength=360).grid(row=i, column=0, sticky="w", padx=(0, 15), pady=5)
            if kind == "bool":
                widget = ttk.Checkbutton(body, variable=var)
            elif isinstance(kind, tuple) or kind == "basis":
                options = kind if isinstance(kind, tuple) else ("ppm", "point_sum", "hz")
                widget = ttk.Combobox(body, textvariable=var, values=options, state="readonly", width=24)
            else:
                widget = ttk.Entry(body, textvariable=var, width=26)
            widget.grid(row=i, column=1, sticky="ew", pady=5)
            self.widgets[key] = widget

    def values(self):
        result = {}
        for key, _, kind in self.specs:
            value = self.vars[key].get()
            if kind in ("positive", "number", "optional"):
                if not str(value).strip() and kind == "optional":
                    result[key] = None
                else:
                    try:
                        result[key] = float(value)
                    except ValueError as exc:
                        raise ValueError(f"{key}: enter a number.") from exc
            else:
                result[key] = value.strip() if isinstance(value, str) else value
        return result

    def set_values(self, values):
        for key, value in values.items():
            if key in self.vars:
                self.vars[key].set("" if value is None else value)


def _window(window, title, geometry="1050x740"):
    window.title(tr(title)); window.geometry(geometry)
    window.minsize(850, 620)
    window.transient(window.master.winfo_toplevel())
    window.after_idle(lambda: localize_widget_tree(window))


def _wrap_controls(frame):
    """Wrap quick controls using actual font-sized widget widths."""
    widgets = frame.winfo_children()
    for widget in widgets: widget.pack_forget()
    def layout(_=None):
        width = max(frame.winfo_width(), 1); used = 0; row = 0; col = 0
        for widget in widgets:
            needed = widget.winfo_reqwidth()+8
            if used and used+needed > width: row += 1; col = 0; used = 0
            widget.grid(row=row, column=col, sticky="w", padx=4, pady=2)
            used += needed; col += 1
    frame.bind("<Configure>", layout, add=True)
    frame.after_idle(layout)


class ParameterWindow(tk.Toplevel):
    def __init__(self, workspace):
        super().__init__(workspace)
        _window(self, "H NMR parameter library")
        self.columnconfigure(0, weight=1); self.rowconfigure(1, weight=1)
        self.workspace = workspace
        self.document = workspace.parameters.load()
        ttk.Label(self, text="Saved independently of spectra and retained across launches. Use the confirmation dialog for one calculation's overrides.",
                  padding=10, wraplength=980).grid(row=0, column=0, sticky="ew")
        self.book = ttk.Notebook(self); self.book.grid(row=1, column=0, sticky="nsew", padx=10)
        self.trees = {}
        for section, label in (("standards", "Internal standards"), ("cores", "Core capacities"),
                               ("ligands", "Ligands"), ("samples", "Sample masses")):
            page = ttk.Frame(self.book); self.book.add(page, text=label)
            specs = PARAMETER_FIELDS[section]
            frame, tree = _tree(page, [(k, title, 230 if i == 0 else 180) for i, (k, title, _) in enumerate(specs)], selectmode="browse")
            frame.pack(fill="both", expand=True); self.trees[section] = tree
            row = ttk.Frame(page, padding=6); row.pack(fill="x")
            for text, func in (("Add...", lambda s=section: self.edit(s, True)), ("Edit...", lambda s=section: self.edit(s)),
                               ("Delete", lambda s=section: self.delete(s)), ("Move up", lambda s=section: self.move(s, -1)),
                               ("Move down", lambda s=section: self.move(s, 1))):
                ttk.Button(row, text=text, command=func).pack(side="left", padx=3)
            tree.bind("<Double-1>", lambda _, s=section: self.edit(s))
        ttk.Label(self, text="MW values are for parent free-base ligands. Effective H excludes exchangeable protons; verify band capture. Lys has MW only.\n"
                  "The supplied standard area is unverified: select its true unit and original grid/frequency before validating absolute values.",
                  padding=10, wraplength=980).grid(row=2, column=0, sticky="ew")
        row = ttk.Frame(self, padding=8); row.grid(row=3, column=0, sticky="ew")
        ttk.Button(row, text="Export parameters...", command=lambda: save_text(self, json.dumps(self.document, indent=2, ensure_ascii=False), "H_NMR_parameters.json", ".json")).pack(side="left")
        ttk.Button(row, text="Import parameters...", command=self.import_parameters).pack(side="left", padx=5)
        self.status = tk.StringVar(value="Edits save immediately after validation.")
        ttk.Label(row, textvariable=self.status).pack(side="left", padx=8)
        self.refresh()

    def refresh(self):
        for section, tree in self.trees.items():
            tree.delete(*tree.get_children())
            for i, row in enumerate(self.document[section]):
                tree.insert("", "end", iid=str(i), values=["" if row[k] is None else row[k] for k, _, _ in PARAMETER_FIELDS[section]])

    def commit(self, document):
        self.workspace.parameters.save(document)
        self.document = document; self.refresh(); self.status.set("Parameters saved.")

    def edit(self, section, new=False):
        selected = self.trees[section].selection()
        if not new and not selected:
            return
        index = len(self.document[section]) if new else int(selected[0])
        values = {} if new else self.document[section][index]
        dialog = tk.Toplevel(self); dialog.title("Edit " + section); dialog.transient(self)
        form = Fields(dialog, PARAMETER_FIELDS[section], values); form.pack(fill="both", expand=True)
        status = tk.StringVar(); ttk.Label(dialog, textvariable=status, foreground="#AE2C28", wraplength=650).pack(fill="x", padx=10)
        def save():
            try:
                document = deepcopy(self.document); row = form.values()
                if new: document[section].append(row)
                else: document[section][index] = row
                self.commit(document)
            except Exception as exc:
                status.set(str(exc)); return
            dialog.destroy()
        ttk.Button(dialog, text="Save", command=save).pack(fill="x", padx=10, pady=10)

    def delete(self, section):
        ids = self.trees[section].selection()
        if ids and messagebox.askyesno("Delete parameter", "Delete this saved parameter?", parent=self):
            document = deepcopy(self.document); document[section].pop(int(ids[0]))
            try: self.commit(document)
            except ValueError as exc: messagebox.showerror("Parameter library", str(exc), parent=self)

    def move(self, section, offset):
        ids = self.trees[section].selection()
        if ids:
            document = deepcopy(self.document); rows = document[section]
            i = int(ids[0]); j = max(0, min(len(rows)-1, i+offset))
            rows.insert(j, rows.pop(i)); self.commit(document); self.trees[section].selection_set(str(j))

    def import_parameters(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[("H NMR parameters", "*.json")])
        if path:
            try:
                document = validate_parameters(json.loads(Path(path).read_text(encoding="utf-8-sig")))
                if messagebox.askyesno("Import parameters", "Replace the parameter library with this file?", parent=self): self.commit(document)
            except Exception as exc: messagebox.showerror("Parameter library", str(exc), parent=self)


PREPROCESS_FIELDS = [
    ("ppm_min", "Common ppm minimum", "number"), ("ppm_max", "Common ppm maximum", "number"),
    ("grid_step", "Grid step (ppm)", "number"), ("phase", "Automatic zero-order phase correction", "bool"),
    ("baseline", "Robust linear edge baseline correction", "bool"),
    ("edge_fraction", "Baseline edge fraction (each end)", "number"),
    ("phase0_offset", "Additional zero-order phase (degrees)", "number"),
    ("phase1_deg", "First-order phase across range (degrees)", "number"),
    ("gaussian_fwhm", "Shared Gaussian FWHM (ppm; 0 = none)", "number"),
    ("align", "Align to first activated spectrum", "bool"), ("max_shift", "Maximum shift (ppm)", "number"),
    ("alignment_min", "Alignment ppm minimum", "number"), ("alignment_max", "Alignment ppm maximum", "number")]


class HPreprocessingDialog(tk.Toplevel):
    def __init__(self, workspace):
        super().__init__(workspace)
        _window(self, "H NMR common preprocessing", "1140x850")
        self.columnconfigure(0, weight=1); self.rowconfigure(0, weight=1)
        self.workspace = workspace; self.active = {s.uid for s in workspace.spectra}
        body = ttk.Panedwindow(self, orient="horizontal"); body.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        left = ttk.Frame(body); right = ttk.Frame(body); body.add(left, weight=1); body.add(right, weight=2)
        ttk.Label(left, text="Click Active or press Space to toggle a spectrum.", padding=5, wraplength=350).pack(fill="x")
        frame, self.tree = _tree(left, [("active", "Active", 65), ("name", "Loaded H NMR spectra", 300)])
        frame.pack(fill="both", expand=True)
        for s in workspace.spectra: self.tree.insert("", "end", iid=s.uid, values=("Yes", s.name))
        self.tree.bind("<Button-1>", self.click); self.tree.bind("<space>", self.toggle_selected)
        ttk.Button(left, text="Select all", command=lambda: self.set_active(True)).pack(fill="x", pady=3)
        ttk.Button(left, text="Clear selection", command=lambda: self.set_active(False)).pack(fill="x", pady=3)
        ttk.Button(left, text="Get preprocessing condition", command=self.get_condition).pack(fill="x", pady=8)
        self.form = Fields(right, PREPROCESS_FIELDS, asdict(common_settings(workspace.spectra)))
        self.form.pack(fill="both", expand=True)
        ttk.Label(self, text="No intensity normalization. Default: measured overlap within -40 to 50 ppm, the coarsest native grid, no broadening/alignment.\n"
                  "Inspect the candidate baseline edges and automatic phase. Per-spectrum manual phase overrides are retained when preparing a group; clear an override to restore automatic phase.",
                  wraplength=1080, padding=8).grid(row=1, column=0, sticky="ew")
        self.status = tk.StringVar(value="Activate sample and matching pristine core together. Applying prepares data in memory; Save to library retains it across launches.")
        ttk.Label(self, textvariable=self.status, wraplength=1080, padding=8).grid(row=2, column=0, sticky="ew")
        ttk.Button(self, text="Apply common preprocessing", command=self.apply).grid(row=3, column=0, sticky="ew", padx=12, pady=8)

    def selected_spectra(self):
        return [s for s in self.workspace.spectra if s.uid in self.active]

    def click(self, event):
        if self.tree.identify_column(event.x) == "#1":
            uid = self.tree.identify_row(event.y)
            if uid: self.toggle(uid)

    def toggle_selected(self, _=None):
        for uid in self.tree.selection(): self.toggle(uid)
        return "break"

    def toggle(self, uid):
        if uid in self.active: self.active.remove(uid)
        else: self.active.add(uid)
        self.tree.set(uid, "active", "Yes" if uid in self.active else "No")

    def set_active(self, enabled):
        self.active = {s.uid for s in self.workspace.spectra} if enabled else set()
        for uid in self.tree.get_children(): self.tree.set(uid, "active", "Yes" if enabled else "No")

    def get_condition(self):
        try:
            settings = common_settings(self.selected_spectra())
            self.form.set_values(asdict(settings))
            self.status.set(f"Common conditions ready for {len(self.active)} spectra. Review, then Apply.")
        except Exception as exc: self.status.set(str(exc))

    def apply(self):
        try:
            selected = self.selected_spectra()
            results = prepare_spectra(selected, HNMRSettings(**self.form.values()))
            self.workspace.invalidate_all(); self.workspace.refresh_rows(); self.workspace._refresh()
            self.status.set(f"Prepared {len(results)} spectra in one group. Individual phases appear below the data list and in the calculation audit. Save to library to retain this group.")
        except Exception as exc: self.status.set(str(exc))


QUANT_SAMPLE = [("core", "Core", "text"), ("ligand", "Ligand / hypothetical ligand for blank check", "text"),
                ("sample_mass_mg", "Mass used as coverage denominator (mg)", "optional"),
                ("reference_mass_mg", "Pristine reference mass (mg)", "optional"),
                ("capacity_umol_mg", "Core maximum loading (umol/mg)", "number"),
                ("molecular_weight", "Parent ligand MW (g/mol)", "number"),
                ("effective_h", "Effective H represented by quantified band", "optional"),
                ("core_scaling", "Core scaling method", ("aromatic", "mass")),
                ("use_prepared", "Use saved common preprocessing", "bool")]
QUANT_CALIBRATION = [("standard_area", "Internal standard area", "number"),
                     ("standard_mmol_h", "Internal standard amount (mmol H)", "number"),
                     ("standard_basis", "Standard area basis", "basis"),
                     ("standard_grid_step", "STANDARD original grid step (ppm)", "optional"),
                     ("frequency_mhz", "Frequency (MHz, for Hz area)", "optional"),
                     ("response_factor", "Sample response multiplier to standard scale", "number"),
                     ("reference_response_factor", "Core response multiplier to standard scale", "number"),
                     ("calibration_verified", "Standard area unit and scale verified", "bool"),
                     ("acquisition_verified", "Quantitative acquisition / response verified", "bool")]
QUANT_REGIONS = [("aliphatic_min", "Aliphatic minimum (ppm)", "number"),
                 ("aliphatic_max", "Aliphatic maximum (ppm)", "number"),
                 ("aromatic_min", "Aromatic minimum (ppm)", "number"),
                 ("aromatic_max", "Aromatic maximum (ppm)", "number"),
                 ("method", "Area method: regions / three-band Gaussian", ("regions", "gaussian")),
                 ("assignments_verified", "Band capture / effective proton count verified", "bool")]


class QuantDialog(tk.Toplevel):
    def __init__(self, workspace, sample):
        super().__init__(workspace)
        _window(self, "Confirm H NMR quantitative analysis", "1040x800")
        self.workspace, self.sample = workspace, sample
        self.columnconfigure(0, weight=1); self.rowconfigure(2, weight=1)
        self.parameters = workspace.parameters.load()
        q = quant_defaults(sample, self.parameters)
        if sample.metadata.get("analysis_parameters"):
            q = QuantSettings(**sample.metadata["analysis_parameters"])
        ttk.Label(self, text="Sample: " + sample.name, padding=10, wraplength=980).grid(row=0, column=0, sticky="ew")
        top = ttk.Frame(self, padding=8); top.grid(row=1, column=0, sticky="ew")
        ttk.Label(top, text="Pristine core reference").grid(row=0, column=0, sticky="w")
        self.reference = ttk.Combobox(top, state="readonly", width=62, values=[f"{i+1}. {s.name}" for i, s in enumerate(workspace.spectra)])
        self.reference.grid(row=0, column=1, sticky="ew", padx=8, pady=4); top.columnconfigure(1, weight=1)
        self.choose_reference(q.core)
        ttk.Label(top, text="Parameter presets").grid(row=1, column=0, sticky="w")
        presets = ttk.Frame(top); presets.grid(row=1, column=1, sticky="ew", pady=5)
        self.presets = {}
        for section, label in (("cores", "Core"), ("ligands", "Ligand"), ("standards", "Standard")):
            box = ttk.Combobox(presets, values=[r["name"] for r in self.parameters[section]], state="readonly", width=19)
            box.set(q.core if section == "cores" else q.ligand if section == "ligands" else self.parameters[section][0]["name"])
            box.pack(side="left", padx=3); self.presets[section] = box
            box.bind("<<ComboboxSelected>>", lambda _, s=section: self.load_preset(s))
        book = ttk.Notebook(self); book.grid(row=2, column=0, sticky="nsew", padx=10)
        self.forms = []
        for label, specs in (("Sample and core", QUANT_SAMPLE), ("Calibration", QUANT_CALIBRATION), ("Regions and decomposition", QUANT_REGIONS)):
            form = Fields(book, specs, asdict(q)); self.forms.append(form); book.add(form, text=label)
        self.fields = {k: v for f in self.forms for k, v in f.vars.items()}
        self.fields["core"].trace_add("write", self.core_changed)
        p = sample.processing
        ttk.Label(self, text=f"Saved preprocessing: {'prepared, group '+p.get('group_id','')[:8] if p.get('prepared') else 'not prepared'}. "
                  "If unchecked, both spectra are freshly processed on a common default grid using the sample's phase/baseline switches.\n"
                  "Region mode subtracts pristine-core aliphatic background scaled by the aromatic band. Gaussian mode is a 3-band model with a middle nuisance band.\n"
                  "Default masses are weighed sample masses. Enter core mass instead if your capacity model uses core mass. Unknown calibration remains provisional.",
                  wraplength=980, padding=10).grid(row=3, column=0, sticky="ew")
        self.status = tk.StringVar()
        ttk.Label(self, textvariable=self.status, foreground="#AE2C28", wraplength=980, padding=6).grid(row=4, column=0, sticky="ew")
        ttk.Button(self, text="Confirm parameters and calculate", command=self.calculate).grid(row=5, column=0, sticky="ew", padx=12, pady=10)

    def choose_reference(self, core):
        candidates = [i for i, s in enumerate(self.workspace.spectra) if infer_identity(s.name) == (core, "")]
        if candidates: self.reference.current(candidates[0])
        else: self.reference.set("")

    def core_changed(self, *_):
        core = self.fields["core"].get()
        self.choose_reference(core)
        for row in self.parameters["cores"]:
            if row["name"] == core: self.fields["capacity_umol_mg"].set(row["capacity"])
        masses = {r["name"]: r["mass_mg"] for r in self.parameters["samples"]}
        self.fields["reference_mass_mg"].set(masses.get(core, ""))

    def load_preset(self, section):
        name = self.presets[section].get()
        row = next(r for r in self.parameters[section] if r["name"] == name)
        if section == "cores": values = {"core": name, "capacity_umol_mg": row["capacity"]}
        elif section == "ligands": values = {"ligand": name, "molecular_weight": row["mw"], "effective_h": row["effective_h"]}
        else:
            values = {k: row[v] for k, v in (("standard_area", "area"), ("standard_mmol_h", "mmol_h"),
                      ("standard_basis", "basis"), ("standard_grid_step", "grid_step"),
                      ("frequency_mhz", "frequency_mhz"), ("calibration_verified", "verified"))}
        for f in self.forms: f.set_values(values)

    def calculate(self):
        try:
            index = self.reference.current()
            if index < 0: raise ValueError("Choose the matching pristine core reference from the loaded data list.")
            values = {}; [values.update(f.values()) for f in self.forms]
            q = QuantSettings(**values)
            ref = self.workspace.spectra[index]
            inferred, ligand = infer_identity(ref.name)
            if (inferred and inferred != q.core) or ligand:
                raise ValueError("Choose a matching pristine core reference. Its name currently identifies another core or a modified sample; rename it if necessary.")
            result = quantify(self.sample, ref, q)
            self.sample.metadata["analysis_parameters"] = asdict(q)
            self.sample.metadata["analysis_audit"] = result.audit
            self.workspace.results[self.sample.uid] = result
            self.workspace._refresh(); self.destroy()
        except Exception as exc: self.status.set(str(exc))


class HLibraryWindow(tk.Toplevel):
    def __init__(self, workspace):
        super().__init__(workspace); _window(self, "H NMR spectrum library")
        self.workspace, self.library = workspace, workspace.library
        row = ttk.Frame(self, padding=8); row.pack(fill="x")
        for label, command in (("Load into data list", self.load), ("Rename...", self.rename),
                               ("Delete", self.delete), ("Move up", lambda: self.move(-1)), ("Move down", lambda: self.move(1))):
            ttk.Button(row, text=tr(label), command=command).pack(side="left", padx=3)
        frame, self.tree = _tree(self, [("name", "Saved H NMR spectra", 400), ("prepared", "Preprocessing", 130), ("group", "Group", 120)])
        frame.pack(fill="both", expand=True, padx=8)
        bottom = ttk.Frame(self, padding=8); bottom.pack(fill="x")
        ttk.Button(bottom, text="Export library JSON...", command=self.export).pack(side="left", padx=3)
        ttk.Button(bottom, text="Import library JSON...", command=self.import_data).pack(side="left", padx=3)
        self.refresh()

    def refresh(self, uid=None):
        self.tree.delete(*self.tree.get_children())
        for row in self.library.entries(): self.tree.insert("", "end", iid=row["uid"], values=(row["name"], "Prepared" if row["prepared"] else "Preview only", row["group"]))
        if uid and self.tree.exists(uid): self.tree.selection_set(uid)

    def load(self):
        self.workspace.add_spectra([self.library.load(uid) for uid in self.tree.selection()])

    def rename(self):
        ids = self.tree.selection()
        if len(ids) == 1:
            name = simpledialog.askstring("Rename", "Spectrum name", initialvalue=self.tree.item(ids[0], "values")[0], parent=self)
            if name and name.strip(): self.library.rename(ids[0], name); self.refresh(ids[0])

    def delete(self):
        ids = self.tree.selection()
        if ids and messagebox.askyesno("Delete saved spectra", "Delete selected library entries? Loaded data are retained.", parent=self):
            self.library.delete(ids); self.refresh()

    def move(self, offset):
        ids = self.tree.selection()
        if len(ids) == 1: self.library.move(ids[0], offset); self.refresh(ids[0])

    def export(self):
        spectra = [self.library.load(r["uid"]) for r in self.library.entries()]
        save_text(self, export_hnmr_library(spectra), "H_NMR_library.json", ".json")

    def import_data(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[("H NMR library", "*.json")])
        if path:
            try:
                spectra = import_hnmr_library(Path(path).read_text(encoding="utf-8-sig"))
                existing = {r["uid"] for r in self.library.entries()}
                if any(s.uid in existing for s in spectra) and not messagebox.askyesno("Import library", "Replace saved spectra with matching IDs?", parent=self): return
                for s in spectra: self.library.save(s)
                self.refresh()
            except Exception as exc: messagebox.showerror("H NMR library", str(exc), parent=self)


class HNMRTab(ttk.Frame):
    def __init__(self, parent, library=None, parameters=None):
        from .ui import PlotPane
        super().__init__(parent)
        self.library = library or HNMRLibrary(); self.parameters = parameters or HNMRParameterLibrary()
        self.spectra = []; self.results = {}; self.cache = {}; self.library_window = None; self.parameter_window = None
        panes = ttk.Panedwindow(self, orient="horizontal"); panes.pack(fill="both", expand=True)
        left = ttk.Frame(panes, padding=8, width=320); right = ttk.Frame(panes, padding=5)
        panes.add(left, weight=0); panes.add(right, weight=1)
        for label, command in (("Import H NMR ASCII...", self.add_dialog), ("Open H NMR library...", self.open_library),
                               ("Parameter library...", self.open_parameters), ("Preprocessing...", self.preprocessing),
                               ("Quantitative analysis...", self.analyze)):
            ttk.Button(left, text=tr(label), command=command).pack(fill="x", pady=3)
        actions = ttk.Frame(left); actions.pack(fill="x", pady=3)
        for label, command in (("Save to library", self.save), ("Rename...", self.rename), ("Remove", self.remove)):
            ttk.Button(actions, text=tr(label), command=command).pack(side="left", fill="x", expand=True, padx=2)
        frame, self.tree = _tree(left, [("name", "Loaded H NMR spectra", 270), ("prepared", "Prep.", 85)])
        frame.pack(fill="both", expand=True, pady=6)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self._refresh())
        self.tree.bind("<Double-1>", lambda _: self.rename())
        order = ttk.Frame(left); order.pack(fill="x")
        ttk.Button(order, text="Move up", command=lambda: self.move(-1)).pack(side="left", expand=True, fill="x")
        ttk.Button(order, text="Move down", command=lambda: self.move(1)).pack(side="left", expand=True, fill="x")
        self.status = tk.StringVar(value="Import complex TopSpin TXT/ASC. Original real and imaginary values are preserved.")
        ttk.Label(left, textvariable=self.status, wraplength=340, padding=(0, 8)).pack(fill="x")
        vertical = ttk.Panedwindow(right, orient="vertical"); vertical.pack(fill="both", expand=True)
        graph = ttk.Frame(vertical); lower = ttk.LabelFrame(vertical, text="Quantitative results", padding=5)
        vertical.add(graph, weight=4); vertical.add(lower, weight=1)
        self.plot = PlotPane(graph, self._draw, PlotOptions("Chemical shift", "ppm", "Intensity", "a.u.", reverse_x=True), compact=True)
        self.plot.vars["x_min"].set("-5"); self.plot.vars["x_max"].set("15")
        self.plot.pack(fill="both", expand=True)
        controls = ttk.Frame(graph, padding=4); controls.pack(side="bottom", before=self.plot, fill="x")
        self.phase = tk.BooleanVar(value=True); self.baseline = tk.BooleanVar(value=True)
        self.show_imag = tk.BooleanVar(value=False); self.show_components = tk.BooleanVar(value=True)
        for label, var, command in (("Phase correction", self.phase, self.correction_changed),
                                     ("Baseline correction", self.baseline, self.correction_changed),
                                     ("Imaginary", self.show_imag, self.plot.refresh),
                                     ("Core / excess / fit", self.show_components, self.plot.refresh)):
            ttk.Checkbutton(controls, text=tr(label), variable=var, command=command).pack(side="left", padx=4)
        ttk.Button(controls, text="Phase override...", command=self.phase_override).pack(side="left", padx=5)
        _wrap_controls(controls)
        frame, self.result_tree = _tree(lower, [("metric", "Result / units", 280), ("value", "Value", 300)], height=4, selectmode="browse")
        frame.pack(fill="both", expand=True)
        buttons = ttk.Frame(lower); buttons.pack(side="bottom", before=frame, fill="x", pady=4)
        ttk.Button(buttons, text="Calculation details...", command=self.audit).pack(side="left", padx=4)
        ttk.Button(buttons, text="Export processed CSV...", command=self.export_result).pack(side="left", padx=4)
        self.result_status = tk.StringVar(value="Select a sample, then Quantitative analysis.")
        self.after_idle(lambda: localize_widget_tree(self))
        ttk.Label(buttons, textvariable=self.result_status, wraplength=460, foreground="#9A3A14").pack(side="left", padx=8)

    def selected(self):
        ids = self.tree.selection(); return [s for s in self.spectra if s.uid in ids]

    def current(self):
        return next(iter(self.selected()), None)

    def add_dialog(self):
        self.add_paths(filedialog.askopenfilenames(parent=self, filetypes=[("Complex TopSpin ASCII", "*.txt *.asc")]))

    def add_paths(self, paths):
        spectra, errors = [], []
        for path in paths:
            try:
                spectrum = parse_hnmr_ascii(path)
                preview_spectrum(spectrum); spectra.append(spectrum)
            except Exception as exc: errors.append(f"{Path(path).name}: {exc}")
        self.add_spectra(spectra)
        if errors: messagebox.showerror("H NMR import", "\n".join(errors), parent=self)

    def add_spectra(self, spectra):
        for s in spectra:
            if s.uid not in {v.uid for v in self.spectra}: self.spectra.append(s)
        self.refresh_rows()
        if spectra: self.tree.selection_set(spectra[-1].uid); self.tree.see(spectra[-1].uid)
        self._refresh()

    def refresh_rows(self):
        ids = self.tree.selection(); self.tree.delete(*self.tree.get_children())
        for s in self.spectra: self.tree.insert("", "end", iid=s.uid, values=(s.name, "Prepared" if s.processing.get("prepared") else "Preview"))
        self.tree.selection_set([uid for uid in ids if self.tree.exists(uid)])

    def invalidate_all(self):
        self.results.clear(); self.cache.clear()
        for s in self.spectra: s.metadata.pop("analysis_audit", None)

    def remove(self):
        ids = self.tree.selection(); self.spectra = [s for s in self.spectra if s.uid not in ids]
        self.invalidate_all(); self.refresh_rows()
        if self.spectra: self.tree.selection_set(self.spectra[0].uid)
        self._refresh()

    def rename(self):
        s = self.current()
        if s:
            name = simpledialog.askstring("Rename H NMR spectrum", "Spectrum name", initialvalue=s.name, parent=self)
            if name and name.strip(): s.name = name.strip(); self.refresh_rows(); self._refresh()

    def move(self, offset):
        s = self.current()
        if s:
            i = next(i for i, v in enumerate(self.spectra) if v.uid == s.uid)
            self.spectra.insert(max(0, min(len(self.spectra)-1, i+offset)), self.spectra.pop(i)); self.refresh_rows()

    def save(self):
        try:
            for s in self.selected(): self.library.save(s)
            self.status.set(f"Saved {len(self.selected())} spectrum/spectra including complex data, colors and preprocessing.")
            if self.library_window and self.library_window.winfo_exists(): self.library_window.refresh()
        except Exception as exc: messagebox.showerror("H NMR library", str(exc), parent=self)

    def open_library(self):
        if self.library_window and self.library_window.winfo_exists(): self.library_window.lift(); self.library_window.refresh()
        else: self.library_window = HLibraryWindow(self)

    def open_parameters(self):
        try:
            if self.parameter_window and self.parameter_window.winfo_exists(): self.parameter_window.lift()
            else: self.parameter_window = ParameterWindow(self)
        except Exception as exc: messagebox.showerror("Parameter library", str(exc), parent=self)

    def preprocessing(self):
        if self.spectra: HPreprocessingDialog(self)
        else: self.status.set("Import H NMR spectra first.")

    def analyze(self):
        s = self.current()
        if s:
            try: QuantDialog(self, s)
            except Exception as exc: messagebox.showerror("Quantitative analysis", str(exc), parent=self)
        else: self.status.set("Select one spectrum to analyze.")

    def correction_changed(self):
        s = self.current()
        if not s: return
        preview_spectrum(s)
        s.processing["settings"].update(phase=self.phase.get(), baseline=self.baseline.get())
        s.processing.update(prepared=False, group_id="")
        self.invalidate_all(); self.refresh_rows(); self._refresh()

    def phase_override(self):
        s = self.current()
        if not s: return
        preview_spectrum(s)
        value = simpledialog.askstring("Phase override", "Zero-order phase in degrees; blank restores automatic phase.\nThis override is retained during group preprocessing.",
                                       initialvalue=s.metadata.get("manual_phase0", s.processing.get("phase0", 0)), parent=self)
        if value is not None:
            try:
                angle = float(value) if value.strip() else None
                if angle is not None and not np.isfinite(angle): raise ValueError()
            except ValueError:
                messagebox.showerror("Phase override", "Enter a finite phase angle or leave blank.", parent=self); return
            if angle is None: s.metadata.pop("manual_phase0", None)
            else: s.metadata["manual_phase0"] = angle
            s.processing.update(phase0=angle, prepared=False, group_id="")
            s.processing["settings"]["phase"] = True
            self.invalidate_all(); self.refresh_rows(); self._refresh()

    def processed(self, s):
        key = (s.uid, json.dumps(s.processing, sort_keys=True))
        if key not in self.cache:
            value = preview_spectrum(s)
            self.cache[(s.uid, json.dumps(s.processing, sort_keys=True))] = value
            return value
        return self.cache[key]

    def _draw(self, axis, options):
        s = self.current()
        if not s:
            axis.text(.5, .5, "Import complex H NMR ASCII data", transform=axis.transAxes, ha="center"); return
        result = self.results.get(s.uid)
        p = result.sample if result else self.processed(s)
        colors = s.metadata.setdefault("curve_colors", {})
        def line(key, label, y, index, style="-"):
            color = curve_color(axis, s.uid+":"+key, label, SERIES_PALETTE[index], colors, key)
            axis.plot(p.x, y, color=color, linewidth=options.line_width, linestyle=style, label=label)
        response = result.parameters["response_factor"] if result else 1.
        line("real", s.name, p.y*response, 0)
        if self.show_imag.get(): line("imag", "Corrected imaginary", p.imaginary*response, 3, "--")
        if result and self.show_components.get():
            line("core", "Scaled pristine core", result.core_curve, 2, "--")
            line("excess", "Excess above core", result.excess_curve, 1)
            for i, y in enumerate(result.components): line("fit"+str(i), ("Aliphatic fit", "Middle-band fit", "Aromatic fit")[i], y*response, i+4, ":")

    def _refresh(self):
        if not hasattr(self, "plot"): return
        s = self.current()
        if s:
            try:
                self.processed(s)
                self.phase.set(s.processing["settings"]["phase"]); self.baseline.set(s.processing["settings"]["baseline"])
                self.status.set(f"{s.name}\n{len(s.x):,} complex points | p0 = {(s.processing.get('phase0') or 0):.3g} deg\n"+
                                ("Common preprocessing prepared" if s.processing.get("prepared") else "Preview corrections; common preprocessing not prepared"))
            except Exception as exc: self.status.set(str(exc)); return
        self.plot.refresh(); self.result_tree.delete(*self.result_tree.get_children())
        result = self.results.get(s.uid) if s else None
        if not result:
            self.result_status.set("No current result. Confirm parameters to calculate."); return
        ordered = ["apparent_coverage_percent", "ligand_umol", "loading_umol_mg", "aliphatic_integral", "aromatic_integral"]
        for key in ordered+[k for k in result.values if k not in ordered]:
            value = result.values[key]
            self.result_tree.insert("", "end", values=(key.replace("_", " "), "Undefined" if value is None else f"{value:.10g}"))
        self.result_status.set("PROVISIONAL / inspect warnings in Calculation details" if any(w.startswith("PROVISIONAL") for w in result.warnings)
                               else "Apparent coverage; inspect model / range diagnostics")
        if not 0 <= result.values["apparent_coverage_percent"] <= 100:
            self.result_status.set("Outside 0-100%: inspect calibration / model. " + self.result_status.get())

    def audit(self):
        s = self.current(); result = self.results.get(s.uid) if s else None
        content = result.audit if result else s.metadata.get("analysis_audit") if s else None
        if not content: return
        dialog = tk.Toplevel(self); _window(dialog, "H NMR calculation details")
        ttk.Button(dialog, text="Save complete calculation record...", command=lambda: save_text(dialog, content, "H_NMR_calculation.txt")).pack(anchor="w", padx=8, pady=8)
        text = ScrolledText(dialog, wrap="word", font=("TkFixedFont", 10)); text.pack(fill="both", expand=True, padx=8, pady=8)
        text.insert("1.0", content); text.configure(state="disabled")

    def export_result(self):
        s = self.current(); result = self.results.get(s.uid) if s else None
        if result: save_text(self, result_csv(result), "H_NMR_processed.csv", ".csv")


class NMRWorkspace(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.book = ttk.Notebook(self)
        self.c = SSNMRTab(self.book); self.h = HNMRTab(self.book)
        self.book.add(self.c, text="C NMR"); self.book.add(self.h, text="H NMR")
        self.book.pack(fill="both", expand=True)
        self.plot = self.c.plot; self.plot_panes = (self.c.plot, self.h.plot)

    def _refresh(self):
        self.c._refresh(); self.h._refresh()

    def add_paths(self, paths):
        for path in paths:
            text = Path(path).read_text(encoding="utf-8-sig")
            h = ("LEFT" in text and "RIGHT" in text and "SIZE" in text) or text.lstrip().lower().startswith("ppm real imag")
            target = self.h if h else self.c
            target.add_paths([path]); self.book.select(target)
