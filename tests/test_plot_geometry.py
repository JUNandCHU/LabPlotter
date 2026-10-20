"""Publication appearance, equal sample frames and unclipped current-view export."""
from dataclasses import fields
from io import BytesIO
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from labplotter.plotting import (
    PlotOptions, apply_origin_style, figure_png_bytes, layout_plot_group,
    save_plot_figure,
)


def options():
    return PlotOptions('Chemical shift', 'ppm', 'Intensity', 'a.u.',
                       font_family='DejaVu Sans', reverse_x=True, legend=False,
                       x_min=-100, x_max=100, figure_ratio=(2, 1))


def samples():
    peers = []
    x = np.linspace(-100, 100, 501)
    for peak in (7e7, 1e8, 1.5e8):
        aromatic = peak / (1 + ((x - 5.3) / 4.8)**2)
        aliphatic = .17 * peak * np.exp(-(x / 3)**2)
        def draw(axis, opts, a=aromatic, b=aliphatic):
            for y, color in ((a, '#A49F9F'), (b, '#002060'), (a+b, '#C00000')):
                axis.plot(x, y, color=color, linewidth=opts.line_width)
            axis._labplotter_y_notation = 'axis_label'
        peers.append((peak, draw))
    return peers


def figure(size=(4.5, 2.25), dpi=150):
    fig = Figure(figsize=size, dpi=dpi)
    FigureCanvasAgg(fig)
    fig._labplotter_export_current_view = True
    return fig, fig.add_subplot(111)


class PublicationGeometryTests(unittest.TestCase):
    def test_legacy_defaults_and_single_sample_pixels(self):
        defaults = PlotOptions()
        self.assertEqual((defaults.font_family, defaults.font_size,
                          defaults.x_font_size, defaults.y_font_size), ('Arial', 12, 13, 13))
        self.assertEqual((defaults.line_width, defaults.spine_width,
                          defaults.tick_width, defaults.tick_length), (2, 1.5, 1.5, 6))
        self.assertNotIn('plot_margins', {field.name for field in fields(PlotOptions)})
        self.assertNotIn('lock_plot_area', {field.name for field in fields(PlotOptions)})
        opts, peer = options(), samples()[0]
        legacy, old_axis = figure((6, 3))
        peer[1](old_axis, opts)
        apply_origin_style(legacy, old_axis, opts)
        legacy.tight_layout()
        legacy.tight_layout()  # old refresh, followed by its resize callback
        buffer = BytesIO()
        legacy.savefig(buffer, format='png', dpi=300, bbox_inches=None)
        restored, axis = figure((6, 3))
        peer[1](axis, opts)
        apply_origin_style(restored, axis, opts)
        layout_plot_group(restored, opts, [peer])
        np.testing.assert_array_equal(
            np.asarray(Image.open(buffer)),
            np.asarray(Image.open(BytesIO(figure_png_bytes(restored)))),
        )

    def test_sample_frames_are_identical_regardless_of_selection_order(self):
        peers, opts = samples(), options()
        expected = None
        for order in (peers, peers[::-1]):
            fig, axis = figure()
            for _, draw in order:
                axis.clear()
                draw(axis, opts)
                apply_origin_style(fig, axis, opts)
                layout_plot_group(fig, opts, order)
                if expected is None:
                    expected = axis.get_position().bounds
                np.testing.assert_allclose(axis.get_position().bounds, expected, atol=1e-10)
                self.assertEqual([line.get_linewidth() for line in axis.lines], [2, 2, 2])
                self.assertEqual(axis.yaxis.label.get_fontsize(), 13)
                self.assertTrue(axis.yaxis._autolabelpos)

    def test_preview_axis_titles_fit_at_different_sizes_and_dpi(self):
        peers, opts = samples(), options()
        for size, dpi in (((4.5, 2.25), 100), ((4.5, 2.25), 200), ((5.5, 2.75), 150)):
            fig, axis = figure(size, dpi)
            for _, draw in peers:
                axis.clear()
                draw(axis, opts)
                apply_origin_style(fig, axis, opts)
                layout_plot_group(fig, opts, peers)
                fig.canvas.draw()
                for label in (axis.xaxis.label, axis.yaxis.label):
                    box = label.get_window_extent(fig.canvas.get_renderer())
                    self.assertGreaterEqual(box.x0, 0)
                    self.assertGreaterEqual(box.y0, 0)
                    self.assertLessEqual(box.x1, fig.bbox.width)
                    self.assertLessEqual(box.y1, fig.bbox.height)
            fig.set_size_inches(7, 3.5)
            layout_plot_group(fig, opts, peers)
            self.assertAlmostEqual(axis.yaxis.label.get_position()[1], .5)

    def test_copy_and_svg_keep_old_physical_size_zoom_and_visible_curves(self):
        fig, axis = figure()
        opts, peers = options(), samples()
        peers[0][1](axis, opts)
        apply_origin_style(fig, axis, opts)
        layout_plot_group(fig, opts, peers)
        axis.set_xlim(80, -80)
        original = (axis.get_position().bounds, axis.get_xticks().copy(),
                    [line.get_ydata().copy() for line in axis.lines])
        png = Image.open(BytesIO(figure_png_bytes(fig, dpi=300)))
        self.assertEqual(png.size, (1350, 675))
        svg = BytesIO()
        save_plot_figure(fig, svg, format='svg')
        root = ET.fromstring(svg.getvalue())
        self.assertEqual((root.attrib['width'], root.attrib['height']), ('324pt', '162pt'))
        self.assertEqual(axis.get_xlim(), (80, -80))
        np.testing.assert_array_equal(fig.get_size_inches(), [4.5, 2.25])
        np.testing.assert_array_equal(axis.get_position().bounds, original[0])
        np.testing.assert_array_equal(axis.get_xticks(), original[1])
        for line, values in zip(axis.lines, original[2]):
            np.testing.assert_array_equal(line.get_ydata(), values)

    def test_shared_layout_cache_tracks_fonts_and_loaded_samples(self):
        fig, axis = figure((6, 3))
        peers, opts = samples(), options()
        peers[0][1](axis, opts)
        apply_origin_style(fig, axis, opts)
        layout_plot_group(fig, opts, peers)
        cached = fig._labplotter_layout_cache
        layout_plot_group(fig, opts, peers)
        self.assertIs(fig._labplotter_layout_cache, cached)
        opts.tick_font_size = 14
        apply_origin_style(fig, axis, opts)
        layout_plot_group(fig, opts, peers)
        self.assertNotEqual(fig._labplotter_layout_cache[0], cached[0])
        cached = fig._labplotter_layout_cache
        layout_plot_group(fig, opts, peers[:2])
        self.assertNotEqual(fig._labplotter_layout_cache[0], cached[0])
        layout_plot_group(fig, opts, peers[:1])
        self.assertIsNone(fig._labplotter_shared_layout)

    def test_hnmr_loaded_sample_measurement_does_not_refit_or_change_values(self):
        from labplotter.hnmr import HNMRSpectrum, ProcessedH
        from labplotter.hnmr_ui import HNMRTab
        x = np.linspace(-100, 100, 501)
        spectra = [HNMRSpectrum(name, x.copy(), peak/(1+(x/5)**2), np.zeros_like(x))
                   for name, peak in (('ANP', 7e7), ('ANP-C18', 1e8))]
        original = [s.real.copy() for s in spectra]
        processed = {s.uid: ProcessedH(s.x, s.real, s.imag, np.zeros_like(x), {}) for s in spectra}
        workspace = SimpleNamespace(spectra=spectra, results={}, fits={},
                                    processed=lambda s: processed[s.uid],
                                    show_imag=SimpleNamespace(get=lambda: False))
        workspace.fitted = lambda s: HNMRTab.fitted(workspace, s)
        with patch('labplotter.hnmr_ui.decompose', side_effect=AssertionError('layout must not fit')):
            peers = HNMRTab._layout_peers(workspace)
            fig, axis = figure((6, 3))
            opts = options()
            peers[0][1](axis, opts)
            apply_origin_style(fig, axis, opts)
            layout_plot_group(fig, opts, peers)
        self.assertEqual(len(peers), 2)
        for sample, values in zip(spectra, original):
            np.testing.assert_array_equal(sample.real, values)
        self.assertEqual(workspace.fits, {})

    def test_copy_flushes_pending_preview_resize(self):
        from labplotter.ui import PlotPane
        fig, axis = figure((8.5, 4.25), 100)
        opts = options()
        samples()[0][1](axis, opts)
        apply_origin_style(fig, axis, opts)
        pane = SimpleNamespace(_layout_job='pending', update_idletasks=Mock(),
                               after_cancel=Mock(), export_current_view=True, canvas=fig.canvas)
        def fit():
            pane._layout_job = None
            fig.set_size_inches(4.5, 2.25)
            layout_plot_group(fig, opts, samples())
        pane._fit_figure = fit
        data = PlotPane._with_annotation_visibility(pane, False, lambda: figure_png_bytes(fig, dpi=100))
        self.assertEqual(Image.open(BytesIO(data)).size, (450, 225))
        pane.after_cancel.assert_called_once_with('pending')


if __name__ == '__main__':
    unittest.main()
