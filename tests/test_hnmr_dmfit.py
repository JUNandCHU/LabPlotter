"""Known instrument spacing, DMfit links, signed accounting and unbiased QC."""
from copy import deepcopy
from dataclasses import asdict, replace
import unittest
import numpy as np
from labplotter.hnmr import (common_settings, process_hnmr, preview_spectrum, prepare_spectra,
    quantify, QuantSettings, default_parameters, restored_quant_settings)
from labplotter.hnmr_decomposition import (decompose, decomposition_defaults, profile, restore_decomposition)
from labplotter.hnmr_library import export_hnmr_library, import_hnmr_library
from labplotter.hnmr_stability import phase_sensitivity
from test_hnmr_sidebands import mas_fixture


class DMfitTests(unittest.TestCase):
    def test_lab_preset_is_explicit_and_old_saved_settings_are_preserved(self):
        s=mas_fixture();s.metadata.pop('acquisition')
        cfg=common_settings([s]);self.assertEqual((cfg.mas_hz,cfg.proton_mhz,cfg.sideband_spacing),(20000.,400.,50.))
        fitcfg=decomposition_defaults(s)
        self.assertFalse(fitcfg.fit_sideband_width);self.assertEqual(fitcfg.sideband_width_scale,1.)
        self.assertEqual(fitcfg.mas_hz/fitcfg.proton_mhz,50.)
        old=asdict(replace(fitcfg,mas_hz=0.,proton_mhz=0.,sideband_spacing=57.,fit_sideband_width=True))
        for k in ('allow_negative_sidebands','aliphatic_gaussian_fraction','aromatic_gaussian_fraction'):old.pop(k)
        s.metadata['decomposition_settings']=old
        restored=decomposition_defaults(s)
        self.assertEqual(restored.sideband_spacing,57.);self.assertTrue(restored.fit_sideband_width)
        self.assertEqual(decomposition_defaults(s,use_saved=False).mas_hz,20000.)

    def test_locked_gaussian_fraction_recovers_lines_and_roundtrips(self):
        s=mas_fixture();s.real[:]=0
        for c,w,g,heights in ((1.4,3.5,.3,[.22,1.8,15,3.8,.7]),(6.7,5.6,.8,[.45,3.5,70,6.,1.1])):
            for n,h in zip(range(-2,3),heights):s.real+=profile(s.x,h,c+n*55,w,1-g)
        prepare_spectra([s],replace(common_settings([s]),phase=False,baseline=False))
        cfg=replace(decomposition_defaults(s),aliphatic_gaussian_fraction=.3,aromatic_gaussian_fraction=.8)
        p=preview_spectrum(s);fit=decompose(p,cfg)
        self.assertGreater(fit.audit['fit_R2'],.999999)
        for family,g in (('aliphatic',.3),('aromatic',.8)):
            lines=[l for l in fit.audit['lines'] if l['family']==family]
            self.assertEqual(len({l['parameters'][2] for l in lines}),1)
            self.assertTrue(all(abs(1-l['parameters'][3]-g)<1e-12 for l in lines))
            self.assertAlmostEqual(sum(l['full_profile_area'] for l in lines),fit.audit['full_profile_areas'][family])
        s.metadata.update(decomposition=fit.record(),decomposition_settings=asdict(cfg))
        loaded=import_hnmr_library(export_hnmr_library([s]))[0]
        recovered=restore_decomposition(preview_spectrum(loaded),loaded.metadata['decomposition'])
        np.testing.assert_array_equal(recovered.total,fit.total)
        self.assertEqual(restored_quant_settings(loaded,default_parameters()).aliphatic_gaussian_fraction,.3)

    def test_signed_weak_satellite_is_retained_and_blocks_coverage(self):
        s=mas_fixture();s.real-=profile(s.x,1.3,6.7+2*55,5.6,0.)
        cfg=replace(common_settings([s]),phase=False,baseline=False);prepare_spectra([s],cfg)
        ds=replace(decomposition_defaults(s),line_shape='gaussian',allow_negative_sidebands=True)
        fit=decompose(preview_spectrum(s),ds)
        row=next(l for l in fit.audit['lines'] if l['family']=='aromatic' and l['order']==2)
        self.assertAlmostEqual(row['parameters'][0],-.2,places=4)
        self.assertLess(row['area'],0.)
        self.assertAlmostEqual(fit.areas['aromatic'],sum(l['area'] for l in fit.audit['lines'] if l['family']=='aromatic'))
        q=QuantSettings(**asdict(ds),calibration_verified=True,acquisition_verified=True,assignments_verified=True,
                        standard_includes_sidebands=True,sideband_scope_verified=True,show_provisional=False)
        result=quantify(s,s,q)
        self.assertIsNone(result.values['apparent_coverage_percent'])
        self.assertIn('signed negative',result.quantitative_status)
        provisional=quantify(s,s,replace(q,show_provisional=True))
        self.assertEqual(provisional.values['apparent_coverage_percent'],0.)
        self.assertTrue(provisional.provisional)
        self.assertTrue(any('signed negative' in issue for issue in provisional.validation_issues))

    def test_lower_aliphatic_sample_is_not_forced_above_reference(self):
        a,b=mas_fixture('PDA-C6',extra=-10),mas_fixture('PDA')
        prepare_spectra([a,b],replace(common_settings([a,b]),phase=False,baseline=False))
        ds=replace(decomposition_defaults(a),line_shape='gaussian')
        q=QuantSettings(**asdict(ds),standard_includes_sidebands=True,sideband_scope_verified=True,
            calibration_verified=True,acquisition_verified=True,assignments_verified=True,
            sample_mass_mg=10,reference_mass_mg=10,standard_area=100,standard_umol_h=1.)
        result=quantify(a,b,q)
        self.assertLess(result.values['aliphatic_area_per_mg_difference'],0.)
        self.assertLess(result.values['excess_aliphatic_area'],0.)
        a.name,b.name='PDA','PDA-C6'
        renamed=quantify(a,b,q)
        self.assertEqual(renamed.values,result.values)

    def test_phase_sensitivity_reprocesses_without_mutation_or_name_bias(self):
        a,b=mas_fixture('modified',extra=10,complex_data=True),mas_fixture('core',complex_data=True)
        cfg=replace(common_settings([a,b]),auto_phase1=False)
        prepare_spectra([a,b],cfg)
        originals=[(s.real.copy(),s.imag.copy(),deepcopy(s.metadata),deepcopy(s.processing)) for s in (a,b)]
        settings=replace(decomposition_defaults(a),line_shape='gaussian')
        result=phase_sensitivity(a,b,settings=settings,sample_mass=10,reference_mass=10)
        self.assertEqual(len(result['rows']),6)
        self.assertGreater(result['comparison']['aliphatic_per_mg']['nominal_difference'],0.)
        self.assertEqual(result['comparison']['aliphatic_per_mg']['ordering'],'sample above reference throughout')
        for s,(real,imag,metadata,processing) in zip((a,b),originals):
            np.testing.assert_array_equal(s.real,real);np.testing.assert_array_equal(s.imag,imag)
            self.assertEqual(s.metadata,metadata);self.assertEqual(s.processing,processing)
        with self.assertRaises(ValueError):phase_sensitivity(a,b,phase_step=0.)
        with self.assertRaises(ValueError):phase_sensitivity(a,b,sample_mass=None)

    def test_old_preprocessing_spacing_cannot_silently_validate_new_fit(self):
        s=mas_fixture()
        cfg=replace(common_settings([s]),mas_hz=0.,proton_mhz=0.,sideband_spacing=50.)
        prepare_spectra([s],cfg)
        ds=replace(decomposition_defaults(s),mas_hz=22000.,proton_mhz=400.,line_shape='gaussian')
        fit=decompose(preview_spectrum(s),ds)
        self.assertTrue(fit.audit['preprocessing_spacing_mismatch'])
        q=QuantSettings(**asdict(ds),calibration_verified=True,acquisition_verified=True,assignments_verified=True,
                        standard_includes_sidebands=True,sideband_scope_verified=True,show_provisional=False)
        result=quantify(s,s,q)
        self.assertIn('preprocessing and fixed fitting spacings differ',result.quantitative_status)
        self.assertIsNone(result.values['apparent_coverage_percent'])


if __name__=='__main__':unittest.main()
