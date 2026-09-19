"""User-owned ssNMR library, outside the installation and patch inventory."""
from __future__ import annotations
import json
import sqlite3
from contextlib import closing
from io import BytesIO
from pathlib import Path
import numpy as np
from .config import data_dir
from .models import Spectrum
from .nmr import _arrays


class NMRLibrary:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else data_dir() / "ssnmr_library.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS spectra (uid TEXT PRIMARY KEY, name TEXT NOT NULL, source TEXT NOT NULL, metadata TEXT NOT NULL, arrays BLOB NOT NULL, position INTEGER NOT NULL)")

    def _connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def entries(self) -> list[dict]:
        with closing(self._connect()) as db:
            return [dict(row) for row in db.execute("SELECT uid, name, source, position FROM spectra ORDER BY position, rowid")]

    def save(self, spectrum: Spectrum):
        x, y = _arrays(spectrum)
        stream = BytesIO(); np.savez_compressed(stream, x=x, y=y)
        if not spectrum.name.strip():
            raise ValueError("Spectrum name cannot be empty.")
        with closing(self._connect()) as db, db:
            position = db.execute("SELECT COALESCE(MAX(position), -1)+1 FROM spectra").fetchone()[0]
            db.execute("INSERT INTO spectra VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(uid) DO UPDATE SET name=excluded.name, source=excluded.source, metadata=excluded.metadata, arrays=excluded.arrays",
                       (spectrum.uid, spectrum.name.strip(), spectrum.source, json.dumps(spectrum.metadata, ensure_ascii=False), stream.getvalue(), position))

    def load(self, uid: str) -> Spectrum:
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM spectra WHERE uid=?", (uid,)).fetchone()
        if row is None:
            raise KeyError("The spectrum no longer exists in the library.")
        with np.load(BytesIO(row["arrays"]), allow_pickle=False) as data:
            return Spectrum(row["name"], data["x"].copy(), data["y"].copy(), row["source"], metadata=json.loads(row["metadata"]), uid=row["uid"])

    def rename(self, uid: str, name: str):
        if not name.strip():
            raise ValueError("Spectrum name cannot be empty.")
        with closing(self._connect()) as db, db:
            db.execute("UPDATE spectra SET name=? WHERE uid=?", (name.strip(), uid))

    def delete(self, uids):
        with closing(self._connect()) as db, db:
            db.executemany("DELETE FROM spectra WHERE uid=?", [(uid,) for uid in uids])

    def move(self, uid: str, offset: int):
        with closing(self._connect()) as db, db:
            ids = [row[0] for row in db.execute("SELECT uid FROM spectra ORDER BY position, rowid")]
            if uid not in ids:
                return
            index = ids.index(uid); target = max(0, min(len(ids)-1, index+offset))
            ids.insert(target, ids.pop(index))
            db.executemany("UPDATE spectra SET position=? WHERE uid=?", enumerate(ids))


def export_portable_library(spectra: list[Spectrum]) -> str:
    return json.dumps({"format": "LabPlotter ssNMR ASCII library", "version": 1, "spectra": [
        {"uid": s.uid, "name": s.name, "source": s.source, "metadata": s.metadata, "ppm": s.x.tolist(), "intensity": s.y.tolist()}
        for s in spectra]}, ensure_ascii=False, allow_nan=False)


def import_portable_library(payload: str) -> list[Spectrum]:
    document = json.loads(payload)
    if not isinstance(document, dict) or document.get("format") != "LabPlotter ssNMR ASCII library" or document.get("version") != 1:
        raise ValueError("Not a supported LabPlotter ssNMR library.")
    rows = document.get("spectra")
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError("Invalid library spectrum list (maximum 1000).")
    output, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid spectrum entry.")
        uid, name = row.get("uid"), row.get("name")
        if not isinstance(uid, str) or not uid or uid in seen or not isinstance(name, str) or not name.strip():
            raise ValueError("Library entries need unique IDs and non-empty names.")
        metadata = row.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("Invalid spectrum metadata.")
        spectrum = Spectrum(name, np.asarray(row["ppm"], dtype=float), np.asarray(row["intensity"], dtype=float), str(row.get("source", "")), metadata=metadata, uid=uid)
        spectrum.x, spectrum.y = _arrays(spectrum)
        output.append(spectrum); seen.add(uid)
    return output
