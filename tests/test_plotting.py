from io import BytesIO
import re
import unittest
import xml.etree.ElementTree as ET
import numpy as np
from PIL import Image
from labplotter.models import Spectrum
from labplotter.plotting import PlotOptions, SERIES_PALETTE, figure_png_bytes, save_plot_figure
from labplotter.web import spectra_figure, figure_svg_bytes, zetasizer_summary_figure


class PlotGeometryTests(unittest.TestCase):
    def test_exact_figure_ratio_survives_png_svg_pdf_and_repeated_export(self):
        spectrum=Spectrum('A long legend',np.arange(5.),np.array([1.,2,4,3,2]))
        for ratio in ((1,1),(4,3)):
            figure=spectra_figure([spectrum],PlotOptions('Chemical shift','ppm','Intensity','a.u.',figure_ratio=ratio))
            original=figure.get_size_inches().copy()
            png=Image.open(BytesIO(figure_png_bytes(figure,dpi=100)))
            self.assertLessEqual(abs(png.width*ratio[1]-png.height*ratio[0]),4)
            svg=ET.fromstring(figure_svg_bytes(figure))
            self.assertAlmostEqual(float(svg.attrib['width'][:-2])/float(svg.attrib['height'][:-2]),ratio[0]/ratio[1],places=5)
            pdf=BytesIO();save_plot_figure(figure,pdf,format='pdf')
            match=re.search(rb'/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)',pdf.getvalue())
            self.assertIsNotNone(match)
            self.assertAlmostEqual(float(match[1])/float(match[2]),ratio[0]/ratio[1],places=5)
            np.testing.assert_array_equal(figure.get_size_inches(),original)
            self.assertTrue(figure.axes[0].get_in_layout())
            second=Image.open(BytesIO(figure_png_bytes(figure,dpi=100)))
            self.assertEqual(second.size,png.size)

    def test_shared_rgb_order_for_curves_and_bars_with_manual_override(self):
        expected=['#000000','#C00000','#002060','#A49F9F','#006C31','#401F68','#B87018']
        spectra=[Spectrum(str(i),np.arange(4.),np.arange(4.)+i) for i in range(7)]
        self.assertEqual(list(SERIES_PALETTE[:7]),expected)
        figure=spectra_figure(spectra,PlotOptions())
        self.assertEqual([line.get_color() for line in figure.axes[0].lines],expected)
        override=spectra_figure(spectra,PlotOptions(),colors={spectra[1].uid:'#123456'})
        self.assertEqual(override.axes[0].lines[1].get_color(),'#123456')
        rows=[{'Particle':str(i),'Mean peak':i+1,'SD':0} for i in range(7)]
        from matplotlib.colors import to_hex
        bars=zetasizer_summary_figure(rows,PlotOptions())
        self.assertEqual([to_hex(p.get_facecolor()).upper() for p in bars.axes[0].patches],expected)
