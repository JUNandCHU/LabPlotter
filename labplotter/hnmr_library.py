"""Independent persistent complex-data and quantitative-parameter libraries."""
from __future__ import annotations
from contextlib import closing
from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path

import numpy as np
from .config import data_dir
from .hnmr import HNMRSpectrum, HNMRSettings, default_parameters
from .nmr_library import NMRLibrary


class HNMRLibrary(NMRLibrary):
    def __init__(self, path=None):
        super().__init__(path or data_dir()/"hnmr_library.sqlite3")

    def save(self, spectrum):
        spectrum.validate()
        stream = BytesIO()
        np.savez_compressed(stream, x=spectrum.x, real=spectrum.real, imag=spectrum.imag)
        document = {"metadata": spectrum.metadata, "processing": spectrum.processing}
        with closing(self._connect()) as db, db:
            position = db.execute("SELECT COALESCE(MAX(position), -1)+1 FROM spectra").fetchone()[0]
            db.execute("INSERT INTO spectra VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(uid) DO UPDATE SET name=excluded.name, source=excluded.source, metadata=excluded.metadata, arrays=excluded.arrays",
                       (spectrum.uid, spectrum.name.strip(), spectrum.source,
                        json.dumps(document, ensure_ascii=False, allow_nan=False), stream.getvalue(), position))

    def load(self, uid):
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM spectra WHERE uid=?", (uid,)).fetchone()
        if row is None:
            raise KeyError("The H NMR spectrum no longer exists in the library.")
        document = json.loads(row["metadata"])
        with np.load(BytesIO(row["arrays"]), allow_pickle=False) as arrays:
            return HNMRSpectrum(row["name"], arrays["x"].copy(), arrays["real"].copy(), arrays["imag"].copy(),
                                row["source"], document["metadata"], document["processing"], uid).validate()

    def entries(self):
        with closing(self._connect()) as db:
            rows = [dict(r) for r in db.execute("SELECT uid,name,source,position,metadata FROM spectra ORDER BY position,rowid")]
        for row in rows:
            p = json.loads(row.pop("metadata")).get("processing", {})
            row["prepared"] = bool(p.get("prepared"))
            row["group"] = p.get("group_id", "")[:8]
        return rows


PARAMETER_FIELDS = {
    "standards": [("name", "Name", "text"), ("area", "Standard area", "positive"),
                  ("mmol_h", "mmol H", "positive"), ("basis", "Area basis: ppm / point_sum / hz", "basis"),
                  ("grid_step", "Standard original grid step (ppm)", "optional"),
                  ("frequency_mhz", "Spectrometer frequency (MHz)", "optional"),
                  ("verified", "Area basis and scale verified", "bool")],
    "cores": [("name", "Core name", "text"), ("capacity", "Maximum loading (umol/mg)", "positive")],
    "ligands": [("name", "Ligand name", "text"), ("mw", "Parent molecular weight (g/mol)", "positive"),
                ("effective_h", "H atoms represented per ligand (blank allowed)", "optional")],
    "samples": [("name", "Sample identity", "text"), ("mass_mg", "Entered mass (mg)", "positive")],
}


def validate_parameters(document):
    if not isinstance(document, dict) or document.get("format") != "LabPlotter H NMR parameters" or document.get("version") != 1:
        raise ValueError("Not a supported H NMR parameter library.")
    for section, fields in PARAMETER_FIELDS.items():
        rows = document.get(section)
        if not isinstance(rows, list) or not rows or len(rows) > 1000:
            raise ValueError(f"{section}: keep 1–1000 parameter entries.")
        names = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Invalid parameter entry.")
            for key, label, kind in fields:
                v = row.get(key)
                if kind == "text" and (not isinstance(v, str) or not v.strip()):
                    raise ValueError(f"{label} is required.")
                if kind in ("positive", "optional") and not (kind == "optional" and v is None):
                    if isinstance(v, bool) or not isinstance(v, (float, int)) or not np.isfinite(v) or v <= 0:
                        raise ValueError(f"{label} must be a finite positive number.")
                if kind == "basis" and v not in ("ppm", "point_sum", "hz"):
                    raise ValueError("Area basis: ppm, point_sum or hz.")
                if kind == "bool" and not isinstance(v, bool):
                    raise ValueError(f"{label} must be a boolean.")
            if row["name"] in names:
                raise ValueError("Parameter names must be unique within each category.")
            names.add(row["name"])
    return deepcopy(document)


class HNMRParameterLibrary:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir()/"hnmr_parameters.json"

    def load(self):
        if not self.path.exists():
            return default_parameters()
        return validate_parameters(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self, document):
        document = validate_parameters(document)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        os.replace(temporary, self.path)


def export_hnmr_library(spectra):
    return json.dumps({"format": "LabPlotter complex H NMR library", "version": 1, "spectra": [
        {"uid": s.uid, "name": s.name, "source": s.source, "metadata": s.metadata, "processing": s.processing,
         "ppm": s.x.tolist(), "real": s.real.tolist(), "imag": s.imag.tolist()} for s in spectra]},
         ensure_ascii=False, allow_nan=False)


def import_hnmr_library(text):
    document = json.loads(text)
    if not isinstance(document, dict) or document.get("format") != "LabPlotter complex H NMR library" or document.get("version") != 1:
        raise ValueError("Not a supported complex H NMR library.")
    rows = document.get("spectra")
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError("Invalid spectrum list.")
    result, seen = [], set()
    for row in rows:
        uid = row.get("uid")
        if not isinstance(uid, str) or not uid or uid in seen:
            raise ValueError("Spectrum IDs must be unique and non-empty.")
        if not isinstance(row.get("metadata", {}), dict) or not isinstance(row.get("processing", {}), dict):
            raise ValueError("Invalid metadata/processing document.")
        p = row.get("processing", {})
        if p:
            HNMRSettings(**p["settings"]).validate()
            if not np.isfinite([p.get("phase0") or 0, p.get("shift", 0)]).all():
                raise ValueError("Invalid saved phase/shift.")
        s = HNMRSpectrum(row["name"], row["ppm"], row["real"], row["imag"], str(row.get("source", "")),
                         row.get("metadata", {}), p, uid).validate()
        result.append(s); seen.add(uid)
    return result
