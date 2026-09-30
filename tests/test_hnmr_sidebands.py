"""MAS area accounting, weak-peak reporting, complex phase and upgrade safety."""
from dataclasses import asdict, replace
import json
import unittest
import numpy as np
from scipy.integrate import trapezoid
from scipy.special import dawsn
from labplotter.hnmr import (HNMRSpectrum, ProcessedH, QuantSettings, common_settings,
    prepare_spectra, preview_spectrum, process_hnmr, quantify, default_parameters, quant_defaults)
from labplotter.hnmr_decomposition import (DecompositionSettings, decomposition_defaults,
    decompose, profile, profile_area, restore_decomposition, decomposition_csv)
from labplotter.hnmr_library import export_hnmr_library, import_hnmr_library, validate_parameters
from labplotter.hnmr_quality import masked_baseline, sideband_diagnostics


def mas_fixture(name='PDA-C6', extra=0., complex_data=False):
    x=np.linspace(-250,260,5101); y=np.zeros_like(x); imaginary=np.zeros_like(x)
    for center,width,amps in [(1.4,3.5,[.22,1.8,15+extra,3.8,.7]),(6.7,5.6,[.45,3.5,70,6.,1.1])]:
        for n,amp in zip(range(-2,3),amps):
            y += profile(x,amp,center+n*55,width,0.)
            imaginary += amp*2/np.sqrt(np.pi)*dawsn(2*np.sqrt(np.log(2))*(x-center-n*55)/width)
    return HNMRSpectrum(name,x,y,imaginary if complex_data else np.zeros_like(x)).validate()


class SidebandTests(unittest.TestCase):
    def test_recovers_independent_orders_and_sum_without_multiplier(self):
        s=mas_fixture();cfg=replace(common_settings([s]),phase=False,baseline=False)
        p=process_hnmr(s,cfg)
        settings=replace(decomposition_defaults(s),sideband_spacing=55,refine_spacing=False,
                         fit_sideband_width=False,line_shape='gaussian')
        fit=decompose(p,settings)
        self.assertGreater(fit.audit['fit_R2'],.999999)
        for family in ('aliphatic','aromatic'):
            rows=[r for r in fit.audit['lines'] if r['family']==family]
            self.assertEqual(len(rows),5)
            self.assertAlmostEqual(sum(r['area'] for r in rows),fit.areas[family],places=9)
            self.assertNotAlmostEqual(rows[0]['area'],rows[-1]['area'],places=3)
            self.assertNotAlmostEqual(fit.areas[family],rows[2]['area']*5,places=3)
            self.assertAlmostEqual(fit.areas[family]/trapezoid(fit.curves[family],fit.x),1,places=5)
        self.assertAlmostEqual(fit.areas['aliphatic']/((.22+1.8+15+3.8+.7)*3.5*np.sqrt(np.pi)/(2*np.sqrt(np.log(2)))),1,places=4)
        self.assertIn('aromatic_order_+2',decomposition_csv(fit).splitlines()[0])
        self.assertIsNotNone(restore_decomposition(p,fit.record()))
        json.dumps(fit.record(),allow_nan=False)

    def test_mas_frequency_sets_spacing_and_invalid_scope_is_rejected(self):
        s=mas_fixture();p=process_hnmr(s,replace(common_settings([s]),phase=False,baseline=False))
        settings=replace(decomposition_defaults(s),mas_hz=22000,proton_mhz=400,
                         sideband_spacing=60,line_shape='gaussian',fit_sideband_width=False)
        fit=decompose(p,settings)
        self.assertEqual(fit.audit['spacing_ppm'],55.)
        self.assertIn('fixed',fit.audit['spacing_source'])
        for bad in (replace(settings,proton_mhz=0),replace(settings,sideband_order=2.5),replace(settings,fit_min=-100)):
            with self.assertRaises(ValueError):bad.validate()

    def test_outer_baseline_anchors_preserve_broad_satellites(self):
        s=mas_fixture();baseline=.5+.001*s.x
        calculated,audit=masked_baseline(s.x,s.real+baseline,55,20,1,145)
        np.testing.assert_allclose(calculated,baseline,atol=1e-8)
        self.assertGreater(audit['anchor_points'],20)
        with self.assertRaisesRegex(ValueError,'anchors'):
            masked_baseline(s.x,s.real,55,20,1,500)

    def test_weak_outer_peaks_are_not_mirrored_into_detections(self):
        s=mas_fixture();rng=np.random.default_rng(91)
        y=s.real.copy();y[abs(s.x-4.5)>85]=0.;y+=rng.normal(0,.03,len(y))
        d=sideband_diagnostics(s.x,y,55,2,anchor_min=145)
        rows={r['order']:r for r in d['envelopes']}
        self.assertEqual(rows[1]['status'],'detected');self.assertEqual(rows[-1]['status'],'detected')
        self.assertEqual(rows[2]['status'],'weak / unresolved');self.assertEqual(rows[-2]['status'],'weak / unresolved')
        self.assertEqual(d['detected_sideband_envelopes'],2)

    def test_phase_zero_first_recovers_complex_signal_without_raw_mutation(self):
        s=mas_fixture(complex_data=True);x=s.x;original=s.real.copy()
        phase=31.+72.*(x-5)/410
        z=(s.real+1j*s.imag)*np.exp(-1j*np.deg2rad(phase))
        s.real=z.real;s.imag=z.imag;raw=(s.real.copy(),s.imag.copy())
        cfg=replace(common_settings([s]),sideband_spacing=55.)
        p=process_hnmr(s,cfg)
        self.assertAlmostEqual(p.audit['auto_phase0_deg'],31.,delta=1.)
        self.assertAlmostEqual(p.audit['auto_phase1_deg'],72.,delta=12.)
        expected=np.interp(p.x,x,original)
        self.assertLess(np.sqrt(np.mean((p.y-expected)**2))/expected.max(),.01)
        np.testing.assert_array_equal(raw[0],s.real);np.testing.assert_array_equal(raw[1],s.imag)
        prepare_spectra([s],cfg);before=preview_spectrum(s)
        restored=import_hnmr_library(export_hnmr_library([s]))[0]
        np.testing.assert_array_equal(preview_spectrum(restored).y,before.y)
        self.assertEqual(restored.processing['phase1'],s.processing['phase1'])

    def test_manual_phase_keeps_physical_slope_when_common_range_changes(self):
        s=mas_fixture(complex_data=True)
        s.metadata.update(manual_phase0=20.,manual_phase1=80.,manual_phase_reference={'pivot':5.,'span':410.})
        cfg=replace(common_settings([s]),baseline=False)
        a=process_hnmr(s,cfg,20.)
        b=process_hnmr(s,replace(cfg,ppm_min=-150.,ppm_max=160.),20.)
        self.assertAlmostEqual(b.audit['auto_phase1_deg'],80*310/410)
        np.testing.assert_allclose(np.interp(b.x,a.x,a.y),b.y,atol=.005)

    def test_standard_scope_migration_and_coverage_gate(self):
        params=default_parameters();old=json.loads(json.dumps(params));old['standards'][0].pop('includes_sidebands')
        migrated=validate_parameters(old)
        self.assertTrue(migrated['standards'][0]['includes_sidebands'])
        self.assertNotIn('includes_sidebands',old['standards'][0])
        old['standards'][0]['name']='Other standard';self.assertFalse(validate_parameters(old)['standards'][0]['includes_sidebands'])
        s=mas_fixture();q=quant_defaults(s,params)
        self.assertTrue(q.sidebands);self.assertTrue(q.standard_includes_sidebands);self.assertFalse(q.calibration_verified)
        self.assertEqual(q.standard_area,42565812.55);self.assertEqual(q.standard_mmol_h,1.861273386)
        from test_hnmr import fixture
        a,b=fixture('PDA-C6',40),fixture()
        prepare_spectra([a,b],replace(common_settings([a,b]),phase=False,baseline=False))
        q=QuantSettings(line_shape='gaussian',standard_includes_sidebands=True,
            calibration_verified=True,acquisition_verified=True,assignments_verified=True)
        result=quantify(a,b,q)
        self.assertIsNone(result.values['apparent_coverage_percent'])
        self.assertIn('scopes do not match',result.quantitative_status)

    def test_sideband_quantitation_known_excess_and_pristine_blank(self):
        a,b=mas_fixture(extra=10),mas_fixture('PDA')
        cfg=replace(common_settings([a,b]),phase=False,baseline=False);prepare_spectra([a,b],cfg)
        fit=replace(decomposition_defaults(a),line_shape='gaussian',sideband_spacing=55.,refine_spacing=False,fit_sideband_width=False)
        q=QuantSettings(**asdict(fit),standard_includes_sidebands=True,sideband_scope_verified=True,
            calibration_verified=True,acquisition_verified=True,assignments_verified=True,
            standard_area=100,standard_mmol_h=.001,sample_mass_mg=10,reference_mass_mg=10,effective_h=2,capacity_umol_mg=.2)
        result=quantify(a,b,q)
        expected=10*3.5*np.sqrt(np.pi)/(2*np.sqrt(np.log(2)))
        self.assertAlmostEqual(result.values['excess_aliphatic_area'],expected,places=3)
        self.assertAlmostEqual(result.values['ligand_umol'],expected/100/2,places=5)
        self.assertEqual(quantify(b,b,q).values['apparent_coverage_percent'],0.)


if __name__=='__main__':unittest.main()
