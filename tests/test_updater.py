from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch as mock_patch

from tools.make_labpatch import build_patch, build_snapshot_patch
from updater import UpdateError, apply_labpatch, available_backups, rollback_backup


def write_install(root: Path, version: str, value: str, include_obsolete: bool = False) -> None:
    package = root / "labplotter"
    package.mkdir(parents=True)
    (root / "version.json").write_text(
        json.dumps({"version": version, "patch_format": 1}), encoding="utf-8"
    )
    (package / "__init__.py").write_text(
        f'__version__ = "{version}"\n', encoding="utf-8"
    )
    (package / "value.py").write_text(f'VALUE = "{value}"\n', encoding="utf-8")
    (root / "requirements.txt").write_text("", encoding="utf-8")
    (root / "run_labplotter.bat").write_text("@echo off\n", encoding="utf-8")
    if include_obsolete:
        (package / "obsolete.py").write_text("OBSOLETE = True\n", encoding="utf-8")


class UpdaterTests(unittest.TestCase):
    def test_apply_and_rollback_patch(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            installed, target = temporary / "installed", temporary / "target"
            write_install(installed, "0.3.0", "old", include_obsolete=True)
            write_install(target, "0.3.1", "new")
            (target / "labplotter" / "new_feature.py").write_text("ENABLED = True\n", encoding="utf-8")
            patch = temporary / "update.labpatch"
            manifest = build_patch(installed, target, "0.3.0", "0.3.1", patch, "Updater test")

            self.assertTrue(manifest["files"])
            result = apply_labpatch(patch, installed, run_smoke=False)
            self.assertEqual(result["to_version"], "0.3.1")
            self.assertEqual(json.loads((installed / "version.json").read_text())["version"], "0.3.1")
            self.assertIn('"new"', (installed / "labplotter" / "value.py").read_text())
            self.assertTrue((installed / "labplotter" / "new_feature.py").exists())
            self.assertFalse((installed / "labplotter" / "obsolete.py").exists())

            backups = available_backups(installed)
            self.assertEqual(len(backups), 1)
            restored = rollback_backup(installed, backups[0])
            self.assertEqual(restored, "0.3.0")
            self.assertIn('"old"', (installed / "labplotter" / "value.py").read_text())
            self.assertTrue((installed / "labplotter" / "obsolete.py").exists())
            self.assertFalse((installed / "labplotter" / "new_feature.py").exists())

    def test_modified_install_is_rejected_before_application(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            installed, target = temporary / "installed", temporary / "target"
            write_install(installed, "0.3.0", "old")
            write_install(target, "0.3.1", "new")
            patch = temporary / "update.labpatch"
            build_patch(installed, target, "0.3.0", "0.3.1", patch)
            (installed / "labplotter" / "value.py").write_text('VALUE = "locally changed"\n', encoding="utf-8")

            with self.assertRaises(UpdateError):
                apply_labpatch(patch, installed, run_smoke=False)
            self.assertEqual(json.loads((installed / "version.json").read_text())["version"], "0.3.0")
            self.assertFalse(available_backups(installed))

    def test_failed_post_update_check_restores_previous_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            installed, target = temporary / "installed", temporary / "target"
            write_install(installed, "0.3.0", "old", include_obsolete=True)
            write_install(target, "0.3.1", "new")
            patch = temporary / "update.labpatch"
            build_patch(installed, target, "0.3.0", "0.3.1", patch)

            with mock_patch("updater._smoke_test", side_effect=UpdateError("simulated check failure")):
                with self.assertRaises(UpdateError):
                    apply_labpatch(patch, installed)

            self.assertEqual(json.loads((installed / "version.json").read_text())["version"], "0.3.0")
            self.assertIn('"old"', (installed / "labplotter" / "value.py").read_text())
            self.assertTrue((installed / "labplotter" / "obsolete.py").exists())
            self.assertFalse(available_backups(installed))

    def test_cumulative_snapshot_updates_multiple_versions_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            target = temporary / "target"
            write_install(target, "0.6.0", "latest")
            patch = temporary / "latest.labpatch"
            manifest = build_snapshot_patch(target, "0.6.0", patch, obsolete_paths=["labplotter/obsolete.py"])
            self.assertEqual(manifest["format_version"], 2)
            self.assertEqual(manifest["from_versions"], ["*"])

            for version in ("legacy", "0.3.0", "0.4.7", "0.5.1"):
                installed = temporary / f"installed-{version}"
                original_version = "0.1.1" if version == "legacy" else version
                write_install(installed, original_version, "old", include_obsolete=True)
                if version == "legacy":
                    (installed / "version.json").unlink()
                local_file = installed / "labplotter" / "local_notes.py"
                local_file.write_text("KEEP = True\n", encoding="utf-8")
                completed = SimpleNamespace(returncode=0, stdout="", stderr="")
                with mock_patch("updater.subprocess.run", return_value=completed):
                    result = apply_labpatch(patch, installed, run_smoke=False)
                    self.assertEqual(result["to_version"], "0.6.0")
                    self.assertIn('"latest"', (installed / "labplotter" / "value.py").read_text())
                    self.assertFalse((installed / "labplotter" / "obsolete.py").exists())
                    self.assertTrue(local_file.exists())
                    restored = rollback_backup(installed, Path(result["backup"]))
                self.assertEqual(restored, version)
                self.assertIn('"old"', (installed / "labplotter" / "value.py").read_text())
                self.assertTrue((installed / "labplotter" / "obsolete.py").exists())
                self.assertTrue(local_file.exists())
                self.assertEqual((installed / "version.json").exists(), version != "legacy")


if __name__ == "__main__":
    unittest.main()
