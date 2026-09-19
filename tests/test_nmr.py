from __future__ import annotations
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
import numpy as np
from scipy.stats import pearsonr
from labplotter.models import Spectrum
from labplotter.nmr import (ComparisonSettings, ComparisonResult, parse_topspin_ascii, default_settings,
    preprocess_pair, comparison_metrics, integral_ratios, region_integral, metrics_audit, integrals_audit, preprocessing_audit,
    comparison_region_metrics, regional_metrics_audit)
from labplotter.nmr_library import NMRLibrary, export_portable_library, import_portable_library
from labplotter.parsers import detect_builtin_kind
from labplotter.web import parse_uploaded_payload


class ASCIIImportTests(unittest.TestCase):
    def test_title_on_first_data_row_and_reversed_ppm_are_preserved(self):
        payload = b'13C title, 10, 1000, 10\n2, 20, 500, 5\n3, 30, 0, 0\n'
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'PDA.txt';path.write_bytes(payload)
            s=parse_topspin_ascii(path)
            self.assertEqual(s.name,'PDA');np.testing.assert_array_equal(s.x,[0,5,10]);np.testing.assert_array_equal(s.y,[30,20,10])
            self.assertEqual(detect_builtin_kind(path),'ssNMR')
            web=parse_uploaded_payload(path.name,payload,'ssNMR').spectra[0]
            np.testing.assert_array_equal(web.x,s.x);np.testing.assert_array_equal(web.y,s.y)
            path.write_text('4000,99\n3000,90\n2000,80\n')
            self.assertEqual(detect_builtin_kind(path),'FTIR')

    def test_corrupt_rows_and_duplicate_ppm_do_not_silently_disappear(self):
        for body in ('title,10,1000,10\n2,NaN,500,5\n3,30,0,0', 'title,10,1000,10\n2,20,500,10\n3,30,0,0', '1,1,1,1\n2,bad,2,2\n3,3,3,3'):
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'bad.txt';path.write_text(body)
                with self.assertRaises(ValueError):parse_topspin_ascii(path)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):parse_topspin_ascii(Path(folder)/'old.zip')


class ComparisonTests(unittest.TestCase):
    def test_regional_statistics_use_changed_bounds_and_one_normalization(self):
        x=np.arange(201.);a=x*x+1;b=a.copy();b[x<=50]*=2
        result=ComparisonResult(('A','B'),x,a,b,ComparisonSettings(),{})
        original_a,original_b=a.copy(),b.copy()
        values=comparison_region_metrics(result,(0,200))
        self.assertEqual(values['Aromatic region']['R2'],1)
        self.assertLess(values['Aliphatic region']['R2'],1)
        self.assertAlmostEqual(values['Aliphatic region']['r2'],1)
        changed=comparison_region_metrics(result,(90,160),(10,30),(90,160))
        m=changed['Aliphatic region'];mask=(x>=10)&(x<=30)
        self.assertEqual(m['requested_range_ppm'],[10,30])
        self.assertAlmostEqual(m['R2'],1-np.sum((a[mask]-b[mask])**2)/np.sum((a[mask]-a[mask].mean())**2))
        self.assertNotEqual(m['R2'],values['Aliphatic region']['R2'])
        self.assertAlmostEqual(m['r2'],pearsonr(a[mask],b[mask]).statistic**2)
        np.testing.assert_array_equal(a,original_a);np.testing.assert_array_equal(b,original_b)
        invalid=comparison_region_metrics(result,(0,200),(500,600))
        self.assertIn('error',invalid['Aliphatic region']);self.assertNotIn('error',invalid['Aromatic region'])
        audit=regional_metrics_audit(result,changed)
        for text in ('Comparison range','Aliphatic region','Aromatic region','SSE','centered_cross','sqrt(SST_A*SS_B)'):
            self.assertIn(text,audit)

    def options(self, **kwargs):
        return ComparisonSettings(baseline=False,align=False,gaussian_fwhm_ppm=0,normalization='None',**kwargs)

    def test_union_grid_does_not_extrapolate_and_metrics_only_use_overlap(self):
        a=Spectrum('A',np.arange(0.,11),np.arange(0.,11)**2)
        b=Spectrum('B',np.arange(5.,16),np.arange(5.,16)**2)
        r=preprocess_pair(a,b,self.options())
        self.assertEqual(r.x[0],0);self.assertEqual(r.x[-1],15)
        self.assertTrue(np.isnan(r.a[r.x>10]).all());self.assertTrue(np.isnan(r.b[r.x<5]).all())
        m=comparison_metrics(r,0,15)
        self.assertEqual(m['n'],6);self.assertEqual(m['R2'],1);self.assertAlmostEqual(m['r2'],1)
        with self.assertRaises(ValueError):region_integral(r.x,r.a,0,15)

    def test_direct_R2_and_pearson_r2_are_distinct_with_signed_r(self):
        x=np.arange(5.);a=np.array([0.,1,3,2,4]);b=2*a+3
        r=ComparisonResult(('A','B'),x,a,b,self.options(),{})
        m=comparison_metrics(r,0,4)
        self.assertAlmostEqual(m['R2'],1-np.sum((a-b)**2)/np.sum((a-a.mean())**2))
        self.assertLess(m['R2'],0);self.assertAlmostEqual(m['r2'],1)
        self.assertAlmostEqual(m['r'],pearsonr(a,b).statistic)
        r.b=-a;m=comparison_metrics(r,0,4)
        self.assertAlmostEqual(m['r'],-1);self.assertAlmostEqual(m['r2'],1)
        r.a=np.ones(5);m=comparison_metrics(r,0,4)
        self.assertTrue(np.isnan(m['R2']));self.assertTrue(np.isnan(m['r2']))

    def test_trapezoid_exact_boundaries_signed_area_and_undefined_denominator(self):
        x=np.arange(0.,201.,2);y=2*x+1
        area=region_integral(x,y,0.5,49.5)
        self.assertAlmostEqual(area['area'],49.5**2+49.5-(0.5**2+0.5))
        self.assertEqual(area['x'][0],0.5);self.assertEqual(area['x'][-1],49.5)
        self.assertAlmostEqual(sum(area['pieces']),area['area'])
        r=ComparisonResult(('A','B'),x,y,3*y,self.options(),{})
        ratios=integral_ratios(r)
        self.assertAlmostEqual(ratios[0]['ratio'],ratios[1]['ratio'])
        r.a=np.zeros_like(x);self.assertTrue(np.isnan(integral_ratios(r)[0]['ratio']))
        r.a=-y;self.assertLess(integral_ratios(r)[0]['aliphatic']['area'],0)

    def test_alignment_recovers_known_translation_and_preserves_inputs(self):
        x=np.linspace(-10,30,2001)
        def f(t):return np.exp(-((t-5)/1.1)**2)+0.7*np.exp(-((t-15)/2)**2)
        a=Spectrum('A',x,f(x));b=Spectrum('B',x,f(x-0.7));original=b.y.copy()
        s=self.options();s.align=True;s.max_shift_ppm=2
        r=preprocess_pair(a,b,s)
        self.assertAlmostEqual(r.log['alignment']['B_shift_added_ppm'],-0.7,places=3)
        self.assertGreater(comparison_metrics(r,-8,28)['R2'],0.9999)
        np.testing.assert_array_equal(b.y,original)

    def test_identical_default_processing_and_audits_are_reproducible(self):
        x=np.linspace(-50,250,3001);y=5+0.02*x+100*np.exp(-((x-130)/10)**2)
        a=Spectrum('A',x,y);b=Spectrum('B',x,3*y)
        r=preprocess_pair(a,b)
        m=comparison_metrics(r,0,200);ratios=integral_ratios(r)
        self.assertAlmostEqual(m['R2'],1,places=9);self.assertAlmostEqual(m['r2'],1,places=9)
        self.assertAlmostEqual(r.log['normalization']['divisors_A_B'][1]/r.log['normalization']['divisors_A_B'][0],3)
        self.assertIn('no fitted gain/offset',metrics_audit(r,m));self.assertIn('segment_area',integrals_audit(r,ratios))
        self.assertIn('A_baseline_corrected',preprocessing_audit(r));self.assertIn('Real-only ASCII',preprocessing_audit(r))
        self.assertEqual(len(r.stages['A_normalized']),len(x))

    def test_grid_and_parameter_validation(self):
        a=Spectrum('A',np.arange(5.),np.arange(5.))
        for s in (self.options(grid_step=1e-10), self.options(ppm_min=2,ppm_max=1), self.options(grid_step=float('nan'))):
            with self.assertRaises(ValueError):preprocess_pair(a,a,s)
        with self.assertRaises(ValueError):comparison_metrics(preprocess_pair(a,a,self.options()),2,2)


class NMRLibraryTests(unittest.TestCase):
    def test_save_reopen_rename_reorder_delete_and_portable_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'ssnmr.sqlite3';lib=NMRLibrary(path)
            a=Spectrum('A',np.arange(5.),np.arange(5.)**2);b=Spectrum('B',np.arange(5.),np.arange(5.)**3)
            lib.save(a);lib.save(b);lib.move(b.uid,-1);lib.rename(a.uid,'renamed')
            reopened=NMRLibrary(path);self.assertEqual([v['name'] for v in reopened.entries()],['B','renamed'])
            restored=reopened.load(a.uid);np.testing.assert_array_equal(restored.y,a.y)
            restored.y[0]=99;self.assertNotEqual(reopened.load(a.uid).y[0],99)
            lib.save(b);self.assertEqual(len(lib.entries()),2)
            portable=import_portable_library(export_portable_library([reopened.load(v['uid']) for v in reopened.entries()]))
            self.assertEqual([s.name for s in portable],['B','renamed'])
            np.testing.assert_array_equal(portable[1].y,a.y)
            lib.delete([a.uid]);self.assertEqual(len(lib.entries()),1)
            # Library deletion cannot mutate an already-loaded workspace spectrum.
            self.assertEqual(restored.name,'renamed')


if __name__=='__main__':unittest.main()
