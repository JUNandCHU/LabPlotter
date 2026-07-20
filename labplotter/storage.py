from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .config import database_path, profiles_path
from .models import ZetaMeasurement


class ParticleLibrary:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self.connect()) as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS particles (
                    name TEXT PRIMARY KEY,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS measurements (
                    particle_name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    replicate INTEGER NOT NULL,
                    x_json TEXT NOT NULL,
                    y_json TEXT NOT NULL,
                    source_file TEXT NOT NULL,
                    sheet_name TEXT NOT NULL,
                    cell_number TEXT NOT NULL DEFAULT '',
                    result_png BLOB,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    imported_at TEXT NOT NULL,
                    PRIMARY KEY (particle_name, kind, replicate),
                    FOREIGN KEY (particle_name) REFERENCES particles(name) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS ocr_results (
                    particle_name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    replicate INTEGER NOT NULL,
                    columns_json TEXT NOT NULL,
                    fields_json TEXT NOT NULL,
                    confidence_json TEXT NOT NULL DEFAULT '[]',
                    engine TEXT NOT NULL DEFAULT '',
                    confirmed_at TEXT NOT NULL,
                    PRIMARY KEY (particle_name, kind, replicate),
                    FOREIGN KEY (particle_name) REFERENCES particles(name) ON DELETE CASCADE
                );
                """
            )
            con.commit()

    def import_measurements(self, measurements: list[ZetaMeasurement]) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as con:
            con.execute("PRAGMA foreign_keys=ON")
            for item in measurements:
                con.execute(
                    "INSERT INTO particles(name, created_at, updated_at) VALUES(?,?,?) "
                    "ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at",
                    (item.particle_name, now, now),
                )
                con.execute(
                    """
                    INSERT INTO measurements(
                        particle_name,kind,replicate,x_json,y_json,source_file,sheet_name,
                        cell_number,result_png,metadata_json,imported_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(particle_name,kind,replicate) DO UPDATE SET
                        x_json=excluded.x_json,y_json=excluded.y_json,source_file=excluded.source_file,
                        sheet_name=excluded.sheet_name,cell_number=excluded.cell_number,
                        result_png=excluded.result_png,metadata_json=excluded.metadata_json,
                        imported_at=excluded.imported_at
                    """,
                    (
                        item.particle_name,
                        item.kind,
                        item.replicate,
                        json.dumps(np.asarray(item.x, dtype=float).tolist()),
                        json.dumps(np.asarray(item.y, dtype=float).tolist()),
                        item.source_basename,
                        item.sheet_name,
                        item.cell_number,
                        item.result_png,
                        json.dumps(item.metadata),
                        now,
                    ),
                )
            con.commit()
        return len(measurements)

    def particles(self, sort_by: str = "name", descending: bool = False) -> list[dict[str, Any]]:
        columns = {
            "name": "p.name COLLATE NOCASE",
            "updated_at": "p.updated_at",
            "dls_count": "dls_count",
            "zeta_count": "zeta_count",
            "source_files": "source_files COLLATE NOCASE",
            "ocr_count": "ocr_count",
        }
        order = columns.get(sort_by, columns["name"])
        direction = "DESC" if descending else "ASC"
        with closing(self.connect()) as con:
            rows = con.execute(
                f"""
                SELECT p.name, p.notes, p.updated_at,
                       SUM(CASE WHEN m.kind='DLS' THEN 1 ELSE 0 END) AS dls_count,
                       SUM(CASE WHEN m.kind='Zeta' THEN 1 ELSE 0 END) AS zeta_count,
                       (SELECT COUNT(*) FROM ocr_results o WHERE o.particle_name=p.name) AS ocr_count,
                       GROUP_CONCAT(DISTINCT m.source_file) AS source_files
                FROM particles p LEFT JOIN measurements m ON m.particle_name=p.name
                GROUP BY p.name ORDER BY {order} {direction}, p.name COLLATE NOCASE ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_particles(self, particle_names: list[str]) -> int:
        names = [str(name) for name in particle_names if str(name)]
        if not names:
            return 0
        marks = ",".join("?" for _ in names)
        with closing(self.connect()) as con:
            con.execute("PRAGMA foreign_keys=ON")
            cursor = con.execute(f"DELETE FROM particles WHERE name IN ({marks})", names)
            con.commit()
            return int(cursor.rowcount)

    def measurements(self, particle_names: list[str], kind: str) -> dict[str, list[dict[str, Any]]]:
        if not particle_names:
            return {}
        marks = ",".join("?" for _ in particle_names)
        query = f"SELECT * FROM measurements WHERE particle_name IN ({marks}) AND kind=? ORDER BY particle_name,replicate"
        with closing(self.connect()) as con:
            rows = con.execute(query, (*particle_names, kind)).fetchall()
        result: dict[str, list[dict[str, Any]]] = {name: [] for name in particle_names}
        for row in rows:
            item = dict(row)
            item["x"] = np.asarray(json.loads(item.pop("x_json")), dtype=float)
            item["y"] = np.asarray(json.loads(item.pop("y_json")), dtype=float)
            item["metadata"] = json.loads(item.pop("metadata_json"))
            result[item["particle_name"]].append(item)
        return result

    def result_image(self, particle_name: str, kind: str, replicate: int) -> bytes | None:
        with closing(self.connect()) as con:
            row = con.execute(
                "SELECT result_png FROM measurements WHERE particle_name=? AND kind=? AND replicate=?",
                (particle_name, kind, replicate),
            ).fetchone()
        return row[0] if row and row[0] else None

    def save_ocr_result(
        self,
        particle_name: str,
        kind: str,
        replicate: int,
        columns: list[str] | tuple[str, ...],
        rows: list[list[str]],
        confidence: list[list[float | None]],
        engine: str,
    ) -> None:
        """Store a user-reviewed OCR table without changing raw measurements."""
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as con:
            con.execute("PRAGMA foreign_keys=ON")
            con.execute(
                """
                INSERT INTO ocr_results(
                    particle_name,kind,replicate,columns_json,fields_json,
                    confidence_json,engine,confirmed_at
                ) VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(particle_name,kind,replicate) DO UPDATE SET
                    columns_json=excluded.columns_json,
                    fields_json=excluded.fields_json,
                    confidence_json=excluded.confidence_json,
                    engine=excluded.engine,
                    confirmed_at=excluded.confirmed_at
                """,
                (
                    particle_name,
                    kind,
                    int(replicate),
                    json.dumps(list(columns), ensure_ascii=False),
                    json.dumps(rows, ensure_ascii=False),
                    json.dumps(confidence),
                    engine,
                    now,
                ),
            )
            con.commit()

    def ocr_result(self, particle_name: str, kind: str, replicate: int) -> dict[str, Any] | None:
        with closing(self.connect()) as con:
            row = con.execute(
                "SELECT * FROM ocr_results WHERE particle_name=? AND kind=? AND replicate=?",
                (particle_name, kind, int(replicate)),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["columns"] = json.loads(item.pop("columns_json"))
        item["rows"] = json.loads(item.pop("fields_json"))
        item["confidence"] = json.loads(item.pop("confidence_json"))
        return item


class FormatProfileStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else profiles_path()

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def save_profile(self, profile: dict[str, Any]) -> None:
        profiles = [p for p in self.load() if p.get("name") != profile.get("name")]
        profiles.append(profile)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(profiles, indent=2, ensure_ascii=False), encoding="utf-8")
