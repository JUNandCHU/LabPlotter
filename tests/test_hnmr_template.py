"""Known-signal recovery, calibration invariants and persistent model switching."""
from copy import deepcopy
from dataclasses import asdict, replace
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from scipy.integrate import trapezoid
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

from labplotter.hnmr import (HNMRSpectrum, HNMRSettings, ProcessedH, QuantSettings, prepare_spectra,
    preview_spectrum, quantify, result_csv, default_parameters, restored_quant_settings)
from labplotter.hnmr_decomposition import (DecompositionSettings, decompose, decomposition_values,
    decomposition_csv, profile, profile_area, restore_decomposition, MODEL_LABELS)
from labplotter.hnmr_library import HNMRLibrary, export_hnmr_library, import_hnmr_library, validate_parameters
from labplotter.hnmr_batch import remember_result, summary_row, batch_plan
from labplotter.hnmr_plot import draw_hnmr
from labplotter.plotting import PlotOptions, figure_png_bytes
from labplotter.hnmr_reactions import reaction_coverage
from labplotter.hnmr_model_review import model_review
from labplotter.hnmr_stability import phase_sensitivity


def data_pair(wide=False):
    x=np.linspace(-180,190,3701) if wide else np.linspace(-40,50,1801)
    core=profile(x,90,6.8,5.5,.4)+profile(x,22,1.8,8,.7)
    ligand=profile(x,35,1.1,3.1,.3)
    if wide:
        for n,h in [(-2,1),(-1,9),(1,7),(2,.5)]:
            core+=profile(x,h,6.8+n*50,5.5,.4)
        for n,h in [(-2,.2),(-1,2.5),(1,1.3),(2,.1)]:
            ligand+=profile(x,h,1.1+n*50,3.1,.3)
    b=HNMRSpectrum('ANP',x,core,np.zeros_like(x)).validate()
    a=HNMRSpectrum('ANP-C6',x,.7*core+ligand,np.zeros_like(x)).validate()
    cfg=HNMRSettings(ppm_min=float(x[0]),ppm_max=float(x[-1]),grid_step=float(x[1]-x[0]),
                     phase=False,baseline=False)
    prepare_spectra([a,b],cfg)
    return a,b,ligand


def model(wide=False):
    return DecompositionSettings(model='core_template',fit_min=-145 if wide else -20,
        fit_max=155 if wide else 25,template_shift_max=0,sidebands=wide,
        sideband_spacing=50,mas_hz=20000 if wide else 0,proton_mhz=400 if wide else 0,refine_spacing=False)


class CoreTemplateTests(unittest.TestCase):
    def test_recovers_core_and_asymmetric_sideband_ligand_areas(self):
        a,b,_=data_pair(True);pa,pb=preview_spectrum(a),preview_spectrum(b)
        fit=decompose(pa,model(True),pb,{'uid':b.uid,'name':b.name})
        expected=sum(profile_area(-145,155,h,1.1+n*50,3.1,.3)
                     for n,h in [(0,35),(-2,.2),(-1,2.5),(1,1.3),(2,.1)])
        self.assertAlmostEqual(fit.audit['core_scale'],.7,places=4)
        self.assertAlmostEqual(fit.areas['ligand']/expected,1.,places=4)
        self.assertGreater(fit.audit['fit_R2'],.99999)
        self.assertEqual(set(fit.curves),{'core_template','ligand'})
        self.assertNotIn('aromatic_integral',decomposition_values(fit))
        self.assertEqual(len(fit.audit['lines']),5)
        np.testing.assert_allclose(fit.total+fit.residual,fit.observed)
        exported=np.genfromtxt(StringIO(decomposition_csv(fit)),delimiter=',',names=True)
        self.assertAlmostEqual(trapezoid(exported['ligand'],exported['ppm'])/expected,1.,places=4)

    def test_reference_is_required_and_fit_domain_cannot_extrapolate(self):
        a,b,_=data_pair();pa,pb=preview_spectrum(a),preview_spectrum(b)
        with self.assertRaisesRegex(ValueError,'requires.*reference'):decompose(pa,model())
        narrow=replace(pb,x=pb.x[(pb.x>=-20)&(pb.x<=25)],y=pb.y[(pb.x>=-20)&(pb.x<=25)])
        with self.assertRaisesRegex(ValueError,'cover'):decompose(pa,replace(model(),template_shift_max=1),narrow)

    def test_mismatched_preprocessing_spacing_is_reported(self):
        a,b,_=data_pair(True)
        for s in (a,b):
            s.processing['settings'].update(phase=True,sideband_spacing=55.)
        q=QuantSettings(**asdict(model(True)),core='ANP')
        r=quantify(a,b,q)
        self.assertTrue(r.sample_fit.audit['preprocessing_spacing_mismatch'])
        self.assertIn('preprocessing and fixed fitting spacings differ',r.validation_issues)
        self.assertIsNotNone(r.values['coverage_lower_percent'])

    def test_coverage_algebra_response_mass_and_standard_units(self):
        a,b,_=data_pair()
        q=QuantSettings(**asdict(model()),core='ANP',sample_mass_mg=20,reference_mass_mg=30,
                        capacity_umol_mg=.16,standard_area=1000,standard_umol_h=2)
        r=quantify(a,b,q)
        area=profile_area(-20,25,35,1.1,3.1,.3)
        expected=100*(area/.7)*(2/1000)/(13*30*.16)
        # prepare_spectra resamples the finite input grid; allow 0.01% discretization error.
        np.testing.assert_allclose(r.values['apparent_coverage_percent'],expected,rtol=1e-4)
        changed=quantify(a,b,replace(q,sample_mass_mg=53,response_factor=3))
        self.assertAlmostEqual(changed.values['apparent_coverage_percent'],r.values['apparent_coverage_percent'])
        doubled=quantify(a,b,replace(q,reference_mass_mg=60))
        self.assertAlmostEqual(doubled.values['apparent_coverage_percent']*2,r.values['apparent_coverage_percent'])
        hz=quantify(a,b,replace(q,standard_basis='hz',frequency_mhz=400,standard_area=400000))
        self.assertAlmostEqual(hz.values['apparent_coverage_percent'],r.values['apparent_coverage_percent'])
        self.assertIn('fit_core_template',result_csv(r));self.assertNotIn('fit_aromatic',result_csv(r))
        np.testing.assert_allclose(r.values['coverage_michael_percent'],expected*13/14,rtol=1e-4)

    def test_mass_mode_fixes_measured_core_scale_and_blank_is_zero(self):
        a,b,_=data_pair()
        q=QuantSettings(**asdict(model()),core='ANP',core_scaling='mass',sample_mass_mg=10,
                        reference_mass_mg=10,sample_core_mass_mg=7)
        result=quantify(a,b,q)
        self.assertEqual(result.sample_fit.audit['fixed_core_scale'],.7)
        expected=result.values['ligand_integral']*q.standard_umol_h/q.standard_ppm_area()/13/10
        self.assertAlmostEqual(result.values['loading_umol_mg'],expected)
        blank=quantify(b,b,replace(q,core_scaling='core_reference',sample_core_mass_mg=None))
        self.assertEqual(blank.values['apparent_coverage_percent'],0.)
        self.assertEqual(blank.values['coverage_lower_percent'],0.)

    def test_library_only_restore_and_both_fingerprints_invalidate(self):
        a,b,_=data_pair();q=QuantSettings(**asdict(model()),core='ANP')
        result=quantify(a,b,q);remember_result(a,b,q,result)
        with tempfile.TemporaryDirectory() as tmp:
            lib=HNMRLibrary(Path(tmp)/'h.sqlite3');lib.save(a);saved=lib.load(a.uid)
            fit=restore_decomposition(preview_spectrum(saved),saved.metadata['decomposition'])
            self.assertIsNotNone(fit)
            np.testing.assert_allclose(fit.total,result.sample_fit.total)
            self.assertEqual(restored_quant_settings(saved,default_parameters()).model,'core_template')
            copy=import_hnmr_library(export_hnmr_library([saved]))[0]
            self.assertIsNotNone(restore_decomposition(preview_spectrum(copy),copy.metadata['decomposition']))
        p=preview_spectrum(a);r=preview_spectrum(b)
        self.assertIsNone(restore_decomposition(replace(p,y=p.y*1.01),result.sample_fit.record()))
        self.assertIsNone(restore_decomposition(p,result.sample_fit.record(),replace(r,y=r.y*1.01)))
        corrupt=deepcopy(result.sample_fit.record());corrupt['template']['y'][0]+=1
        self.assertIsNone(restore_decomposition(p,corrupt))

    def test_fresh_processing_calculation_is_restorable_after_save(self):
        a,b,_=data_pair();a.processing['settings']['grid_step'] *= 2
        q=QuantSettings(**asdict(model()),core='ANP',use_prepared=False)
        result=quantify(a,b,q);remember_result(a,b,q,result)
        self.assertIsNotNone(restore_decomposition(preview_spectrum(a),a.metadata['decomposition']))

    def test_legacy_default_and_model_switch_batch_persistence(self):
        a,b,_=data_pair()
        self.assertEqual(DecompositionSettings().model,'envelopes')
        self.assertEqual(QuantSettings().model,'envelopes')
        self.assertEqual(MODEL_LABELS['envelopes'],'model Ver1')
        self.assertEqual(restored_quant_settings(a,default_parameters()).model,'envelopes')
        q=QuantSettings(**asdict(model()),core='ANP');r=quantify(a,b,q);remember_result(a,b,q,r)
        requests=batch_plan([a,b],default_parameters())
        self.assertEqual([v.settings.model for v in requests],['core_template','envelopes'])
        row=summary_row(requests[0],r)
        self.assertEqual(row['decomposition_model'],'Legacy core template (0.10.7-0.10.8)');self.assertGreater(row['coverage_lower_percent'],0)
        old=default_parameters()
        for row in old['ligands']:row.pop('schiff_h');row.pop('michael_h')
        migrated=validate_parameters(old)
        self.assertIsNone(migrated['ligands'][-1]['effective_h'])
        self.assertIsNone(migrated['ligands'][0]['schiff_h'])

    def test_styles_visibility_and_png_contain_selected_model_curves(self):
        a,b,_=data_pair();p=preview_spectrum(a);fit=decompose(p,model(),preview_spectrum(b))
        a.metadata.update(curve_colors={'ligand':'#123ABC'},decomposition_styles={'ligand':{'width':3.5,'line_style':'--'}})
        fig=Figure();FigureCanvasAgg(fig);ax=fig.add_subplot(111)
        draw_hnmr(ax,a,p,PlotOptions(),fit)
        line=next(v for v in ax.lines if v.get_label()=='Additional ligand component')
        self.assertEqual(line.get_color(),'#123ABC');self.assertEqual(line.get_linewidth(),3.5)
        self.assertEqual(line.get_linestyle(),'--');self.assertEqual(len(ax.lines),4)
        self.assertNotIn('Residual (data - fit)',[v.get_label() for v in ax.lines])
        self.assertTrue(figure_png_bytes(fig).startswith(b'\x89PNG'))

    def test_reaction_endpoints_are_conditional_sorted_and_editable(self):
        q=QuantSettings(capacity_umol_mg=.1)
        counts,r= reaction_coverage(.13,q)
        self.assertEqual(counts,{'schiff_H_per_ligand':13.,'michael_H_per_ligand':14.})
        self.assertAlmostEqual(r['coverage_schiff_percent'],10)
        self.assertAlmostEqual(r['coverage_michael_percent'],10*13/14)
        _,same=reaction_coverage(.13,replace(q,include_linkage_nh=False))
        self.assertEqual(same['coverage_lower_percent'],same['coverage_upper_percent'])
        _,negative=reaction_coverage(-.13,q)
        self.assertLess(negative['coverage_lower_percent'],negative['coverage_upper_percent'])
        counts,custom=reaction_coverage(.13,replace(q,schiff_h=10,michael_h=20))
        self.assertEqual(counts['schiff_H_per_ligand'],10.)
        self.assertAlmostEqual(custom['coverage_lower_percent'],6.5)
        self.assertAlmostEqual(custom['coverage_upper_percent'],13.)
        with self.assertRaisesRegex(ValueError,'schiff_h'):replace(q,schiff_h=0).validate()

    def test_review_and_independent_phase_scenarios_keep_inputs_unchanged(self):
        a,b,_=data_pair()
        before=(a.real.copy(),b.real.copy(),deepcopy(a.metadata))
        report=model_review(preview_spectrum(a),model(),preview_spectrum(b))
        self.assertIn('ligand_integral',report['rows'][0])
        self.assertFalse(any('error' in row for row in report['rows']))
        a.processing['settings']['phase']=True;b.processing['settings']['phase']=True
        cfg=replace(model(),line_shape='gaussian')
        report=phase_sensitivity(a,b,settings=cfg)
        self.assertEqual(len(report['rows']),9)
        self.assertIn('reference_phase_offset_deg',report['rows'][0])
        np.testing.assert_array_equal(a.real,before[0]);np.testing.assert_array_equal(b.real,before[1])
        self.assertEqual(a.metadata,before[2])


if __name__ == '__main__':unittest.main()
