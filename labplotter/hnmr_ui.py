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
from .hnmr import (HNMRSpectrum, HNMRSettings, QuantSettings, common_settings, infer_identity,
                   parse_hnmr_ascii, prepare_spectra, preview_spectrum, quant_defaults,
                   quantify, result_csv, restored_quant_settings)
from .hnmr_decomposition import (DecompositionSettings, decompose, restore_decomposition, decomposition_values, decomposition_csv, decomposition_defaults)
from .hnmr_decomposition import MODEL_LABELS, SCALING_LABELS, select_model
from .hnmr_summary import UNITS, summary_cells, short_status, number
from .hnmr_reactions import REACTION_NOTE
from .hnmr_plot import ROLES, draw_hnmr, default_visible
from .table_copy import SelectableTreeCells
from .hnmr_library import (HNMRLibrary, HNMRParameterLibrary, PARAMETER_FIELDS,
                           export_hnmr_library, import_hnmr_library, validate_parameters)
from .hnmr_batch import batch_plan, remember_result, summary_row, summary_csv
from .nmr_ui import SSNMRTab, nmr_tree_style, save_text
from .nmr_import import parse_nmr_ascii
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


def _fit_table_values(tree):
    """Keep scientific notation legible at the user's font size; allow scrolling."""
    font = tkfont.nametofont('TkDefaultFont')
    for index, key in enumerate(tree['columns']):
        texts = [tree.heading(key, 'text')]+[str(tree.item(iid, 'values')[index]) for iid in tree.get_children()]
        width = max(font.measure(text) for text in texts)+28
        tree.column(key, width=max(int(tree.column(key, 'width')), width))


class Fields(ttk.Frame):
    """Short, labeled forms; nullable numbers remain blank, never guessed."""
    def __init__(self, parent, specs, values):
        super().__init__(parent, padding=10)
        self.specs, self.vars, self.widgets, self.labels = specs, {}, {}, {}
        self.canvas = tk.Canvas(self, highlightthickness=0, width=650, height=min(480, len(specs)*48))
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True); scrollbar.pack(side="right", fill="y")
        body = ttk.Frame(self.canvas)
        window = self.canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(window, width=event.width))
        body.columnconfigure(1, weight=1, minsize=170)
        for i, (key, label, kind) in enumerate(specs):
            value = values.get(key)
            if key == 'model': value = MODEL_LABELS.get(value,value)
            if key == 'core_scaling': value = SCALING_LABELS.get(value,value)
            var = tk.BooleanVar(value=bool(value)) if kind == "bool" else tk.StringVar(value="" if value is None else str(value))
            self.vars[key] = var
            self.labels[key] = ttk.Label(body, text=tr(label), wraplength=360)
            self.labels[key].grid(row=i, column=0, sticky="w", padx=(0, 15), pady=5)
            if kind == "bool":
                widget = ttk.Checkbutton(body, variable=var)
            elif isinstance(kind, tuple) or kind == "basis":
                options = tuple(MODEL_LABELS.values()) if key == 'model' else kind if isinstance(kind, tuple) else ("ppm", "point_sum", "hz")
                if key == 'core_scaling': options = tuple(SCALING_LABELS.get(k,k) for k in kind)
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
            if key == 'model': result[key] = next((k for k,v in MODEL_LABELS.items() if v == value), value)
            if key == 'core_scaling': result[key] = next((k for k,v in SCALING_LABELS.items() if v == value), value)
        return result

    def set_values(self, values):
        for key, value in values.items():
            if key in self.vars:
                if key == 'model': value = MODEL_LABELS.get(value,value)
                if key == 'core_scaling': value = SCALING_LABELS.get(value,value)
                self.vars[key].set("" if value is None else value)


def _model_fields(forms):
    variables = {k:v for form in forms for k,v in form.vars.items()}
    widgets = {k:v for form in forms for k,v in form.widgets.items()}
    model = next((k for k,v in MODEL_LABELS.items() if v == variables['model'].get()),variables['model'].get())
    previous = getattr(forms[0], '_last_model', model)
    cache = getattr(forms[0], '_model_cache', {})
    cache[previous] = {k:v.get() for k,v in variables.items() if k in DecompositionSettings.__dataclass_fields__ and k != 'model'}
    if previous != model:
        if model in cache:
            for k,value in cache[model].items(): variables[k].set(value)
        elif model == 'broad_core3':
            old = asdict(DecompositionSettings())
            preset = asdict(select_model(DecompositionSettings(),model))
            for k,value in preset.items():
                if k != 'model' and value != old[k] and k in variables:
                    variables[k].set('' if value is None else value)
    forms[0]._model_cache = cache
    forms[0]._last_model = model
    modern = model == 'core_template'
    family = model == 'broad_core3'
    for name in ('unassigned_min','unassigned_max','unassigned_fwhm_min','unassigned_fwhm_max',
                 'complex_fit_min','complex_fit_max','joint_phase','joint_phase0_limit','joint_phase1_limit'):
        if name in widgets: widgets[name].configure(state='normal' if family else 'disabled')
    for name in ('overlap_band','refine_spacing','fit_sideband_width','allow_negative_sidebands'):
        if name in widgets: widgets[name].configure(state='disabled' if family else 'normal')
    for name in ('ligand_min','ligand_max','ligand_fwhm_min','ligand_fwhm_max','template_shift_max','template_broadening_max'):
        if name in widgets: widgets[name].configure(state='normal' if modern else 'disabled')
    for form in forms:
        if 'aliphatic_gaussian_fraction' in form.labels:
            form.labels['aliphatic_gaussian_fraction'].configure(text=tr('Additional ligand G fraction (0=L, 1=G; blank=fit)' if modern else 'Aliphatic G fraction (0=L, 1=G; blank=fit)'))
            form.labels['aromatic_gaussian_fraction'].configure(text=tr('Aromatic G fraction (Ver1 only)' if modern else 'Aromatic G fraction (0=L, 1=G; blank=fit)'))
            form.widgets['aromatic_gaussian_fraction'].configure(state='disabled' if modern else 'normal')
    if 'core_scaling' in variables:
        target = 'core_reference' if modern else 'aromatic_reference'
        widgets['core_scaling'].configure(values=(SCALING_LABELS[target],SCALING_LABELS['mass']))
        if variables['core_scaling'].get() not in ('mass',SCALING_LABELS['mass']): variables['core_scaling'].set(SCALING_LABELS[target])
    return modern


def _window(window, title, geometry="1050x740"):
    window.title(tr(title)); window.geometry(geometry)
    window.minsize(850, 620)
    window.transient(window.master.winfo_toplevel())
    window.after_idle(lambda: localize_widget_tree(window))


def _wrap_controls(frame):
    """Wrap quick controls using actual font-sized widget widths."""
    widgets = frame.winfo_children()
    for widget in widgets: widget.pack_forget()
    # Grid columns are shared across rows, so their maximum widths can make
    # a supposedly wrapped row overflow. Place each row independently.
    frame.pack_propagate(False); frame.grid_propagate(False)
    def layout(_=None):
        width = max(frame.winfo_width(), 1); used = 0; y = 0; height = 0
        for widget in widgets:
            needed = widget.winfo_reqwidth()+8
            if used and used+needed > width:
                y += height; used = 0; height = 0
            widget.place(x=used+4, y=y+2)
            used += needed; height = max(height, widget.winfo_reqheight()+4)
        frame.configure(height=max(1,y+height))
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
    ("grid_step", "Grid step (ppm)", "number"), ("phase", "Phase correction", "bool"),
    ("auto_phase1", "Bounded automatic PH0 / PH1 (complex data)", "bool"),
    ("balance_sidebands", "Refine phase using resolved sidebands", "bool"),
    ("baseline", "Baseline correction", "bool"),
    ("masked_baseline", "Exclude main peak and sidebands from baseline", "bool"),
    ("baseline_degree", "Masked baseline degree (0 / 1 / 2)", "number"),
    ("baseline_exclusion", "Peak exclusion half-width (ppm)", "number"),
    ("baseline_anchor_min", "Baseline anchors: minimum distance from 4.5 ppm", "number"),
    ("sideband_spacing", "Approximate sideband spacing for exclusion (ppm)", "number"),
    ("mas_hz", "MAS preset (Hz; both 0 = estimated spacing)", "number"),
    ("proton_mhz", "1H frequency preset (MHz)", "number"),
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
        ttk.Button(left, text="400 MHz / 20 kHz preset", command=lambda: self.form.set_values(
            {'mas_hz':20000.,'proton_mhz':400.,'sideband_spacing':50.})).pack(fill="x", pady=3)
        self.form = Fields(right, PREPROCESS_FIELDS, asdict(common_settings(workspace.spectra)))
        self.form.pack(fill="both", expand=True)
        ttk.Label(self, text="Wide exports start with the editable lab preset: 400 MHz / 20 kHz = 50 ppm. This is not acquisition metadata read from ASCII. No intensity normalization.\n"
                  "Inspect Phase / baseline QC. Baseline anchors must be signal-free. PH1 uses the current processing span; manual PH0/PH1 overrides remain active for group preparation.",
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


QUANT_SAMPLE = [('model','Decomposition model',tuple(MODEL_LABELS)),
                ("core", "Core", "text"), ("ligand", "Ligand / hypothetical ligand for blank check", "text"),
                ("core_scaling", "Aromatic correction", ("aromatic_reference", "mass")),
                ("sample_mass_mg", "Mass used as coverage denominator (mg)", "optional"),
                ("reference_mass_mg", "Pristine reference mass (mg)", "optional"),
                ("capacity_umol_mg", "Core maximum loading (umol/mg)", "number"),
                ("molecular_weight", "Parent ligand MW (g/mol)", "number"),
                ("effective_h", "H atoms represented per ligand (not particle mass)", "optional"),
                ('include_linkage_nh', 'Michael scenario includes one linkage N-H (if captured)', 'bool'),
                ('schiff_h', 'Schiff H override (blank = automatic)', 'optional'),
                ('michael_h', 'Michael H override (blank = automatic)', 'optional'),
                ("sample_core_mass_mg", "Known core mass in sample (mg; mass method only)", "optional"),
                ("use_prepared", "Use saved common preprocessing", "bool")]
QUANT_CALIBRATION = [("show_provisional", "Show provisional coverage despite unresolved checks", "bool"),
                     ("standard_area", "Internal standard area", "number"),
                     ("standard_umol_h", "Internal standard amount (umol H)", "number"),
                     ("standard_basis", "Standard area basis", "basis"),
                     ("standard_grid_step", "STANDARD original grid step (ppm)", "optional"),
                     ("frequency_mhz", "Frequency (MHz, for Hz area)", "optional"),
                     ("standard_includes_sidebands", "Standard area includes ALL spinning sidebands", "bool"),
                     ("response_factor", "Sample response multiplier to standard scale", "number"),
                     ("reference_response_factor", "Core response multiplier to standard scale", "number"),
                     ("calibration_verified", "Standard area unit and scale verified", "bool"),
                     ("acquisition_verified", "Quantitative acquisition / response verified", "bool")]
DECOMPOSITION_FIELDS = [('model','Decomposition model',tuple(MODEL_LABELS)),
                        ("fit_min", "Fit / component integration minimum (ppm)", "number"),
                        ("fit_max", "Fit / component integration maximum (ppm)", "number"),
                        ("aliphatic_min", "Aliphatic center lower bound (ppm)", "number"),
                        ("aliphatic_max", "Aliphatic center upper bound (ppm)", "number"),
                        ("aromatic_min", "Aromatic center lower bound (ppm)", "number"),
                        ("aromatic_max", "Aromatic center upper bound (ppm)", "number"),
                        ("fwhm_min", "Minimum component FWHM (ppm)", "number"),
                        ("fwhm_max", "Maximum component FWHM (ppm)", "number"),
                        ("line_shape", "Component line shape", ("pseudo_voigt", "gaussian", "lorentzian")),
                        ("aliphatic_gaussian_fraction", "Aliphatic G fraction (0=L, 1=G; blank=fit)", "optional"),
                        ("aromatic_gaussian_fraction", "Aromatic G fraction (0=L, 1=G; blank=fit)", "optional"),
                        ("overlap_band", "Add unassigned overlap band between center ranges", "bool"),
                        ("sidebands", "Fit / integrate MAS spinning sidebands", "bool"),
                        ("sideband_order", "Maximum order on EACH side (1-4)", "number"),
                        ("sideband_spacing", "Estimated sideband spacing (ppm)", "number"),
                        ("refine_spacing", "Refine estimated spacing (ignored with known MAS / MHz)", "bool"),
                        ("mas_hz", "Actual 1H MAS rate (Hz; 0 = unknown)", "number"),
                        ("proton_mhz", "Actual 1H frequency (MHz; 0 = unknown)", "number"),
                        ("sideband_width_scale", "Sideband / central FWHM multiplier (1 = DMfit link)", "number"),
                        ("fit_sideband_width", "Fit common sideband-width multiplier", "bool"),
                        ("allow_negative_sidebands", "Signed satellite heights (diagnostic only)", "bool"),
                        ('ligand_min','Legacy template ligand center lower bound (ppm)','number'),
                        ('ligand_max','Legacy template ligand center upper bound (ppm)','number'),
                        ('ligand_fwhm_min','Legacy template ligand minimum FWHM (ppm)','number'),
                        ('ligand_fwhm_max','Legacy template ligand maximum FWHM (ppm)','number'),
                        ('template_shift_max','Legacy template maximum core shift (ppm; 0 = fixed)','number'),
                        ('template_broadening_max','Legacy template maximum extra core FWHM (ppm; 0 = none)','number'),
                        ('unassigned_min','Ver2 broad unassigned center minimum (ppm)','number'),
                        ('unassigned_max','Ver2 broad unassigned center maximum (ppm)','number'),
                        ('unassigned_fwhm_min','Ver2 broad unassigned minimum FWHM (ppm)','number'),
                        ('unassigned_fwhm_max','Ver2 broad unassigned maximum FWHM (ppm)','number'),
                        ('complex_fit_min','Ver2 complex fitting minimum (ppm)','number'),
                        ('complex_fit_max','Ver2 complex fitting maximum (ppm)','number'),
                        ('joint_phase','Ver2 jointly refine automatic phase (manual overrides stay fixed)','bool'),
                        ('joint_phase0_limit','Ver2 absolute PH0 limit (+/- degrees)','number'),
                        ('joint_phase1_limit','Ver2 absolute PH1 limit (+/- degrees across processing span)','number')]
QUANT_REGIONS = [row for row in DECOMPOSITION_FIELDS if row[0] != 'model'] + [("assignments_verified", "Component assignments, H count and core model reviewed", "bool"),
                        ("sideband_scope_verified", "Included orders, weak peaks, phase and baseline reviewed", "bool")]


class HDecompositionStyle:
    title = "H NMR decomposition"

    def __init__(self, owner):
        self.owner = owner; self.vars = {}

    def build(self, parent):
        self.sample = self.owner.current(); self.vars = {}
        if not self.sample:
            ttk.Label(parent, text="Select a spectrum first.").pack(); return
        ttk.Label(parent, text="Colors: use the shared Curve colors page. Width, style and visibility below apply to the selected sample and its saved library entry.\nCopy and save include exactly the visible decomposition layers.", wraplength=600).pack(anchor="w", pady=8)
        form = ttk.Frame(parent); form.pack(fill="x")
        for i, text in enumerate(("Curve", "Visible", "Width (blank = common)", "Style")):
            ttk.Label(form, text=text).grid(row=0, column=i, padx=5, pady=5)
        styles = self.sample.metadata.get("decomposition_styles", {})
        for i, (key, label, _, default) in enumerate(ROLES, 1):
            saved = styles.get(key, {})
            variables = {"visible": tk.BooleanVar(value=saved.get("visible", default_visible(key))),
                         "width": tk.StringVar(value=saved.get("width") or ""),
                         "line_style": tk.StringVar(value=saved.get("line_style", default))}
            self.vars[key] = variables
            ttk.Label(form, text=label).grid(row=i, column=0, sticky="w", padx=5, pady=5)
            ttk.Checkbutton(form, variable=variables["visible"]).grid(row=i, column=1)
            ttk.Entry(form, textvariable=variables["width"], width=12).grid(row=i, column=2)
            ttk.Combobox(form, textvariable=variables["line_style"], values=("-", "--", ":", "-."), state="readonly", width=8).grid(row=i, column=3)
        self.fill = tk.BooleanVar(value=self.sample.metadata.get("decomposition_fill", False))
        ttk.Checkbutton(parent, text="Shade fitted component areas", variable=self.fill).pack(anchor="w", pady=8)
        self.notation = tk.StringVar(value=self.sample.metadata.get('intensity_notation', 'axis_label'))
        ttk.Label(parent, text='Intensity numbers: axis_label = multiplier in axis title; plain = full numbers; scientific = top offset').pack(anchor='w')
        ttk.Combobox(parent, textvariable=self.notation, values=('axis_label', 'plain', 'scientific'), state='readonly').pack(anchor='w', pady=5)
        self.error = ttk.Label(parent, foreground="#a00000"); self.error.pack(anchor="w")

    def variables(self):
        return [v for row in self.vars.values() for v in row.values()]+([self.fill, self.notation] if hasattr(self, 'fill') else [])

    def apply(self):
        if not self.vars: return
        try:
            styles = {}
            for key, row in self.vars.items():
                width = float(row['width'].get()) if row['width'].get().strip() else None
                if width is not None and (not np.isfinite(width) or not 0 < width <= 20): raise ValueError()
                styles[key] = {'visible': row['visible'].get(), 'width': width, 'line_style': row['line_style'].get()}
        except ValueError:
            self.error.configure(text="Width must be 0–20 or blank."); return
        self.error.configure(text="")
        self.sample.metadata.update(decomposition_styles=styles, decomposition_fill=self.fill.get(), intensity_notation=self.notation.get())
        self.owner.plot.refresh()

    def restore_defaults(self):
        for key, _, _, default in ROLES:
            if key in self.vars:
                self.vars[key]['visible'].set(default_visible(key)); self.vars[key]['width'].set(''); self.vars[key]['line_style'].set(default)
        if hasattr(self, 'fill'): self.fill.set(False)
        if hasattr(self, 'notation'): self.notation.set('axis_label')
        self.apply()


class HDecompositionDialog(tk.Toplevel):
    def __init__(self, workspace, sample):
        from .ui import PlotPane
        super().__init__(workspace); _window(self, "H NMR decomposition", "1350x830")
        self.workspace, self.sample = workspace, sample
        self.processed = workspace.processed(sample); self.fit = None
        self.columnconfigure(0, weight=1); self.rowconfigure(1, weight=1)
        top = ttk.Frame(self, padding=8); top.grid(row=0,column=0,sticky='ew'); top.columnconfigure(1,weight=1)
        ttk.Label(top,text='Ver1: aliphatic/aromatic envelopes. Ver2: complex aliphatic + aromatic + broad unassigned families. Legacy template requires a pristine reference.',wraplength=1150).grid(row=0,column=0,columnspan=2,sticky='w')
        ttk.Label(top,text='Legacy template reference').grid(row=1,column=0,sticky='w',pady=5)
        self.reference = ttk.Combobox(top,state='readonly',values=[s.name for s in workspace.spectra],width=45)
        self.reference.grid(row=1,column=1,sticky='ew',padx=8)
        uid = sample.metadata.get('analysis_reference_uid') or sample.metadata.get('decomposition',{}).get('reference',{}).get('uid')
        core,_ = infer_identity(sample.name)
        candidates = [i for i,s in enumerate(workspace.spectra) if infer_identity(s.name)==(core,'')]
        index = next((i for i in candidates if workspace.spectra[i].uid == uid),candidates[0] if candidates else None)
        if index is not None: self.reference.current(index)
        panes = ttk.Panedwindow(self, orient='horizontal'); panes.grid(row=1, column=0, sticky='nsew')
        settings = decomposition_defaults(sample)
        self.form = Fields(panes, DECOMPOSITION_FIELDS, asdict(settings)); panes.add(self.form, weight=0)
        self.form.vars['model'].trace_add('write',lambda *_: self.model_changed())
        self.model_changed()
        self.form.canvas.configure(width=550)
        self.plot = PlotPane(panes, self.draw, PlotOptions('Chemical shift', 'ppm', 'Intensity', 'a.u.', reverse_x=True), compact=True, export_current_view=True)
        self.plot.vars['x_min'].set(str(settings.fit_min)); self.plot.vars['x_max'].set(str(settings.fit_max)); panes.add(self.plot, weight=1)
        self.status = tk.StringVar(value='Fit and inspect both the component curves and residual before accepting assignments.')
        ttk.Label(self, textvariable=self.status, wraplength=1230, padding=8).grid(row=2, column=0, sticky='ew')
        actions = ttk.Frame(self, padding=8); actions.grid(row=3, column=0, sticky='ew')
        ttk.Button(actions, text='Fit and preview', command=self.preview).pack(side='left', padx=4)
        ttk.Button(actions, text='MAS sideband defaults', command=self.sideband_defaults).pack(side='left', padx=4)
        ttk.Button(actions, text='Component integrals...', command=lambda: HComponentDialog(self, self.fit) if self.fit else None).pack(side='left', padx=4)
        ttk.Button(actions, text='Phase / baseline QC...', command=workspace.quality).pack(side='left', padx=4)
        ttk.Button(actions, text='Apply decomposition to spectrum', command=self.apply).pack(side='left', padx=4)
        ttk.Button(actions, text='Close', command=self.destroy).pack(side='right')
        _wrap_controls(actions)
        self.plot.refresh()

    def sideband_defaults(self):
        model = self.form.values()['model']
        settings = decomposition_defaults(self.sample, use_saved=False)
        settings = select_model(settings, model)
        self.form.set_values(asdict(settings)); self.fit = None
        self.plot.vars['x_min'].set(str(settings.fit_min)); self.plot.vars['x_max'].set(str(settings.fit_max))
        self.plot.refresh()
        self.status.set('DMfit link: sidebands share each central line width and G/L. Review the editable MAS/MHz preset. Reapply preprocessing when changing acquisition settings.')

    def draw(self, axis, options):
        draw_hnmr(axis, self.sample, self.processed, options, self.fit)

    def model_changed(self):
        modern = _model_fields([self.form])
        self.reference.configure(state='readonly' if modern else 'disabled')
        self.fit = None

    def selected_reference(self, settings):
        if settings.model != 'core_template': return None
        index = self.reference.current()
        if index < 0: raise ValueError('Load and select a pristine core reference for model Ver2.')
        ref = self.workspace.spectra[index]
        core,ligand = infer_identity(ref.name)
        sample_core,_ = infer_identity(self.sample.name)
        if ligand or (core and sample_core and core != sample_core):
            raise ValueError('Select the matching pristine core, not a modified sample.')
        return ref

    def preview(self):
        try:
            self.processed = self.workspace.processed(self.sample)
            settings = DecompositionSettings(**self.form.values())
            ref = self.selected_reference(settings)
            self.fit = decompose(self.processed, settings, self.workspace.processed(ref) if ref else None,
                                  {'uid':ref.uid,'name':ref.name,'source':ref.source} if ref else None)
            self.plot.refresh()
            a = self.fit.areas
            self.status.set(f"{MODEL_LABELS[settings.model]} | R2 = {self.fit.audit['fit_R2']:.6f} | "+' | '.join(f'{k} area = {v:.7g}' for k,v in a.items())+' intensity*ppm\n'+
                            (f'{len(self.fit.warnings)} warning(s): open Component integrals / QC.' if self.fit.warnings else 'Inspect residual and chemical assignments; high R2 alone does not establish a unique decomposition.'))
        except Exception as exc: self.fit = None; self.plot.refresh(); self.status.set(str(exc))

    def apply(self):
        try:
            settings = DecompositionSettings(**self.form.values()).validate()
            if self.fit is None or asdict(settings) != self.fit.audit['settings']:
                raise ValueError('Fit and preview the current settings before applying.')
            ref = self.selected_reference(settings)
            if ref and ref.uid != self.fit.audit.get('reference',{}).get('uid'):
                raise ValueError('Reference selection changed. Fit and preview again before applying.')
            if restore_decomposition(self.workspace.processed(self.sample), self.fit.record(), self.workspace.processed(ref) if ref else None) is None:
                raise ValueError('Processing changed. Fit and preview again before applying.')
            self.workspace.invalidate_all(fits=False)
            self.sample.metadata.update(decomposition=self.fit.record(), decomposition_settings=asdict(settings))
            if ref: self.sample.metadata['analysis_reference_uid'] = ref.uid
            self.workspace.fits[self.sample.uid] = self.fit
            if settings.sidebands: self.workspace.set_view(settings.fit_min, settings.fit_max)
            self.workspace._refresh(); self.destroy()
        except Exception as exc: self.status.set(str(exc))


class QuantDialog(tk.Toplevel):
    def __init__(self, workspace, sample):
        super().__init__(workspace)
        _window(self, "Confirm H NMR quantitative analysis", "1040x800")
        self.workspace, self.sample = workspace, sample
        self.columnconfigure(0, weight=1); self.rowconfigure(2, weight=1)
        self.parameters = workspace.parameters.load()
        q = restored_quant_settings(sample, self.parameters)
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
        self.fields['model'].trace_add('write',lambda *_: _model_fields(self.forms))
        _model_fields(self.forms)
        self.fields["core"].trace_add("write", self.core_changed)
        p = sample.processing
        notes = ScrolledText(book,wrap='word',font='TkDefaultFont',height=8,padx=12,pady=12)
        book.add(notes,text=tr('Model / calibration notes'))
        notes.insert('1.0',"If saved preprocessing is unchecked, both spectra are freshly processed on a common default grid using the sample's phase/baseline switches.\n\n"
                  "aromatic_reference: match aromatic H per mg to pristine core, then subtract core aliphatic H per mg. The sample mass cancels from coverage; reference mass remains.\n"
                  "Ver2 jointly fits complex data and a broad unassigned family. Aromatic correction OFF uses entered masses; ON uses aromatic-reference normalization. Legacy core_reference uses measured core scaling. Schiff/Michael endpoints assume neutral single attachment; the optional +1 N-H must be captured. C-H-only counts are identical.\n"
                  "Default standard: 42565812.55 intensity*ppm = 1.861273386 umol H. This is an editable working assumption; response multipliers default to 1.\n"
                  "Turn off 'Show provisional coverage' in Calibration for reviewed-only mode. Negative and >100% estimates remain visible.\n\n"+REACTION_NOTE)
        notes.configure(state='disabled')
        ttk.Label(self, text=f"Saved preprocessing: {'prepared, group '+p.get('group_id','')[:8] if p.get('prepared') else 'not prepared'}. "
                  "Review H counts and calibration before calculating; assumptions are in Model / calibration notes.",
                  wraplength=940, padding=10).grid(row=3, column=0, sticky='ew')
        self.status = tk.StringVar()
        ttk.Label(self, textvariable=self.status, foreground="#AE2C28", wraplength=980, padding=6).grid(row=4, column=0, sticky="ew")
        ttk.Button(self, text="Confirm parameters and calculate", command=self.calculate).grid(row=5, column=0, sticky="ew", padx=12, pady=10)

    def choose_reference(self, core):
        candidates = [i for i, s in enumerate(self.workspace.spectra) if infer_identity(s.name) == (core, "")]
        saved_uid = self.sample.metadata.get('analysis_reference_uid')
        selected = next((i for i in candidates if self.workspace.spectra[i].uid == saved_uid), None)
        if candidates: self.reference.current(selected if selected is not None else candidates[0])
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
        elif section == "ligands": values = {"ligand": name, "molecular_weight": row["mw"], "effective_h": row["effective_h"],
                                              'schiff_h':row.get('schiff_h'),'michael_h':row.get('michael_h')}
        else:
            values = {k: row[v] for k, v in (("standard_area", "area"), ("standard_umol_h", "umol_h"),
                      ("standard_basis", "basis"), ("standard_grid_step", "grid_step"),
                      ("frequency_mhz", "frequency_mhz"), ("calibration_verified", "verified"),
                      ("standard_includes_sidebands", "includes_sidebands"))}
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
            remember_result(self.sample, ref, q, result)
            self.workspace.results[self.sample.uid] = result
            self.workspace.fits[self.sample.uid] = result.sample_fit
            self.workspace._refresh(); self.destroy()
        except Exception as exc: self.status.set(str(exc))


class HBatchQuantDialog(tk.Toplevel):
    """Review all sample-specific presets before computing the batch."""
    def __init__(self, workspace):
        super().__init__(workspace); _window(self, 'All H NMR provisional results', '1320x800')
        self.workspace = workspace
        self.plan = batch_plan(workspace.spectra, workspace.parameters.load())
        self.rows = [summary_row(item) for item in self.plan]
        self.columnconfigure(0, weight=1); self.rowconfigure(1, weight=1)
        ttk.Label(self, text='Uses each sample\'s saved parameters or library defaults. Default assumptions: standard 42565812.55 intensity*ppm = 1.861273386 umol H; response multipliers 1.\n'
            'Warnings do not hide estimates. Negative and >100% values are retained. Unknown numeric inputs still require entry. '
            'Edit individual parameters in Quantitative analysis or the parameter library, then reopen this window.\n'
            'Uses compatible saved preprocessing when available; otherwise recomputes a common grid for each sample/reference pair.',
            wraplength=1230, padding=10).grid(row=0, column=0, sticky='ew')
        frame, self.tree = _tree(self, [('sample','Sample',240),('reference','Reference',220),('mass','Mass mg',100),
            ('basis','Std. basis',100),('response','Response S / R',150),('coverage','Coverage % (provisional)',240),
            ('range','Coverage range % (H-count scenarios)',290),('model','Decomposition model',180),
            ('loading','Loading umol/mg',170),('status','Status',410)], height=12)
        frame.grid(row=1, column=0, sticky='nsew', padx=8)
        self.status = tk.StringVar(value='Review the presets above, then calculate all loaded spectra.')
        ttk.Label(self,textvariable=self.status,wraplength=1230,padding=8).grid(row=2,column=0,sticky='ew')
        actions=ttk.Frame(self,padding=8);actions.grid(row=3,column=0,sticky='ew')
        self.run_button=ttk.Button(actions,text='Confirm and calculate all',command=self.run);self.run_button.pack(side='left')
        ttk.Button(actions,text='Export provisional results CSV...',command=self.export).pack(side='left',padx=8)
        ttk.Button(actions,text='Close',command=self.destroy).pack(side='right')
        self.refresh(); self.grab_set()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for row in self.rows:
            self.tree.insert('','end',values=(row['sample'],row['reference'],row['sample_mass_mg'],row['standard_basis'],
                f"{row['response_factor']} / {row['reference_response_factor']}",
                '' if row['apparent_coverage_percent'] is None else f"{row['apparent_coverage_percent']:.8g}",
                '' if row['coverage_lower_percent'] is None else f"{row['coverage_lower_percent']:.8g} – {row['coverage_upper_percent']:.8g}",
                row['decomposition_model'],'' if row['loading_umol_mg'] is None else f"{row['loading_umol_mg']:.8g}",row['status']))

    def run(self):
        self.run_button.configure(state='disabled')
        self.workspace.invalidate_all(fits=False); self.rows=[]
        completed=0
        for i,item in enumerate(self.plan,1):
            self.status.set(f'Calculating {i}/{len(self.plan)}: {item.sample.name}'); self.update_idletasks()
            try:
                if item.error: raise ValueError(item.error)
                result=quantify(item.sample,item.reference,item.settings)
                remember_result(item.sample,item.reference,item.settings,result)
                self.workspace.results[item.sample.uid]=result
                self.workspace.fits[item.sample.uid]=result.sample_fit
                self.rows.append(summary_row(item,result)); completed+=1
            except Exception as exc:
                self.rows.append(summary_row(item,error=str(exc)))
            self.refresh(); self.update_idletasks()
        self.workspace._refresh()
        self.status.set(f'{completed}/{len(self.plan)} numeric results. Select each sample in the main list to see its graph, areas and calculation details. Save spectra to library to retain parameters.')
        self.run_button.configure(state='normal')

    def export(self):
        save_text(self,summary_csv(self.rows),'H_NMR_provisional_results.csv','.csv')


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
    def __init__(self, parent, library=None, parameters=None, *, import_paths=None):
        from .ui import PlotPane
        super().__init__(parent)
        self.library = library or HNMRLibrary(); self.parameters = parameters or HNMRParameterLibrary()
        self.import_paths = import_paths or self.add_paths
        self.spectra = []; self.results = {}; self.fits = {}; self.cache = {}; self.library_window = None; self.parameter_window = None
        panes = ttk.Panedwindow(self, orient="horizontal"); panes.pack(fill="both", expand=True)
        left = ttk.Frame(panes, padding=8, width=320); right = ttk.Frame(panes, padding=5)
        panes.add(left, weight=0); panes.add(right, weight=1)
        for label, command in (("Import H NMR ASCII...", self.add_dialog), ("Open H NMR library...", self.open_library),
                               ("Parameter library...", self.open_parameters), ("Preprocessing...", self.preprocessing),
                               ("Decompose spectrum...", self.decompose_dialog), ("Quantitative analysis...", self.analyze),
                               ("Calculate all (provisional)...", self.analyze_all)):
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
        self.plot = PlotPane(graph, self._draw, PlotOptions("Chemical shift", "ppm", "Intensity", "a.u.", reverse_x=True), compact=True, export_current_view=True)
        self.plot.settings_extension = HDecompositionStyle(self)
        self.plot.vars["x_min"].set("-5"); self.plot.vars["x_max"].set("15")
        self.plot.pack(fill="both", expand=True)
        controls = ttk.Frame(graph, padding=4); controls.pack(side="bottom", before=self.plot, fill="x")
        self.phase = tk.BooleanVar(value=True); self.baseline = tk.BooleanVar(value=True)
        self.show_imag = tk.BooleanVar(value=False); self.show_components = tk.BooleanVar(value=True)
        for label, var, command in (("Phase correction", self.phase, self.correction_changed),
                                     ("Baseline correction", self.baseline, self.correction_changed),
                                     ("Imaginary", self.show_imag, self.plot.refresh),
                                     ("Show decomposition", self.show_components, self.components_changed)):
            ttk.Checkbutton(controls, text=tr(label), variable=var, command=command).pack(side="left", padx=4)
        ttk.Button(controls, text="Phase override...", command=self.phase_override).pack(side="left", padx=5)
        ttk.Button(controls, text="Phase / baseline QC...", command=self.quality).pack(side="left", padx=4)
        ttk.Button(controls, text="Refine phase / baseline", command=self.refine_corrections).pack(side="left", padx=4)
        ttk.Button(controls, text="Phase sensitivity...", command=self.stability).pack(side="left", padx=4)
        ttk.Button(controls, text="Model sensitivity...", command=self.model_review).pack(side="left", padx=4)
        ttk.Button(controls, text="Main peak", command=lambda: self.set_view(-10,20)).pack(side="left", padx=4)
        ttk.Button(controls, text="Full sidebands", command=self.full_view).pack(side="left", padx=4)
        _wrap_controls(controls)
        frame, self.result_tree = _tree(lower, [("sample", "Sample", 210),
            ("aromatic", "Aromatic ¹H (µmol/mg)", 180), ("aliphatic", "Aliphatic ¹H (µmol/mg)", 180),
            ("coverage", "Ligand coverage (%)", 210)], height=4, selectmode="browse")
        self.result_selection = SelectableTreeCells(self.result_tree, columns=('aromatic','aliphatic','coverage'))
        lower.columnconfigure(0, weight=1); lower.rowconfigure(1, weight=1)
        frame.grid(row=1, column=0, sticky='nsew')
        buttons = ttk.Frame(lower); buttons.grid(row=2, column=0, sticky='ew', pady=4)
        self.result_units = tk.StringVar(value=UNITS['h_per_mg'])
        ttk.Label(buttons, text='Area display').pack(side='left', padx=4)
        unit_box = ttk.Combobox(buttons, textvariable=self.result_units, values=tuple(UNITS.values()),state='readonly',width=28)
        unit_box.pack(side='left',padx=4); unit_box.bind('<<ComboboxSelected>>', lambda _: self._refresh())
        ttk.Button(buttons, text="More info...", command=self.audit).pack(side="left", padx=4)
        ttk.Button(buttons, text="Export processed CSV...", command=self.export_result).pack(side="left", padx=4)
        ttk.Button(buttons, text="Copy value", command=self.result_selection.copy_value).pack(side="left", padx=4)
        ttk.Button(buttons, text="Copy results table", command=self.result_selection.copy_table).pack(side="left", padx=4)
        self.result_status = tk.StringVar(value="Select a sample, then Quantitative analysis.")
        self.after_idle(lambda: localize_widget_tree(self))
        ttk.Label(lower, textvariable=self.result_status, foreground="#9A3A14", wraplength=650).grid(row=0, column=0, sticky='ew', pady=3)
        _wrap_controls(buttons)
        self.after_idle(lambda: vertical.sashpos(0, max(180, vertical.winfo_height()-245)))

    def selected(self):
        ids = self.tree.selection(); return [s for s in self.spectra if s.uid in ids]

    def current(self):
        return next(iter(self.selected()), None)

    def add_dialog(self):
        self.import_paths(filedialog.askopenfilenames(parent=self,
            title=tr('Import NMR ASCII (C / H auto-detect)'),
            filetypes=[("TopSpin ASCII", "*.txt *.asc *.csv *.tsv")]))

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
        first = not self.spectra
        for s in spectra:
            if s.uid not in {v.uid for v in self.spectra}: self.spectra.append(s)
        self.refresh_rows()
        if spectra: self.tree.selection_set(spectra[-1].uid); self.tree.see(spectra[-1].uid)
        if first and spectra and spectra[-1].x[0] <= -150 and spectra[-1].x[-1] >= 160:
            self.plot.vars['x_min'].set('-145'); self.plot.vars['x_max'].set('155')
        self._refresh()

    def refresh_rows(self):
        ids = self.tree.selection(); self.tree.delete(*self.tree.get_children())
        for s in self.spectra: self.tree.insert("", "end", iid=s.uid, values=(s.name, "Prepared" if s.processing.get("prepared") else "Preview"))
        self.tree.selection_set([uid for uid in ids if self.tree.exists(uid)])

    def invalidate_all(self, fits=True):
        self.results.clear(); self.cache.clear()
        if fits: self.fits.clear()
        for s in self.spectra:
            s.metadata.pop("analysis_audit", None)
            if fits: s.metadata.pop("decomposition", None)

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

    def analyze_all(self):
        if self.spectra: HBatchQuantDialog(self)
        else: self.status.set("Import H NMR spectra first.")

    def decompose_dialog(self):
        s = self.current()
        if s: HDecompositionDialog(self, s)
        else: self.status.set("Select one spectrum first.")

    def components_changed(self):
        s = self.current()
        if s: s.metadata["show_decomposition"] = self.show_components.get()
        self.plot.refresh()

    def fitted(self, s):
        result = self.results.get(s.uid)
        if result: return result.sample_fit
        fit = restore_decomposition(self.processed(s), s.metadata.get("decomposition"))
        if fit: self.fits[s.uid] = fit
        else: self.fits.pop(s.uid, None)
        return fit

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
        dialog = tk.Toplevel(self); dialog.title('Manual PH0 / PH1')
        values = {'phase0':s.metadata.get('manual_phase0',s.processing.get('phase0',0.)),
                  'phase1':s.metadata.get('manual_phase1',s.processing.get('phase1',0.))}
        form = Fields(dialog, [('phase0','PH0 at processing midpoint (degrees)','optional'),
                               ('phase1','PH1 across processing span (degrees)','optional')], values)
        form.pack(fill='both', expand=True)
        cfg=s.processing['settings']
        ttk.Label(dialog,text=f"Pivot: {(cfg['ppm_min']+cfg['ppm_max'])/2:g} ppm; span: {cfg['ppm_max']-cfg['ppm_min']:g} ppm.\nBoth blank restores automatic phase. Overrides persist through group preprocessing.",wraplength=640,padding=8).pack(fill='x')
        status=tk.StringVar();ttk.Label(dialog,textvariable=status,foreground='#a00000').pack(fill='x')
        def apply():
            try:
                values=form.values()
                if (values['phase0'] is None) != (values['phase1'] is None): raise ValueError('Enter both angles, or leave both blank for automatic correction.')
                for key,angle in values.items():
                    if angle is not None and not np.isfinite(angle): raise ValueError('Enter finite angles.')
                    if angle is None: s.metadata.pop('manual_'+key,None)
                    else: s.metadata['manual_'+key]=angle
            except ValueError as exc: status.set(str(exc));return
            if values['phase0'] is None: s.metadata.pop('manual_phase_reference',None)
            else: s.metadata['manual_phase_reference']={'pivot':(cfg['ppm_min']+cfg['ppm_max'])/2,'span':cfg['ppm_max']-cfg['ppm_min']}
            s.processing.update(**values, prepared=False, group_id="")
            s.processing["settings"]["phase"] = True
            self.invalidate_all(); self.refresh_rows(); self._refresh();dialog.destroy()
        ttk.Button(dialog,text='Apply PH0 / PH1',command=apply).pack(fill='x',padx=8,pady=8)

    def set_view(self, low, high):
        self.plot.vars['x_min'].set(str(low)); self.plot.vars['x_max'].set(str(high)); self.plot.refresh()

    def full_view(self):
        s=self.current()
        if s:
            p=self.processed(s);self.set_view(p.x[0],p.x[-1])

    def quality(self):
        s=self.current()
        if s: HQualityDialog(self,s)

    def refine_corrections(self):
        s=self.current()
        if not s:return
        try:
            if 'manual_phase0' in s.metadata or 'manual_phase1' in s.metadata:
                raise ValueError('Manual phase override is active. Clear both phase overrides before automatic refinement.')
            # Keep a prepared group's common grid/settings consistent.
            group=s.processing.get('group_id')
            targets=[v for v in self.spectra if group and v.processing.get('group_id')==group] if group else [s]
            cfg=HNMRSettings(**s.processing['settings']) if s.processing else common_settings(targets)
            cfg.phase=cfg.baseline=cfg.auto_phase1=cfg.masked_baseline=cfg.balance_sidebands=True
            prepare_spectra(targets,cfg,prepared=bool(group))
            self.invalidate_all(); self.refresh_rows(); self._refresh(); self.quality()
        except Exception as exc:messagebox.showerror('Phase / baseline',str(exc),parent=self)

    def stability(self):
        s=self.current()
        if s: HStabilityDialog(self,s)

    def model_review(self):
        s = self.current()
        if s: HModelReviewDialog(self, s)

    def component_details(self):
        s=self.current(); fit=self.fitted(s) if s else None
        if fit: HComponentDialog(self,fit)

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
        draw_hnmr(axis, s, p, options, self.fitted(s), self.show_components.get(), self.show_imag.get(), self.plot.register_overlay)

    def _refresh(self):
        if not hasattr(self, "plot"): return
        s = self.current()
        if s:
            try:
                self.processed(s)
                self.show_components.set(s.metadata.get("show_decomposition", True))
                self.phase.set(s.processing["settings"]["phase"]); self.baseline.set(s.processing["settings"]["baseline"])
                self.status.set(f"{s.name}\n{len(s.x):,} complex points | PH0 = {(s.processing.get('phase0') or 0):.3g}, PH1 = {(s.processing.get('phase1') or 0):.3g} deg\n"+
                                ("Common preprocessing prepared" if s.processing.get("prepared") else "Preview corrections; common preprocessing not prepared"))
            except Exception as exc: self.status.set(str(exc)); return
        self.plot.refresh(); self.result_selection.hide(); self.result_tree.delete(*self.result_tree.get_children())
        result = self.results.get(s.uid) if s else None
        fit = self.fitted(s) if s else None
        if s and fit and fit.audit.get('version') == 5:
            self.status.set(f"{s.name}\n{len(s.x):,} complex points | Ver2 fitted display\nPH0 = {fit.audit['phase0_deg']:.4g}, PH1 = {fit.audit['phase1_deg']:.4g} deg\n"+
                            ('Common preprocessing prepared' if s.processing.get('prepared') else 'Common preprocessing not prepared'))
        units = next(k for k,v in UNITS.items() if v == self.result_units.get())
        for key in ('aromatic','aliphatic'):
            title = key.title()+(' ¹H (µmol/mg)' if units == 'h_per_mg' else ' integral (intensity·ppm)')
            self.result_tree.heading(key,text=title)
        for spectrum in self.spectra:
            row_result = self.results.get(spectrum.uid)
            row_fit = self.fitted(spectrum) if spectrum.uid == (s.uid if s else None) or spectrum.uid in self.fits else None
            self.result_tree.insert('', 'end', iid=spectrum.uid, values=summary_cells(spectrum,row_result,row_fit,units))
        if s and self.result_tree.exists(s.uid):
            self.result_tree.selection_set(s.uid); self.result_tree.see(s.uid)
        _fit_table_values(self.result_tree)
        self.result_status.set(short_status(result,fit)+'\nH/mg values precede aromatic normalization. Coverage range: Schiff/Michael H-count scenarios.')

    def audit(self):
        s = self.current(); result = self.results.get(s.uid) if s else None
        fit = self.fitted(s) if s else None
        content = result.audit if result else json.dumps(fit.audit, indent=2, ensure_ascii=False) if fit else None
        if not content: return
        dialog = tk.Toplevel(self); _window(dialog, "H NMR additional information")
        buttons = ttk.Frame(dialog, padding=8); buttons.pack(fill='x')
        ttk.Button(buttons, text="Save complete calculation record...", command=lambda: save_text(dialog, content, "H_NMR_calculation.txt")).pack(side='left',padx=4)
        ttk.Button(buttons, text="Component integrals...", command=lambda: HComponentDialog(dialog,fit)).pack(side='left',padx=4)
        book = ttk.Notebook(dialog); book.pack(fill='both',expand=True,padx=8,pady=8)
        values_page = ttk.Frame(book); book.add(values_page,text='All values')
        frame, tree = _tree(values_page, [('metric','Result / units',480),('value','Value',280)])
        frame.pack(fill='both',expand=True)
        values = result.values if result else decomposition_values(fit)
        for key,value in values.items(): tree.insert('', 'end', values=(key.replace('_',' '),number(value)))
        _fit_table_values(tree)
        selection = SelectableTreeCells(tree,columns=('value',)); dialog.value_selection = selection
        ttk.Button(values_page,text='Copy all values',command=selection.copy_table).pack(anchor='w',pady=6)
        warnings = ScrolledText(book,wrap='word',font='TkDefaultFont'); book.add(warnings,text='Assumptions / diagnostics')
        warning_text = short_status(result,fit)+'\n\n'+'\n\n'.join(result.warnings if result else fit.warnings)
        if fit.audit.get('version') == 5:
            warning_text += f"\n\nJoint phase: PH0 = {fit.audit['phase0_deg']:.8g}°, PH1 = {fit.audit['phase1_deg']:.8g}° (pivot {fit.audit['phase_pivot_ppm']:g} ppm; span {fit.audit['phase_span_ppm']:g} ppm).\nBroad unassigned integral = {fit.areas['unassigned']:.12g} intensity·ppm; excluded from coverage."
        warnings.insert('1.0',warning_text); warnings.configure(state='disabled')
        text = ScrolledText(book, wrap="word", font=("TkFixedFont", 10)); book.add(text,text='Full calculation record')
        text.insert("1.0", content); text.configure(state="disabled")

    def export_result(self):
        s = self.current(); result = self.results.get(s.uid) if s else None
        fit = self.fitted(s) if s else None
        if result or fit: save_text(self, result_csv(result) if result else decomposition_csv(fit), "H_NMR_decomposition.csv", ".csv")


class HModelReviewDialog(tk.Toplevel):
    def __init__(self, workspace, sample):
        super().__init__(workspace)
        _window(self, 'H NMR model sensitivity', '1250x760')
        self.workspace, self.sample, self.report = workspace, sample, None
        self.columnconfigure(0, weight=1); self.rowconfigure(2, weight=1)
        ttk.Label(self, text='Compare line shapes on the same corrected spectrum. This review does not replace the current decomposition. '
            'An added overlap component can improve R2 without identifying a chemical group. Areas include all selected sidebands.',
            wraplength=1150, padding=10).grid(row=0, column=0, sticky='ew')
        frame, self.tree = _tree(self, [('model','Model',220), ('ali','Aliphatic area',180),
            ('aro','Aromatic area',180), ('unassigned','Unassigned area',170), ('fraction','Aliphatic / all (%)',165), ('r2','R2',120)], height=6)
        frame.grid(row=1, column=0, sticky='nsew', padx=10)
        self.selection = SelectableTreeCells(self.tree)
        self.details = ScrolledText(self, wrap='word', height=12)
        self.details.grid(row=2, column=0, sticky='nsew', padx=10, pady=8)
        row = ttk.Frame(self, padding=8); row.grid(row=3, column=0, sticky='ew')
        ttk.Button(row, text='Run model comparison', command=self.run).pack(side='left', padx=4)
        ttk.Button(row, text='Copy comparison', command=self.selection.copy_table).pack(side='left', padx=4)
        ttk.Button(row, text='Save review...', command=self.save).pack(side='left', padx=4)
        self.status = tk.StringVar(value='Ready.'); ttk.Label(row, textvariable=self.status).pack(side='left', padx=8)

    def run(self):
        from .hnmr_model_review import model_review
        self.status.set('Comparing models...'); self.update_idletasks()
        try:
            result = self.workspace.results.get(self.sample.uid)
            processed = result.sample if result else self.workspace.processed(self.sample)
            fit = self.workspace.fitted(self.sample)
            settings = DecompositionSettings(**fit.audit['settings']) if fit else decomposition_defaults(self.sample)
            reference = None
            if settings.model == 'core_template':
                from .hnmr_template import template_processed
                if not fit: raise ValueError('Fit model Ver2 with its pristine reference before reviewing sensitivity.')
                reference = template_processed(fit.audit)
            self.report = model_review(processed, settings, reference,
                                       fit.audit.get('reference') if fit else None,
                                       fit.audit.get('fixed_core_scale') if fit else None)
            modern = settings.model == 'core_template'
            for key,text in (('ali','Ligand area' if modern else 'Aliphatic area'),('aro','Core template area' if modern else 'Aromatic area'),
                             ('fraction','Ligand / all (%)' if modern else 'Aliphatic / all (%)')):
                self.tree.heading(key,text=text)
            self.selection.hide(); self.tree.delete(*self.tree.get_children())
            for row in self.report['rows']:
                values = [row['model']]+[f'{row[k]:.12g}' if row.get(k) is not None else '' for k in
                    (('ligand_integral','core_template_integral','unassigned_integral','ligand_fraction_of_all_components_percent','fit_R2') if modern else
                     ('aliphatic_integral','aromatic_integral','unassigned_integral','aliphatic_fraction_of_all_components_percent','fit_R2'))]
                self.tree.insert('', 'end', values=values)
            _fit_table_values(self.tree)
            text = self.report['note']+'\n\n'+'\n\n'.join(row['model']+':\n'+
                ('ERROR: '+row['error'] if 'error' in row else '\n'.join(row['warnings']) or 'No numerical warnings.') for row in self.report['rows'])
            self.details.configure(state='normal'); self.details.delete('1.0','end'); self.details.insert('1.0', text); self.details.configure(state='disabled')
            self.status.set('Review complete; current decomposition unchanged.')
        except Exception as exc: self.status.set(str(exc))

    def save(self):
        if self.report:
            save_text(self, json.dumps(self.report, indent=2, ensure_ascii=False), 'H_NMR_model_review.json', '.json')


class HComponentDialog(tk.Toplevel):
    """DMfit-style line accounting with explicit finite / infinite domains."""
    def __init__(self, parent, fit):
        super().__init__(parent); _window(self, 'H NMR component integrals', '1230x760')
        self.columnconfigure(0, weight=1); self.rowconfigure(1, weight=3); self.rowconfigure(2, weight=1)
        a=fit.audit
        ttk.Label(self, text=f"Measured-domain integration: {a['area_domain_ppm'][0]:g} to {a['area_domain_ppm'][1]:g} ppm, intensity*ppm.\n"
                  "Family area = central + all included +/- orders. G fraction: 1 = Gaussian, 0 = Lorentzian. Full-profile area extrapolates tails to infinity.",
                  padding=8, wraplength=1150).grid(row=0, column=0, sticky='ew')
        frame,self.tree=_tree(self, [('family','Family',130),('order','Order',70),('center','Center ppm',110),
            ('width','FWHM ppm',110),('gauss','G fraction',100),('area','Finite area',155),
            ('full','Full-profile area',155),('percent','Finite total %',125)], height=11)
        frame.grid(row=1,column=0,sticky='nsew',padx=8)
        self.cell_selection = SelectableTreeCells(self.tree)
        lines=a.get('lines') or [{'family':k,'order':0,'parameters':v,'area':fit.areas[k]} for k,v in a['parameters'].items()]
        if a.get('version') == 4:
            self.tree.insert('','end',values=('core_template','measured','','','',f"{fit.areas['core_template']:.10g}",'',''))
        total=sum(fit.areas.values())
        for line in lines:
            amp,c,w,eta=line['parameters']
            full=line.get('full_profile_area',amp*w*((1-eta)*np.sqrt(np.pi)/(2*np.sqrt(np.log(2)))+eta*np.pi/2))
            self.tree.insert('','end',values=(line['family'],f"{line['order']:+d}",f'{c:.6g}',f'{w:.6g}',f'{1-eta:.6g}',
                f"{line['area']:.10g}",f'{full:.10g}',f"{100*line['area']/total:.5f}" if total else 'undefined'))
        for family, area in fit.areas.items():
            self.tree.insert('','end',values=(family,'SUM','','','',f'{area:.10g}',
                f"{a.get('full_profile_areas',{}).get(family,0):.10g}" if family in a.get('full_profile_areas',{}) else '',
                f'{100*area/total:.5f}' if total else 'undefined'))
        _fit_table_values(self.tree)
        warnings=ScrolledText(self,height=5,wrap='word');warnings.grid(row=2,column=0,sticky='nsew',padx=8,pady=6)
        warnings.insert('1.0','\n'.join(fit.warnings) or 'Review line assignments and phase/baseline; a good fit alone does not validate surface coverage.')
        warnings.configure(state='disabled')
        ttk.Button(self,text='Save complete calculation record...',command=lambda:save_text(self,json.dumps(a,indent=2,ensure_ascii=False),'H_NMR_components.json','.json')).grid(row=3,column=0,sticky='w',padx=8,pady=8)


class HStabilityDialog(tk.Toplevel):
    def __init__(self, workspace, sample):
        super().__init__(workspace);_window(self,'H NMR phase sensitivity','1220x820')
        self.workspace,self.sample,self.report=workspace,sample,None
        self.columnconfigure(0,weight=1);self.rowconfigure(2,weight=1)
        top=ttk.Frame(self,padding=8);top.grid(row=0,column=0,sticky='ew')
        ttk.Label(top,text='Reference spectrum').grid(row=0,column=0,sticky='w')
        self.reference=ttk.Combobox(top,state='readonly',values=['None (single spectrum)']+[s.name for s in workspace.spectra],width=40)
        self.reference.grid(row=0,column=1,sticky='ew',padx=8)
        core,_=infer_identity(sample.name)
        index=next((i+1 for i,s in enumerate(workspace.spectra) if infer_identity(s.name)==(core,'')),0)
        self.reference.current(index)
        q=quant_defaults(sample,workspace.parameters.load())
        self.form=Fields(self,[('phase_step','PH0 perturbation (+/- degrees)','number'),
                              ('sample_mass','Sample mass (mg)','number'),('reference_mass','Reference mass (mg)','number'),
                              ('sample_response','Sample response multiplier','number'),('reference_response','Reference response multiplier','number')],
                         {'phase_step':2.,'sample_mass':q.sample_mass_mg,'reference_mass':q.reference_mass_mg,
                          'sample_response':q.response_factor,'reference_response':q.reference_response_factor})
        self.form.grid(row=1,column=0,sticky='ew')
        frame,self.tree=_tree(self,[('name','Spectrum',230),('phase','PH0 offset',100),('ali','Aliphatic area',155),
            ('aro','Aromatic area',155),('mg','Aliphatic / mg',155),('fraction','Aliphatic %',125),('r2','Fit R2',105)],height=7)
        frame.grid(row=2,column=0,sticky='nsew',padx=8)
        self.status=tk.StringVar(value='Refits PH0 -step / 0 / +step with fixed PH1 and recomputed baseline. Neither sample names nor expected ordering constrain the fit.')
        ttk.Label(self,textvariable=self.status,wraplength=1140,padding=8).grid(row=3,column=0,sticky='ew')
        actions=ttk.Frame(self,padding=8);actions.grid(row=4,column=0,sticky='ew')
        self.run_button=ttk.Button(actions,text='Run phase sensitivity',command=self.run);self.run_button.pack(side='left')
        ttk.Button(actions,text='Export sensitivity record...',command=self.export).pack(side='left',padx=8)

    def run(self):
        from .hnmr_stability import phase_sensitivity
        self.run_button.configure(state='disabled');self.status.set('Running phase sensitivity...');self.update_idletasks()
        try:
            values=self.form.values();index=self.reference.current()
            reference=self.workspace.spectra[index-1] if index>0 else None
            result=phase_sensitivity(self.sample,reference,settings=decomposition_defaults(self.sample),**values)
            self.report=result;self.tree.delete(*self.tree.get_children())
            modern = result['decomposition']['model'] == 'core_template'
            for key,text in (('phase','PH0 S / R' if modern else 'PH0 offset'),('ali','Ligand area' if modern else 'Aliphatic area'),
                             ('aro','Core template area' if modern else 'Aromatic area'),('mg','Ligand ref. area / mg' if modern else 'Aliphatic / mg'),
                             ('fraction','Ligand %' if modern else 'Aliphatic %')):
                self.tree.heading(key,text=text)
            for row in result['rows']:
                phase = f"{row['phase_offset_deg']:+g}" + (f" / {row['reference_phase_offset_deg']:+g}" if modern else '')
                keys = ('ligand_area','core_template_area','ligand_reference_area_per_mg','ligand_fraction_percent','fit_R2') if modern else ('aliphatic_area','aromatic_area','aliphatic_per_mg','aliphatic_fraction_percent','fit_R2')
                self.tree.insert('','end',values=(row['sample'],phase,
                    *[f'{row[k]:.8g}' if row[k] is not None else 'undefined' for k in keys]))
            _fit_table_values(self.tree)
            message='; '.join(k.replace('_',' ')+': '+v['ordering'] for k,v in result.get('comparison',{}).items())
            self.status.set((message+'\n' if message else '')+'Diagnostic sensitivity only; not confidence intervals or validated coverage. Full warnings are in the exported record.')
        except Exception as exc:self.report=None;self.status.set(str(exc))
        finally:self.run_button.configure(state='normal')

    def export(self):
        if self.report:save_text(self,json.dumps(self.report,indent=2,ensure_ascii=False,allow_nan=False),'H_NMR_phase_sensitivity.json','.json')


class HQualityDialog(tk.Toplevel):
    """Visible correction trace and envelope QC; never treats height equality as phase proof."""
    def __init__(self, workspace, sample):
        from .ui import PlotPane
        super().__init__(workspace); _window(self, 'H NMR phase / baseline / sideband QC', '1330x930')
        self.sample=sample; self.processed=workspace.processed(sample)
        p=self.processed; fit=workspace.fitted(sample); self.fit=fit
        diagnostic=(fit.audit.get('sideband_diagnostics') if fit else p.audit.get('sideband_diagnostics')) or {}
        body=ttk.Panedwindow(self,orient='vertical');body.pack(fill='both',expand=True)
        top=ttk.Frame(body);bottom=ttk.Frame(body);body.add(top,weight=3);body.add(bottom,weight=2)
        self.plot=PlotPane(top,self.draw,PlotOptions('Chemical shift','ppm','Intensity','a.u.',reverse_x=True),compact=True,export_current_view=True)
        self.plot.vars['x_min'].set(str(p.x[0]));self.plot.vars['x_max'].set(str(p.x[-1]));self.plot.pack(fill='both',expand=True)
        note=(f"Preprocessing PH0 {p.audit['auto_phase0_deg']:.3f} deg; PH1 {p.audit.get('auto_phase1_deg',0):.3f} deg across {p.x[-1]-p.x[0]:g} ppm. "
              f"Pivot {p.audit['phase_pivot_ppm']:g} ppm. Detected sideband envelopes: {diagnostic.get('detected_sideband_envelopes','n/a')}.\n"
              "Positions follow a common spacing; +/- heights need not be equal. Weak outer peaks remain uncertain. Peak count alone does not establish aliphatic/aromatic assignment.")
        if fit and fit.audit.get('version') == 5:
            note += f"\nDisplayed Ver2 fit: PH0 {fit.audit['phase0_deg']:.4g}, PH1 {fit.audit['phase1_deg']:.4g} deg (same pivot/span); see the Ver2 corrected trace."
        refinement=p.audit.get('phase_diagnostics',{}).get('sideband_refinement')
        if refinement:
            note+='\nSideband refinement: '+refinement['reason']
        ttk.Label(bottom,text=note,wraplength=1250,padding=8).pack(fill='x')
        frame, self.tree=_tree(bottom,[('order','Order',70),('status','Envelope status',240),('ppm','Peak ppm',110),
            ('snr','Prominence / noise',150),('neg','Negative fraction',150),('error','Local RMSE / peak',160),
            ('ali','Aliphatic area',160),('aro','Aromatic area',160)],height=5)
        self.tree.column('order',stretch=False);self.tree.column('status',stretch=True)
        frame.pack(fill='both',expand=True)
        local={r['order']:r['RMSE_over_local_peak'] for r in fit.audit.get('local_fit_errors',[])} if fit else {}
        areas={(r['order'],r['family']):r['area'] for r in fit.audit.get('lines',[])} if fit else {}
        for row in diagnostic.get('envelopes',[]):
            self.tree.insert('','end',values=(f"{row['order']:+d}",row['status'],
                '' if row['peak_ppm'] is None else f"{row['peak_ppm']:.3f}",'' if row['SNR'] is None else f"{row['SNR']:.2f}",
                '' if row['negative_fraction'] is None else f"{row['negative_fraction']:.1%}",
                '' if row['order'] not in local else f"{local[row['order']]:.1%}",
                *['' if (row['order'],family) not in areas else f"{areas[row['order'],family]:.6g}" for family in ('aliphatic','aromatic')]))
        warnings=p.audit.get('phase_diagnostics',{}).get('warnings',[])+(fit.warnings if fit else diagnostic.get('warnings',[]))
        ttk.Label(bottom,text='\n'.join(warnings[:4])+('\nMore warnings in the complete QC record.' if len(warnings)>4 else '') or 'Inspect residual absorption/dispersion and baseline anchors; automatic correction is a proposal.',
                  foreground='#983814',wraplength=1250,padding=8).pack(fill='x')
        self.audit=json.dumps({'preprocessing':p.audit,'fit':fit.audit if fit else None},indent=2,ensure_ascii=False)
        row=ttk.Frame(self,padding=8);row.pack(fill='x')
        ttk.Button(row,text='Save complete QC record...',command=lambda:save_text(self,self.audit,'H_NMR_QC.json','.json')).pack(side='left',padx=4)
        ttk.Button(row,text='Close',command=self.destroy).pack(side='right')
        self.after_idle(lambda:body.sashpos(0,int(body.winfo_height()*.58)))
        self.plot.refresh()

    def draw(self, axis, options):
        p=self.processed;s=self.sample
        colors=s.metadata.setdefault('qc_curve_colors',{})
        for key,label,y,default,style in (
            ('raw','Raw real',np.interp(p.x-p.audit['shift_added_ppm'],s.x,s.real),'#a49f9f','-'),
            ('phased','Phased, before baseline',p.y+p.baseline,'#002060','-'),
            ('corrected','Corrected real',p.y,'#000000','-'),
            ('baseline','Subtracted baseline',p.baseline,'#c00000','--')):
            color=curve_color(axis,s.uid+':qc:'+key,label,default,colors,key)
            axis.plot(p.x,y,color=color,lw=options.line_width,ls=style,label=label)
        if self.fit and self.fit.audit.get('version') == 5:
            from .hnmr_family import corrected_complex
            y=corrected_complex(p,self.fit.audit).real
            color=curve_color(axis,s.uid+':qc:ver2','Ver2 corrected real','#401f68',colors,'ver2')
            axis.plot(p.x,y,color=color,lw=options.line_width,label='Ver2 corrected real')
        axis.axhline(0,color='#006c31',lw=.6,ls=':')
        # PlotPane applies common axes, legend and export settings after drawing.


class NMRWorkspace(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.book = ttk.Notebook(self)
        self.c = SSNMRTab(self.book, import_paths=self.add_paths)
        self.h = HNMRTab(self.book, import_paths=self.add_paths)
        self.book.add(self.c, text="C NMR"); self.book.add(self.h, text="H NMR")
        self.book.pack(fill="both", expand=True)
        self.plot = self.c.plot; self.plot_panes = (self.c.plot, self.h.plot)

    def _refresh(self):
        self.c._refresh(); self.h._refresh()

    def add_paths(self, paths):
        loaded = {self.c: [], self.h: []}
        errors = []
        last_target = None
        for path in paths:
            try:
                spectrum = parse_nmr_ascii(path)
                target = self.h if isinstance(spectrum, HNMRSpectrum) else self.c
                if target is self.h:
                    preview_spectrum(spectrum)
                loaded[target].append(spectrum)
                last_target = target
            except Exception as exc:
                errors.append(f"{Path(path).name}: {exc}")
        for target, spectra in loaded.items():
            if spectra:
                target.add_spectra(spectra)
        if last_target is not None:
            self.book.select(last_target)
        if errors:
            messagebox.showerror(tr('NMR ASCII import'), '\n'.join(errors), parent=self)
