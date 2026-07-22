from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable

from labplotter.i18n import tr


PATCH_FORMATS = {1, 2}
UPDATER_VERSION = 2
PRODUCT = "LabPlotter"
ALLOWED_DIRECTORIES = {"labplotter", "tools", "tests"}
ALLOWED_ROOT_FILES = {
    "README.md", "README_KO.md", "CHANGELOG.md", "requirements.txt", "requirements-build.txt", "pyproject.toml", "version.json",
    "run_labplotter.bat", "build_windows.bat", "apply_update.bat",
    "rollback_last_update.bat", "update_to_latest.bat", "launcher.py", "updater.py",
}
IGNORED_PARTS = {"__pycache__", ".venv", ".buildvenv", ".updates", "build", "dist"}


class UpdateError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_relative_path(value: str) -> Path:
    pure = PurePosixPath(value)
    if not value or pure.is_absolute() or ".." in pure.parts or "." in pure.parts:
        raise UpdateError(tr("Unsafe patch path: {path}", path=repr(value)))
    if "\\" in value or ":" in value:
        raise UpdateError(tr("Non-portable patch path: {path}", path=repr(value)))
    if pure.parts[0] not in ALLOWED_DIRECTORIES and value not in ALLOWED_ROOT_FILES:
        raise UpdateError(tr("Patch path is outside the LabPlotter allowlist: {path}", path=value))
    if any(part in IGNORED_PARTS for part in pure.parts):
        raise UpdateError(tr("Patch cannot modify protected directory: {path}", path=value))
    return Path(*pure.parts)


def read_current_version(app_root: Path, allow_legacy: bool = False) -> str:
    path = app_root / "version.json"
    if not path.exists():
        if allow_legacy and (app_root / "labplotter").is_dir() and (app_root / "run_labplotter.bat").is_file():
            return "legacy"
        raise UpdateError(tr("version.json is missing; this installation cannot accept .labpatch files."))
    try:
        value = json.loads(path.read_text(encoding="utf-8"))["version"]
    except Exception as exc:
        raise UpdateError(tr("Could not read the installed version: {error}", error=exc)) from exc
    return str(value)


def read_manifest(archive: zipfile.ZipFile) -> dict:
    try:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
    except KeyError as exc:
        raise UpdateError(tr("The patch does not contain manifest.json.")) from exc
    except Exception as exc:
        raise UpdateError(tr("Invalid manifest.json: {error}", error=exc)) from exc
    if manifest.get("format_version") not in PATCH_FORMATS:
        raise UpdateError(tr("Unsupported patch format: {format}", format=manifest.get("format_version")))
    if manifest.get("product") != PRODUCT:
        raise UpdateError(tr("This patch is not for LabPlotter."))
    if not isinstance(manifest.get("from_versions"), list) or not manifest.get("to_version"):
        raise UpdateError(tr("Patch version metadata is incomplete."))
    if not isinstance(manifest.get("files", []), list) or not isinstance(manifest.get("delete", []), list):
        raise UpdateError(tr("Patch file lists are invalid."))
    if manifest.get("format_version") == 2:
        if manifest.get("mode") != "snapshot" or manifest.get("from_versions") != ["*"]:
            raise UpdateError(tr("Invalid cumulative snapshot metadata."))
        if not isinstance(manifest.get("managed_paths"), list):
            raise UpdateError(tr("Invalid cumulative snapshot metadata."))
    return manifest


def _validate_patch_contents(archive: zipfile.ZipFile, manifest: dict, app_root: Path) -> list[tuple[dict, Path, bytes]]:
    output = []
    seen = set()
    snapshot = manifest.get("format_version") == 2 and manifest.get("mode") == "snapshot"
    for entry in manifest.get("files", []):
        if not isinstance(entry, dict) or not all(key in entry for key in ("path", "sha256", "size")):
            raise UpdateError(tr("A patch file entry is incomplete."))
        relative = validate_relative_path(str(entry["path"]))
        normalized = relative.as_posix()
        if normalized in seen:
            raise UpdateError(tr("Duplicate patch path: {path}", path=normalized))
        seen.add(normalized)
        try:
            data = archive.read(f"payload/{normalized}")
        except KeyError as exc:
            raise UpdateError(tr("Patch payload is missing: {path}", path=normalized)) from exc
        if len(data) != int(entry["size"]) or sha256_bytes(data) != entry["sha256"]:
            raise UpdateError(tr("Checksum validation failed: {path}", path=normalized))
        destination = app_root / relative
        if not snapshot:
            old_hash = entry.get("old_sha256")
            if old_hash is None:
                if destination.exists():
                    raise UpdateError(tr("Patch expected a new file, but it already exists: {path}", path=normalized))
            elif not destination.exists() or sha256_file(destination) != old_hash:
                raise UpdateError(tr("Installed file differs from the expected base version: {path}", path=normalized))
        output.append((entry, relative, data))

    if snapshot:
        managed = [validate_relative_path(str(path)).as_posix() for path in manifest.get("managed_paths", [])]
        if len(managed) != len(set(managed)) or set(managed) != seen:
            raise UpdateError(tr("Cumulative snapshot file inventory is incomplete."))

    for entry in manifest.get("delete", []):
        if not isinstance(entry, dict) or "path" not in entry or (not snapshot and "old_sha256" not in entry):
            raise UpdateError(tr("A delete entry is incomplete."))
        relative = validate_relative_path(str(entry["path"]))
        normalized = relative.as_posix()
        if normalized in seen:
            raise UpdateError(tr("A path cannot be replaced and deleted together: {path}", path=normalized))
        seen.add(normalized)
        destination = app_root / relative
        if not snapshot and (not destination.exists() or sha256_file(destination) != entry["old_sha256"]):
            raise UpdateError(tr("File scheduled for deletion differs from the expected base: {path}", path=normalized))
    return output


def _app_data_dir() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        return root / PRODUCT
    return Path.home() / ".local" / "share" / PRODUCT


def _backup_installation(app_root: Path, manifest: dict, files: list[tuple[dict, Path, bytes]], current: str | None = None) -> Path:
    updates = app_root / ".updates"
    backups = updates / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    current = current or read_current_version(app_root)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = backups / f"{stamp}_{current}_to_{manifest['to_version']}"
    file_backup = backup / "files"
    file_backup.mkdir(parents=True)
    backed_up, created = [], []
    all_paths = [relative for _, relative, _ in files]
    all_paths.extend(validate_relative_path(str(entry["path"])) for entry in manifest.get("delete", []))
    for relative in all_paths:
        source = app_root / relative
        if source.exists():
            destination = file_backup / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            backed_up.append(relative.as_posix())
        else:
            created.append(relative.as_posix())

    database_backup = None
    if manifest.get("database_migration"):
        database = _app_data_dir() / "particle_library.sqlite3"
        if database.exists():
            database_backup = "particle_library.sqlite3"
            shutil.copy2(database, backup / database_backup)

    dependency_snapshot = None
    if manifest.get("requirements_changed"):
        result = subprocess.run(
            [str(_python_console_executable()), "-m", "pip", "freeze"],
            cwd=app_root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode:
            raise UpdateError(tr("Could not snapshot the current Python environment.\n{details}", details=result.stderr[-3000:]))
        dependency_snapshot = "pip_freeze_before.txt"
        (backup / dependency_snapshot).write_text(result.stdout, encoding="utf-8")

    backup_manifest = {
        "format_version": 1,
        "status": "prepared",
        "from_version": current,
        "to_version": manifest["to_version"],
        "created_at": utc_now(),
        "backed_up_files": backed_up,
        "created_files": created,
        "database_backup": database_backup,
        "dependency_snapshot": dependency_snapshot,
        "patch_notes": manifest.get("notes", ""),
    }
    (backup / "backup_manifest.json").write_text(json.dumps(backup_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return backup


def _write_backup_status(backup: Path, status: str, **extra) -> None:
    path = backup / "backup_manifest.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["status"] = status
    value[f"{status}_at"] = utc_now()
    value.update(extra)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def rollback_backup(app_root: Path, backup: Path, status: Callable[[str], None] | None = None) -> str:
    report = status or (lambda _message: None)
    path = backup / "backup_manifest.json"
    if not path.exists():
        raise UpdateError(tr("The selected backup is incomplete."))
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("status") == "applied" and read_current_version(app_root) != str(value.get("to_version")):
        raise UpdateError(tr("This backup does not match the currently installed version."))
    report(tr("Restoring LabPlotter {version}…", version=value["from_version"]))
    for relative_text in value.get("backed_up_files", []):
        relative = validate_relative_path(relative_text)
        source = backup / "files" / relative
        destination = app_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".rollback_tmp")
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    for relative_text in value.get("created_files", []):
        destination = app_root / validate_relative_path(relative_text)
        if destination.is_file():
            destination.unlink()
    if value.get("database_backup"):
        source = backup / value["database_backup"]
        destination = _app_data_dir() / "particle_library.sqlite3"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    if value.get("dependency_snapshot"):
        report(tr("Restoring the previous Python dependency versions…"))
        snapshot = backup / value["dependency_snapshot"]
        result = subprocess.run(
            [str(_python_console_executable()), "-m", "pip", "install", "-r", str(snapshot)],
            cwd=app_root,
            capture_output=True,
            text=True,
            timeout=900,
        )
        if result.returncode:
            detail = (result.stdout + "\n" + result.stderr)[-6000:]
            raise UpdateError(tr("Files were restored, but dependency restoration failed.\n{details}", details=detail))
    _write_backup_status(backup, "rolled_back")
    return str(value["from_version"])


def available_backups(app_root: Path) -> list[Path]:
    root = app_root / ".updates" / "backups"
    if not root.exists():
        return []
    output = []
    for backup in sorted(root.iterdir(), reverse=True):
        manifest = backup / "backup_manifest.json"
        if not manifest.exists():
            continue
        try:
            value = json.loads(manifest.read_text(encoding="utf-8"))
            if value.get("status") == "applied":
                output.append(backup)
        except Exception:
            continue
    return output


def _python_console_executable() -> Path:
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        console = executable.with_name("python.exe")
        if console.exists():
            return console
    return executable


def _install_requirements(app_root: Path, staged_requirements: Path, log: Callable[[str], None]) -> None:
    log(tr("Installing updated Python dependencies…"))
    command = [str(_python_console_executable()), "-m", "pip", "install", "-r", str(staged_requirements)]
    result = subprocess.run(command, cwd=app_root, capture_output=True, text=True, timeout=900)
    if result.returncode:
        detail = (result.stdout + "\n" + result.stderr)[-6000:]
        raise UpdateError(tr("Dependency installation failed.\n{details}", details=detail))


def _smoke_test(app_root: Path, target_version: str) -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(app_root) + os.pathsep + environment.get("PYTHONPATH", "")
    code = f"import labplotter; import labplotter.ui; assert labplotter.__version__ == {target_version!r}"
    result = subprocess.run([str(_python_console_executable()), "-c", code], cwd=app_root, env=environment, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise UpdateError(tr("Post-update smoke test failed.\n{details}", details=(result.stdout + result.stderr)[-5000:]))


def apply_labpatch(
    patch_path: Path,
    app_root: Path,
    status: Callable[[str], None] | None = None,
    run_smoke: bool = True,
) -> dict:
    report = status or (lambda _message: None)
    patch_path, app_root = patch_path.resolve(), app_root.resolve()
    if patch_path.suffix.lower() != ".labpatch":
        raise UpdateError(tr("Select a file with the .labpatch extension."))
    if not patch_path.exists():
        raise UpdateError(tr("The selected patch file does not exist."))
    backup = None
    staging = None
    log_path = app_root / ".updates" / "update.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(message: str) -> None:
        report(message)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{utc_now()}  {message}\n")

    try:
        log(tr("Validating {name}…", name=patch_path.name))
        with zipfile.ZipFile(patch_path) as archive:
            manifest = read_manifest(archive)
            cumulative = manifest.get("format_version") == 2 and manifest.get("mode") == "snapshot"
            current = read_current_version(app_root, allow_legacy=cumulative)
            if not cumulative and current not in [str(v) for v in manifest["from_versions"]]:
                raise UpdateError(tr("This patch accepts {versions}, but the installed version is {current}.", versions=", ".join(manifest["from_versions"]), current=current))
            if str(manifest["to_version"]) == current:
                raise UpdateError(tr("This patch is already installed."))
            files = _validate_patch_contents(archive, manifest, app_root)
            backup = _backup_installation(app_root, manifest, files, current)
            staging = Path(tempfile.mkdtemp(prefix="staging_", dir=app_root / ".updates"))
            for _entry, relative, data in files:
                destination = staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)

        if manifest.get("requirements_changed"):
            staged_requirements = staging / "requirements.txt"
            if not staged_requirements.exists():
                raise UpdateError(tr("The manifest declares dependency changes but does not include requirements.txt."))
            _install_requirements(app_root, staged_requirements, log)

        log(tr("Applying verified files…"))
        version_relative = Path("version.json")
        ordered_files = sorted(files, key=lambda item: item[1] == version_relative)
        for _entry, relative, _data in ordered_files:
            source = staging / relative
            destination = app_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + ".update_tmp")
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
        for entry in manifest.get("delete", []):
            destination = app_root / validate_relative_path(str(entry["path"]))
            if destination.exists():
                destination.unlink()

        if run_smoke:
            log(tr("Running post-update validation…"))
            _smoke_test(app_root, str(manifest["to_version"]))
        _write_backup_status(backup, "applied", patch_file=patch_path.name)
        log(tr("Update completed: {current} → {target}", current=current, target=manifest["to_version"]))
        return {"from_version": current, "to_version": str(manifest["to_version"]), "backup": str(backup)}
    except Exception as exc:
        if backup and backup.exists():
            try:
                log(tr("Update failed; restoring the previous version…"))
                rollback_backup(app_root, backup, report)
                _write_backup_status(backup, "failed_and_restored", error=str(exc))
            except Exception as rollback_exc:
                raise UpdateError(tr("Update failed: {error}\nRollback also failed: {rollback_error}", error=exc, rollback_error=rollback_exc)) from exc
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError(str(exc)) from exc
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def wait_for_process(pid: int | None, timeout_seconds: int = 45) -> None:
    if not pid:
        return
    if os.name == "nt":
        synchronize = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, int(pid))
        if handle:
            ctypes.windll.kernel32.WaitForSingleObject(handle, timeout_seconds * 1000)
            ctypes.windll.kernel32.CloseHandle(handle)
        return
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.2)


def launch_app(app_root: Path) -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(app_root) + os.pathsep + environment.get("PYTHONPATH", "")
    subprocess.Popen([sys.executable, "-m", "labplotter"], cwd=app_root, env=environment)


class UpdateWindow:
    def __init__(self, app_root: Path, patch: Path | None, rollback: str | None, pid: int | None, restart: bool):
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk

        self.tk, self.messagebox = tk, messagebox
        self.root = tk.Tk()
        self.root.title(tr("LabPlotter Update Manager"))
        self.root.geometry("610x260")
        self.root.resizable(False, False)
        self.app_root, self.patch, self.rollback, self.pid, self.restart = app_root, patch, rollback, pid, restart
        ttk.Label(self.root, text=tr("LabPlotter Update Manager"), font=("Arial", 15, "bold"), padding=(12, 12, 12, 4)).pack(anchor="w")
        self.status_var = tk.StringVar(value=tr("Preparing update…"))
        ttk.Label(self.root, textvariable=self.status_var, wraplength=570, padding=(12, 8)).pack(anchor="w")
        self.progress = ttk.Progressbar(self.root, mode="indeterminate")
        self.progress.pack(fill="x", padx=12, pady=8)
        self.progress.start(12)
        self.log = tk.Text(self.root, height=5, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        if self.patch is None and not self.rollback:
            chosen = filedialog.askopenfilename(parent=self.root, title=tr("Select LabPlotter patch"), filetypes=((tr("LabPlotter patch"), "*.labpatch"),))
            self.patch = Path(chosen) if chosen else None
            if not self.patch:
                self.root.destroy()
                return
        threading.Thread(target=self._worker, daemon=True).start()
        self.root.mainloop()

    def _post(self, message: str) -> None:
        def update():
            self.status_var.set(message)
            self.log.configure(state="normal")
            self.log.insert("end", message + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.root.after(0, update)

    def _worker(self) -> None:
        try:
            wait_for_process(self.pid)
            if self.rollback:
                backups = available_backups(self.app_root)
                if not backups:
                    raise UpdateError(tr("No applied update backup is available."))
                version = rollback_backup(self.app_root, backups[0], self._post)
                result_text = tr("Rollback completed. Restored LabPlotter {version}.", version=version)
            else:
                result = apply_labpatch(self.patch, self.app_root, self._post)
                result_text = tr("Update completed: {current} → {target}", current=result["from_version"], target=result["to_version"])
            self.root.after(0, lambda: self._finish_success(result_text))
        except Exception as exc:
            detail = traceback.format_exc()
            log_path = self.app_root / ".updates" / "update_manager_error.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(detail, encoding="utf-8")
            self.root.after(0, lambda message=str(exc), path=log_path: self._finish_error(message, path))

    def _finish_success(self, text: str) -> None:
        self.progress.stop()
        self.status_var.set(text)
        self.messagebox.showinfo(tr("LabPlotter Update Manager"), text, parent=self.root)
        if self.restart:
            launch_app(self.app_root)
        self.root.destroy()

    def _finish_error(self, text: str, log_path: Path) -> None:
        self.progress.stop()
        self.status_var.set(tr("Update failed."))
        self.messagebox.showerror(
            tr("LabPlotter Update Manager"),
            f"{text}\n\n{tr('The previous installation was kept or restored when possible.')}\n{tr('Log:')} {log_path}",
            parent=self.root,
        )
        if self.restart:
            launch_app(self.app_root)
        self.root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--patch", type=Path)
    parser.add_argument("--app-root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--rollback", choices=("latest",))
    parser.add_argument("--no-restart", action="store_true")
    args = parser.parse_args()
    UpdateWindow(args.app_root.resolve(), args.patch, args.rollback, args.pid, not args.no_restart)


if __name__ == "__main__":
    main()
