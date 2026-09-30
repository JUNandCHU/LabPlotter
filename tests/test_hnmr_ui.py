"""Real Tk flows, including confirmation, persistence, stale results and sizing."""
from dataclasses import replace
import tempfile
from pathlib import Path
import tkinter as tk
from tkinter import ttk, font as tkfont
from unittest.mock import patch
import unittest
import numpy as np
from labplotter.hnmr import common_settings, prepare_spectra, preview_spectrum, quantify, QuantSettings
from labplotter.hnmr_library import HNMRLibrary,HNMRParameterLibrary
from labplotter.hnmr_ui import HNMRTab,HPreprocessingDialog,HDecompositionDialog,HQualityDialog,QuantDialog,ParameterWindow,NMRWorkspace
from labplotter.nmr_ui import nmr_tree_style
from test_hnmr import fixture


class HNMRDesktopTests(unittest.TestCase):
    def setUp(self):
        try:self.root=tk.Tk()
        except tk.TclError:self.skipTest('Tk display unavailable')
        self.temp=tempfile.TemporaryDirectory();path=Path(self.temp.name)
        self.root.geometry('1250x900');self.errors=[]
        self.root.report_callback_exception=lambda *args:self.errors.append(args)
        self.tab=HNMRTab(self.root,HNMRLibrary(path/'h.sqlite3'),HNMRParameterLibrary(path/'params.json'))
        self.tab.pack(fill='both',expand=True)
        self.a,self.b=fixture('PDA-C6',20),fixture()
        self.tab.add_spectra([self.b,self.a]);self.root.update()

    def tearDown(self):
        if hasattr(self,'root'):self.root.destroy()
        if hasattr(self,'temp'):self.temp.cleanup()

    def test_prepare_confirm_calculate_and_correction_invalidates(self):
        d=HPreprocessingDialog(self.tab);d.get_condition();d.apply();self.root.update()
        self.assertTrue(self.a.processing['prepared']);self.assertEqual(self.a.processing['group_id'],self.b.processing['group_id'])
        d.destroy()
        q=QuantDialog(self.tab,self.a);self.root.update()
        self.assertFalse(self.tab.results)  # Opening the dialog never calculates.
        q.fields['standard_area'].set('100');q.fields['standard_mmol_h'].set('.001')
        q.calculate();self.root.update()
        self.assertIn(self.a.uid,self.tab.results)
        self.assertGreater(len(self.tab.result_tree.get_children()),10)
        self.assertEqual(len(self.tab.plot.axis.lines),5)
        self.tab.baseline.set(False);self.tab.correction_changed();self.root.update()
        self.assertFalse(self.tab.results);self.assertFalse(self.a.processing['prepared'])
        self.assertEqual(len(self.tab.plot.axis.lines),1);self.assertFalse(self.errors)

    def test_reference_core_switch_updates_capacity_and_library_load(self):
        c=fixture('ANP');self.tab.add_spectra([c]);self.tab.tree.selection_set(self.a.uid)
        q=QuantDialog(self.tab,self.a);q.fields['core'].set('ANP');self.root.update()
        self.assertAlmostEqual(float(q.fields['capacity_umol_mg'].get()),.1619)
        self.assertEqual(self.tab.spectra[q.reference.current()].uid,c.uid);q.destroy()
        prepare_spectra([self.a,self.b],common_settings([self.a,self.b]))
        self.tab.tree.selection_set(self.a.uid,self.b.uid);self.tab.save();self.tab.remove()
        self.tab.open_library();lib=self.tab.library_window;self.root.update()
        self.assertEqual(len(lib.tree.get_children()),2)
        lib.tree.selection_set(self.a.uid,self.b.uid);lib.load();self.root.update()
        self.assertEqual(len(self.tab.spectra),3)
        saved=next(s for s in self.tab.spectra if s.uid==self.a.uid)
        np.testing.assert_array_equal(saved.imag,self.a.imag);self.assertTrue(saved.processing['prepared'])
        self.assertFalse(self.errors)

    def test_shared_curve_color_ratio_and_export(self):
        prepare_spectra([self.a,self.b],common_settings([self.a,self.b]))
        self.tab.results[self.a.uid]=quantify(self.a,self.b,QuantSettings())
        self.tab._refresh();self.root.update();self.tab.plot.open_settings();self.root.update()
        editor=self.tab.plot.settings_window.curve_editor
        key=self.a.uid+':aliphatic';editor.variables[key].set('#123ABC');self.root.update()
        self.assertEqual(next(line for line in self.tab.plot.axis.lines if line.get_label()=='Aliphatic component').get_color(),'#123ABC')
        self.assertEqual(self.a.metadata['curve_colors']['aliphatic'],'#123ABC')
        from labplotter.plotting import figure_png_bytes
        from PIL import Image
        from io import BytesIO
        image=Image.open(BytesIO(figure_png_bytes(self.tab.plot.figure)))
        self.assertGreater(image.width,500)
        self.assertFalse(self.errors)

    def test_large_font_rows_and_scrollable_dialog_forms(self):
        font=tkfont.nametofont('TkDefaultFont');old=font.cget('size');font.configure(size=20)
        try:
            nmr_tree_style(self.root);self.root.update()
            height=int(ttk.Style(self.root).lookup('SSNMR.Treeview','rowheight'))
            self.assertGreaterEqual(height,font.metrics('linespace')+12)
            q=QuantDialog(self.tab,self.a);q.geometry('1000x700');self.root.update()
            self.assertTrue(q.forms[0].canvas.cget('yscrollcommand'))
            self.assertGreater(q.forms[0].canvas.bbox('all')[3],q.forms[0].canvas.winfo_height())
            buttons=[w for w in q.winfo_children() if isinstance(w,ttk.Button)]
            self.assertTrue(buttons[-1].winfo_ismapped())
            self.assertLessEqual(buttons[-1].winfo_y()+buttons[-1].winfo_height(),q.winfo_height())
            q.destroy()
        finally:font.configure(size=old);nmr_tree_style(self.root)
        self.assertFalse(self.errors)

    def test_fit_preview_styles_export_and_library_roundtrip(self):
        d=HDecompositionDialog(self.tab,self.a);self.root.update();d.preview();self.root.update()
        self.assertIsNotNone(d.fit);self.assertNotIn('decomposition',self.a.metadata)
        d.apply();self.root.update()
        self.assertEqual(len(self.tab.plot.axis.lines),5)
        self.assertTrue(self.tab.plot.export_current_view)
        self.tab.plot.open_settings();self.root.update()
        ext=self.tab.plot.settings_extension
        ext.vars['aliphatic']['width'].set('4.25');ext.vars['aliphatic']['line_style'].set('-.');ext.apply()
        self.root.update()
        line=next(line for line in self.tab.plot.axis.lines if line.get_label()=='Aliphatic component')
        self.assertEqual(line.get_linewidth(),4.25);self.assertEqual(line.get_linestyle(),'-.')
        self.tab.show_components.set(False);self.tab.components_changed();self.root.update()
        self.assertEqual(len(self.tab.plot.axis.lines),1)
        captured=[]
        self.tab.plot._with_annotation_visibility(True,lambda:captured.append(len(self.tab.plot.axis.lines)))
        self.assertEqual(captured,[1])
        self.tab.save();saved=self.tab.library.load(self.a.uid)
        self.assertEqual(saved.metadata['decomposition_styles']['aliphatic']['width'],4.25)
        self.assertIn('decomposition',saved.metadata)
        self.tab.show_components.set(True);self.tab.components_changed();self.root.update()
        captured=[]
        self.tab.plot._with_annotation_visibility(False,lambda:captured.append([v.get_visible() for v in self.tab.plot.overlay_artists]))
        self.assertEqual(captured,[[True]*4])
        self.assertFalse(self.errors)

    def test_parameters_persist_and_lys_stays_unconfigured(self):
        window=ParameterWindow(self.tab);self.root.update()
        doc=window.document;doc['cores'][0]['capacity']=.27;window.commit(doc);window.destroy()
        self.assertEqual(self.tab.parameters.load()['cores'][0]['capacity'],.27)
        self.assertIsNone(self.tab.parameters.load()['ligands'][-1]['effective_h'])
        self.assertFalse(self.errors)

    def test_sideband_qc_full_view_styles_and_library_preserve_orders(self):
        from test_hnmr_sidebands import mas_fixture
        from labplotter.hnmr_decomposition import decomposition_defaults,decompose
        s=mas_fixture();prepare_spectra([s],replace(common_settings([s]),phase=False,baseline=False))
        settings=replace(decomposition_defaults(s),line_shape='gaussian',sideband_spacing=55,refine_spacing=False,fit_sideband_width=False)
        fit=decompose(preview_spectrum(s),settings)
        s.metadata.update(decomposition=fit.record(),decomposition_settings=fit.audit['settings'])
        self.tab.add_spectra([s]);self.tab.full_view();self.root.update()
        self.assertGreater(max(self.tab.plot.axis.get_xlim()),150)
        self.assertEqual(len(self.tab.plot.axis.lines),5)
        d=HQualityDialog(self.tab,s);self.root.update()
        self.assertEqual(len(d.tree.get_children()),6)
        self.assertEqual(len(d.plot.axis.lines),5)
        self.assertEqual(len(d.plot.axis._labplotter_color_series),4)
        self.assertTrue(d.plot.export_current_view)
        d.destroy();self.tab.save();loaded=self.tab.library.load(s.uid)
        self.assertEqual(len(loaded.metadata['decomposition']['lines']),10)
        self.tab.set_view(-10,20);self.root.update()
        self.assertEqual(loaded.processing['group_id'],s.processing['group_id'])
        self.assertFalse(self.errors)


if __name__=='__main__':unittest.main()
