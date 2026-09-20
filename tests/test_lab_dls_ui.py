"""Desktop workflows, including a real mouse drag and clipboard-image capture."""
from io import BytesIO
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import font as tkfont, ttk
import unittest
from unittest.mock import patch

from matplotlib.backend_bases import MouseEvent
import numpy as np
from PIL import Image

from labplotter.config import SettingsStore
from labplotter.lab_dls import parse_dls_text
from labplotter.lab_dls_library import DLSLibrary
from labplotter.lab_dls_ui import LabDLSTab


class LabDLSDesktopTests(unittest.TestCase):
    def setUp(self):
        try:self.root=tk.Tk()
        except tk.TclError:self.skipTest('Tk display is unavailable')
        self.root.geometry('1450x900')
        self.temp=tempfile.TemporaryDirectory()
        self.errors=[]
        self.root.report_callback_exception=lambda *args:self.errors.append(args)
        self.tab=LabDLSTab(self.root,DLSLibrary(Path(self.temp.name)/'dls.sqlite3'),SettingsStore(Path(self.temp.name)/'settings.json'))
        self.tab.pack(fill='both',expand=True)
        text='Radius (nm),Meas 1,Meas 2\n1,0,0\n10,20,40\n100,80,60\n1000,0,0\n'
        self.a,self.b=[parse_dls_text(text,name+'.csv') for name in ('Particle A','Particle B')]
        self.tab.add_particles([self.a,self.b]);self.settle()

    def settle(self):
        self.root.update();self.root.after(140,self.root.quit);self.root.mainloop();self.root.update()

    def tearDown(self):
        if hasattr(self,'root'):self.root.destroy()
        if hasattr(self,'temp'):self.temp.cleanup()

    def test_explicit_overlay_library_and_statistics(self):
        tab=self.tab
        self.assertEqual(len(tab.plot.axis.lines),4)  # 2 raw curves and 2 mean lines
        self.assertEqual(len(tab.plot.axis.texts),2)
        self.assertEqual(len(tab.panes['overlay'].axis.lines),0)
        self.assertEqual(len(tab.results['selected'].rows),3)
        tab.tree.selection_set(self.a.uid,self.b.uid);tab.register_overlay();self.settle()
        self.assertEqual(len(tab.panes['overlay'].axis.lines),2)
        self.assertEqual(len(tab.panes['overlay'].axis.texts),0)
        self.assertEqual(len(tab.results['overlay'].rows),8)
        tab.all_measurements.set(True);tab.refresh_overlay()
        self.assertEqual(len(tab.panes['overlay'].axis.lines),4)
        self.assertEqual(len(tab.results['overlay'].rows),6)
        tab.save();tab.open_library();self.settle()
        self.assertEqual(len(tab.library_window.tree.get_children()),2)
        tab.remove();self.assertEqual(len(tab.particles),0);self.assertEqual(tab.overlay_ids,[])
        tab.library_window.tree.selection_set(self.a.uid,self.b.uid);tab.library_window.load();self.settle()
        self.assertEqual(len(tab.particles),2);self.assertEqual(tab.overlay_ids,[])
        tab.tree.selection_set(self.a.uid,self.b.uid);tab.register_overlay()
        tab.overlay_tree.selection_set(self.a.uid);tab.remove_overlay()
        self.assertEqual(tab.overlay_ids,[self.b.uid]);self.assertEqual(len(tab.particles),2)
        tab.fit_y('selected');self.assertGreater(tab.plot.axis.get_ylim()[1],80)
        self.assertFalse(self.errors)

    def test_label_drag_refresh_copy_and_settings(self):
        tab=self.tab;pane=tab.plot;drag=tab.drags['selected']
        key,artist=next(iter(drag.artists.items()))
        pane.canvas.draw()
        original=np.array(artist.get_position())
        bbox=artist.get_window_extent(pane.canvas.get_renderer())
        px,py=bbox.x0+bbox.width/2,bbox.y0+bbox.height/2
        for name,x,y in (('button_press_event',px,py),('motion_notify_event',px-40,py-35),('button_release_event',px-40,py-35)):
            pane.canvas.callbacks.process(name,MouseEvent(name,pane.canvas,x,y,button=1))
        self.settle()
        changed=drag.positions[key]
        self.assertLess(changed[0],original[0]);self.assertLess(changed[1],original[1])
        pane.refresh();self.settle()
        self.assertEqual(drag.artists[key].get_position(),changed)
        self.assertEqual(tuple(tab.settings.get('lab_dls_positions_selected')[key]),changed)
        before=BytesIO();pane.figure.savefig(before,format='png',dpi=300,bbox_inches=None)
        with patch('labplotter.ui.copy_png_to_clipboard') as clipboard,patch('labplotter.ui.messagebox.showinfo'):
            pane.copy_image(False)
        # Same frame and visible labels as a direct save of the current canvas.
        with Image.open(BytesIO(clipboard.call_args.args[0])) as copied,Image.open(before) as visible:
            np.testing.assert_array_equal(np.asarray(copied),np.asarray(visible))
        pane.open_settings();self.settle()
        extension=tab.extensions['selected']
        extension.vars['show_lines'].set(False);extension.vars['show_labels'].set(False)
        extension.apply();self.settle()
        self.assertEqual(len(pane.axis.lines),2);self.assertEqual(len(pane.axis.texts),0)
        pane.settings_window.restore_defaults();self.settle()
        self.assertEqual(len(pane.axis.lines),4);self.assertFalse(drag.positions)
        self.assertFalse(self.errors)

    def test_large_font_rows_and_results_stay_below_plots(self):
        font=tkfont.nametofont('TkDefaultFont');previous=font.actual('size')
        try:
            font.configure(size=19)
            self.tab.open_library()
            from labplotter.lab_dls_ui import dls_tree_style
            dls_tree_style(self.root);self.settle()
            style=ttk.Style(self.root)
            self.assertGreaterEqual(int(style.lookup('LabDLS.Treeview','rowheight')),font.metrics('linespace')+12)
            tree=self.tab.tree
            height=tree.bbox(self.a.uid)[3]
            self.assertGreaterEqual(height,font.metrics('linespace')+12)
            for key,pane in self.tab.panes.items():
                graph=pane.canvas.get_tk_widget();results=self.tab.results[key]
                self.assertGreaterEqual(results.winfo_rooty(),graph.winfo_rooty()+graph.winfo_height())
        finally:font.configure(size=previous)
        self.assertFalse(self.errors)
