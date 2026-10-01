"""Ver2 recovery on independent complex synthetic data and all output paths."""
from copy import deepcopy
from dataclasses import asdict, replace
import io
import json
import unittest
import numpy as np
from scipy.special import wofz
from scipy.integrate import trapezoid
from matplotlib.figure import Figure

from labplotter.hnmr import (HNMRSpectrum,HNMRSettings,QuantSettings,process_hnmr,quantify,
                            prepare_spectra,preview_spectrum,result_csv,coverage_algebra)
from labplotter.hnmr_decomposition import (DecompositionSettings,decompose,select_model,restore_decomposition,
                                         decomposition_csv,decomposition_defaults)
from labplotter.hnmr_family import corrected_complex
from labplotter.hnmr_plot import draw_hnmr
from labplotter.hnmr_batch import remember_result
from labplotter.hnmr_library import export_hnmr_library, import_hnmr_library
from labplotter.hnmr_summary import summary_cells,short_status
from labplotter.plotting import PlotOptions


def synthetic():
    x=np.linspace(-205,215,1681)
    shapes=[(1.3,3.7,.25),(7.1,9.,.65),(5.4,24.,.1)]
    heights=np.array([[120,30,22,8,6],[40,14,10,7,4],[10,3,4,2,1.5]])
    orders=[0,-1,1,-2,2]
    def components(xx):
        out=[]
        for (mu,w,eta),hs in zip(shapes,heights):
            out.append(sum(h*((1-eta)*wofz(2*np.sqrt(np.log(2))*(xx-mu-50*n)/w)
                             +eta/(1-2j*(xx-mu-50*n)/w)) for h,n in zip(hs,orders)))
        return out
    t=(x-5)/410
    absorption=sum(components(x))
    z=absorption*np.exp(-1j*np.deg2rad(-12+100*t)) + .6+.2*t+1j*(.4-.1*t)
    s=HNMRSpectrum('ANP',x,z.real,z.imag).validate()
    cfg=HNMRSettings(ppm_min=-200,ppm_max=210,grid_step=.25,phase=True,baseline=True,
                     auto_phase1=True,masked_baseline=True,mas_hz=20000,proton_mhz=400,sideband_spacing=50)
    settings=select_model(decomposition_defaults(s),'broad_core3')
    return s,cfg,settings,components


class FamilyModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s,cls.cfg,cls.settings,components=synthetic()
        cls.components=staticmethod(components)
        cls.p=process_hnmr(cls.s,cls.cfg,phase0=0.,phase1=0.)
        cls.fit=decompose(cls.p,cls.settings)

    def test_complex_recovery_and_finite_integrals_include_independent_satellites(self):
        f=self.fit
        self.assertGreater(f.audit['complex_fit_R2'],.99999999)
        self.assertAlmostEqual(f.audit['phase0_deg'],-12,places=3)
        self.assertAlmostEqual(f.audit['phase1_deg'],100,places=3)
        xx=np.linspace(-145,155,60001)
        for name,part in zip(('aliphatic','aromatic','unassigned'),self.components(xx)):
            self.assertAlmostEqual(f.areas[name]/trapezoid(part.real,xx),1.,places=5)
        self.assertEqual(len(f.audit['lines']),15)
        self.assertLess(np.max(abs(f.residual)),1e-3)
        self.assertGreater(f.areas['unassigned'],0)
        self.assertAlmostEqual(f.areas['aliphatic'],sum(f.audit['area_breakdown']['aliphatic'].values()))
        json.dumps(f.record(),allow_nan=False)

    def test_saved_complex_fit_invalidates_for_imaginary_and_manual_phase_changes(self):
        record=json.loads(json.dumps(self.fit.record()))
        loaded=restore_decomposition(self.p,record)
        self.assertIsNotNone(loaded)
        np.testing.assert_allclose(loaded.observed,self.fit.observed)
        np.testing.assert_allclose(loaded.total,self.fit.total)
        changed=deepcopy(self.p);changed.raw_complex += 1j
        self.assertIsNone(restore_decomposition(changed,record))
        changed=deepcopy(self.p);changed.audit['phase_source']='manual PH0/PH1 override'
        self.assertIsNone(restore_decomposition(changed,record))

    def test_plot_csv_and_library_use_same_corrected_signal(self):
        fig=Figure();ax=fig.add_subplot(111)
        draw_hnmr(ax,self.s,self.p,PlotOptions(),self.fit)
        np.testing.assert_allclose(ax.lines[0].get_ydata(),corrected_complex(self.p,self.fit.audit).real)
        labels=[l.get_label() for l in ax.lines]
        self.assertIn('Aliphatic component',labels);self.assertIn('Aromatic component',labels)
        self.assertNotIn('Residual (data - fit)',labels)
        csv=np.genfromtxt(io.StringIO(decomposition_csv(self.fit)),delimiter=',',names=True)
        np.testing.assert_allclose(csv['processed'],self.fit.observed,rtol=1e-10)
        np.testing.assert_allclose(csv['aliphatic']+csv['aromatic']+csv['unassigned'],csv['total_fit'],rtol=1e-10)
        s=deepcopy(self.s);s.metadata['decomposition']=self.fit.record()
        s.processing={'prepared':False,'group_id':'','settings':asdict(self.cfg),'phase0':0.,'phase1':0.,'shift':0.,'audit':self.p.audit}
        saved=import_hnmr_library(export_hnmr_library([s]))[0]
        restored=restore_decomposition(preview_spectrum(saved),saved.metadata['decomposition'])
        self.assertIsNotNone(restored)
        np.testing.assert_allclose(restored.total,self.fit.total)

    def test_manual_and_disabled_corrections_are_respected(self):
        s=deepcopy(self.s);s.metadata.update(manual_phase0=-12.,manual_phase1=100.)
        p=process_hnmr(s,self.cfg)
        f=decompose(p,self.settings)
        self.assertFalse(f.audit['joint_phase_refined'])
        self.assertEqual(f.audit['phase0_deg'],-12.)
        p=process_hnmr(s,replace(self.cfg,phase=False,baseline=False))
        f=decompose(p,self.settings)
        self.assertEqual(f.audit['phase0_deg'],0.);self.assertEqual(f.audit['phase1_deg'],0.)
        self.assertFalse(f.audit['complex_background_fitted'])
        self.assertEqual(f.audit['complex_background'],[0,0,0,0])

    def test_phase_sensitivity_is_centered_on_joint_fit_and_does_not_reoptimize_zero(self):
        from labplotter.hnmr_stability import phase_sensitivity
        s=deepcopy(self.s)
        prepare_spectra([s],self.cfg)
        s.metadata['decomposition_settings']=asdict(self.settings)
        report=phase_sensitivity(s,phase_step=2.)
        rows=report['rows']
        for row,offset in zip(rows,(-2,0,2)):
            self.assertAlmostEqual(row['phase0_deg'],-12+offset,places=3)
            self.assertAlmostEqual(row['phase1_deg'],100.,places=3)
        self.assertAlmostEqual(rows[1]['aliphatic_area']/self.fit.areas['aliphatic'],1.,places=4)

    def test_real_only_fallback_remains_explicit_and_supports_components(self):
        s=deepcopy(self.s);s.real=sum(self.components(s.x)).real;s.imag[:]=0
        p=process_hnmr(s,replace(self.cfg,phase=False,baseline=False))
        f=decompose(p,self.settings)
        self.assertFalse(f.audit['joint_complex'])
        self.assertTrue(any('Real-only' in w for w in f.warnings))
        np.testing.assert_allclose(f.observed,np.interp(f.x,p.x,p.y))
        for name in f.areas: self.assertAlmostEqual(f.areas[name]/self.fit.areas[name],1.,places=4)

    def test_both_normalizations_and_blank_work_with_ver2_without_unassigned_area(self):
        core=deepcopy(self.s);sample=deepcopy(self.s);sample.uid+='modified';sample.name='ANP-C6'
        sample.real *= 1.1;sample.imag *= 1.1
        prepare_spectra([core,sample],self.cfg)
        for s in (core,sample):
            s.metadata['decomposition']=decompose(preview_spectrum(s),self.settings).record()
        q=QuantSettings(**asdict(self.settings),core='ANP',sample_mass_mg=10.,reference_mass_mg=20.,capacity_umol_mg=.1619)
        for mode in ('mass','aromatic_reference'):
            qq=replace(q,core_scaling=mode)
            r=quantify(sample,core,qq)
            expected=coverage_algebra(r.sample_fit.areas['aliphatic'],r.sample_fit.areas['aromatic'],
                                     r.reference_fit.areas['aliphatic'],r.reference_fit.areas['aromatic'],qq)[1]
            self.assertEqual(r.values['apparent_coverage_percent'],expected['apparent_coverage_percent'])
            self.assertIn('unassigned_integral',r.values)
            self.assertIn('aliphatic',result_csv(r).splitlines()[0]);self.assertIn('aromatic',result_csv(r).splitlines()[0])
            self.assertEqual(summary_cells(sample,r,units='integral')[2],f"{r.values['aliphatic_integral']:.6g}")
            self.assertIn('ON' if mode=='aromatic_reference' else 'OFF',short_status(r))
            remember_result(sample,core,qq,r)
        blank=quantify(core,core,replace(q,sample_mass_mg=20.))
        self.assertAlmostEqual(blank.values['apparent_coverage_percent'],0.,places=10)
        self.assertEqual(DecompositionSettings().model,'envelopes')


if __name__=='__main__':unittest.main()
