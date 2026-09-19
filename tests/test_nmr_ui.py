"""Exercise Tk workflows when a display is available (including Windows CI)."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont, ttk
from unittest.mock import patch
from io import BytesIO
from PIL import Image
import numpy as np
from labplotter.models import Spectrum
from labplotter.nmr_library import NMRLibrary
from labplotter.nmr_ui import SSNMRTab, ComparisonWindow, PreprocessingDialog, AuditWindow, nmr_tree_style


class NMRDesktopWorkflowTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root=tk.Tk()
        except tk.TclError:
            self.skipTest('Tk display is unavailable')
        self.temp=tempfile.TemporaryDirectory()
        self.root.geometry('1100x780')
        self.errors=[]
        self.root.report_callback_exception=lambda *args:self.errors.append(args)
        self.tab=SSNMRTab(self.root,NMRLibrary(Path(self.temp.name)/'nmr.sqlite3'))
        self.tab.pack(fill='both',expand=True)
        x=np.linspace(-20,220,481)
        self.a=Spectrum('Same name',x,10+np.exp(-((x-130)/20)**2)*100)
        self.b=Spectrum('Same name',x,5+np.exp(-((x-130)/20)**2)*80+np.exp(-((x-25)/8)**2)*20)

    def tearDown(self):
        if hasattr(self,'root'):
            self.root.destroy()
        if hasattr(self,'temp'):
            self.temp.cleanup()

    def test_list_library_selection_and_pair_dialog(self):
        self.tab.add_spectra([self.a,self.b]);self.root.update()
        self.tab.tree.selection_set(self.a.uid);self.root.update()
        np.testing.assert_array_equal(self.tab.plot.axis.lines[0].get_ydata(),self.a.y)
        self.tab.tree.selection_set(self.a.uid,self.b.uid);self.tab.save()
        self.tab.open_library();self.root.update()
        self.assertEqual(len(self.tab.library_window.tree.get_children()),2)
        self.tab.remove();self.assertEqual(len(self.tab.spectra),0)
        self.tab.library_window.tree.selection_set(self.a.uid,self.b.uid)
        self.tab.library_window.load();self.root.update()
        self.assertEqual(len(self.tab.spectra),2)
        self.tab.tree.selection_set(self.a.uid,self.b.uid)
        self.tab.compare();self.root.update()  # same names must not compare ndarray equality
        self.assertFalse(self.errors)

    def test_preprocessing_comparison_and_full_audit_windows(self):
        results=[]
        dialog=PreprocessingDialog(self.root,self.a,self.b,results.append)
        dialog.run();self.assertEqual(len(results),1)
        window=ComparisonWindow(self.root,self.a,self.b,results[0]);self.root.update()
        self.assertIsNotNone(window.metrics);self.assertIsNotNone(window.ratios)
        self.assertEqual(len(window.plot.axis.lines),2)
        self.root.after(150,self.root.quit);self.root.mainloop();self.root.update()
        widget=window.plot.canvas.get_tk_widget()
        self.assertLessEqual(window.plot.figure.bbox.width,widget.winfo_width()+1)
        self.assertLessEqual(window.plot.figure.bbox.height,widget.winfo_height()+1)
        window.metric_details();window.integral_details();self.root.update()
        audits=[v for v in window.winfo_children() if isinstance(v,AuditWindow)]
        self.assertEqual(len(audits),2)
        window.fields['low'].set('0');self.assertIsNone(window.metrics)
        window.fields['high'].set('200');window.calculate()
        self.assertEqual(window.metrics['requested_range_ppm'],[0,200])
        before=window.region_metrics['Aliphatic region']['n']
        window.fields['ahigh'].set('30')
        self.root.after(500,self.root.quit);self.root.mainloop();self.root.update()
        self.assertEqual(window.region_metrics['Aliphatic region']['requested_range_ppm'],[0,30])
        self.assertLess(window.region_metrics['Aliphatic region']['n'],before)
        self.assertFalse(self.errors)

    def test_region_buttons_reprocess_and_custom_bounds_reach_settings_dialog(self):
        from labplotter.nmr import preprocess_pair
        window=ComparisonWindow(self.root,self.a,self.b,preprocess_pair(self.a,self.b));self.root.update()
        todo=[window];buttons={}
        while todo:
            widget=todo.pop();todo.extend(widget.winfo_children())
            if isinstance(widget,ttk.Button):buttons[widget.cget('text')]=widget
        ratios=[row['ratio'] for row in window.ratios]
        for label,bounds in (('Aliphatic region',(0,50)),('Aromatic region',(90,160)),('Custom region',(0,200))):
            buttons[label].invoke();self.root.update()
            self.assertEqual((window.result.settings.ppm_min,window.result.settings.ppm_max),bounds)
            self.assertEqual(window.plot.axis.get_xlim(),tuple(reversed(bounds)))
            self.assertEqual(window.metrics['requested_range_ppm'],list(bounds))
            self.assertAlmostEqual(np.nanmax(np.abs(window.result.a)),1)
            np.testing.assert_allclose([row['ratio'] for row in window.ratios],ratios)
        window.fields['clow'].set('10');window.fields['chigh'].set('180')
        buttons['Custom region'].invoke();self.root.update()
        self.assertEqual(window.plot.axis.get_xlim(),(180,10))
        window.reprocess();self.root.update()
        dialog=next(w for w in window.winfo_children() if isinstance(w,PreprocessingDialog))
        self.assertEqual(float(dialog.vars['ppm_min'].get()),10)
        self.assertEqual(float(dialog.vars['ppm_max'].get()),180)
        dialog.destroy()
        before=window.result;window.fields['chigh'].set('0')
        with patch('labplotter.nmr_ui.messagebox.showerror') as error:
            buttons['Custom region'].invoke();self.assertTrue(error.called)
        self.assertIs(window.result,before)
        self.assertEqual(window.plot.axis.get_xlim(),(180,10))
        self.assertFalse(self.errors)

    def test_large_font_rows_and_square_clipboard_then_default_restore(self):
        font=tkfont.nametofont('TkDefaultFont');previous=font.cget('size')
        try:
            font.configure(size=18);nmr_tree_style(self.tab)
            self.tab.add_spectra([self.a,self.b]);self.root.update()
            height=self.tab.tree.bbox(self.a.uid)[3]
            self.assertGreaterEqual(height,font.metrics('linespace')+8)
            self.tab.tree.selection_set(self.a.uid);self.tab.save();self.tab.open_library();self.root.update()
            self.assertGreaterEqual(self.tab.library_window.tree.bbox(self.a.uid)[3],font.metrics('linespace')+8)
        finally:
            font.configure(size=previous);nmr_tree_style(self.tab)
        plot=self.tab.plot
        plot.open_settings();self.root.update()
        plot.set_figure_ratio((1,1))
        self.root.after(160,self.root.quit);self.root.mainloop();self.root.update()
        widget=plot.canvas.get_tk_widget()
        self.assertEqual(widget.winfo_width(),widget.winfo_height())
        with patch('labplotter.ui.copy_png_to_clipboard') as copy,patch('labplotter.ui.messagebox.showinfo'):
            plot.copy_image()
            png=Image.open(BytesIO(copy.call_args.args[0]))
            self.assertEqual(png.width,png.height)
        plot.set_figure_ratio()
        self.root.after(160,self.root.quit);self.root.mainloop();self.root.update()
        self.assertIsNone(plot.options.figure_ratio)
        self.assertEqual(widget.winfo_width(),plot.canvas_host.winfo_width())
        self.assertEqual(widget.winfo_height(),plot.canvas_host.winfo_height())
        self.assertFalse(self.errors)


if __name__=='__main__':unittest.main()
