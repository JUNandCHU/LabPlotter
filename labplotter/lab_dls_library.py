"""Independent, user-owned Lab DLS library. No shared instrument tables."""
from __future__ import annotations

from contextlib import closing
from io import BytesIO
import json
from pathlib import Path
import sqlite3

import numpy as np

from .config import data_dir
from .lab_dls import DLSMeasurement, DLSParticle


class DLSLibrary:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else data_dir() / "lab_dls_library.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS particles (uid TEXT PRIMARY KEY, name TEXT NOT NULL, source TEXT NOT NULL, measurements TEXT NOT NULL, arrays BLOB NOT NULL, position INTEGER NOT NULL)")

    def _connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def entries(self):
        with closing(self._connect()) as db:
            return [dict(r) for r in db.execute("SELECT uid, name, source, position FROM particles ORDER BY position, rowid")]

    def save(self, particle: DLSParticle):
        if not particle.name.strip():
            raise ValueError("Particle name cannot be empty.")
        arrays = {}
        for i, m in enumerate(particle.measurements):
            arrays[f"x{i}"], arrays[f"y{i}"] = m.radius, m.intensity
        stream = BytesIO()
        np.savez_compressed(stream, **arrays)
        with closing(self._connect()) as db, db:
            pos = db.execute("SELECT COALESCE(MAX(position), -1)+1 FROM particles").fetchone()[0]
            db.execute("INSERT INTO particles VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(uid) DO UPDATE SET name=excluded.name, source=excluded.source, measurements=excluded.measurements, arrays=excluded.arrays",
                       (particle.uid, particle.name.strip(), particle.source, json.dumps([m.name for m in particle.measurements]), stream.getvalue(), pos))

    def load(self, uid):
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM particles WHERE uid=?", (uid,)).fetchone()
        if row is None:
            raise KeyError("The particle no longer exists in the Lab DLS library.")
        with np.load(BytesIO(row["arrays"]), allow_pickle=False) as arrays:
            measurements = [DLSMeasurement(name, arrays[f"x{i}"], arrays[f"y{i}"])
                            for i, name in enumerate(json.loads(row["measurements"]))]
        return DLSParticle(row["name"], measurements, row["source"], row["uid"])

    def rename(self, uid, name):
        if not name.strip():
            raise ValueError("Particle name cannot be empty.")
        with closing(self._connect()) as db, db:
            db.execute("UPDATE particles SET name=? WHERE uid=?", (name.strip(), uid))

    def delete(self, uids):
        with closing(self._connect()) as db, db:
            db.executemany("DELETE FROM particles WHERE uid=?", [(uid,) for uid in uids])

    def move(self, uid, offset):
        with closing(self._connect()) as db, db:
            ids = [r[0] for r in db.execute("SELECT uid FROM particles ORDER BY position, rowid")]
            if uid not in ids:
                return
            index = ids.index(uid)
            ids.insert(max(0, min(len(ids)-1, index+offset)), ids.pop(index))
            db.executemany("UPDATE particles SET position=? WHERE uid=?", enumerate(ids))


def export_dls_library(particles):
    return json.dumps({"format": "LabPlotter Lab DLS library", "version": 1, "particles": [
        {"uid": p.uid, "name": p.name, "source": p.source, "measurements": [
            {"name": m.name, "radius": m.radius.tolist(), "intensity": m.intensity.tolist()}
            for m in p.measurements]} for p in particles]}, ensure_ascii=False, allow_nan=False)


def import_dls_library(payload):
    document = json.loads(payload)
    if not isinstance(document, dict) or document.get("format") != "LabPlotter Lab DLS library" or document.get("version") != 1:
        raise ValueError("Not a supported Lab DLS library.")
    rows = document.get("particles")
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError("Invalid particle list (maximum 1000).")
    particles, seen = [], set()
    try:
        for row in rows:
            uid = row["uid"]
            if not isinstance(uid, str) or not uid or uid in seen or not isinstance(row["name"], str):
                raise ValueError("Library entries need unique IDs and nonempty names.")
            measurements = [DLSMeasurement(m["name"], m["radius"], m["intensity"]) for m in row["measurements"]]
            particles.append(DLSParticle(row["name"], measurements, str(row.get("source", "")), uid))
            seen.add(uid)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid Lab DLS library entry.") from exc
    return particles
