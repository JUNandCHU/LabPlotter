from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch as mock_patch

from tools.make_labpatch import build_patch
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


if __name__ == "__main__":
    unittest.main()
