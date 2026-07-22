from __future__ import annotations

import tempfile
import unittest
import ctypes
import sqlite3
import zipfile
from contextlib import closing
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image
from matplotlib.figure import Figure

from labplotter.clipboard import _configure_windows_clipboard_api, png_to_dib
from labplotter.i18n import LanguageManager, canonical, translate_value
from labplotter.nmr import parse_bruker_zip
from labplotter.ocr import OCR_COLUMNS, _Token, _table_from_tokens
from labplotter.models import ZetaMeasurement
from labplotter.parsers import detect_builtin_kind
from labplotter.plotting import PlotOptions, apply_origin_style, font_family_for_text
from labplotter.processing import asls_baseline, estimate_ftir_baseline, mean_curve, normalize, process_ftir
from labplotter.storage import FormatProfileStore, ParticleLibrary, default_particle_label
from labplotter.ui import ZetaTab


class ProcessingTests(unittest.TestCase):
    def test_baseline_and_normalization(self):
        x = np.linspace(0, 10, 500)
        y = 2 + 0.1 * x - np.exp(-((x - 5) ** 2))
        baseline = asls_baseline(y, lam=1e4, p=0.01, upper=True)
        self.assertEqual(baseline.shape, y.shape)
        scaled = normalize(y, "Min-max (0–1)")
        self.assertAlmostEqual(float(scaled.min()), 0.0)
        self.assertAlmostEqual(float(scaled.max()), 1.0)

    def test_mean_curve(self):
        x = np.linspace(1, 10, 30)
        grid, mean, sd = mean_curve([(x, x), (x, x + 2)], points=40)
        self.assertEqual(len(grid), 40)
        self.assertTrue(np.allclose(mean, grid + 1))
        self.assertTrue(np.all(sd > 0))

    def test_common_ftir_baselines_are_finite(self):
        x = np.linspace(600, 4000, 1200)
        baseline = 70 - 0.001 * x
        y = baseline - 8 * np.exp(-((x - 3400) / 180) ** 2) - 4 * np.exp(-((x - 1600) / 80) ** 2)
        methods = (
            "Linear endpoints (diagonal)", "Rubberband (convex hull)",
            "Modified polynomial (ModPoly)", "AsLS (asymmetric least squares)",
            "arPLS (asymmetrically reweighted PLS)", "airPLS (adaptive reweighted PLS)",
        )
        for method in methods:
            estimate = estimate_ftir_baseline(x, y, method, lam=1e8)
            corrected = process_ftir(x, y, True, method, lam=1e8)
            self.assertEqual(estimate.shape, y.shape)
            self.assertTrue(np.all(np.isfinite(estimate)), method)
            self.assertTrue(np.all(np.isfinite(corrected)), method)

    def test_inverse_centimeter_uses_mathtext(self):
        self.assertEqual(PlotOptions.axis_label("Wavenumber", "cm^-1"), "Wavenumber (cm$^{-1}$)")
        self.assertEqual(PlotOptions.axis_label("Wavenumber", "cm⁻¹"), "Wavenumber (cm$^{-1}$)")

    def test_axis_components_have_independent_fonts_and_colors(self):
        figure = Figure()
        axis = figure.add_subplot(111)
        axis.plot([0, 1], [0, 1])
        options = PlotOptions(
            "Chemical shift", "ppm", "Intensity", "a.u.",
            tick_font_size=9, tick_color="#112233",
            x_font_size=15, x_color="#223344", x_bold=False,
            y_font_size=17, y_color="#334455", y_bold=True,
        )
        apply_origin_style(figure, axis, options)
        self.assertEqual(axis.xaxis.label.get_fontsize(), 15)
        self.assertEqual(axis.yaxis.label.get_fontsize(), 17)
        self.assertEqual(axis.xaxis.label.get_color(), "#223344")
        self.assertEqual(axis.yaxis.label.get_color(), "#334455")
        self.assertIsInstance(font_family_for_text("Arial", "화학적 이동"), str)


class StorageTests(unittest.TestCase):
    def test_empty_library_and_profiles(self):
        with tempfile.TemporaryDirectory() as temp:
            library = ParticleLibrary(Path(temp) / "library.sqlite3")
            self.assertEqual(library.particles(), [])
            profiles = FormatProfileStore(Path(temp) / "profiles.json")
            profiles.save_profile({"name": "A", "x_column": "A", "y_columns": ["B"]})
            profiles.save_profile({"name": "A", "x_column": "A", "y_columns": ["C"]})
            self.assertEqual(len(profiles.load()), 1)
            self.assertEqual(profiles.load()[0]["y_columns"], ["C"])

    def test_particle_library_sort_and_delete(self):
        with tempfile.TemporaryDirectory() as temp:
            library = ParticleLibrary(Path(temp) / "library.sqlite3")
            measurements = [
                ZetaMeasurement("Beta", "DLS", 1, np.array([1, 2, 3]), np.array([3, 2, 1]), "b.xlsx", "B"),
                ZetaMeasurement("Alpha", "Zeta", 1, np.array([-1, 0, 1]), np.array([1, 3, 1]), "a.xlsx", "A"),
                ZetaMeasurement("Alpha", "Zeta", 2, np.array([-1, 0, 1]), np.array([1, 4, 1]), "a.xlsx", "A"),
            ]
            library.import_measurements(measurements)
            self.assertEqual([row["name"] for row in library.particles()], ["Alpha", "Beta"])
            self.assertEqual(library.particles("zeta_count", True)[0]["name"], "Alpha")
            self.assertEqual(library.delete_particles(["Alpha"]), 1)
            self.assertEqual([row["name"] for row in library.particles()], ["Beta"])
            self.assertEqual(library.measurements(["Alpha"], "Zeta")["Alpha"], [])

    def test_reviewed_ocr_is_stored_and_deleted_with_particle(self):
        with tempfile.TemporaryDirectory() as temp:
            library = ParticleLibrary(Path(temp) / "library.sqlite3")
            library.import_measurements([
                ZetaMeasurement("Sample", "DLS", 1, np.array([1, 2]), np.array([3, 4]), "a.xlsx", "A")
            ])
            rows = [["Z-Average (nm)", "738.9", "", "", "738.9", "738.9"]]
            library.save_ocr_result("Sample", "DLS", 1, OCR_COLUMNS, rows, [[0.99] * 6], "test")
            saved = library.ocr_result("Sample", "DLS", 1)
            self.assertEqual(saved["rows"], rows)
            self.assertEqual(library.particles()[0]["ocr_count"], 1)
            library.delete_particles(["Sample"])
            self.assertIsNone(library.ocr_result("Sample", "DLS", 1))

    def test_automatic_ocr_summaries_and_batch_labels(self):
        with tempfile.TemporaryDirectory() as temp:
            library = ParticleLibrary(Path(temp) / "library.sqlite3")
            measurements = []
            for replicate in (1, 2, 3):
                measurements.extend((
                    ZetaMeasurement("241101_JM10A_AMP", "DLS", replicate, np.array([1, 2]), np.array([3, 4]), "a.xlsx", "A"),
                    ZetaMeasurement("241101_JM10A_AMP", "Zeta", replicate, np.array([-1, 1]), np.array([3, 4]), "a.xlsx", "A"),
                ))
            library.import_measurements(measurements)
            for replicate, (z_average, zeta) in enumerate(((100, -20), (110, -22), (120, -24)), start=1):
                library.save_ocr_result("241101_JM10A_AMP", "DLS", replicate, OCR_COLUMNS,
                    [["Z-Average (d.nm)", str(z_average), "", "", "", ""]], [[0.99] * 6], "test", reviewed=False)
                library.save_ocr_result("241101_JM10A_AMP", "Zeta", replicate, OCR_COLUMNS,
                    [["Zeta Potential (mV)", str(zeta), "", "", "", ""]], [[0.99] * 6], "test", reviewed=False)
            row = library.particles()[0]
            self.assertEqual(default_particle_label(row["name"]), "JM10A")
            self.assertEqual(row["plot_label"], "JM10A")
            self.assertAlmostEqual(row["dls_z_mean"], 110)
            self.assertAlmostEqual(row["dls_z_sd"], 10)
            self.assertAlmostEqual(row["zeta_average_mean"], -22)
            self.assertEqual(row["ocr_auto"], 6)
            library.set_plot_label(row["name"], "Custom batch")
            self.assertEqual(library.particles()[0]["plot_label"], "Custom batch")

    def test_pre_070_library_is_reset_once_and_new_database_is_stamped(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "library.sqlite3"
            with closing(sqlite3.connect(path)) as con:
                con.execute("CREATE TABLE legacy_particle(name TEXT)")
                con.execute("INSERT INTO legacy_particle VALUES('old')")
                con.commit()
            library = ParticleLibrary(path)
            with library.connect() as con:
                self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], ParticleLibrary.SCHEMA_GENERATION)
                self.assertIsNone(con.execute("SELECT name FROM sqlite_master WHERE name='legacy_particle'").fetchone())
            library.import_measurements([ZetaMeasurement("Keep", "DLS", 1, np.array([1]), np.array([2]), "a.xlsx", "A")])
            reopened = ParticleLibrary(path)
            self.assertEqual(reopened.particles()[0]["name"], "Keep")


class OCRTests(unittest.TestCase):
    def test_tokens_are_mapped_to_editable_table_columns(self):
        def token(text, x, y):
            return _Token(text, 0.98, x, y, 12)

        centers = [50, 150, 250, 350, 450, 550]
        tokens = [token(label, x, 10) for label, x in zip(OCR_COLUMNS, centers)]
        tokens += [token("Z-Average (nm)", 50, 35), token("738.9", 150, 35), token("738.9", 450, 35), token("738.9", 550, 35)]
        result = _table_from_tokens(tokens, column_centers=centers)
        self.assertEqual(result.columns, OCR_COLUMNS)
        self.assertEqual(result.rows[0], ["Z-Average (nm)", "738.9", "", "", "738.9", "738.9"])


class ZetaDashboardTests(unittest.TestCase):
    def test_distribution_peak_overlay_and_batch_summary_bar(self):
        with tempfile.TemporaryDirectory() as temp:
            library = ParticleLibrary(Path(temp) / "library.sqlite3")
            items = [
                ZetaMeasurement("241101_JM10A_AMP", "DLS", rep, np.array([10, 20, 30]), np.array([1, 8 + rep, 2]), "a.xlsx", "A")
                for rep in (1, 2, 3)
            ]
            library.import_measurements(items)
            for rep, value in enumerate((100, 110, 120), 1):
                library.save_ocr_result(items[0].particle_name, "DLS", rep, OCR_COLUMNS,
                    [["Z-Average (d.nm)", str(value), "", "", "", ""]], [[0.99] * 6], "test", reviewed=False)
            overlays = []
            variable = lambda value: SimpleNamespace(get=lambda: value)
            extension = SimpleNamespace(statistic=variable("Mean"), error_bars=variable(True), error_type=variable("SD"))
            dashboard = SimpleNamespace(
                library=library, active_names=lambda: [items[0].particle_name], mode=variable("Mean ± SD"),
                log_x=variable(True), peak_labels=variable(True), multi_peak_labels=variable(False),
                dls_plot=SimpleNamespace(register_overlay=overlays.append), zeta_plot=SimpleNamespace(register_overlay=lambda artist: None),
                dls_batch_settings=extension, zeta_batch_settings=extension,
            )
            figure = Figure(); axis = figure.add_subplot(111)
            ZetaTab._draw_kind(dashboard, "DLS", axis, PlotOptions("X", "nm", "Y", "%"))
            self.assertEqual(len(overlays), 1)
            self.assertEqual(axis.get_xscale(), "log")
            axis.clear()
            ZetaTab._draw_batch(dashboard, "DLS", axis, PlotOptions("Batch", "", "Z-average", "nm"))
            self.assertEqual(len(axis.patches), 1)
            self.assertAlmostEqual(axis.patches[0].get_height(), 110)


class ClipboardAndLanguageTests(unittest.TestCase):
    def test_windows_api_uses_pointer_sized_return_types(self):
        class Function:
            pass

        class Library:
            pass

        kernel32, user32 = Library(), Library()
        for name in ("GlobalAlloc", "GlobalLock", "GlobalUnlock", "GlobalFree"):
            setattr(kernel32, name, Function())
        for name in ("OpenClipboard", "EmptyClipboard", "SetClipboardData", "CloseClipboard"):
            setattr(user32, name, Function())
        _configure_windows_clipboard_api(kernel32, user32)
        self.assertIs(kernel32.GlobalLock.restype, ctypes.c_void_p)
        self.assertEqual(kernel32.GlobalAlloc.argtypes[1], ctypes.c_size_t)

    def test_png_is_converted_to_valid_dib(self):
        source = BytesIO()
        Image.new("RGB", (3, 2), (10, 20, 30)).save(source, format="PNG")
        dib = png_to_dib(source.getvalue())
        self.assertEqual(int.from_bytes(dib[:4], "little"), 40)
        self.assertEqual(int.from_bytes(dib[4:8], "little", signed=True), 3)
        self.assertEqual(int.from_bytes(dib[8:12], "little", signed=True), 2)

    def test_language_is_saved_and_canonical_values_are_stable(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            manager = LanguageManager(path)
            self.assertEqual(manager.current, "en")
            manager.set("ko")
            self.assertEqual(LanguageManager(path).current, "ko")
            self.assertEqual(translate_value("White", "en", "ko"), "흰색")
            self.assertEqual(canonical("흰색"), "White")
            self.assertEqual(translate_value("Installed version: 0.3.1", "en", "ko"), "설치된 버전: 0.3.1")
            self.assertEqual(canonical("Zeta 전위"), "Zeta")


class SolidStateNMRTests(unittest.TestCase):
    def test_bruker_zip_imports_1d_fid_and_reports_ser(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.zip"
            points = 128
            time = np.arange(points) / 1000.0
            fid = 100000 * np.exp(-time * 40.0) * np.exp(2j * np.pi * 100.0 * time)
            interleaved = np.empty(points * 2, dtype="<i4")
            interleaved[0::2] = np.real(fid).astype(np.int32)
            interleaved[1::2] = np.imag(fid).astype(np.int32)
            acqus = "\n".join((
                "##$TD= 256", "##$DTYPA= 0", "##$BYTORDA= 0", "##$NC= 0",
                "##$GRPDLY= 0", "##$SW_h= 1000", "##$SFO1= 100", "##$O1= 0",
                "##$NUC1= <13C>", "##$PULPROG= <cp>", "##$MASR= 10000", "##$NS= 16",
            ))
            procs = "\n".join((
                "##$SI= 512", "##$SW_p= 1000", "##$SF= 100", "##$OFFSET= 5",
                "##$AXNUC= <13C>", "##$WDW= 0", "##$LB= 0", "##$PHC0= 0", "##$PHC1= 0",
            ))
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("sample/1/acqus", acqus)
                archive.writestr("sample/1/fid", interleaved.tobytes())
                archive.writestr("sample/1/pdata/1/procs", procs)
                archive.writestr("sample/1/pdata/1/title", "synthetic 13C")
                archive.writestr("sample/2/acqus", acqus)
                archive.writestr("sample/2/ser", b"pseudo-2D")
            self.assertEqual(detect_builtin_kind(path), "ssNMR")
            spectra, skipped = parse_bruker_zip(path)
            self.assertEqual(len(spectra), 1)
            self.assertEqual(spectra[0].metadata["nucleus"], "13C")
            self.assertEqual(len(spectra[0].x), 512)
            self.assertTrue(np.all(np.isfinite(spectra[0].y)))
            self.assertTrue(any("pseudo-2D" in item for item in skipped))


if __name__ == "__main__":
    unittest.main()
