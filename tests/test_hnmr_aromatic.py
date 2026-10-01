"""Independent spreadsheet algebra, explicit units, migration and display scale."""
from copy import deepcopy
from dataclasses import asdict, replace
import unittest
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

from labplotter.hnmr import (QuantSettings, ProcessedH, coverage_algebra, default_parameters,
                             restored_quant_settings)
from labplotter.hnmr_library import validate_parameters
from labplotter.hnmr_plot import draw_hnmr
from labplotter.plotting import PlotOptions, apply_origin_style
from test_hnmr import fixture


class AromaticQuantitationTests(unittest.TestCase):
    def test_spreadsheet_pda_c6_13H_reproduces_894_percent_and_intermediates(self):
        q = QuantSettings(sample_mass_mg=17.28, reference_mass_mg=18.33)
        steps, result = coverage_algebra(192830223.90855214, 768986144.5055121,
                                        166688903.1345779, 799449726.7379593, q)
        self.assertAlmostEqual(steps['sample_aliphatic_H_umol_per_mg'], .48795593728988496)
        self.assertAlmostEqual(steps['aromatic_normalization_factor'], .9800628263498697)
        self.assertAlmostEqual(steps['normalized_sample_aliphatic_H_umol_per_mg'], .47822747503452445)
        self.assertAlmostEqual(steps['reference_aliphatic_H_umol_per_mg'], .39764311125831886)
        self.assertAlmostEqual(result['apparent_coverage_percent'], 8.944873324032145)
        self.assertAlmostEqual(result['loading_umol_mg'], (.47822747503452445-.39764311125831886)/13)

    def test_mass_and_response_cancellation_only_for_aromatic_matching(self):
        inputs = (200., 300., 50., 200.)
        q = QuantSettings(sample_mass_mg=10, reference_mass_mg=20, standard_area=100., standard_umol_h=2.)
        _, base = coverage_algebra(*inputs, q)
        _, changed = coverage_algebra(*inputs, replace(q, sample_mass_mg=37., response_factor=3.))
        self.assertAlmostEqual(base['apparent_coverage_percent'], changed['apparent_coverage_percent'])
        _, doubled_ref_mass = coverage_algebra(*inputs, replace(q, reference_mass_mg=40.))
        self.assertAlmostEqual(base['apparent_coverage_percent']/2, doubled_ref_mass['apparent_coverage_percent'])
        _, mass_mode = coverage_algebra(*inputs, replace(q, core_scaling='mass'))
        _, mass_changed = coverage_algebra(*inputs, replace(q, core_scaling='mass', sample_mass_mg=37.))
        self.assertNotAlmostEqual(mass_mode['apparent_coverage_percent'], mass_changed['apparent_coverage_percent'])

    def test_anp_new_core_mass_retains_negative_not_clipped(self):
        q = QuantSettings(core='ANP',sample_mass_mg=19.20,reference_mass_mg=38.38,capacity_umol_mg=.1619)
        args = (751048379.6029751,664379967.1234674,1014157062.4382751,481506332.7667056)
        _, result = coverage_algebra(*args,q)
        self.assertAlmostEqual(result['apparent_coverage_percent'],-25.4332808837681)
        _, mass = coverage_algebra(*args,replace(q,core_scaling='mass'))
        self.assertAlmostEqual(mass['apparent_coverage_percent'],26.370801604343843)
        for invalid in (0.,-1.):
            with self.assertRaisesRegex(ValueError,'positive.*aromatic'):
                coverage_algebra(args[0],invalid,*args[2:],q)

    def test_parameter_migration_is_idempotent_and_preserves_custom_amounts(self):
        old = default_parameters();old['version']=1
        standard=old['standards'][0];standard['mmol_h']=standard.pop('umol_h')
        old['standards'].append(dict(standard, name='Custom',mmol_h=.012))
        old['standards'].append(dict(standard, name='Verified legacy',verified=True))
        for row in old['samples']:
            if row['name']=='ANP':row['mass_mg']=19.25
            if row['name']=='ANP-DMEN(+)':row['mass_mg']=42.3
        original=deepcopy(old);new=validate_parameters(old)
        self.assertEqual(old,original)
        self.assertEqual(new['standards'][0]['umol_h'],1.861273386)
        self.assertEqual(new['standards'][1]['umol_h'],12.)
        self.assertAlmostEqual(new['standards'][2]['umol_h'],1861.273386)
        masses={r['name']:r['mass_mg'] for r in new['samples']}
        self.assertEqual(masses['ANP'],38.38);self.assertEqual(masses['ANP-DMEN(+)'],42.3)
        self.assertEqual(new,validate_parameters(new))

    def test_saved_quantitation_migrates_default_but_preserves_custom_and_new_method(self):
        s=fixture('ANP-DMEN');s.metadata['analysis_parameters']={
            'method':'decomposition','core_scaling':'mass','standard_mmol_h':1.861273386,
            'standard_area':42565812.55,'sample_mass_mg':18.27,'reference_mass_mg':19.25}
        q=restored_quant_settings(s,default_parameters())
        self.assertEqual(q.standard_umol_h,1.861273386)
        self.assertEqual((q.sample_mass_mg,q.reference_mass_mg),(55.18,38.38))
        self.assertEqual(q.core_scaling,'aromatic_reference')
        s.metadata['analysis_parameters'].update(standard_mmol_h=.003,standard_area=500,sample_mass_mg=32.)
        q=restored_quant_settings(s,default_parameters())
        self.assertEqual(q.standard_umol_h,3.);self.assertEqual(q.sample_mass_mg,32.)
        q.core_scaling='mass';s.metadata['analysis_parameters']=asdict(q)
        self.assertEqual(restored_quant_settings(s,default_parameters()).core_scaling,'mass')

    def test_axis_multiplier_is_title_only_and_raw_data_are_preserved(self):
        s=fixture();p=ProcessedH(s.x,s.real*1e7,s.imag,np.zeros_like(s.x),{})
        fig=Figure();FigureCanvasAgg(fig);axis=fig.add_subplot(111)
        opts=PlotOptions('Chemical shift','ppm','Intensity','a.u.')
        draw_hnmr(axis,s,p,opts);apply_origin_style(fig,axis,opts);fig.canvas.draw()
        np.testing.assert_array_equal(axis.lines[0].get_ydata(),p.y)
        self.assertFalse(axis.yaxis.get_offset_text().get_visible())
        self.assertIn('10^{',axis.get_ylabel());self.assertIn('a.u.',axis.get_ylabel())
        self.assertEqual(axis.yaxis.get_major_formatter()(2e8,None),'2')


if __name__=='__main__':unittest.main()
