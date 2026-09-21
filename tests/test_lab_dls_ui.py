"""Desktop workflows, including a real mouse drag and clipboard-image capture."""
from io import BytesIO
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import font as tkfont, ttk
import unittest
from unittest.mock import patch

from matplotlib.backend_bases import MouseEvent, KeyEvent
import numpy as np
from PIL import Image

from labplotter.config import SettingsStore
from labplotter.lab_dls import parse_dls_text, distribution_statistics
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

    def test_measurement_checkboxes_live_averages_quick_controls_and_collapsed_overlay(self):
        tab=self.tab;p=self.b
        self.assertLess(tab.controls.winfo_rootx(),tab.plot.winfo_rootx())
        tab.tree.selection_set(p.uid);tab.register_overlay();self.settle()
        result=tab.results['selected'];overlay=tab.results['overlay']
        tree=overlay.tree
        self.assertEqual(tree.get_children(),(p.uid,))
        self.assertFalse(tree.item(p.uid,'open'))
        self.assertEqual(tree.set(p.uid,'expand'),'+')
        x,y,w,h=tree.bbox(p.uid,'expand')
        tree.event_generate('<Button-1>',x=x+w//2,y=y+h//2);self.settle()
        self.assertTrue(tree.item(p.uid,'open'))
        self.assertTrue(tree.bbox(tree.get_children(p.uid)[0]))
        hide=result.checks[('row-1','hidden')]
        self.assertTrue(hide.winfo_ismapped())
        hide.invoke();self.settle()
        self.assertTrue(p.measurements[0].hidden)
        self.assertEqual(len(tab.curves('selected')[0]),1)
        self.assertAlmostEqual(result.rows[0]['mean_radius'],73)
        result.checks[('row-2','excluded')].invoke();self.settle()
        self.assertEqual(result.rows[0]['included_count'],1)
        self.assertAlmostEqual(result.rows[0]['mean_radius'],82)
        self.assertAlmostEqual(distribution_statistics(tab.curves('overlay')[0][0][2])['mean_radius'],82)
        self.assertTrue(tree.item(p.uid,'open'))  # preserves expansion through recomputation
        tab.quick_controls['selected']['average'].invoke();self.settle()
        self.assertEqual(len(tab.curves('selected')[0]),1)
        self.assertEqual(len(tab.plot.axis.lines),2)
        self.assertEqual(len(tab.drags['selected'].artists),1)
        for key in ('selected','overlay'):
            for field in ('show_labels','show_lines'):
                before=getattr(tab.extensions[key].style,field)
                tab.quick_controls[key][field].invoke();self.settle()
                self.assertEqual(getattr(tab.extensions[key].style,field),not before)
            tab.drags[key].positions[p.uid+':mean']=(.2,.4)
            tab.quick_controls[key]['reset'].invoke();self.settle()
            self.assertFalse(tab.drags[key].positions)
        result.checks[('row-1','excluded')].invoke();self.settle()
        self.assertEqual(result.rows[0]['included_count'],0)
        self.assertIsNone(result.rows[0]['mean_radius'])
        self.assertEqual(tab.curves('overlay')[0],[])
        self.assertFalse(self.errors)

    def test_common_legend_click_unlock_move_corner_resize_toggle_and_clean_copy(self):
        # Noncompact pane is shared by FTIR, ssNMR, NanoDrop and TEM as well.
        from labplotter.ui import PlotPane
        from labplotter.plotting import PlotOptions, figure_png_bytes
        top=tk.Toplevel(self.root);top.geometry('950x660')
        def draw(ax,opts):
            for i in range(6):ax.plot([1,2,3],[i,i+1,i+2],label=f'Particle {i+1}')
        pane=PlotPane(top,draw,PlotOptions(),export_current_view=True)
        pane.pack(fill='both',expand=True);pane.refresh();self.settle()
        def mouse(name,x,y):
            pane.canvas.callbacks.process(name,MouseEvent(name,pane.canvas,x,y,button=1))
        def drag(x,y,dx,dy):
            mouse('button_press_event',x,y);mouse('motion_notify_event',x+dx,y+dy);mouse('button_release_event',x+dx,y+dy);self.settle()
        editor=pane.legend_editor;before=editor.bounds().frozen()
        drag(before.x0+20,before.y0+15,40,20)
        self.assertTrue(editor.active)
        np.testing.assert_allclose(editor.bounds().bounds,before.bounds) # first drag only unlocks
        drag(before.x0+20,before.y0+15,35,-20)
        self.assertAlmostEqual(editor.bounds().x0,before.x0+35,delta=2)
        self.assertAlmostEqual(editor.bounds().y0,before.y0-20,delta=2)
        before=editor.bounds().frozen()
        # Widen the upper-right corner: reflow six vertical entries into columns.
        drag(before.x1,before.y1,350,-before.height/2)
        self.assertGreater(editor.bounds().width,before.width+200)
        self.assertGreater(pane._legend_artist._ncols,1)
        self.assertLess(editor.bounds().height,before.height)
        frame=editor.bounds().frozen()
        for label in pane._legend_artist.get_texts():
            box=label.get_window_extent(pane.canvas.get_renderer())
            self.assertTrue(frame.padded(2).contains(box.x0,box.y0))
            self.assertTrue(frame.padded(2).contains(box.x1,box.y1))
        geometry=(pane.legend_position,pane.legend_size)
        pane.axis.set_xlim(1.2,2.5)
        pane.toolbar.legend_button.invoke();self.settle()
        self.assertIsNone(pane.axis.get_legend())
        self.assertEqual(pane.axis.get_xlim(),(1.2,2.5))
        pane.toolbar.legend_button.invoke();self.settle()
        # Axes/display transforms can round-trip with a few ULPs of error.
        # 1e-12 axes units is far below a pixel, while still catching any movement.
        np.testing.assert_allclose((pane.legend_position,pane.legend_size),geometry,rtol=0,atol=1e-12)
        bbox=editor.bounds();mouse('button_press_event',bbox.x0+20,bbox.y0+15);mouse('button_release_event',bbox.x0+20,bbox.y0+15)
        self.settle();self.assertEqual(len(editor.decorations),5)
        active_png=figure_png_bytes(pane.figure,dpi=130)
        # Toolbar savefig and Copy graph must both omit the blue edit handles.
        direct=BytesIO();pane.figure.savefig(direct,format='png',dpi=130)
        pane.canvas.callbacks.process('key_press_event',KeyEvent('key_press_event',pane.canvas,key='escape'))
        self.assertFalse(editor.active)
        clean_png=figure_png_bytes(pane.figure,dpi=130)
        for data in (active_png,direct.getvalue()):
            with Image.open(BytesIO(data)) as edited,Image.open(BytesIO(clean_png)) as clean:
                np.testing.assert_array_equal(np.asarray(edited),np.asarray(clean))
        pane.refresh();self.settle()
        np.testing.assert_allclose((pane.legend_position,pane.legend_size),geometry,rtol=0,atol=1e-12)
        pane.restore_defaults();pane.refresh();self.settle()
        self.assertIsNone(pane.legend_size);self.assertIsNone(pane.legend_position)
        top.destroy();self.assertFalse(self.errors)
