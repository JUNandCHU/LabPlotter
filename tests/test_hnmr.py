"""Scientific invariants: complex preservation, shared processing, units and blanks."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from scipy.integrate import trapezoid
from labplotter.hnmr import (HNMRSpectrum, HNMRSettings, QuantSettings, automatic_phase,
    common_settings, default_parameters, infer_identity, integrate, parse_hnmr_text,
    parse_hnmr_ascii, prepare_spectra, preview_spectrum, process_hnmr, quantify, quant_defaults, result_csv)
from labplotter.hnmr_library import (HNMRLibrary, HNMRParameterLibrary, export_hnmr_library,
    import_hnmr_library, validate_parameters)


def fixture(name="PDA", extra=0., scale=1., step=.02):
    x = np.arange(-40., 50.+step/2, step)
    aromatic = 80*np.exp(-.5*((x-7.3)/.6)**2)
    aliphatic = (12+extra)*np.exp(-.5*((x-2.)/.35)**2)
    return HNMRSpectrum(name, x, scale*(aromatic+aliphatic), np.zeros_like(x)).validate()


class HNMRTests(unittest.TestCase):
    def test_complex_header_axis_and_source_preserved(self):
        text = '# LEFT = 12 ppm. RIGHT = -2 ppm.\n# SIZE = 8\n'+'\n'.join(f'{i+1}-{2*i+1}i' for i in range(8))
        s = parse_hnmr_text(text, 'PDA-시료', 'sample.txt')
        np.testing.assert_array_equal(s.real, np.arange(8,0,-1))
        np.testing.assert_array_equal(s.imag, -np.arange(15,0,-2))
        np.testing.assert_allclose(s.x, np.arange(-2,13,2))
        self.assertEqual(s.name, 'PDA-시료')
        with self.assertRaisesRegex(ValueError,'SIZE'): parse_hnmr_text(text.replace('SIZE = 8','SIZE = 9'))
        with self.assertRaisesRegex(ValueError,'Line'): parse_hnmr_text(text.replace('1-1i','__import__("os")'))

    def test_explicit_complex_table_and_invalid_data(self):
        s = parse_hnmr_text('ppm,real,imag\n'+'\n'.join(f'{i},{i*2},{i*3}' for i in range(8)))
        self.assertEqual(s.imag[-1],21)
        for invalid in ('0 1 2 3\n1 4 5 6', 'ppm real imag\n0 1 2', '# LEFT = 2\n# RIGHT = 1\n# SIZE = 8\n'+'\n'.join(['nan+1i']*8)):
            with self.assertRaises(ValueError): parse_hnmr_text(invalid)

    def test_autophase_rotates_complex_absorption_without_mutating_raw(self):
        x = np.linspace(-40,50,4501)
        # Analytic Lorentzian and its dispersive partner, rotated 43 degrees.
        z = 1/(1+1j*(x-5)/.8)*np.exp(1j*np.deg2rad(43))
        s = HNMRSpectrum('phase',x,z.real.copy(),z.imag.copy()).validate()
        before = (s.real.copy(),s.imag.copy())
        settings=HNMRSettings(grid_step=.02,baseline=False)
        p=process_hnmr(s,settings)
        self.assertLess(abs(p.audit['auto_phase0_deg']+43),3)
        np.testing.assert_array_equal(s.real,before[0]);np.testing.assert_array_equal(s.imag,before[1])
        unphased=process_hnmr(s,replace(settings,phase=False))
        np.testing.assert_allclose(unphased.y,s.real,rtol=1e-10,atol=1e-10)

    def test_baseline_toggle_and_no_quantitative_normalization(self):
        s=fixture();s.real+=10+.05*s.x
        settings=replace(common_settings([s]),phase=False)
        corrected=process_hnmr(s,settings)
        off=process_hnmr(s,replace(settings,baseline=False))
        np.testing.assert_allclose(off.y-corrected.y,10+.05*corrected.x,atol=1e-8)
        self.assertGreater(corrected.y.max(),70)
        self.assertIn('None',corrected.audit['normalization'])
        real_only=fixture()
        self.assertEqual(automatic_phase(real_only.x,real_only.real.astype(complex)),0.)
        self.assertGreater(preview_spectrum(real_only).y.max(),79.)

    def test_manual_phase_survives_common_preparation_and_library_preview(self):
        s=fixture();s.metadata['manual_phase0']=12.
        prepare_spectra([s],common_settings([s]))
        self.assertEqual(s.processing['phase0'],12.)
        s.processing['settings']['phase']=False;preview_spectrum(s)
        self.assertEqual(s.processing['phase0'],12.)
        s.processing['settings']['phase']=True
        self.assertEqual(preview_spectrum(s).audit['auto_phase0_deg'],12.)

    def test_common_overlap_coarsest_grid_and_no_extrapolation(self):
        a=fixture(step=.02);b=fixture(step=.07)
        b.x=b.x[20:-20];b.real=b.real[20:-20];b.imag=b.imag[20:-20]
        settings=common_settings([a,b]);self.assertAlmostEqual(settings.grid_step,.07)
        self.assertGreaterEqual(settings.ppm_min,b.x[0]);self.assertLessEqual(settings.ppm_max,b.x[-1])
        prepare_spectra([a,b],settings)
        np.testing.assert_array_equal(preview_spectrum(a).x,preview_spectrum(b).x)
        with self.assertRaisesRegex(ValueError,'coverage'): process_hnmr(b,HNMRSettings())

    def test_preparation_atomic_when_any_spectrum_lacks_coverage(self):
        a=fixture();b=HNMRSpectrum('narrow',np.linspace(0,10,101),np.ones(101),np.zeros(101)).validate()
        with self.assertRaises(ValueError): prepare_spectra([a,b],HNMRSettings())
        self.assertEqual(a.processing,{})

    def test_trapezoid_exact_endpoints_and_signed_area(self):
        x=np.arange(-4.,12.,.3);y=2*x+3
        self.assertAlmostEqual(integrate(x,y,.17,4.31),(4.31**2+3*4.31)-(.17**2+3*.17))
        self.assertLess(integrate(x,-np.ones_like(x),0,2),0)
        with self.assertRaises(ValueError):integrate(x,y,-20,10)

    def test_known_ligand_recovery_and_pristine_zero_are_not_hardcoded(self):
        a=fixture('PDA-C6',extra=40);b=fixture('PDA')
        settings=replace(common_settings([a,b]),phase=False,baseline=False)
        prepare_spectra([a,b],settings)
        q=QuantSettings(line_shape="gaussian", calibration_verified=True, acquisition_verified=True, assignments_verified=True, sample_mass_mg=10,reference_mass_mg=10,capacity_umol_mg=.2,
                        standard_area=100,standard_mmol_h=.001,effective_h=2)
        r=quantify(a,b,q)
        expected_area=40*.35*np.sqrt(2*np.pi)
        self.assertAlmostEqual(r.values['excess_aliphatic_area'],expected_area,places=5)
        self.assertAlmostEqual(r.values['ligand_umol'],expected_area/100/2,places=6)
        self.assertAlmostEqual(r.values['apparent_coverage_percent'],100*expected_area/100/2/10/.2,places=6)
        self.assertEqual(quantify(b,b,q).values['apparent_coverage_percent'],0.)
        clone=fixture('different name',scale=2)
        prepare_spectra([b,clone],settings)
        self.assertAlmostEqual(quantify(clone,b,replace(q,sample_mass_mg=20)).values['apparent_coverage_percent'],0.,places=12)

    def test_stale_or_separately_prepared_data_block_saved_group_analysis(self):
        a,b=fixture('PDA-C6'),fixture()
        prepare_spectra([a],common_settings([a]));prepare_spectra([b],common_settings([b]))
        with self.assertRaisesRegex(ValueError,'together'):quantify(a,b,QuantSettings())
        r=quantify(a,b,QuantSettings(use_prepared=False,calibration_verified=True,acquisition_verified=True,assignments_verified=True))
        self.assertAlmostEqual(r.values['apparent_coverage_percent'],0.)

    def test_standard_units_do_not_depend_on_sample_resampling_grid(self):
        a,b=fixture('PDA-C6',extra=40),fixture()
        prepare_spectra([a,b],replace(common_settings([a,b]),phase=False))
        base=QuantSettings(standard_area=100,calibration_verified=True,acquisition_verified=True,assignments_verified=True)
        values=[]
        for q in (base,replace(base,standard_basis='point_sum',standard_area=10000,standard_grid_step=.01),
                  replace(base,standard_basis='hz',standard_area=40000,frequency_mhz=400)):
            values.append(quantify(a,b,q).values['ligand_umol'])
        np.testing.assert_allclose(values,values[0])
        with self.assertRaisesRegex(ValueError,'STANDARD'):replace(base,standard_basis='point_sum').validate()

    def test_mass_scaling_response_multiplier_and_unclipped_negative(self):
        a,b=fixture('PDA-C6',extra=-6),fixture()
        prepare_spectra([a,b],replace(common_settings([a,b]),phase=False))
        q=QuantSettings(core_scaling='mass',sample_mass_mg=10,reference_mass_mg=10,calibration_verified=True,acquisition_verified=True,assignments_verified=True)
        r=quantify(a,b,q);self.assertLess(r.values['apparent_coverage_percent'],0)
        self.assertTrue(any('NOT been clipped' in w for w in r.warnings))
        r2=quantify(a,b,replace(q,response_factor=2,reference_response_factor=2))
        self.assertAlmostEqual(r2.values['ligand_umol'],2*r.values['ligand_umol'])
        self.assertIn('standard_mmol_H * 1000',r.audit)
        self.assertEqual(len(result_csv(r).splitlines()),len(r.sample_fit.x)+1)

    def test_gaussian_decomposition_has_recoverable_components_and_zero_blank(self):
        s=fixture();prepare_spectra([s],replace(common_settings([s]),phase=False))
        r=quantify(s,s,QuantSettings(line_shape='gaussian',calibration_verified=True,acquisition_verified=True,assignments_verified=True))
        self.assertEqual(r.values['apparent_coverage_percent'],0)
        self.assertEqual(len(r.components),2)
        np.testing.assert_allclose(sum(r.components),r.sample_fit.observed,atol=.002)

    def test_defaults_identity_missing_lys_and_invalid_inputs(self):
        p=default_parameters();self.assertEqual(len(p['samples']),10)
        self.assertEqual(p['standards'][0]['area'],42565812.55)
        self.assertFalse(p['standards'][0]['verified'])
        q=quant_defaults(fixture('Hnmr_i_ANP_Plus_JM37B'),p)
        self.assertEqual((q.core,q.ligand,q.sample_mass_mg,q.molecular_weight,q.effective_h),('ANP','DMEN(+)',18.27,88.15,10.))
        lys=quant_defaults(fixture('PDA-Lys'),p)
        self.assertIsNone(lys.effective_h);self.assertIsNone(lys.sample_mass_mg)
        self.assertEqual(lys.molecular_weight,146.19)
        for q in (lys,QuantSettings(standard_area=-1),QuantSettings(response_factor=float('nan')),QuantSettings(aliphatic_max=8)):
            with self.assertRaises(ValueError):q.validate()

    def test_complex_library_roundtrip_order_delete_and_prep_state(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'h.sqlite3';lib=HNMRLibrary(path)
            a,b=fixture('PDA-C6',10),fixture()
            a.imag=a.real*.4;prepare_spectra([a,b],common_settings([a,b]))
            a.metadata['curve_colors']={'real':'#12AB34'}
            for s in (a,b):lib.save(s)
            lib=HNMRLibrary(path);aa=lib.load(a.uid)
            np.testing.assert_array_equal(aa.imag,a.imag)
            self.assertEqual(aa.processing,a.processing);self.assertEqual(aa.metadata,a.metadata)
            self.assertTrue(lib.entries()[0]['prepared'])
            lib.move(b.uid,-1);self.assertEqual(lib.entries()[0]['uid'],b.uid)
            lib.rename(a.uid,'한글 이름');self.assertEqual(lib.load(a.uid).name,'한글 이름')
            lib.delete([a.uid]);self.assertEqual(len(lib.entries()),1)

    def test_portable_libraries_and_atomic_parameter_validation(self):
        s=fixture();prepare_spectra([s],common_settings([s]))
        restored=import_hnmr_library(export_hnmr_library([s]))[0]
        np.testing.assert_array_equal(restored.real,s.real);self.assertEqual(restored.processing,s.processing)
        with self.assertRaises(ValueError):import_hnmr_library(export_hnmr_library([s,s]))
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'parameters.json';lib=HNMRParameterLibrary(path)
            doc=lib.load();doc['cores'][0]['capacity']=.5;lib.save(doc)
            self.assertEqual(HNMRParameterLibrary(path).load()['cores'][0]['capacity'],.5)
            doc['cores'][0]['capacity']=float('nan')
            with self.assertRaises(ValueError):lib.save(doc)
            self.assertEqual(lib.load()['cores'][0]['capacity'],.5)

    def test_smart_import_complex_export(self):
        from labplotter.parsers import detect_builtin_kind
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'proton.txt'
            p.write_text('# LEFT = 10\n# RIGHT = -2\n# SIZE = 16\n'+'\n'.join(['1-2i']*16))
            self.assertEqual(detect_builtin_kind(p),'ssNMR')


if __name__=='__main__':unittest.main()
