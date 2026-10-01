"""Provisional reporting keeps evidence, signs, calibration units and raw data."""
from dataclasses import asdict, replace
import json
import unittest
import numpy as np
from labplotter.hnmr import (QuantSettings, common_settings, prepare_spectra, quantify,
    default_parameters, restored_quant_settings, process_hnmr)
from labplotter.hnmr_batch import batch_plan, remember_result, summary_row, summary_csv
from labplotter.hnmr_library import export_hnmr_library, import_hnmr_library
from labplotter.hnmr_quality import refine_sideband_phase
from test_hnmr import fixture
from test_hnmr_sidebands import mas_fixture


class ProvisionalTests(unittest.TestCase):
    def setUp(self):
        self.a,self.b=fixture('PDA-C6',40),fixture('PDA')
        prepare_spectra([self.a,self.b],replace(common_settings([self.a,self.b]),phase=False,baseline=False))

    def test_default_reports_same_algebra_without_marking_checks_verified(self):
        q=QuantSettings(line_shape='gaussian',sample_mass_mg=10,reference_mass_mg=10)
        result=quantify(self.a,self.b,q)
        strict=quantify(self.a,self.b,replace(q,show_provisional=False))
        audit=json.loads(result.audit[result.audit.index('{'):])
        expected=40*.35*np.sqrt(2*np.pi)/q.standard_area*q.standard_umol_h/13/10/.0693*100
        self.assertAlmostEqual(result.values['apparent_coverage_percent'],expected,places=7)
        self.assertIsNone(strict.values['apparent_coverage_percent'])
        self.assertEqual(result.values['apparent_coverage_percent'],audit['unvalidated_algebra_only']['apparent_coverage_percent'])
        self.assertTrue(result.provisional);self.assertFalse(q.calibration_verified)
        self.assertTrue(audit['assumptions']['equal_response_assumed'])
        self.assertEqual(result.validation_issues,strict.validation_issues)
        np.testing.assert_array_equal(result.sample_fit.total,strict.sample_fit.total)

    def test_negative_large_and_self_reference_results_are_not_clipped(self):
        q=QuantSettings(line_shape='gaussian',sample_mass_mg=10,reference_mass_mg=10,standard_area=.001)
        positive=quantify(self.a,self.b,q);negative=quantify(self.b,self.a,q)
        self.assertGreater(positive.values['apparent_coverage_percent'],100)
        self.assertAlmostEqual(positive.values['apparent_coverage_percent'],-negative.values['apparent_coverage_percent'],places=5)
        self.assertEqual(quantify(self.b,self.b,q).values['apparent_coverage_percent'],0.)

    def test_batch_plans_and_persistence_use_user_values_and_do_not_guess_missing_inputs(self):
        params=default_parameters();params['standards'][0].update(basis='hz',frequency_mhz=400.)
        self.a.metadata['analysis_parameters']={'method':'decomposition','response_factor':2.,'show_provisional':False}
        plan=batch_plan([self.a,self.b],params)
        self.assertTrue(plan[0].settings.show_provisional)
        self.assertEqual(plan[0].settings.standard_basis,'hz')
        self.assertEqual(plan[0].settings.response_factor,2.)
        result=quantify(self.a,self.b,plan[0].settings)
        remember_result(self.a,self.b,plan[0].settings,result)
        loaded=import_hnmr_library(export_hnmr_library([self.a]))[0]
        restored=restored_quant_settings(loaded,params)
        self.assertTrue(restored.show_provisional);self.assertFalse(restored.calibration_verified)
        self.assertEqual(loaded.metadata['analysis_reference_uid'],self.b.uid)
        csv=summary_csv([summary_row(plan[0],result)])
        self.assertIn('provisional',csv);self.assertIn('unresolved_checks',csv)
        self.assertIn('hz',csv)
        for sample in (fixture('PDA-Lys'),fixture('Unrecognized sample')):
            self.assertTrue(batch_plan([sample,self.b],params)[0].error)
        self.assertTrue(batch_plan([self.a],params)[0].error)
        self.assertEqual(batch_plan([self.a,self.b,fixture('PDA')],params)[0].reference.uid,self.b.uid)
        self.a.metadata.pop('analysis_reference_uid')
        self.assertTrue(batch_plan([self.a,self.b,fixture('PDA')],params)[0].error)

    def test_saved_pre_0104_settings_get_provisional_mode_without_false_verification(self):
        self.a.metadata['analysis_parameters']={'method':'decomposition','standard_basis':'point_sum','standard_grid_step':.03}
        q=restored_quant_settings(self.a,default_parameters())
        self.assertTrue(q.show_provisional);self.assertEqual(q.standard_basis,'point_sum')
        self.assertFalse(q.calibration_verified)
        with self.assertRaises(ValueError):quantify(self.a,self.b,replace(q,standard_grid_step=None))

    def test_refinement_improves_negative_satellites_using_one_phase_without_mutation(self):
        s=mas_fixture(complex_data=True);cfg=common_settings([s]);m=(s.x>=cfg.ppm_min)&(s.x<=cfg.ppm_max)
        x=s.x[m];z=(s.real+1j*s.imag)[m]*np.exp(-1j*np.deg2rad(30.+55.*(x-5)/410))
        raw=z.copy()
        phase,audit=refine_sideband_phase(x,z,[30.,0.],55,20,1,145)
        self.assertTrue(audit['accepted']);self.assertLess(audit['negative_score_after'],audit['negative_score_before'])
        self.assertLessEqual(abs(phase[0]-30),5.);self.assertLessEqual(abs(phase[1]),60.)
        self.assertGreaterEqual(audit['central_positive_area_ratio'],.9)
        np.testing.assert_array_equal(z,raw)
        self.assertEqual(len(audit['resolved_orders']),4)

    def test_known_phase_recovery_and_manual_override_survive_new_refinement(self):
        s=mas_fixture(complex_data=True);raw=(s.real.copy(),s.imag.copy())
        phase=31.+72.*(s.x-5)/410
        z=(s.real+1j*s.imag)*np.exp(-1j*np.deg2rad(phase));s.real=z.real;s.imag=z.imag
        p=process_hnmr(s,common_settings([s]))
        self.assertAlmostEqual(p.audit['auto_phase0_deg'],31.,delta=1.)
        self.assertAlmostEqual(p.audit['auto_phase1_deg'],72.,delta=12.)
        s.metadata.update(manual_phase0=12.,manual_phase1=45.,manual_phase_reference={'pivot':5.,'span':410.})
        p=process_hnmr(s,common_settings([s]))
        self.assertEqual(p.audit['auto_phase0_deg'],12.);self.assertEqual(p.audit['auto_phase1_deg'],45.)
        self.assertEqual(p.audit['phase_source'],'manual PH0/PH1 override')


if __name__=='__main__':unittest.main()
