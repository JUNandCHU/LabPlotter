"""Import through the actual C/H buttons, including the wrong selected tab."""
import os
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

import numpy as np

from labplotter.hnmr import HNMRSpectrum, parse_hnmr_ascii
from labplotter.hnmr_ui import NMRWorkspace
from labplotter.i18n import tr
from labplotter.models import Spectrum
from labplotter.nmr import parse_topspin_ascii
from labplotter.nmr_import import parse_nmr_ascii


def write_fixtures(folder):
    # Deliberately misleading filenames: only the exported layout decides.
    h = folder / 'MultiCP_시료.txt'
    h.write_text('# LEFT = 12 ppm. RIGHT = -2 ppm.\n# SIZE = 64\n' +
                 '\n'.join(f'{20+i}-{i+1}i' for i in range(64)), encoding='utf-8-sig')
    c = folder / 'Hnmr_carbon.txt'
    c.write_text('\n'.join(f'{i}\t{20+i}\t{100*(12-i)}\t{12-i}'
                            for i in range(16)), encoding='utf-8')
    return h, c


class NMRImportTests(unittest.TestCase):
    def test_auto_import_preserves_both_layouts_and_ignores_filenames(self):
        with tempfile.TemporaryDirectory() as tmp:
            h, c = write_fixtures(Path(tmp))
            proton, carbon = parse_nmr_ascii(h), parse_nmr_ascii(c)
            self.assertIsInstance(proton, HNMRSpectrum)
            self.assertIsInstance(carbon, Spectrum)
            direct_h, direct_c = parse_hnmr_ascii(h), parse_topspin_ascii(c)
            for key in ('x', 'real', 'imag'):
                np.testing.assert_array_equal(getattr(proton, key), getattr(direct_h, key))
            for key in ('x', 'y'):
                np.testing.assert_array_equal(getattr(carbon, key), getattr(direct_c, key))
            self.assertEqual(proton.name, h.stem)
            self.assertEqual(proton.source, str(h))

    def test_complex_tables_accept_every_supported_delimiter_with_comments_and_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sample.csv'
            for delimiter in (',', ';', '\t', '  '):
                with self.subTest(delimiter=delimiter):
                    path.write_text('# exported spectrum\n\n' +
                        delimiter.join(('PPM', 'REAL', 'IMAG')) + '\n' +
                        '\n'.join(delimiter.join(map(str, (i, i*2, -i))) for i in range(8)),
                        encoding='utf-8-sig')
                    s = parse_nmr_ascii(path)
                    self.assertIsInstance(s, HNMRSpectrum)
                    np.testing.assert_array_equal(s.imag, -np.arange(8))

    def test_damaged_complex_file_keeps_specific_size_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            h, _ = write_fixtures(Path(tmp))
            h.write_text(h.read_text(encoding='utf-8-sig').replace('SIZE = 64', 'SIZE = 65'),
                         encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'SIZE says 65 points, but 64 were read'):
                parse_nmr_ascii(h)


class NMRImportDesktopTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest('Tk display unavailable')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {'LABPLOTTER_DATA_DIR': str(self.folder / 'data')})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.addCleanup(self.root.destroy)
        self.hfile, self.cfile = write_fixtures(self.folder)
        self.root.geometry('1250x900')
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.workspace = NMRWorkspace(self.root)
        self.workspace.pack(fill='both', expand=True)
        self.root.update()

    def import_button(self, tab, label, paths):
        pending = [tab]
        while pending:
            widget = pending.pop()
            if isinstance(widget, ttk.Button) and widget.cget('text') == tr(label):
                with patch('tkinter.filedialog.askopenfilenames', return_value=paths):
                    widget.invoke()
                self.root.update()
                self.assertFalse(self.errors)
                return
            pending.extend(widget.winfo_children())
        self.fail(f'Import button missing: {label}')

    def test_complex_import_from_default_c_button_opens_h_and_preserves_complex_data(self):
        workspace = self.workspace
        self.assertEqual(workspace.book.select(), str(workspace.c))
        with patch('tkinter.messagebox.showerror') as error:
            self.import_button(workspace.c, 'Import ASCII TXT…', [str(self.hfile)])
            error.assert_not_called()
        self.assertEqual(workspace.book.select(), str(workspace.h))
        self.assertFalse(workspace.c.spectra)
        self.assertEqual(len(workspace.h.spectra), 1)
        imported = workspace.h.spectra[0]
        direct = parse_hnmr_ascii(self.hfile)
        np.testing.assert_array_equal(imported.imag, direct.imag)
        np.testing.assert_array_equal(imported.real, direct.real)
        self.assertTrue(imported.processing['settings']['phase'])
        self.assertTrue(imported.processing['settings']['baseline'])
        self.assertEqual(len(workspace.h.plot.axis.lines), 1)

    def test_four_column_import_from_h_button_opens_c(self):
        workspace = self.workspace
        workspace.book.select(workspace.h)
        with patch('tkinter.messagebox.showerror') as error:
            self.import_button(workspace.h, 'Import H NMR ASCII...', [str(self.cfile)])
            error.assert_not_called()
        self.assertEqual(workspace.book.select(), str(workspace.c))
        self.assertFalse(workspace.h.spectra)
        self.assertEqual(len(workspace.c.spectra), 1)
        np.testing.assert_array_equal(workspace.c.plot.axis.lines[0].get_ydata(),
                                      parse_topspin_ascii(self.cfile).y)

    def test_mixed_batch_keeps_valid_files_and_reports_bad_files_once(self):
        bad = self.folder / 'bad.txt'
        bad.write_text(self.hfile.read_text(encoding='utf-8-sig').replace('SIZE = 64', 'SIZE = 65'),
                       encoding='utf-8')
        missing = self.folder / 'missing.txt'
        with patch('tkinter.messagebox.showerror') as error:
            self.workspace.add_paths([self.hfile, bad, self.cfile, missing])
            self.root.update()
        self.assertEqual((len(self.workspace.h.spectra), len(self.workspace.c.spectra)), (1, 1))
        self.assertEqual(self.workspace.book.select(), str(self.workspace.c))
        error.assert_called_once()
        self.assertIn('SIZE says 65', error.call_args.args[1])
        self.assertIn('missing.txt', error.call_args.args[1])
        self.assertNotIn('four-column', error.call_args.args[1])
        self.assertFalse(self.errors)
        with patch('tkinter.messagebox.showerror') as error:
            self.import_button(self.workspace.c, 'Import ASCII TXT…', ())
            error.assert_not_called()
        self.assertEqual((len(self.workspace.h.spectra), len(self.workspace.c.spectra)), (1, 1))


if __name__ == '__main__':
    unittest.main()
