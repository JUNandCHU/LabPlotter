"""Regression coverage for manual-camera metadata and numbered NTA exports.

All fixtures are synthetic; instrument measurement files stay outside the repo.
"""
import csv
from io import StringIO
import unittest

import numpy as np

from labplotter.nta import NTAImportError, import_nta_zips, parse_summary, qc_rows
from test_nta import archive, csv_bytes, members, summary


def replace_summary_field(payload, key, value):
    rows = list(csv.reader(StringIO(payload.decode('cp1252'))))
    for row in rows:
        if row and row[0] == key:
            row[1:] = [value] * (len(row) - 1)
    return csv_bytes(rows)


def export_set(suffix='', threshold='2', camera='Manual settings used', sample='Example'):
    """One synthetic export; the suffix is not part of the acquisition name."""
    result = {}
    for filename, payload in members().items():
        if filename.endswith('Summary.csv'):
            payload = replace_summary_field(payload, 'Camera Level', camera)
            payload = replace_summary_field(payload, 'Detection Threshold', threshold)
        filename = filename.replace('Example', sample)
        payload = payload.replace(b'Example', sample.encode('ascii'))
        result[filename[:-4] + suffix + '.csv'] = payload
    return result


class NTAManualCameraTests(unittest.TestCase):
    def test_manual_camera_value_is_preserved_in_experiment_and_video_summaries(self):
        for value in ('Manual settings used', 'manual settings used', 'MANUAL SETTINGS USED'):
            with self.subTest(value=value):
                data = export_set(camera=value)
                pack = import_nta_zips([archive(data)], expected_runs=2)[0]
                self.assertEqual(pack.summary.conditions['Camera Level'], [value, value])
                single = parse_summary(data['Example 0_Summary.csv'], experiment=False)
                self.assertEqual(single.conditions['Camera Level'], [value])
                self.assertEqual(pack.summary.conditions['Shutter/ms'], ['1', '1'])
                self.assertEqual(pack.summary.conditions['Slider Gain'], ['1', '1'])

    def test_numeric_and_mixed_camera_values_remain_valid(self):
        numeric = replace_summary_field(summary(), 'Camera Level', '12')
        self.assertEqual(parse_summary(numeric).conditions['Camera Level'], ['12', '12'])
        mixed = numeric.replace(b'Camera Level,12,12', b'Camera Level,Manual settings used,12')
        self.assertEqual(parse_summary(mixed).conditions['Camera Level'], ['Manual settings used', '12'])

    def test_missing_unknown_and_nonfinite_camera_values_are_rejected(self):
        for value in ('', 'Unknown', 'Manual', 'NaN', 'Infinity', '-inf'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_summary(replace_summary_field(summary(), 'Camera Level', value))

    def test_manual_camera_does_not_relax_other_numeric_conditions(self):
        for key in ('Frame rate/fps', 'Shutter/ms', 'Slider Gain'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                data = replace_summary_field(summary(), 'Camera Level', 'Manual settings used')
                parse_summary(replace_summary_field(data, key, 'not recorded'))


class NTANumberedExportTests(unittest.TestCase):
    def three_exports(self):
        return {**export_set(), **export_set('_1', '4'), **export_set('_2', '6')}

    def test_three_analysis_exports_keep_distinct_names_ids_and_thresholds(self):
        packs = import_nta_zips([archive(self.three_exports())], expected_runs=2)
        self.assertEqual(len(packs), 3)
        self.assertEqual(len({p.uid for p in packs}), 3)
        self.assertEqual(len({p.name for p in packs}), 3)
        by_threshold = {p.summary.settings['Detection Threshold'][0]: p for p in packs}
        self.assertEqual(set(by_threshold), {'2', '4', '6'})
        for threshold, suffix in (('4', '_1'), ('6', '_2')):
            self.assertIn(suffix, by_threshold[threshold].name)
            self.assertIn(threshold, by_threshold[threshold].name)
            self.assertEqual(by_threshold[threshold].analysis_suffix, suffix)
        for pack in packs:
            self.assertEqual(pack.summary.runs, ['Example 0', 'Example 1'])
            self.assertEqual([video.name for video in pack.videos], pack.summary.runs)
            self.assertEqual(pack.summary.settings['Detection Threshold'], [
                pack.summary.settings['Detection Threshold'][0]] * 2)
            np.testing.assert_equal(pack.summary.distributions[('Size', 'Number')].stats['Mean'], [50, 50])
            self.assertEqual(len(pack.videos[0].tracks), 5)

        exported = qc_rows([by_threshold['4']])
        self.assertEqual(len(exported), 2)
        for row in exported:
            self.assertEqual(row['analysis_export_suffix'], '_1')
            self.assertEqual(row['conditions/Camera Level'], 'Manual settings used')
            self.assertEqual(row['settings/Detection Threshold'], '4')

    def test_numbered_export_can_import_without_an_unsuffixed_export(self):
        for suffix in ('_1', '_2', '_12'):
            with self.subTest(suffix=suffix):
                data = {'nested/' + k: v for k, v in export_set(suffix, '6').items()}
                packs = import_nta_zips([archive(data)], expected_runs=2)
                self.assertEqual(len(packs), 1)
                self.assertEqual(len(packs[0].videos), 2)
                self.assertIn(suffix, packs[0].name)

    def test_numbers_inside_sample_name_are_not_export_suffixes(self):
        data = {**export_set(sample='Trial_1'), **export_set('_2', '6', sample='Trial_1')}
        packs = import_nta_zips([archive(data)], expected_runs=2)
        self.assertEqual(len(packs), 2)
        for pack in packs:
            self.assertEqual(pack.summary.runs, ['Trial_1 0', 'Trial_1 1'])
            self.assertIn('Trial_1', pack.name)

    def test_missing_variant_member_cannot_use_a_different_export(self):
        for role in ('Summary', 'ParticleData', 'AllTracks'):
            with self.subTest(role=role):
                data = self.three_exports()
                missing = f'Example 0_{role}_1.csv'
                del data[missing]
                with self.assertRaises(NTAImportError) as caught:
                    import_nta_zips([archive(data)], expected_runs=2)
                self.assertIn('missing ' + missing, str(caught.exception))

    def test_missing_whole_variant_video_is_still_reported(self):
        data = {name: payload for name, payload in self.three_exports().items()
                if not (name.startswith('Example 1_') and name.endswith('_2.csv'))}
        with self.assertRaises(NTAImportError) as caught:
            import_nta_zips([archive(data)], expected_runs=2)
        for role in ('Summary', 'ParticleData', 'AllTracks'):
            self.assertIn(f'Example 1_{role}_2.csv', str(caught.exception))

    def test_cross_file_summary_checks_still_apply_within_a_variant(self):
        data = self.three_exports()
        name = 'Example 0_Summary_2.csv'
        data[name] = replace_summary_field(data[name], 'Detection Threshold', '8')
        with self.assertRaises(NTAImportError) as caught:
            import_nta_zips([archive(data)], expected_runs=2)
        self.assertIn('Detection Threshold', str(caught.exception))
        self.assertIn('disagrees', str(caught.exception))

    def test_repeated_archive_is_deduplicated_without_combining_analysis_exports(self):
        packs = import_nta_zips([archive(self.three_exports()), archive(self.three_exports())], 2)
        self.assertEqual(len(packs), 3)

    def test_failed_manifest_has_no_misleading_child_orphan_flood(self):
        data = self.three_exports()
        name = 'Example-ExperimentSummary_1.csv'
        data[name] = replace_summary_field(data[name], 'Camera Level', 'unknown camera')
        with self.assertRaises(NTAImportError) as caught:
            import_nta_zips([archive(data)], expected_runs=2)
        message = str(caught.exception)
        self.assertIn('Camera Level', message)
        self.assertIn(name, message)
        self.assertNotIn('no matching ExperimentSummary entry', message)

    def test_real_orphans_and_unknown_suffixes_are_still_rejected(self):
        for filename in ('Orphan_AllTracks_1.csv', 'Example 0_AllTracks_extra.csv'):
            with self.subTest(filename=filename):
                data = export_set()
                data[filename] = members()['Example 0_AllTracks.csv']
                with self.assertRaises(NTAImportError) as caught:
                    import_nta_zips([archive(data)], expected_runs=2)
                self.assertIn(filename, str(caught.exception))

    def test_a_broken_variant_blocks_the_entire_multi_zip_import(self):
        data = export_set('_1', '4')
        del data['Example 0_ParticleData_1.csv']
        with self.assertRaises(NTAImportError) as caught:
            import_nta_zips([archive(export_set()), archive(data)], expected_runs=2)
        self.assertIn('no new data loaded', str(caught.exception))
        self.assertIn('Example 0_ParticleData_1.csv', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
