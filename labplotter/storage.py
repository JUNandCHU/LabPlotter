from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .config import database_path, profiles_path
from .models import ZetaMeasurement


_BATCH_PATTERN = re.compile(r"(?i)(JM\d+[A-Z]?)")
_NUMBER_PATTERN = re.compile(r"[-+]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[Ee][-+]?\d+)?")


def default_particle_label(name: str) -> str:
    """Return the compact batch label used by ZetaSizer comparison plots."""
    match = _BATCH_PATTERN.search(str(name))
    return match.group(1).upper() if match else str(name)


def _number(value: Any) -> float | None:
    match = _NUMBER_PATTERN.search(str(value).replace("−", "-"))
    if not match:
        return None
    token = match.group(0)
    if token.count(",") == 1 and "." not in token:
        token = token.replace(",", ".")
    else:
        token = token.replace(",", "")
    try:
        return float(token)
    except ValueError:
        return None


class ParticleLibrary:
    SCHEMA_GENERATION = 7

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._reset_legacy_database()
        self._initialize()

    def _reset_legacy_database(self) -> None:
        """Perform the explicitly requested one-time 0.7 Zeta library reset.

        The 0.6 updater backs up migration databases but predates the
        ``database_reset`` manifest flag. Checking SQLite's user_version here
        makes the reset happen on first 0.7 launch even when that older updater
        applied the patch. Fresh 0.7 databases are stamped and kept.
        """
        if not self.path.exists() or not self.path.stat().st_size:
            return
        try:
            with closing(sqlite3.connect(self.path)) as con:
                generation = int(con.execute("PRAGMA user_version").fetchone()[0])
        except sqlite3.DatabaseError:
            generation = 0
        if generation < self.SCHEMA_GENERATION:
            self.path.unlink()

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
                    plot_label TEXT NOT NULL DEFAULT '',
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
                    status TEXT NOT NULL DEFAULT 'auto',
                    error_text TEXT NOT NULL DEFAULT '',
                    confirmed_at TEXT NOT NULL,
                    PRIMARY KEY (particle_name, kind, replicate),
                    FOREIGN KEY (particle_name) REFERENCES particles(name) ON DELETE CASCADE
                );
                """
            )
            self._ensure_column(con, "particles", "plot_label", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(con, "ocr_results", "status", "TEXT NOT NULL DEFAULT 'auto'")
            self._ensure_column(con, "ocr_results", "error_text", "TEXT NOT NULL DEFAULT ''")
            con.execute(f"PRAGMA user_version={self.SCHEMA_GENERATION}")
            con.commit()

    @staticmethod
    def _ensure_column(con: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
        existing = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def import_measurements(self, measurements: list[ZetaMeasurement]) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as con:
            con.execute("PRAGMA foreign_keys=ON")
            for item in measurements:
                con.execute(
                    "INSERT INTO particles(name, plot_label, created_at, updated_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at",
                    (item.particle_name, default_particle_label(item.particle_name), now, now),
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
            "ocr_reviewed": "ocr_reviewed",
            "plot_label": "p.plot_label COLLATE NOCASE",
        }
        order = columns.get(sort_by, columns["name"])
        direction = "DESC" if descending else "ASC"
        with closing(self.connect()) as con:
            rows = con.execute(
                f"""
                SELECT p.name, p.plot_label, p.notes, p.updated_at,
                       SUM(CASE WHEN m.kind='DLS' THEN 1 ELSE 0 END) AS dls_count,
                       SUM(CASE WHEN m.kind='Zeta' THEN 1 ELSE 0 END) AS zeta_count,
                       (SELECT COUNT(*) FROM ocr_results o WHERE o.particle_name=p.name) AS ocr_count,
                       (SELECT COUNT(*) FROM ocr_results o WHERE o.particle_name=p.name AND o.status='auto') AS ocr_auto,
                       (SELECT COUNT(*) FROM ocr_results o WHERE o.particle_name=p.name AND o.status='reviewed') AS ocr_reviewed,
                       (SELECT COUNT(*) FROM ocr_results o WHERE o.particle_name=p.name AND o.status='failed') AS ocr_failed,
                       GROUP_CONCAT(DISTINCT m.source_file) AS source_files
                FROM particles p LEFT JOIN measurements m ON m.particle_name=p.name
                GROUP BY p.name ORDER BY {order} {direction}, p.name COLLATE NOCASE ASC
                """
            ).fetchall()
        results = [dict(row) for row in rows]
        summaries = self.particle_summaries([row["name"] for row in results])
        for row in results:
            row["plot_label"] = row["plot_label"] or default_particle_label(row["name"])
            row.update(summaries.get(row["name"], {}))
        return results

    def set_plot_label(self, particle_name: str, label: str) -> None:
        value = str(label).strip() or default_particle_label(particle_name)
        with closing(self.connect()) as con:
            con.execute(
                "UPDATE particles SET plot_label=?, updated_at=? WHERE name=?",
                (value, datetime.now(timezone.utc).isoformat(), particle_name),
            )
            con.commit()

    def reset_plot_labels(self, particle_names: list[str]) -> None:
        with closing(self.connect()) as con:
            now = datetime.now(timezone.utc).isoformat()
            con.executemany(
                "UPDATE particles SET plot_label=?, updated_at=? WHERE name=?",
                [(default_particle_label(name), now, name) for name in particle_names],
            )
            con.commit()

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
        reviewed: bool = True,
    ) -> None:
        """Store a user-reviewed OCR table without changing raw measurements."""
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as con:
            con.execute("PRAGMA foreign_keys=ON")
            con.execute(
                """
                INSERT INTO ocr_results(
                    particle_name,kind,replicate,columns_json,fields_json,
                    confidence_json,engine,status,error_text,confirmed_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(particle_name,kind,replicate) DO UPDATE SET
                    columns_json=excluded.columns_json,
                    fields_json=excluded.fields_json,
                    confidence_json=excluded.confidence_json,
                    engine=excluded.engine,
                    status=excluded.status,
                    error_text='',
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
                    "reviewed" if reviewed else "auto",
                    "",
                    now,
                ),
            )
            con.commit()

    def save_ocr_failure(self, particle_name: str, kind: str, replicate: int, error: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as con:
            con.execute("PRAGMA foreign_keys=ON")
            con.execute(
                """
                INSERT INTO ocr_results(
                    particle_name,kind,replicate,columns_json,fields_json,
                    confidence_json,engine,status,error_text,confirmed_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(particle_name,kind,replicate) DO UPDATE SET
                    status='failed', error_text=excluded.error_text,
                    confirmed_at=excluded.confirmed_at
                """,
                (particle_name, kind, int(replicate), "[]", "[]", "[]", "", "failed", str(error), now),
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

    def ocr_results(self, particle_name: str, kind: str | None = None) -> list[dict[str, Any]]:
        parameters: list[Any] = [particle_name]
        where = "particle_name=?"
        if kind:
            where += " AND kind=?"
            parameters.append(kind)
        with closing(self.connect()) as con:
            rows = con.execute(
                f"SELECT * FROM ocr_results WHERE {where} ORDER BY kind,replicate",
                parameters,
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["columns"] = json.loads(item.pop("columns_json"))
            item["rows"] = json.loads(item.pop("fields_json"))
            item["confidence"] = json.loads(item.pop("confidence_json"))
            results.append(item)
        return results

    def measurement_records(self, particle_name: str) -> list[dict[str, Any]]:
        with closing(self.connect()) as con:
            rows = con.execute(
                """
                SELECT m.particle_name,m.kind,m.replicate,m.source_file,m.sheet_name,m.cell_number,
                       m.imported_at,m.metadata_json,
                       COALESCE(o.status,'missing') AS ocr_status,
                       COALESCE(o.engine,'') AS ocr_engine,
                       COALESCE(o.error_text,'') AS ocr_error
                FROM measurements m LEFT JOIN ocr_results o
                  ON o.particle_name=m.particle_name AND o.kind=m.kind AND o.replicate=m.replicate
                WHERE m.particle_name=? ORDER BY m.kind,m.replicate
                """,
                (particle_name,),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json"))
            results.append(item)
        return results

    @staticmethod
    def _summary_value(item: dict[str, Any], kind: str) -> float | None:
        columns = [str(value).casefold() for value in item.get("columns", [])]
        try:
            mean_column = next(index for index, value in enumerate(columns) if "mean" in value)
        except StopIteration:
            mean_column = 1
        for row in item.get("rows", []):
            if not row:
                continue
            label = str(row[0]).casefold().replace(" ", "")
            if kind == "DLS":
                matches = "z-average" in label or "zaverage" in label
            else:
                matches = ("zetapotential" in label or "zetapotential" in label.replace(" ", "")) and "wall" not in label
            if matches and mean_column < len(row):
                return _number(row[mean_column])
        return None

    def particle_summaries(self, particle_names: list[str] | None = None) -> dict[str, dict[str, Any]]:
        if particle_names is not None and not particle_names:
            return {}
        parameters: list[Any] = []
        where = "WHERE status!='failed'"
        if particle_names is not None:
            marks = ",".join("?" for _ in particle_names)
            where += f" AND particle_name IN ({marks})"
            parameters.extend(particle_names)
        with closing(self.connect()) as con:
            rows = con.execute(
                f"SELECT * FROM ocr_results {where} ORDER BY particle_name,kind,replicate",
                parameters,
            ).fetchall()
        values: dict[str, dict[str, list[float]]] = {}
        for row in rows:
            item = dict(row)
            item["columns"] = json.loads(item.pop("columns_json"))
            item["rows"] = json.loads(item.pop("fields_json"))
            value = self._summary_value(item, item["kind"])
            if value is not None and np.isfinite(value):
                values.setdefault(item["particle_name"], {}).setdefault(item["kind"], []).append(float(value))
        result: dict[str, dict[str, Any]] = {}
        names = particle_names if particle_names is not None else list(values)
        for name in names:
            entry: dict[str, Any] = {}
            for kind, prefix in (("DLS", "dls_z"), ("Zeta", "zeta_average")):
                data = np.asarray(values.get(name, {}).get(kind, []), dtype=float)
                entry[f"{prefix}_values"] = data.tolist()
                entry[f"{prefix}_n"] = int(data.size)
                entry[f"{prefix}_mean"] = float(np.mean(data)) if data.size else None
                entry[f"{prefix}_median"] = float(np.median(data)) if data.size else None
                entry[f"{prefix}_sd"] = float(np.std(data, ddof=1)) if data.size > 1 else 0.0 if data.size else None
                entry[f"{prefix}_sem"] = float(np.std(data, ddof=1) / np.sqrt(data.size)) if data.size > 1 else 0.0 if data.size else None
            result[name] = entry
        return result


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
