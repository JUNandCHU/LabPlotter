"""Color editing exercises the real common settings window and tab renderers."""
from io import BytesIO
from types import SimpleNamespace
import tkinter as tk
from tkinter import font as tkfont
import unittest
from unittest.mock import patch

import numpy as np
from matplotlib.colors import to_hex
from PIL import Image

from labplotter.models import Spectrum
from labplotter.plotting import PlotOptions, SERIES_PALETTE, figure_png_bytes, save_plot_figure
from labplotter.ui import FTIRTab, NanoDropTab, GenericTab, TEMTab, ZetaTab, PlotPane


class CurveColorDesktopTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest('Tk display is unavailable')
        self.root.geometry('1000x760')
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.error_patch = patch('labplotter.ui.messagebox.showerror', side_effect=lambda *args, **kwargs: self.errors.append(args))
        self.error_patch.start()

    def tearDown(self):
        if hasattr(self, 'error_patch'):
            self.error_patch.stop()
        if hasattr(self, 'root'):
            self.root.destroy()

    def settle(self):
        self.root.update()
        self.root.after(120, self.root.quit)
        self.root.mainloop()
        self.root.update()

    def pane(self, draw):
        pane = PlotPane(self.root, draw, PlotOptions(font_family='DejaVu Sans'), export_current_view=True)
        pane.pack(fill='both', expand=True)
        pane.refresh(); self.settle()
        pane.open_settings(); self.settle()
        return pane, pane.settings_window.curve_editor

    def test_ftir_nanodrop_custom_colors_identity_validation_reset_and_exports(self):
        for tab in (FTIRTab, NanoDropTab, GenericTab):
            with self.subTest(tab=tab.__name__):
                spectra = [Spectrum('Same name', np.arange(5.), np.array([0., 1., 5., 2., 0.]) + i) for i in range(2)]
                source = [s.y.copy() for s in spectra]
                owner = SimpleNamespace(tree=SimpleNamespace(visible=lambda: [s for s in spectra if s.visible]),
                    _processed=lambda s: s.y, peaks=tk.BooleanVar(value=True),
                    prominence=tk.StringVar(value='0.01'), orientation=tk.StringVar(value='Absorbance'))
                pane, editor = self.pane(lambda ax, opts: tab._draw(owner, ax, opts))
                pane.axis.set_xlim(1, 3)
                editor.variables[spectra[0].uid].set('#123456')
                editor.variables[spectra[1].uid].set('#789ABC')
                self.settle()
                self.assertEqual(pane.axis.get_xlim(), (1, 3))
                self.assertEqual([line.get_color() for line in pane.axis.lines], ['#123456', '#789ABC'])
                if tab is FTIRTab:
                    self.assertEqual([text.get_color() for text in pane.axis.texts], ['#123456', '#789ABC'])
                # Renaming/reordering/hiding must not transfer an override to another curve.
                spectra.reverse(); spectra[0].name = 'Renamed'; spectra[1].visible = False
                pane.refresh(); self.settle()
                self.assertEqual(pane.axis.lines[0].get_color(), '#789ABC')
                self.assertEqual(len(editor.variables), 1)
                spectra[1].visible = True
                pane.refresh(); self.settle()
                self.assertEqual([line.get_color() for line in pane.axis.lines], ['#789ABC', '#123456'])
                key = spectra[0].uid
                editor.variables[key].set('invalid color')
                self.assertFalse(editor.apply())
                self.assertEqual(pane.axis.lines[0].get_color(), '#789ABC')
                editor.variables[key].set('tab:blue')  # valid Matplotlib name, converted for Tk swatch
                self.assertEqual(pane.axis.lines[0].get_color(), '#1F77B4')
                with patch('labplotter.curve_color_editor.colorchooser.askcolor', return_value=(None, None)):
                    editor.choose(key)
                self.assertEqual(pane.axis.lines[0].get_color(), '#1F77B4')
                pane.settings_window.live.set(False)
                editor.variables[key].set('#ABCDEF')
                self.assertEqual(pane.axis.lines[0].get_color(), '#1F77B4')
                pane.settings_window.apply(); self.settle()
                self.assertEqual(pane.axis.lines[0].get_color(), '#ABCDEF')
                legend = pane.axis.get_legend()
                self.assertEqual([to_hex(h.get_color()).upper() for h in legend.legend_handles], ['#ABCDEF', '#123456'])
                svg = BytesIO(); save_plot_figure(pane.figure, svg, format='svg')
                self.assertIn(b'#abcdef', svg.getvalue())
                self.assertIn(b'#123456', svg.getvalue())
                visible = figure_png_bytes(pane.figure)
                with patch('labplotter.ui.copy_png_to_clipboard') as copy, patch('labplotter.ui.messagebox.showinfo'):
                    pane.copy_image(False)
                with Image.open(BytesIO(visible)) as expected, Image.open(BytesIO(copy.call_args.args[0])) as actual:
                    np.testing.assert_array_equal(np.asarray(expected), np.asarray(actual))
                pane.settings_window.live.set(True)
                editor.reset_all(); self.settle()
                self.assertEqual([line.get_color() for line in pane.axis.lines], list(SERIES_PALETTE[:2]))
                for s, original in zip(reversed(spectra), source):
                    np.testing.assert_array_equal(s.y, original)
                pane.settings_window._close(); pane.destroy(); self.settle()
        self.assertFalse(self.errors)

    def test_tem_histogram_and_median_share_color_and_large_font_rows(self):
        records = [dict(batch_name=name, status='analyzed', included=True, diameters_nm=[10, 12, 15, 21, 28])
                   for name in ('Batch A', 'Batch B')]
        owner = SimpleNamespace(_selected_batches=lambda: [], library=SimpleNamespace(images=lambda: records))
        font = tkfont.nametofont('TkDefaultFont'); previous = font.cget('size')
        try:
            font.configure(size=19)
            pane, editor = self.pane(lambda ax, opts: TEMTab._draw_distribution(owner, ax, opts))
            self.assertEqual(len(editor.variables), 2)
            editor.variables['Batch B'].set('#12AB34'); self.settle()
            self.assertEqual(to_hex(pane.axis.patches[1].get_edgecolor()).upper(), '#12AB34')
            self.assertEqual(pane.axis.lines[1].get_color(), '#12AB34')
            notebook = next(w for w in pane.settings_window.winfo_children() if w.winfo_class() == 'TNotebook')
            notebook.select(notebook.tabs()[1]); self.settle()
            for widget in editor.rows.winfo_children():
                if widget.winfo_class() == 'TLabel':
                    self.assertGreaterEqual(widget.winfo_height(), font.metrics('linespace'))
            pane.settings_window._close()
        finally:
            font.configure(size=previous)
        self.assertFalse(self.errors)

    def test_zetasizer_replicates_mean_and_sd_are_independently_editable(self):
        variable = lambda value: SimpleNamespace(get=lambda: value)
        items = [dict(x=np.array([10., 20., 30.]), y=np.array([1., 4.+i, 2.]), replicate=i) for i in (1, 2)]
        owner = SimpleNamespace(active_names=lambda: ['Particle'], mode=tk.StringVar(value='Mean + replicates'),
            library=SimpleNamespace(measurements=lambda *_: {'Particle': items}),
            series_color=lambda *_: '#000000', peak_labels=variable(True),
            multi_peak_labels=variable(True), log_x=variable(False))
        # The callback references the pane only after construction.
        pane = PlotPane(self.root, lambda ax, opts: ZetaTab._draw_kind(owner, 'DLS', ax, opts), PlotOptions())
        owner.dls_plot = pane
        pane.pack(fill='both', expand=True); pane.refresh(); self.settle()
        pane.open_settings(); self.settle(); editor = pane.settings_window.curve_editor
        self.assertEqual(len(editor.variables), 3)
        editor.variables['replicate:Particle:2'].set('#123456')
        editor.variables['mean:Particle'].set('#AB1234'); self.settle()
        self.assertEqual([line.get_color() for line in pane.axis.lines], ['#000000', '#123456', '#AB1234'])
        owner.mode.set('Mean ± SD'); pane.refresh(); self.settle()
        self.assertEqual(len(editor.variables), 1)
        self.assertEqual(to_hex(pane.axis.collections[0].get_facecolor()[0]).upper(), '#AB1234')
        self.assertEqual(pane.axis.texts[0].get_color(), '#AB1234')
        owner.mode.set('Replicates only'); pane.refresh(); self.settle()
        self.assertEqual(pane.axis.lines[1].get_color(), '#123456')
        self.assertFalse(self.errors)
