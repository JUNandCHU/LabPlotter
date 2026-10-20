"""Ver3 numerical recovery and compatibility through public analysis paths."""
from copy import deepcopy
from dataclasses import asdict, replace
import io
import json
import unittest
import numpy as np
from scipy.special import wofz
from scipy.integrate import trapezoid
from matplotlib.figure import Figure
from labplotter.hnmr import HNMRSpectrum,HNMRSettings,QuantSettings,process_hnmr,prepare_spectra,preview_spectrum,quantify,coverage_algebra
from labplotter.hnmr_decomposition import decompose,decomposition_defaults,select_model,restore_decomposition,decomposition_csv,DecompositionSettings
from labplotter.hnmr_family import corrected_complex
from labplotter.hnmr_plot import draw_hnmr
from labplotter.hnmr_library import export_hnmr_library,import_hnmr_library
from labplotter.plotting import PlotOptions


def fixture():
    x=np.linspace(-205,215,1681)
    def parts(xx):
        rows=[(1.3,3.7,.25,[120,30,22,8,6]),(7.1,9.,.65,[40,14,10,7,4]),(7.1,24.,.1,[10,3,4,2,1.5])]
        return [sum(h*((1-eta)*wofz(2*np.sqrt(np.log(2))*(xx-mu-50*n)/w)+eta/(1-2j*(xx-mu-50*n)/w))
                    for h,n in zip(hs,[0,-1,1,-2,2])) for mu,w,eta,hs in rows]
    t=(x-5)/410;z=sum(parts(x))*np.exp(-1j*np.deg2rad(-12+100*t))+.6+.2*t+1j*(.4-.1*t)
    s=HNMRSpectrum('ANP',x,z.real,z.imag).validate()
    cfg=HNMRSettings(ppm_min=-200,ppm_max=210,grid_step=.25,mas_hz=20000,proton_mhz=400,sideband_spacing=50)
    q=select_model(decomposition_defaults(s),'broad_aromatic3')
    return s,cfg,q,parts


class Ver3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s,cls.cfg,cls.q,parts=fixture();cls.parts=staticmethod(parts)
        cls.p=process_hnmr(cls.s,cls.cfg,phase0=0.,phase1=0.)
        cls.fit=decompose(cls.p,cls.q)

    def test_known_complex_integrals_shared_center_and_phase(self):
        f=self.fit;xx=np.linspace(-145,155,60001);p=self.parts(xx)
        self.assertEqual(set(f.areas),{'aliphatic','aromatic'})
        self.assertGreater(f.audit['complex_fit_R2'],.99999999)
        self.assertAlmostEqual(f.audit['phase0_deg'],-12.,places=3)
        self.assertAlmostEqual(f.audit['phase1_deg'],100.,places=3)
        for name,truth in [('aliphatic',p[0]),('aromatic',p[1]+p[2])]:
            self.assertAlmostEqual(f.areas[name]/trapezoid(truth.real,xx),1.,places=5)
        self.assertEqual(f.audit['parameters']['aromatic_narrow'][1],f.audit['parameters']['aromatic_broad'][1])
        self.assertEqual(len(f.audit['lines']),15)
        self.assertAlmostEqual(sum(f.audit['subareas'][k] for k in ('aromatic_narrow','aromatic_broad')),f.areas['aromatic'])
        self.assertAlmostEqual(sum(f.audit['area_breakdown']['aromatic'].values()),f.areas['aromatic'])

    def test_corrected_plot_csv_library_and_invalidation(self):
        fig=Figure();ax=fig.add_subplot(111);draw_hnmr(ax,self.s,self.p,PlotOptions(),self.fit)
        np.testing.assert_allclose(ax.lines[0].get_ydata(),corrected_complex(self.p,self.fit.audit).real)
        labels=[l.get_label() for l in ax.lines];self.assertNotIn('Unassigned overlap',labels)
        self.assertIn('Aliphatic component',labels);self.assertIn('Aromatic component',labels)
        self.assertNotIn('Residual (data - fit)',labels)
        csv=np.genfromtxt(io.StringIO(decomposition_csv(self.fit)),delimiter=',',names=True)
        np.testing.assert_allclose(csv['aliphatic']+csv['aromatic'],csv['total_fit'],rtol=1e-10)
        s=deepcopy(self.s);s.metadata.update(decomposition=self.fit.record(),decomposition_settings=asdict(self.q))
        s.processing=dict(prepared=False,group_id='',settings=asdict(self.cfg),phase0=0.,phase1=0.,shift=0.,audit=self.p.audit)
        loaded=import_hnmr_library(export_hnmr_library([s]))[0]
        fit=restore_decomposition(preview_spectrum(loaded),loaded.metadata['decomposition']);self.assertIsNotNone(fit)
        np.testing.assert_allclose(fit.total,self.fit.total)
        json.dumps(fit.record(),allow_nan=False)
        p=deepcopy(self.p);p.raw_complex+=1j;self.assertIsNone(restore_decomposition(p,fit.record()))

    def test_coverage_both_scalings_and_blank(self):
        core=deepcopy(self.s);s=deepcopy(self.s);s.uid+='modified';s.name='ANP-C6';s.real*=1.1;s.imag*=1.1
        prepare_spectra([core,s],self.cfg)
        for item in (core,s):item.metadata['decomposition']=decompose(preview_spectrum(item),self.q).record()
        q=QuantSettings(**asdict(self.q),core='ANP',sample_mass_mg=10.,reference_mass_mg=20.,capacity_umol_mg=.1619)
        for scaling in ['mass','aromatic_reference']:
            qq=replace(q,core_scaling=scaling);r=quantify(s,core,qq)
            f,b=r.sample_fit,r.reference_fit
            expect=coverage_algebra(f.areas['aliphatic'],f.areas['aromatic'],b.areas['aliphatic'],b.areas['aromatic'],qq)[1]
            self.assertEqual(r.values['apparent_coverage_percent'],expect['apparent_coverage_percent'])
        self.assertEqual(quantify(core,core,replace(q,sample_mass_mg=20.)).values['apparent_coverage_percent'],0.)

    def test_manual_phase_baseline_switch_and_real_fallback(self):
        s=deepcopy(self.s);s.metadata.update(manual_phase0=-12.,manual_phase1=100.)
        f=decompose(process_hnmr(s,self.cfg),self.q)
        self.assertFalse(f.audit['joint_phase_refined']);self.assertEqual(f.audit['phase0_deg'],-12.)
        f=decompose(process_hnmr(s,replace(self.cfg,phase=False,baseline=False)),self.q)
        self.assertFalse(f.audit['complex_background_fitted']);self.assertEqual(f.audit['complex_background'],[0.,0.,0.,0.])
        self.assertEqual(f.audit['phase0_deg'],0.)
        s.real=sum(self.parts(s.x)).real;s.imag[:]=0
        f=decompose(process_hnmr(s,replace(self.cfg,phase=False,baseline=False)),self.q)
        self.assertFalse(f.audit['joint_complex'])
        for name in f.areas:self.assertAlmostEqual(f.areas[name]/self.fit.areas[name],1.,places=4)

    def test_phase_sensitivity_uses_nominal_joint_phase(self):
        from labplotter.hnmr_stability import phase_sensitivity
        s=deepcopy(self.s);prepare_spectra([s],self.cfg);s.metadata['decomposition_settings']=asdict(self.q)
        r=phase_sensitivity(s,phase_step=2.)
        for row,offset in zip(r['rows'],[-2,0,2]):
            self.assertAlmostEqual(row['phase0_deg'],-12+offset,places=3)
            self.assertAlmostEqual(row['phase1_deg'],100,places=3)
        self.assertAlmostEqual(r['rows'][1]['aliphatic_area']/self.fit.areas['aliphatic'],1.,places=4)

    def test_presets_do_not_rewrite_old_models(self):
        self.assertEqual(DecompositionSettings().model,'envelopes')
        with self.assertRaises(ValueError):replace(self.q,broad_aromatic_fwhm_max=10.).validate()
        self.assertEqual(replace(self.q,unassigned_fwhm_max=1000.).validate().model,'broad_aromatic3')
        self.assertEqual(select_model(self.q,'broad_core3').validate().model,'broad_core3')
        old=asdict(DecompositionSettings());old.pop('broad_aromatic_fwhm_min');old.pop('broad_aromatic_fwhm_max')
        self.assertEqual(DecompositionSettings(**old).validate().model,'envelopes')
