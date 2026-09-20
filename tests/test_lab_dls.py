from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import tempfile
from pathlib import Path
import unittest

import numpy as np
from PIL import Image

from labplotter.lab_dls import (DLSMeasurement, DLSParticle, parse_dls_text, parse_dls_csv,
                               distribution_statistics, measurement_average, representative_curve, statistics_rows)
from labplotter.lab_dls_library import DLSLibrary, export_dls_library, import_dls_library
from labplotter.lab_dls_plot import DLSStyle, dls_figure, dls_plot_options, plot_series
from labplotter.plotting import SERIES_PALETTE, figure_png_bytes
from labplotter.parsers import detect_builtin_kind


SPARSE_CSV = "Radius (nm),Meas 2,Meas 4\n1,0,\n2,,0\n10,25,\n20,,50\n100,75,\n200,,50\n1000,0,\n2000,,0\n"


def fixture(name="Particle"):
    return parse_dls_text(SPARSE_CSV, name+".csv")


class LabDLSCoreTests(unittest.TestCase):
    def test_sparse_csv_keeps_measurement_coordinates_and_filename(self):
        p = parse_dls_text('\ufeff'+SPARSE_CSV, 'PDA_C6.Graph_raw.csv')
        self.assertEqual(p.name, 'PDA_C6.Graph_raw')
        self.assertEqual([m.name for m in p.measurements], ['Meas 2','Meas 4'])
        np.testing.assert_array_equal(p.measurements[0].radius, [1,10,100,1000])
        np.testing.assert_array_equal(p.measurements[1].radius, [2,20,200,2000])
        np.testing.assert_array_equal(p.measurements[0].intensity, [0,25,75,0])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'PDA.csv';path.write_text(SPARSE_CSV)
            self.assertEqual(detect_builtin_kind(path),'Lab DLS')
            self.assertEqual(parse_dls_csv(path).name,'PDA')

    def test_bin_weighted_moments_and_arithmetic_replicate_average(self):
        p=fixture();a,b=p.measurements
        stats=distribution_statistics(a)
        self.assertAlmostEqual(stats['mean_radius'],77.5)
        self.assertAlmostEqual(stats['mean_diameter'],155)
        expected_sd=np.sqrt(.25*(10-77.5)**2+.75*(100-77.5)**2)
        self.assertAlmostEqual(stats['pd_percent'],100*expected_sd/77.5)
        avg=measurement_average(p)
        self.assertAlmostEqual(avg['mean_radius'],(77.5+110)/2)
        self.assertAlmostEqual(avg['pd_percent'],(stats['pd_percent']+100*90/110)/2)
        scaled=DLSMeasurement('scaled',a.radius,a.intensity*5)
        self.assertEqual(distribution_statistics(scaled),stats)
        zero=DLSMeasurement('zero',[1,2],[0,0]);p.measurements.append(zero)
        self.assertIsNone(distribution_statistics(zero)['pd_percent'])
        self.assertIsNone(measurement_average(p)['mean_radius'])

    def test_mean_uses_log_interpolation_without_mutating_raw_or_normalizing_peaks(self):
        p=fixture();before=deepcopy(p)
        mean=representative_curve(p)
        # Radius 10: Meas 2=25; Meas 4 interpolates between radius 2 and 20
        # in log radius (not in row order or linear radius).
        self.assertAlmostEqual(mean.radius[1],10)
        expected=(25+50*np.log10(10/2))/2
        self.assertAlmostEqual(mean.intensity[1],expected)
        for a,b in zip(p.measurements,before.measurements):
            np.testing.assert_array_equal(a.radius,b.radius);np.testing.assert_array_equal(a.intensity,b.intensity)
        p.measurements[1]=DLSMeasurement('Meas 4',p.measurements[0].radius,[0,50,150,0])
        np.testing.assert_array_equal(representative_curve(p).intensity,[0,37.5,112.5,0])
        self.assertEqual(len(statistics_rows(particles=[p],include_representative=True)),4)

    def test_bad_values_and_incomplete_coverage_are_explicit(self):
        for content in (SPARSE_CSV.replace('Radius (nm)','Diameter (nm)'),
                        SPARSE_CSV.replace('10,25,','10,-25,'),SPARSE_CSV.replace('10,25,','10,NaN,'),
                        SPARSE_CSV.replace('10,25,','0,25,'),SPARSE_CSV.replace('10,25,','10,bad,'),
                        'Radius (nm),Meas 1\n1,1\n1,2\n'):
            with self.subTest(content=content),self.assertRaises(ValueError):
                parse_dls_text(content,'bad.csv')
        p=fixture();p.measurements[1].intensity[0]=1
        with self.assertRaisesRegex(ValueError,'coverage'):
            representative_curve(p)
        curves,errors=plot_series([p],overlay=True)
        self.assertEqual(curves,[]);self.assertTrue(errors)
        self.assertEqual(len(plot_series([p],overlay=True,all_measurements=True)[0]),2)

    def test_library_roundtrip_order_upsert_delete_and_identity(self):
        a,b=fixture('same'),fixture('same')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'dls.sqlite3';lib=DLSLibrary(path)
            lib.save(a);lib.save(b);lib.move(b.uid,-1);lib.rename(a.uid,'renamed')
            self.assertEqual([r['uid'] for r in lib.entries()],[b.uid,a.uid])
            loaded=DLSLibrary(path).load(a.uid)
            self.assertEqual(loaded.name,'renamed')
            for left,right in zip(a.measurements,loaded.measurements):
                np.testing.assert_array_equal(left.radius,right.radius)
                np.testing.assert_array_equal(left.intensity,right.intensity)
            lib.save(loaded);self.assertEqual(len(lib.entries()),2)
            self.assertEqual([r['uid'] for r in lib.entries()],[b.uid,a.uid])
            lib.delete([a.uid]);self.assertEqual(lib.entries()[0]['uid'],b.uid)
            self.assertEqual(a.name,'same')
        restored=import_dls_library(export_dls_library([a,b]))
        self.assertEqual([p.uid for p in restored],[a.uid,b.uid])
        np.testing.assert_array_equal(restored[1].measurements[1].radius,b.measurements[1].radius)
        with self.assertRaises(ValueError):import_dls_library(export_dls_library([a,a]))

    def test_plot_pdf_limits_overlay_palette_and_exact_export_frame(self):
        particles=[fixture(str(i)) for i in range(7)]
        curves,_=plot_series(particles,overlay=True)
        self.assertEqual(len(curves),7)
        figure=dls_figure(curves,style=DLSStyle(show_lines=False,show_labels=False))
        axis=figure.axes[0]
        self.assertEqual(axis.get_xscale(),'log')
        self.assertEqual(axis.get_xlim(),(.01,1e6));self.assertEqual(axis.get_ylim(),(0,20))
        self.assertEqual([line.get_color() for line in axis.lines],list(SERIES_PALETTE[:7]))
        self.assertEqual(len(axis.texts),0)
        curves,_=plot_series(particles[:1]);options=dls_plot_options();options.figure_ratio=(1,1)
        key=curves[0][0]
        figure=dls_figure(curves,options,positions={key:(.35,.8)})
        texts=figure.axes[0].texts
        self.assertEqual(texts[0].get_position(),(.35,.8))
        np.testing.assert_array_equal(figure.axes[0].lines[0].get_xdata(),particles[0].measurements[0].radius)
        with Image.open(BytesIO(figure_png_bytes(figure,dpi=100))) as img:
            self.assertEqual(img.size,(850,850))
        self.assertEqual(texts[0].get_position(),(.35,.8))


if __name__=='__main__':
    unittest.main()
