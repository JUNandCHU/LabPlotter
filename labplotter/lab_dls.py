"""Lab DLS intensity-bin CSVs, independent of Tk and the ZetaSizer reader.

The exported ordinates are %Intensity per size bin (not a density per nm).
Moments therefore use bin weights, never an integral over linear radius.
These are distribution statistics, not a cumulants Z-average/PDI estimate.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
import re
from uuid import uuid4

import numpy as np


STATISTICS_NOTE = (
    "CSV distribution statistics: mean R = sum(I × R) / sum(I); mean D = 2 × mean R; "
    "%PD = 100 × sqrt(sum(I × (R - mean R)²) / sum(I)) / mean R. "
    "All exported bins are used, regardless of the displayed axis range. "
    "Measurement average is the arithmetic mean of included individual results. Hide only affects individual curves; Exclude removes measurements from all averages. "
    "These values are not the instrument's cumulants Z-average or PDI."
)
AVERAGING_NOTE = (
    "Representative curve: equal-weight mean of included measurements interpolated linearly in log(radius) "
    "on a common, uniformly spaced log grid. No smoothing, fitting or peak normalization. "
    "Zero-intensity tails extend as zero; nonzero tails cannot be extrapolated. "
    "Its mean R is calculated from this representative curve; the measurement average is listed separately."
)


@dataclass(eq=False)
class DLSMeasurement:
    name: str
    radius: np.ndarray
    intensity: np.ndarray
    hidden: bool = False
    excluded: bool = False

    def __post_init__(self):
        if not isinstance(self.hidden, bool) or not isinstance(self.excluded, bool):
            raise ValueError("Measurement visibility/exclusion flags must be booleans.")
        self.radius = np.asarray(self.radius, dtype=float).copy()
        self.intensity = np.asarray(self.intensity, dtype=float).copy()
        x, y = self.radius, self.intensity
        if (x.ndim != 1 or y.ndim != 1 or len(x) != len(y) or len(x) < 2
                or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y))
                or np.any(x <= 0) or np.any(y < 0)):
            raise ValueError(f"{self.name}: need at least two finite positive radii and nonnegative intensities.")
        order = np.argsort(x, kind="stable")
        x, y = x[order], y[order]
        duplicates = np.diff(x) == 0
        if np.any(duplicates & (np.diff(y) != 0)):
            raise ValueError(f"{self.name}: conflicting intensities at the same radius.")
        keep = np.r_[True, ~duplicates]
        self.radius, self.intensity = x[keep], y[keep]
        if len(self.radius) < 2:
            raise ValueError(f"{self.name}: need at least two distinct radii.")


@dataclass(eq=False)
class DLSParticle:
    name: str
    measurements: list[DLSMeasurement]
    source: str = ""
    uid: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self):
        if not self.name.strip() or not self.measurements:
            raise ValueError("A Lab DLS particle needs a name and at least one measurement.")
        names = [m.name for m in self.measurements]
        if any(not n.strip() for n in names) or len(set(names)) != len(names):
            raise ValueError("Measurement names must be nonempty and unique.")


def is_dls_header(row):
    return (len(row) >= 2 and re.fullmatch(r"radius\s*\(\s*nm\s*\)", row[0].strip(), re.I)
            and all(re.fullmatch(r"meas(?:urement)?\s*\d+", v.strip(), re.I) for v in row[1:]))


def parse_dls_csv(path: str | Path) -> DLSParticle:
    path = Path(path)
    return parse_dls_text(path.read_text(encoding="utf-8-sig"), path.name, str(path))


def parse_dls_text(text: str, filename: str, source: str | None = None) -> DLSParticle:
    text = text.lstrip("\ufeff")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = [(i, row) for i, row in enumerate(csv.reader(StringIO(text), dialect), 1) if any(v.strip() for v in row)]
    if not rows or not is_dls_header(rows[0][1]):
        raise ValueError("Expected Radius (nm), Meas 1, Meas 2, ... in the CSV header.")
    header = [v.strip() for v in rows[0][1]]
    points = [[] for _ in header[1:]]
    for lineno, row in rows[1:]:
        if len(row) > len(header) and any(v.strip() for v in row[len(header):]):
            raise ValueError(f"Row {lineno}: unexpected extra columns.")
        row = row[:len(header)] + [""] * max(0, len(header) - len(row))
        if not any(v.strip() for v in row[1:]):
            continue
        try:
            radius = float(row[0])
            for column, cell in enumerate(row[1:]):
                # Blank is missing for this measurement, never a zero reading.
                if cell.strip():
                    points[column].append((radius, float(cell)))
        except ValueError as exc:
            raise ValueError(f"Row {lineno}: invalid numeric value.") from exc
    measurements = []
    for name, pairs in zip(header[1:], points):
        if len(pairs) < 2:
            raise ValueError(f"{name}: fewer than two measured points.")
        x, y = np.asarray(pairs, dtype=float).T
        measurements.append(DLSMeasurement(name, x, y))
    name = Path(filename.replace("\\", "/")).stem
    return DLSParticle(name, measurements, source if source is not None else filename)


def distribution_statistics(measurement: DLSMeasurement) -> dict:
    x, y = measurement.radius, measurement.intensity
    # Scale before summing to avoid overflow for imported arbitrary magnitudes.
    peak = float(y.max())
    if peak == 0:
        return {"mean_radius": None, "mean_diameter": None, "pd_percent": None, "sd_radius": None}
    weights = y / peak
    weights /= weights.sum()
    mean = float(np.dot(weights, x))
    sd = float(np.sqrt(np.dot(weights, (x - mean) ** 2)))
    return {"mean_radius": mean, "mean_diameter": 2 * mean, "pd_percent": 100 * sd / mean, "sd_radius": sd}


def measurement_average(particle: DLSParticle) -> dict:
    stats = [distribution_statistics(m) for m in particle.measurements if not m.excluded]
    # Do not silently omit an all-zero measurement from the reported average.
    return {key: (float(np.mean([s[key] for s in stats])) if stats and all(s[key] is not None for s in stats) else None)
            for key in ("mean_radius", "mean_diameter", "pd_percent", "sd_radius")}


def representative_curve(particle: DLSParticle) -> DLSMeasurement:
    measurements = [m for m in particle.measurements if not m.excluded]
    if not measurements:
        raise ValueError("No measurements included in analysis.")
    first = measurements[0]
    if all(np.array_equal(m.radius, first.radius) for m in measurements):
        return DLSMeasurement("Representative curve", first.radius, np.mean([m.intensity for m in measurements], axis=0))
    logs = [np.log(m.radius) for m in measurements]
    low, high = min(x[0] for x in logs), max(x[-1] for x in logs)
    # Complete distributions may be zero-padded, but unmeasured nonzero tails
    # must not silently become zero or be cut off to fabricate a full mean.
    for m, x in zip(measurements, logs):
        if (x[0] > low and m.intensity[0] != 0) or (x[-1] < high and m.intensity[-1] != 0):
            raise ValueError("Representative curve needs matching coverage or zero-intensity tails. Use all measurements for this particle.")
    step = min(float(np.median(np.diff(x))) for x in logs)
    count = int(np.ceil((high - low) / step)) + 1
    if count > 200000:
        raise ValueError("The representative log grid is too large; use all measurements.")
    # Keep the native log step: redistributing 179 intervals into 180 merely
    # because endpoints differ by rounding can displace narrow peaks by a bin.
    grid = low + step * np.arange(count)
    curves = [np.interp(grid, x, m.intensity, left=0, right=0) for x, m in zip(logs, measurements)]
    return DLSMeasurement("Representative curve", np.exp(grid), np.mean(curves, axis=0))


def statistics_rows(particles: list[DLSParticle], include_representative: bool = False) -> list[dict]:
    rows = []
    for particle in particles:
        count = sum(not m.excluded for m in particle.measurements)
        identity = {"particle": particle.name, "particle_uid": particle.uid}
        rows.append({**identity, "measurement": f"Measurement average (n={count})", "kind": "average",
                     "included_count": count, "excluded": False, "hidden": False,
                     **measurement_average(particle)})
        for index, m in enumerate(particle.measurements):
            rows.append({**identity, "measurement": m.name, "measurement_index": index, "kind": "measurement",
                         "excluded": m.excluded, "hidden": m.hidden, **distribution_statistics(m)})
        if include_representative:
            try:
                m = representative_curve(particle)
            except ValueError:
                continue
            rows.append({**identity, "measurement": m.name, "kind": "representative", "excluded": False,
                         "hidden": False, **distribution_statistics(m)})
    return rows


def statistics_csv(particles, include_representative=False):
    out = StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(("Particle", "Measurement", "Mean radius (nm)", "Mean diameter (nm)", "%PD (distribution)", "SD radius (nm)", "Excluded from analysis", "Hidden individual curve"))
    for row in statistics_rows(particles, include_representative):
        writer.writerow([row[k] if row[k] is not None else "N/A" for k in
                         ("particle", "measurement", "mean_radius", "mean_diameter", "pd_percent", "sd_radius", "excluded", "hidden")])
    return out.getvalue()
