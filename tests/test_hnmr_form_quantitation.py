"""Exercise actual desktop form serialization without requiring a Tk display.

The 0.10.7 GUI serialized sideband order as a float while its synthetic wide
tests supplied ints; the central-only GUI test could not expose the crash.
"""
from dataclasses import asdict, replace
import json
from types import SimpleNamespace
import tkinter as tk
import unittest

import numpy as np

from labplotter.hnmr import QuantSettings, default_parameters, preview_spectrum, quantify, restored_quant_settings
from labplotter.hnmr_batch import batch_plan, remember_result
from labplotter.hnmr_decomposition import DecompositionSettings, restore_decomposition, MODEL_LABELS
from labplotter.hnmr_template import fit_template
from labplotter.hnmr_ui import Fields, QUANT_SAMPLE, QUANT_CALIBRATION, QUANT_REGIONS
from test_hnmr_template import data_pair, model


class HNMRFormQuantitationTests(unittest.TestCase):
    def form_values(self, q):
        # Tk variables work in a Tcl interpreter; no X server or window needed.
        interp = tk.Tcl()
        specs = QUANT_SAMPLE + QUANT_CALIBRATION + QUANT_REGIONS
        values = asdict(q)
        values['model'] = MODEL_LABELS[q.model]
        variables = {key: (tk.BooleanVar(interp, value=values[key]) if kind == 'bool' else
                          tk.StringVar(interp, value='' if values[key] is None else str(values[key])))
                     for key, _, kind in specs}
        return Fields.values(SimpleNamespace(specs=specs, vars=variables))

    def test_wide_ver2_desktop_form_blank_and_modified_prepared_and_fresh(self):
        sample, core, _ = data_pair(True)
        raw = (sample.real.copy(), core.real.copy())
        nominal = QuantSettings(**asdict(model(True)), core='ANP')
        for prepared in (False, True):
            for source in (core, sample):
                with self.subTest(prepared=prepared, sample=source.name):
                    entered = self.form_values(replace(nominal, use_prepared=prepared))
                    self.assertIs(type(entered['sideband_order']), float)
                    q = QuantSettings(**entered)
                    result = quantify(source, core, q)
                    expected = quantify(source, core, replace(nominal, use_prepared=prepared))
                    self.assertIs(type(q.sideband_order), int)
                    self.assertIs(type(result.parameters['sideband_order']), int)
                    self.assertIs(type(result.sample_fit.audit['settings']['sideband_order']), int)
                    self.assertEqual(len(result.sample_fit.audit['lines']), 5)
                    self.assertEqual(result.values, expected.values)
                    if source is core:
                        self.assertEqual(result.values['coverage_lower_percent'], 0.)
                        self.assertEqual(result.values['coverage_upper_percent'], 0.)
                    else:
                        self.assertGreater(result.values['coverage_lower_percent'], 0.)
                        self.assertLess(result.values['coverage_lower_percent'], result.values['coverage_upper_percent'])
        np.testing.assert_array_equal(sample.real, raw[0])
        np.testing.assert_array_equal(core.real, raw[1])

    def test_saved_float_order_restores_and_batch_result_is_canonical(self):
        sample, core, _ = data_pair(True)
        values = self.form_values(QuantSettings(**asdict(model(True)), core='ANP'))
        sample.metadata.update(analysis_parameters=json.loads(json.dumps(values)),
                               decomposition_settings={k:values[k] for k in DecompositionSettings.__dataclass_fields__},
                               analysis_reference_uid=core.uid)
        restored = restored_quant_settings(sample, default_parameters())
        self.assertEqual(restored.sideband_order, 2)
        request = batch_plan([sample, core], default_parameters())[0]
        self.assertFalse(request.error)
        result = quantify(sample, core, request.settings)
        remember_result(sample, core, request.settings, result)
        self.assertIs(type(sample.metadata['analysis_parameters']['sideband_order']), int)
        fit = restore_decomposition(preview_spectrum(sample), sample.metadata['decomposition'])
        self.assertIsNotNone(fit)
        np.testing.assert_array_equal(fit.total, result.sample_fit.total)

    def test_direct_template_entry_validates_order_and_rejects_fractional_value(self):
        sample, core, _ = data_pair(True)
        a, b = preview_spectrum(sample), preview_spectrum(core)
        settings = replace(model(True), sideband_order=2.0)
        fit = fit_template(a, b, settings)
        self.assertIs(type(fit.audit['settings']['sideband_order']), int)
        for invalid in (2.5, 0., 5.):
            with self.subTest(order=invalid):
                with self.assertRaisesRegex(ValueError, 'integer from 1 to 4'):
                    fit_template(a, b, replace(model(True), sideband_order=invalid))
                with self.assertRaisesRegex(ValueError, 'integer from 1 to 4'):
                    QuantSettings(**asdict(replace(model(True), sideband_order=invalid))).validate()

    def test_ver1_form_results_are_unchanged(self):
        sample, core, _ = data_pair(True)
        q = QuantSettings(**asdict(replace(model(True), model='envelopes')), core='ANP')
        result = quantify(sample, core, QuantSettings(**self.form_values(q)))
        original = quantify(sample, core, q)
        self.assertEqual(result.values, original.values)
        self.assertEqual(result.parameters['model'], 'envelopes')


if __name__ == '__main__': unittest.main()
