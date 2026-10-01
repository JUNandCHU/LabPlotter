import tempfile
import tkinter as tk
from pathlib import Path
import unittest
from unittest.mock import patch

from labplotter.config import SettingsStore
from labplotter.nta_ui import NTATab
from labplotter.nta_plot import PLOT_TYPES
from test_nta import pack, archive, members


class NTADesktopTests(unittest.TestCase):
    def setUp(self):
        try:self.root=tk.Tk()
        except tk.TclError:self.skipTest('Tk display unavailable')
        self.root.geometry('1450x950');self.temp=tempfile.TemporaryDirectory();self.errors=[]
        self.mock=patch('tkinter.messagebox.showerror',side_effect=lambda *a,**k:self.errors.append(a));self.mock.start()
        self.root.report_callback_exception=lambda *a:self.errors.append(a)
        self.tab=NTATab(self.root,SettingsStore(Path(self.temp.name)/'settings.json'));self.tab.pack(fill='both',expand=True)
        self.tab.accept_packs([pack()]);self.root.update()

    def tearDown(self):
        if hasattr(self,'root'):self.root.destroy()
        if hasattr(self,'mock'):self.mock.stop()
        if hasattr(self,'temp'):self.temp.cleanup()

    def test_modes_exclusion_inputs_settings_and_export(self):
        t=self.tab;p=t.selected()[0]
        for kind in PLOT_TYPES:
            t.vars['kind'].set(kind);t.apply_controls();self.root.update();self.assertTrue(t.plot_rows,kind)
        t.vars['kind'].set('Size distribution');t.apply_controls()
        t.plot.vars['x_max'].set('600');t.plot.vars['tick_font_size'].set('17');t.plot.refresh()
        t.vars['kind'].set('Replicate summary');t.apply_controls();self.assertEqual(t.plot.vars['x_max'].get(),'')
        t.vars['kind'].set('Size distribution');t.apply_controls();self.assertEqual(t.plot.vars['x_max'].get(),'600')
        self.assertEqual(t.plot.vars['tick_font_size'].get(),'17')
        t.results.selection_set(f'{p.uid}:0');t.toggle_videos();self.assertEqual(p.excluded,{0})
        self.assertEqual(t.plot_rows[-1]['n'],1)
        t.dilution.set('1000');t.mass.set('10');t.apply_inputs();self.assertEqual(p.dilution,1000)
        for kind in ('plot','qc','summary'):
            path=Path(self.temp.name)/(kind+'.csv')
            with patch('tkinter.filedialog.asksaveasfilename',return_value=str(path)):t.export(kind)
            self.assertTrue(path.exists());self.assertGreater(path.stat().st_size,100)
        self.assertFalse(self.errors,self.errors)

    def test_background_import_failure_preserves_existing_data(self):
        t=self.tab;before=set(t.packs);d=members();del d['Example 0_AllTracks.csv']
        path=Path(self.temp.name)/'bad.zip';path.write_bytes(archive(d).getvalue());t.expected.set('2')
        reports=[];t.text_window=lambda title,text:reports.append(text);t.add_paths([path])
        def check():
            if t._busy:self.root.after(30,check)
            else:self.root.quit()
        self.root.after(30,check);self.root.after(8000,self.root.quit);self.root.mainloop()
        self.assertFalse(t._busy);self.assertEqual(set(t.packs),before)
        self.assertIn('Example 0_AllTracks.csv',reports[0]);self.assertFalse(self.errors)
