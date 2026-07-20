from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ALLOWED_DIRECTORIES = {"labplotter", "tools", "tests"}
ALLOWED_ROOT_FILES = {
    "README_KO.md", "requirements.txt", "requirements-build.txt", "pyproject.toml", "version.json",
    "run_labplotter.bat", "build_windows.bat", "apply_update.bat",
    "rollback_last_update.bat", "launcher.py", "updater.py",
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
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--from-version", required=True)
    parser.add_argument("--to-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--notes", default="")
    parser.add_argument("--database-migration", action="store_true")
    args = parser.parse_args()
    manifest = build_patch(args.base, args.new, args.from_version, args.to_version, args.output, args.notes, args.database_migration)
    print(json.dumps({"files": len(manifest["files"]), "delete": len(manifest["delete"]), "to_version": manifest["to_version"]}))


if __name__ == "__main__":
    main()
