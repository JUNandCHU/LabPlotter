"""Recover overlapping finite-domain component areas and enforce calibration gates."""
from dataclasses import replace
import json
import unittest
import numpy as np
from scipy.integrate import trapezoid
from labplotter.hnmr import (HNMRSpectrum, ProcessedH, QuantSettings, common_settings, prepare_spectra,
    quantify, restored_quant_settings, default_parameters, result_csv)
from labplotter.hnmr_decomposition import (DecompositionSettings, decompose, profile, profile_area,
    restore_decomposition, decomposition_csv)
from test_hnmr import fixture


def processed(x, y):
    return ProcessedH(x,y,np.zeros_like(x),np.zeros_like(x),{})


class DecompositionTests(unittest.TestCase):
    def test_overlapping_pseudo_voigt_areas_and_residual_recovery(self):
        x=np.linspace(-20,25,1801)
        a=profile(x,36,1.2,4.8,.6);b=profile(x,81,6.6,7.5,.35)
        f=decompose(processed(x,a+b))
        self.assertGreater(f.audit['fit_R2'],.99999999)
        self.assertAlmostEqual(f.areas['aliphatic']/trapezoid(a,x),1.,places=5)
        self.assertAlmostEqual(f.areas['aromatic']/trapezoid(b,x),1.,places=5)
        self.assertLess(np.max(np.abs(f.residual)),.001)
        self.assertGreater(f.areas['aliphatic'],trapezoid(a[(x>=0)&(x<=4.5)],x[(x>=0)&(x<=4.5)]))
        np.testing.assert_allclose(f.total+f.residual,f.observed)
        json.dumps(f.record(),allow_nan=False)
        self.assertIn('total_fit,residual',decomposition_csv(f).splitlines()[0])

    def test_analytic_areas_match_independent_dense_quadrature(self):
        x=np.linspace(-17,22,100001)
        for eta in (0.,.4,1.):
            expected=trapezoid(profile(x,2.7,6.1,8.2,eta),x)
            self.assertAlmostEqual(profile_area(-17,22,2.7,6.1,8.2,eta),expected,places=8)

    def test_finite_fit_domain_does_not_extrapolate_missing_data(self):
        x=np.linspace(-10,15,801);p=processed(x,profile(x,10,2,4,.3))
        with self.assertRaisesRegex(ValueError,'exceeds'):decompose(p)
        with self.assertRaisesRegex(ValueError,'flat'):decompose(processed(np.linspace(-20,25,100),np.zeros(100)))

    def test_optional_overlap_is_separate_from_ligand_area(self):
        x=np.linspace(-20,25,1601)
        parts=[profile(x,30,1,3,0),profile(x,60,7,3,0),profile(x,10,5,1,0)]
        f=decompose(processed(x,sum(parts)),DecompositionSettings(line_shape='gaussian',overlap_band=True))
        self.assertEqual(set(f.curves),{'aliphatic','aromatic','unassigned'})
        self.assertAlmostEqual(f.areas['unassigned']/trapezoid(parts[2],x),1.,places=5)

    def test_stored_fit_invalidates_after_intensity_or_phase_change(self):
        x=np.linspace(-20,25,901);p=processed(x,profile(x,30,2,3,0)+profile(x,60,7,4,0))
        f=decompose(p,DecompositionSettings(line_shape='gaussian'))
        self.assertIsNotNone(restore_decomposition(p,f.record()))
        self.assertIsNone(restore_decomposition(processed(x,p.y*1.01),f.record()))

    def test_unknown_calibration_withholds_absolute_coverage_not_components(self):
        a,b=fixture('PDA-C6',40),fixture()
        prepare_spectra([a,b],replace(common_settings([a,b]),phase=False,baseline=False))
        q=QuantSettings(line_shape='gaussian',sample_mass_mg=10,reference_mass_mg=10,show_provisional=False)
        r=quantify(a,b,q)
        self.assertIsNone(r.values['apparent_coverage_percent']);self.assertIsNone(r.values['ligand_umol'])
        self.assertGreater(r.values['aliphatic_integral'],0)
        self.assertIn('Withheld',r.quantitative_status)
        self.assertIn('unvalidated_algebra_only',r.audit)
        for flag in ('calibration_verified','acquisition_verified','assignments_verified'):
            ready=replace(q,calibration_verified=True,acquisition_verified=True,assignments_verified=True)
            setattr(ready,flag,False)
            self.assertIsNone(quantify(a,b,ready).values['apparent_coverage_percent'])

    def test_aromatic_amplitude_is_not_a_particle_mass_proxy(self):
        a,b=fixture('PDA-C6',40),fixture()
        a.real += 80*np.exp(-.5*((a.x-7.3)/.6)**2)
        prepare_spectra([a,b],replace(common_settings([a,b]),phase=False,baseline=False))
        q=QuantSettings(core_scaling='mass',line_shape='gaussian',sample_mass_mg=10,reference_mass_mg=10)
        r=quantify(a,b,q)
        self.assertEqual(r.values['core_scale'],1.)
        self.assertAlmostEqual(r.values['excess_aliphatic_area'],40*.35*np.sqrt(2*np.pi),places=5)
        with self.assertRaisesRegex(ValueError,'Choose aromatic_reference'):quantify(a,b,replace(q,core_scaling='aromatic'))
        self.assertIn('reference_total_fit',result_csv(r).splitlines()[0])

    def test_legacy_parameters_migrate_without_reusing_verification(self):
        s=fixture('PDA-C6');s.metadata['analysis_parameters']={'method':'regions','core_scaling':'aromatic','calibration_verified':True,'assignments_verified':True}
        q=restored_quant_settings(s,default_parameters())
        self.assertEqual(q.method,'decomposition');self.assertEqual(q.core_scaling,'aromatic_reference')
        self.assertFalse(q.calibration_verified);self.assertFalse(q.assignments_verified)


if __name__=='__main__':unittest.main()
