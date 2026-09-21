"""Desktop ASCII ssNMR workspace; all numerical operations live in nmr.py."""
from __future__ import annotations
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, font as tkfont
from tkinter.scrolledtext import ScrolledText

import numpy as np
from .i18n import tr
from .models import Spectrum
from .nmr import (PHASE_NOTE, ComparisonSettings, default_settings, parse_topspin_ascii,
                  preprocess_pair, regional_metrics_audit, regional_preprocessing_audit,
                  integrals_audit, preprocessing_audit, comparison_csv)
from .nmr_comparison import ComparisonSession
from .nmr_library import NMRLibrary
from .plotting import PlotOptions, SERIES_PALETTE


def number(value):
    return f"{value:.6g}" if np.isfinite(value) else tr("Undefined")


def save_text(parent, content, filename, extension=".txt"):
    path = filedialog.asksaveasfilename(parent=parent, initialfile=filename, defaultextension=extension,
                                      filetypes=[(extension.upper().strip('.'), '*'+extension)])
    if path:
        try:
            Path(path).write_text(content, encoding="utf-8-sig")
        except OSError as exc:
            messagebox.showerror(tr("Export"), str(exc), parent=parent)


def nmr_tree_style(parent):
    font = tkfont.nametofont("TkDefaultFont")
    style = ttk.Style(parent)
    style.configure("SSNMR.Treeview", font=font, rowheight=max(32, font.metrics("linespace")+12))
    style.configure("SSNMR.Treeview.Heading", font=font, padding=(4, 6))
    return "SSNMR.Treeview"


class AuditWindow(tk.Toplevel):
    def __init__(self, parent, title, calculation, result, preprocessing=None):
        super().__init__(parent)
        self.title(tr(title)); self.geometry("1050x720")
        book = ttk.Notebook(self); book.pack(fill="both", expand=True, padx=8, pady=8)
        for label, content, filename in (("Calculation details", calculation, "ssNMR_calculation.txt"),
                                          ("Preprocessing audit", preprocessing if preprocessing is not None else preprocessing_audit(result), "ssNMR_preprocessing.txt")):
            page = ttk.Frame(book); book.add(page, text=tr(label))
            ttk.Button(page, text=tr("Save complete audit…"), command=lambda c=content, f=filename: save_text(self, c, f)).pack(anchor="w", pady=4)
            text = ScrolledText(page, wrap="none", font=("TkFixedFont", 10))
            text.pack(fill="both", expand=True)
            xscroll = ttk.Scrollbar(page, orient="horizontal", command=text.xview)
            xscroll.pack(fill="x"); text.configure(xscrollcommand=xscroll.set)
            text.insert("1.0", content); text.configure(state="disabled")


class PreprocessingDialog(tk.Toplevel):
    def __init__(self, parent, a, b, on_done, settings=None):
        super().__init__(parent)
        self.title(tr("ssNMR preprocessing")); self.transient(parent.winfo_toplevel()); self.resizable(False, False)
        self.a, self.b, self.on_done = a, b, on_done
        s = settings or default_settings(a, b)
        self.vars = {}
        frame = ttk.Frame(self, padding=14); frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=f"A: {a.name}\nB: {b.name}", wraplength=610).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0,8))
        labels = [("Common ppm minimum", "ppm_min"), ("Common ppm maximum", "ppm_max"),
                  ("Grid step (ppm)", "grid_step"), ("Baseline edge fraction", "edge_fraction"),
                  ("Maximum B shift (ppm)", "max_shift_ppm"), ("Alignment minimum (blank = full)", "alignment_min"),
                  ("Alignment maximum (blank = full)", "alignment_max"), ("Shared Gaussian FWHM (ppm)", "gaussian_fwhm_ppm")]
        for i, (label, key) in enumerate(labels, 1):
            value = getattr(s, key)
            self.vars[key] = tk.StringVar(value="" if value is None else f"{value:.12g}")
            ttk.Label(frame, text=tr(label)).grid(row=i, column=0, sticky="w", padx=(0,18), pady=3)
            ttk.Entry(frame, textvariable=self.vars[key], width=22).grid(row=i, column=1, sticky="ew")
        self.baseline, self.align = tk.BooleanVar(value=s.baseline), tk.BooleanVar(value=s.align)
        ttk.Checkbutton(frame, text=tr("Automatic linear edge baseline"), variable=self.baseline).grid(row=9, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(frame, text=tr("Automatic bounded chemical-shift alignment"), variable=self.align).grid(row=10, column=0, columnspan=2, sticky="w")
        ttk.Label(frame, text=tr("Normalization")).grid(row=11, column=0, sticky="w", pady=4)
        self.norm = ttk.Combobox(frame, values=[tr(v) for v in ("Maximum absolute intensity", "Total absolute area", "None")], state="readonly", width=28)
        self.norm.current(("Maximum absolute intensity", "Total absolute area", "None").index(s.normalization))
        self.norm.grid(row=11, column=1)
        ttk.Label(frame, text=tr(PHASE_NOTE), wraplength=600, foreground="#555555").grid(row=12, column=0, columnspan=2, sticky="w", pady=8)
        ttk.Label(frame, text=tr("The union range is used by default. Missing coverage stays blank; calculations use measured overlap. Gaussian smoothing uses the same ppm width for both spectra. Normalization uses the full common measured range."), wraplength=600).grid(row=13, column=0, columnspan=2, sticky="w", pady=5)
        self.status = tk.StringVar()
        ttk.Label(frame, textvariable=self.status, foreground="#AE2C28", wraplength=600).grid(row=14, column=0, columnspan=2, sticky="w")
        self.run_button = ttk.Button(frame, text=tr("Process and compare"), command=self.run)
        self.run_button.grid(row=15, column=0, columnspan=2, sticky="ew", pady=8)
        self.grab_set()

    def run(self):
        try:
            kwargs = {key: float(var.get()) if var.get().strip() else None for key, var in self.vars.items()}
            for key in ("edge_fraction", "max_shift_ppm", "gaussian_fwhm_ppm"):
                if kwargs[key] is None:
                    raise ValueError("Baseline, shift and broadening parameters cannot be blank.")
            settings = ComparisonSettings(**kwargs, baseline=self.baseline.get(), align=self.align.get(),
                       normalization=("Maximum absolute intensity", "Total absolute area", "None")[self.norm.current()])
            self.status.set(tr("Processing…")); self.update_idletasks()
            result = preprocess_pair(self.a, self.b, settings)
        except Exception as exc:
            self.status.set(str(exc)); return
        self.grab_release(); self.destroy()
        self.on_done(result)


class ComparisonWindow(tk.Toplevel):
    def __init__(self, parent, a, b, result):
        from .ui import PlotPane
        super().__init__(parent)
        self.title(tr("Spectrum comparison")); self.geometry("1250x900"); self.minsize(950, 720)
        self.session = ComparisonSession(a, b, result)
        self.a_raw, self.b_raw, self.result = self.session.a_raw, self.session.b_raw, result
        self.metrics = self.ratios = None
        self.region_metrics = {}
        self.region_results = {}
        self.integral_result = None
        self._recalc_job = None
        self.bind("<Destroy>", self._cancel_recalculation, add=True)
        self.rowconfigure(1, weight=1); self.columnconfigure(0, weight=1)
        top = ttk.Frame(self, padding=7); top.grid(row=0, column=0, sticky="ew")
        ttk.Label(top, text=f"A ({tr('reference')}): {a.name}     B: {b.name}", wraplength=1150).pack(anchor="w")
        actions = ttk.Frame(top); actions.pack(fill="x", pady=4)
        ttk.Button(actions, text=tr("Preprocessing settings…"), command=self.reprocess).pack(side="left")
        ttk.Button(actions, text=tr("Export comparison CSV…"), command=lambda: save_text(self, comparison_csv(self.result), "ssNMR_comparison.csv", ".csv")).pack(side="left", padx=5)
        self.process_label = ttk.Label(top, wraplength=1150, foreground="#555555"); self.process_label.pack(anchor="w")
        self.plot = PlotPane(self, self._draw, PlotOptions("Chemical shift", "ppm", "Intensity", "normalized a.u.", reverse_x=True), compact=True)
        self.plot.grid(row=1, column=0, sticky="nsew", padx=8)
        lower = ttk.LabelFrame(self, text=tr("Comparison results"), padding=8); lower.grid(row=2, column=0, sticky="ew", padx=8, pady=8)
        region_buttons = ttk.Frame(lower); region_buttons.pack(fill="x", pady=(0,6))
        ttk.Label(region_buttons, text=tr("Reprocess region")+":").pack(side="left", padx=(0,6))
        for label, low_key, high_key in (("Aliphatic region", "alow", "ahigh"), ("Aromatic region", "rlow", "rhigh"),
                                       ("Custom region", "clow", "chigh")):
            ttk.Button(region_buttons, text=tr(label),
                       command=lambda lo=low_key, hi=high_key: self.show_region(lo, hi)).pack(side="left", padx=(0,6))
        bounds = ttk.Frame(lower); bounds.pack(fill="x")
        self.fields = {}
        for label, key, value in (("Comparison min", "low", result.x[0]), ("Comparison max", "high", result.x[-1]),
                                   ("Aliphatic min", "alow", 0), ("Aliphatic max", "ahigh", 50),
                                   ("Aromatic min", "rlow", 90), ("Aromatic max", "rhigh", 160),
                                   ("Custom min", "clow", 0), ("Custom max", "chigh", 200)):
            i = len(self.fields)
            box = ttk.Frame(bounds); box.grid(row=i//2, column=i%2, sticky="ew", padx=(0,12), pady=2)
            bounds.columnconfigure(i%2, weight=1)
            ttk.Label(box, text=tr(label)+" (ppm)").pack(side="left")
            var = tk.StringVar(value=f"{value:.10g}"); self.fields[key] = var
            ttk.Entry(box, textvariable=var, width=13).pack(side="right")
        buttons = ttk.Frame(lower); buttons.pack(fill="x", pady=6)
        ttk.Button(buttons, text=tr("Calculate / update range"), command=self.calculate).pack(side="left")
        ttk.Button(buttons, text=tr("R² / r² calculation details…"), command=self.metric_details).pack(side="left", padx=6)
        ttk.Button(buttons, text=tr("Integral calculation details…"), command=self.integral_details).pack(side="left")
        self.metric_text = tk.StringVar(); self.integral_text = tk.StringVar()
        ttk.Label(lower, textvariable=self.metric_text, wraplength=1130, font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=4)
        ttk.Label(lower, textvariable=self.integral_text, wraplength=1130).pack(anchor="w", pady=3)
        ttk.Label(lower, text=tr("Region statistics use separate preprocessing. Integral ratios use one shared preprocessing result for both regions."), wraplength=1130, foreground="#555555").pack(anchor="w")
        ttk.Label(lower, text=tr("R²: direct agreement with reference A (no fitted scaling). r²: squared Pearson r. Integrals use processed signed intensities and exact region boundaries."), wraplength=1130, foreground="#555555").pack(anchor="w", pady=3)
        for key, var in self.fields.items():
            if key not in ('clow', 'chigh'):
                var.trace_add("write", self._invalidate)
        self._process_status(); self.calculate()

    def show_region(self, low_key, high_key):
        low, high = self.fields[low_key].get(), self.fields[high_key].get()
        try:
            result = self.session.select_region(low, high)
        except (ValueError, TypeError) as exc:
            messagebox.showerror(tr("ssNMR preprocessing"), str(exc), parent=self)
            return
        self.result = result
        self.fields['low'].set(low); self.fields['high'].set(high)
        self._process_status()
        self.calculate()

    def _invalidate(self, *_):
        self.metrics = self.ratios = None
        self.region_metrics = {}
        self.metric_text.set(tr("Updating results…")); self.integral_text.set("")
        if self._recalc_job is not None:
            self.after_cancel(self._recalc_job)
        self._recalc_job = self.after(350, self.calculate)

    def _cancel_recalculation(self, event):
        if event.widget is self and self._recalc_job is not None:
            self.after_cancel(self._recalc_job)
            self._recalc_job = None

    def _process_status(self):
        r = self.result
        limit = " — " + tr("Alignment reached the shift limit; inspect the overlay.") if r.log['alignment'].get('at_limit') else ""
        self.process_label.configure(text=f"{tr('Processing range')}: {r.settings.ppm_min:g}–{r.settings.ppm_max:g} ppm | {tr('Applied B shift')}: {r.log['alignment']['B_shift_added_ppm']:+.6g} ppm | {tr('Grid')}: {len(r.x):,} / {r.log['actual_grid_step_ppm']:.6g} ppm | Gaussian FWHM: {r.settings.gaussian_fwhm_ppm:g} ppm | {tr(r.settings.normalization)}{limit}\n{tr(PHASE_NOTE)}")
        self.plot.vars['y_unit'].set('a.u.' if r.settings.normalization == 'None' else 'normalized a.u.')

    def _draw(self, axis, options):
        for name, values, color in zip(self.result.names, (self.result.a, self.result.b), SERIES_PALETTE[:2]):
            axis.plot(self.result.x, values, label=name, color=color, linewidth=options.line_width)

    def calculate(self):
        if self._recalc_job is not None:
            self.after_cancel(self._recalc_job)
            self._recalc_job = None
        self.metrics = self.ratios = None
        # Invalid/partially typed entries are independent of the other ranges.
        def value(key):
            try:
                return float(self.fields[key].get())
            except ValueError:
                return float('nan')
        low, high = value('low'), value('high')
        bounds = [value(k) for k in ('alow', 'ahigh', 'rlow', 'rhigh')]
        self.region_metrics, self.region_results = self.session.statistics((low,high), bounds[:2], bounds[2:])
        lines = []
        for label, m in self.region_metrics.items():
            if 'error' in m:
                lines.append(f"{tr(label)}: {m['error']}")
            else:
                lo, hi = m['requested_range_ppm']
                lines.append(f"{tr(label)} ({lo:g}–{hi:g} ppm):   R² = {number(m['R2'])}   r² = {number(m['r2'])}   r = {number(m['r'])}   N = {m['n']:,}")
        self.metric_text.set('\n'.join(lines))
        overall = self.region_metrics['Comparison range']
        if 'error' not in overall:
            self.metrics = overall
            self.plot.vars['x_min'].set(str(low)); self.plot.vars['x_max'].set(str(high)); self.plot.refresh()
        try:
            self.integral_result, self.ratios = self.session.integrals(bounds[:2], bounds[2:])
            self.integral_text.set('\n'.join(f"{row['name']}:    I({bounds[0]:g}–{bounds[1]:g}) = {number(row['aliphatic']['area'])}    I({bounds[2]:g}–{bounds[3]:g}) = {number(row['aromatic']['area'])}    {tr('Ratio')} = {number(row['ratio'])}" for row in self.ratios))
        except (ValueError, TypeError) as exc:
            self.integral_text.set(str(exc))

    def metric_details(self):
        if any('error' not in values for values in self.region_metrics.values()):
            AuditWindow(self, "R² / r² calculation details", regional_metrics_audit(self.result, self.region_metrics, self.region_results),
                        self.result, regional_preprocessing_audit(self.region_results))
        else:
            messagebox.showinfo(tr("Calculation details"), tr("Calculate valid results first."), parent=self)

    def integral_details(self):
        if self.ratios is not None:
            AuditWindow(self, "Integral calculation details", integrals_audit(self.integral_result, self.ratios), self.integral_result)
        else:
            messagebox.showinfo(tr("Calculation details"), tr("Calculate valid results first."), parent=self)

    def reprocess(self):
        def done(result):
            self.session.reset(result)
            self.result = result
            self.fields['low'].set(f"{result.x[0]:.10g}"); self.fields['high'].set(f"{result.x[-1]:.10g}")
            self._process_status(); self.calculate()
        PreprocessingDialog(self, self.a_raw, self.b_raw, done, self.result.settings)


class NMRLibraryWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.workspace, self.library = parent, parent.library
        self.title(tr("ssNMR library")); self.geometry("780x500")
        actions = ttk.Frame(self, padding=8); actions.pack(fill="x")
        for label, command in (("Load into data list", self.load), ("Rename…", self.rename), ("Delete from library…", self.delete),
                               ("Move up", lambda: self.move(-1)), ("Move down", lambda: self.move(1))):
            ttk.Button(actions, text=tr(label), command=command).pack(side="left", padx=2)
        self.tree = ttk.Treeview(self, columns=('name','source'), show='headings', selectmode='extended', style=nmr_tree_style(self))
        self.tree.heading('name', text=tr('Series name')); self.tree.heading('source', text=tr('Source'))
        self.tree.column('name', width=300); self.tree.column('source', width=430)
        scroll = ttk.Scrollbar(self, command=self.tree.yview); scroll.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=scroll.set); self.tree.pack(fill='both', expand=True, padx=8, pady=8)
        self.tree.bind('<Double-1>', lambda _: self.load())
        self.refresh()

    def refresh(self, selected=None):
        self.tree.delete(*self.tree.get_children())
        for row in self.library.entries():
            self.tree.insert('', 'end', iid=row['uid'], values=(row['name'], Path(row['source']).name))
        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected); self.tree.see(selected)

    def load(self):
        self.workspace.add_spectra([self.library.load(uid) for uid in self.tree.selection()])

    def rename(self):
        selected = self.tree.selection()
        if len(selected) != 1:
            return
        uid = selected[0]
        value = simpledialog.askstring(tr('Rename series'), tr('Series name'), initialvalue=self.tree.item(uid, 'values')[0], parent=self)
        if value and value.strip():
            self.library.rename(uid, value); self.refresh(uid)

    def delete(self):
        selected = self.tree.selection()
        if selected and messagebox.askyesno(tr('Delete from library…'), tr('Delete selected saved spectra? The current data list is kept.'), parent=self):
            self.library.delete(selected); self.refresh()

    def move(self, offset):
        selected = self.tree.selection()
        if len(selected) == 1:
            self.library.move(selected[0], offset); self.refresh(selected[0])


class SSNMRTab(ttk.Frame):
    def __init__(self, parent, library=None):
        from .ui import PlotPane
        super().__init__(parent)
        self.library = library or NMRLibrary()
        self.spectra: list[Spectrum] = []
        self.library_window = None
        panes = ttk.Panedwindow(self, orient='horizontal'); panes.pack(fill='both', expand=True)
        controls, graph = ttk.Frame(panes, padding=8, width=340), ttk.Frame(panes, padding=5)
        panes.add(controls, weight=0); panes.add(graph, weight=1)
        for labels in ((("Import ASCII TXT…", self.add_dialog), ("Remove from list", self.remove)),
                       (("Rename…", self.rename), ("Save to library", self.save)),
                       (("Open ssNMR library…", self.open_library), ("Compare two spectra…", self.compare))):
            row = ttk.Frame(controls); row.pack(fill='x', pady=3)
            for label, command in labels:
                ttk.Button(row, text=tr(label), command=command).pack(side='left', fill='x', expand=True, padx=2)
        self.tree = ttk.Treeview(controls, columns=('name',), show='headings', selectmode='extended', style=nmr_tree_style(self))
        self.tree.heading('name', text=tr('Loaded spectra')); self.tree.column('name', width=310)
        scroll = ttk.Scrollbar(controls, command=self.tree.yview); scroll.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=scroll.set); self.tree.pack(fill='both', expand=True, pady=5)
        self.tree.bind('<<TreeviewSelect>>', lambda _: self._refresh())
        self.tree.bind('<Double-1>', lambda _: self.rename())
        self.status = tk.StringVar(value=tr('Column 4 = ppm; column 2 = intensity. Click a row to preview its raw spectrum.'))
        ttk.Label(controls, textvariable=self.status, wraplength=320).pack(anchor='w', pady=7)
        self.plot = PlotPane(graph, self._draw, PlotOptions('Chemical shift', 'ppm', 'Intensity', 'a.u.', reverse_x=True), compact=True)
        self.plot.pack(fill='both', expand=True)

    def add_dialog(self):
        paths = filedialog.askopenfilenames(parent=self, filetypes=[('TopSpin ASCII', '*.txt *.asc *.csv *.tsv')])
        self.add_paths(paths)

    def add_paths(self, paths):
        loaded, errors = [], []
        for path in paths:
            try:
                loaded.append(parse_topspin_ascii(path))
            except Exception as exc:
                errors.append(f"{Path(path).name}: {exc}")
        self.add_spectra(loaded)
        if errors:
            messagebox.showerror(tr('ssNMR import'), '\n'.join(errors), parent=self)

    def add_spectra(self, spectra):
        existing = {s.uid for s in self.spectra}
        for spectrum in spectra:
            if spectrum.uid in existing:
                continue
            self.spectra.append(spectrum); existing.add(spectrum.uid)
            self.tree.insert('', 'end', iid=spectrum.uid, values=(spectrum.name,))
        if spectra:
            self.tree.selection_set(spectra[-1].uid); self.tree.focus(spectra[-1].uid)
        self._refresh()

    def selected(self):
        ids = self.tree.selection()
        return [s for s in self.spectra if s.uid in ids]

    def remove(self):
        ids = self.tree.selection(); self.spectra = [s for s in self.spectra if s.uid not in ids]
        self.tree.delete(*ids)
        if self.spectra:
            self.tree.selection_set(self.spectra[0].uid)
        self._refresh()

    def rename(self):
        selected = self.selected()
        if len(selected) != 1:
            messagebox.showinfo(tr('Rename series'), tr('Select exactly one spectrum.'), parent=self); return
        spectrum = selected[0]
        name = simpledialog.askstring(tr('Rename series'), tr('Series name'), initialvalue=spectrum.name, parent=self)
        if name and name.strip():
            spectrum.name = name.strip(); self.tree.item(spectrum.uid, values=(spectrum.name,)); self._refresh()

    def save(self):
        selected = self.selected()
        try:
            for spectrum in selected:
                self.library.save(spectrum)
            self.status.set(tr('Saved spectra: {count}', count=len(selected)))
            if self.library_window and self.library_window.winfo_exists():
                self.library_window.refresh()
        except Exception as exc:
            messagebox.showerror(tr('ssNMR library'), str(exc), parent=self)

    def open_library(self):
        if self.library_window and self.library_window.winfo_exists():
            self.library_window.lift(); self.library_window.refresh()
        else:
            self.library_window = NMRLibraryWindow(self)

    def compare(self):
        if len(self.spectra) < 2:
            messagebox.showinfo(tr('Spectrum comparison'), tr('Load at least two spectra.'), parent=self); return
        dialog = tk.Toplevel(self); dialog.title(tr('Select two spectra')); dialog.transient(self.winfo_toplevel())
        frame = ttk.Frame(dialog, padding=15); frame.pack(fill='both', expand=True)
        values = [f"{i+1}. {s.name}" for i, s in enumerate(self.spectra)]
        boxes = []
        for i, label in enumerate(('Reference A', 'Spectrum B')):
            ttk.Label(frame, text=tr(label)).grid(row=i, column=0, sticky='w', padx=6, pady=6)
            box = ttk.Combobox(frame, values=values, state='readonly', width=45); box.current(i)
            box.grid(row=i, column=1); boxes.append(box)
        selected = self.selected()
        if len(selected) == 2:
            for box, spectrum in zip(boxes, selected):
                box.current(next(i for i, item in enumerate(self.spectra) if item.uid == spectrum.uid))
        def choose():
            i, j = [box.current() for box in boxes]
            if i == j:
                messagebox.showerror(tr('Spectrum comparison'), tr('Choose two different spectra.'), parent=dialog); return
            a, b = self.spectra[i], self.spectra[j]
            dialog.grab_release(); dialog.destroy()
            PreprocessingDialog(self, a, b, lambda result: ComparisonWindow(self, a, b, result))
        ttk.Button(frame, text=tr('Continue to preprocessing'), command=choose).grid(row=2, column=0, columnspan=2, sticky='ew', pady=8)
        dialog.grab_set()

    def _draw(self, axis, options):
        selected = self.selected()
        if selected:
            spectrum = selected[0]
            axis.plot(spectrum.x, spectrum.y, label=spectrum.name, color=SERIES_PALETTE[0], linewidth=options.line_width)
        else:
            axis.text(0.5, 0.5, tr('Import TopSpin ASCII TXT data'), ha='center', transform=axis.transAxes)

    def _refresh(self):
        if hasattr(self, 'plot'):
            self.plot.refresh()
