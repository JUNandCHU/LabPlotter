from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ALLOWED_DIRECTORIES = {"labplotter", "tools", "tests"}
ALLOWED_ROOT_FILES = {
    "README.md", "README_KO.md", "CHANGELOG.md", "requirements.txt", "requirements-build.txt", "pyproject.toml", "version.json",
    "run_labplotter.bat", "build_windows.bat", "apply_update.bat",
    "rollback_last_update.bat", "update_to_latest.bat", "launcher.py", "updater.py",
}
IGNORED_PARTS = {"__pycache__", ".venv", ".buildvenv", ".updates", "build", "dist"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def collect_files(root: Path) -> dict[str, bytes]:
    output: dict[str, bytes] = {}
    for name in ALLOWED_ROOT_FILES:
        path = root / name
        if path.is_file():
            output[name] = path.read_bytes()
    for directory in ALLOWED_DIRECTORIES:
        base = root / directory
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and not any(part in IGNORED_PARTS for part in path.relative_to(root).parts):
                output[path.relative_to(root).as_posix()] = path.read_bytes()
    return output


def build_patch(
    base_root: Path,
    new_root: Path,
    from_version: str,
    to_version: str,
    output: Path,
    notes: str = "",
    database_migration: bool = False,
    database_reset: bool = False,
) -> dict:
    base_root, new_root = base_root.resolve(), new_root.resolve()
    base, new = collect_files(base_root), collect_files(new_root)
    version_path = new_root / "version.json"
    if not version_path.exists() or str(json.loads(version_path.read_text(encoding="utf-8")).get("version")) != str(to_version):
        raise ValueError("The target version does not match new_root/version.json.")

    files = []
    for path in sorted(new):
        if path not in base or new[path] != base[path]:
            entry = {"path": path, "sha256": sha256(new[path]), "size": len(new[path])}
            entry["old_sha256"] = sha256(base[path]) if path in base else None
            files.append(entry)
    delete = [{"path": path, "old_sha256": sha256(base[path])} for path in sorted(set(base) - set(new))]
    requirements_changed = base.get("requirements.txt") != new.get("requirements.txt")
    if requirements_changed and "requirements.txt" not in {entry["path"] for entry in files}:
        raise ValueError("requirements.txt changed but is not included in the patch.")
    manifest = {
        "format_version": 1,
        "product": "LabPlotter",
        "from_versions": [str(from_version)],
        "to_version": str(to_version),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes,
        "requirements_changed": requirements_changed,
        "database_migration": bool(database_migration),
        "database_reset": bool(database_reset),
        "files": files,
        "delete": delete,
    }
    if output.suffix.lower() != ".labpatch":
        output = output.with_suffix(".labpatch")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        for entry in files:
            archive.writestr(f"payload/{entry['path']}", new[entry["path"]])
    return manifest


def build_snapshot_patch(
    new_root: Path,
    to_version: str,
    output: Path,
    notes: str = "",
    obsolete_paths: list[str] | None = None,
    database_reset: bool = False,
) -> dict:
    """Build a complete target snapshot accepted by updater format 2.

    A snapshot overwrites every managed target file, so one artifact can move
    any patch-enabled LabPlotter installation to the target version. Unknown
    user files are preserved; only explicitly listed obsolete paths are removed.
    """
    new_root = new_root.resolve()
    new = collect_files(new_root)
    version_path = new_root / "version.json"
    if not version_path.exists() or str(json.loads(version_path.read_text(encoding="utf-8")).get("version")) != str(to_version):
        raise ValueError("The target version does not match new_root/version.json.")
    files = [
        {"path": path, "sha256": sha256(data), "size": len(data)}
        for path, data in sorted(new.items())
    ]
    delete = [{"path": path} for path in sorted(set(obsolete_paths or []))]
    manifest = {
        "format_version": 2,
        "mode": "snapshot",
        "product": "LabPlotter",
        "from_versions": ["*"],
        "to_version": str(to_version),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes,
        "requirements_changed": True,
        "database_migration": True,
        "database_reset": bool(database_reset),
        "managed_paths": [entry["path"] for entry in files],
        "files": files,
        "delete": delete,
    }
    if output.suffix.lower() != ".labpatch":
        output = output.with_suffix(".labpatch")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        for entry in files:
            archive.writestr(f"payload/{entry['path']}", new[entry["path"]])
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a verified LabPlotter .labpatch artifact")
    parser.add_argument("--base", type=Path)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--from-version")
    parser.add_argument("--to-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--notes", default="")
    parser.add_argument("--database-migration", action="store_true")
    parser.add_argument("--reset-database", action="store_true", help="Back up, then reset the ZetaSizer particle database during update")
    parser.add_argument("--snapshot", action="store_true", help="Build a format-2 cumulative snapshot from any supported version")
    parser.add_argument("--obsolete-path", action="append", default=[], help="Managed obsolete path to remove in snapshot mode")
    args = parser.parse_args()
    if args.snapshot:
        manifest = build_snapshot_patch(args.new, args.to_version, args.output, args.notes, args.obsolete_path, args.reset_database)
    else:
        if args.base is None or not args.from_version:
            parser.error("--base and --from-version are required unless --snapshot is used")
        manifest = build_patch(args.base, args.new, args.from_version, args.to_version, args.output, args.notes, args.database_migration or args.reset_database, args.reset_database)
    print(json.dumps({"files": len(manifest["files"]), "delete": len(manifest["delete"]), "to_version": manifest["to_version"]}))


if __name__ == "__main__":
    main()
