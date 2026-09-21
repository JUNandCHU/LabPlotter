"""TopSpin four-column ASCII spectra and auditable real-spectrum comparisons.

Column 2 is real intensity; column 3 is frequency (Hz); column 4 is shift
(ppm). No imaginary spectrum or FID is inferred from these exports.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from io import StringIO
from pathlib import Path

import numpy as np
from scipy.integrate import trapezoid
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import minimize_scalar

from .models import Spectrum
from .processing import linear_endpoints_baseline

MAX_GRID_POINTS = 200_000
PHASE_NOTE = "Real-only ASCII: preserve exported TopSpin phase; complex phase correction is unavailable."


def parse_topspin_ascii(path: str | Path) -> Spectrum:
    path = Path(path)
    if path.suffix.lower() not in {".txt", ".asc", ".csv", ".tsv"}:
        raise ValueError("Import a four-column TopSpin ASCII .txt file. ZIP/FID import has been removed.")
    payload = path.read_bytes()
    text = payload.decode("utf-8-sig", errors="replace")
    rows, headers = [], []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith(("#", "$$", ";")):
            continue
        fields = next(csv.reader([line])) if "," in line else re.split(r"[\t;\s]+", line.strip())
        # The title can replace column 1 on the FIRST DATA ROW; keep columns 2–4.
        if len(fields) != 4:
            if not rows and not re.match(r"^[+-]?\d+[\t,; ]", line):
                headers.append(line)
                continue
            raise ValueError(f"Line {number}: expected four columns (index/title, intensity, Hz, ppm).")
        try:
            intensity, hz, ppm = (float(v.strip().replace("D", "E")) for v in fields[1:])
        except ValueError as exc:
            if not rows and not re.match(r"^[+-]?\d+$", fields[0].strip()):
                headers.append(line)
                continue
            raise ValueError(f"Line {number}: non-numeric intensity, Hz or ppm.") from exc
        if not np.all(np.isfinite([intensity, hz, ppm])):
            raise ValueError(f"Line {number}: intensity, Hz and ppm must be finite.")
        rows.append((ppm, intensity, hz))
        if not fields[0].strip().isdigit():
            headers.append(fields[0].strip())
    if len(rows) < 3:
        raise ValueError("At least three numeric four-column data rows are required.")
    data = np.asarray(rows, dtype=float)
    data = data[np.argsort(data[:, 0])]
    if np.any(np.diff(data[:, 0]) <= 0):
        raise ValueError("Duplicate chemical shifts are ambiguous; export a single 1D spectrum.")
    frequency = float(np.median(np.diff(data[:, 2]) / np.diff(data[:, 0])))
    return Spectrum(path.stem, data[:, 0].copy(), data[:, 1].copy(), str(path), metadata={
        "kind": "ssnmr_ascii", "columns": {"x_ppm": 4, "y_intensity": 2, "frequency_hz": 3},
        "header": "\n".join(headers), "points": len(rows), "sha256": hashlib.sha256(payload).hexdigest(),
        "frequency_mhz_from_axes": frequency, "phase": PHASE_NOTE,
    })


def _arrays(spectrum: Spectrum) -> tuple[np.ndarray, np.ndarray]:
    x, y = np.asarray(spectrum.x, dtype=float), np.asarray(spectrum.y, dtype=float)
    if x.ndim != 1 or y.shape != x.shape or len(x) < 3 or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise ValueError("Each spectrum needs at least three finite ppm/intensity pairs.")
    order = np.argsort(x)
    x, y = x[order], y[order]
    if np.any(np.diff(x) <= 0):
        raise ValueError("Chemical shifts must be unique.")
    return x, y


@dataclass
class ComparisonSettings:
    ppm_min: float | None = None
    ppm_max: float | None = None
    grid_step: float | None = None
    baseline: bool = True
    edge_fraction: float = 0.03
    align: bool = True
    max_shift_ppm: float = 2.0
    alignment_min: float | None = None
    alignment_max: float | None = None
    gaussian_fwhm_ppm: float = 0.3
    normalization: str = "Maximum absolute intensity"


def default_settings(a: Spectrum, b: Spectrum) -> ComparisonSettings:
    ax, _ = _arrays(a); bx, _ = _arrays(b)
    return ComparisonSettings(float(min(ax[0], bx[0])), float(max(ax[-1], bx[-1])),
                              float(max(np.median(np.diff(ax)), np.median(np.diff(bx)))))


@dataclass
class ComparisonResult:
    names: tuple[str, str]
    x: np.ndarray
    a: np.ndarray
    b: np.ndarray
    settings: ComparisonSettings
    log: dict
    stages: dict[str, np.ndarray] = field(default_factory=dict)


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    da, db = a - np.mean(a), b - np.mean(b)
    na, nb = np.linalg.norm(da), np.linalg.norm(db)
    if na <= np.finfo(float).eps * max(np.linalg.norm(a), np.finfo(float).tiny) * 32 or nb <= np.finfo(float).eps * max(np.linalg.norm(b), np.finfo(float).tiny) * 32:
        return float("nan")
    return float(np.clip(np.dot(da / na, db / nb), -1, 1))


def _alignment(ax, ay, bx, by, step, settings):
    bound = settings.max_shift_ppm
    low, high = max(ax[0], bx[0] + bound), min(ax[-1], bx[-1] - bound)
    if settings.alignment_min is not None:
        low = max(low, settings.alignment_min)
    if settings.alignment_max is not None:
        high = min(high, settings.alignment_max)
    if high <= low or (high - low) / step < 8:
        raise ValueError("Alignment needs at least eight common points with room for the allowed shift.")
    x = np.linspace(low, high, min(20_000, max(9, int((high - low) / step) + 1)))
    a = np.interp(x, ax, ay)
    def score(shift):
        return _corr(a, np.interp(x - shift, bx, by))
    shifts = np.linspace(-bound, bound, 81) if bound else np.array([0.0])
    scores = np.asarray([score(d) for d in shifts])
    before = score(0)
    if not np.any(np.isfinite(scores)):
        return 0.0, {"status": "constant signal; alignment skipped", "window_ppm": [low, high]}
    index = int(np.nanargmax(scores))
    shift, best = float(shifts[index]), float(scores[index])
    if bound and 0 < index < len(shifts) - 1:
        fit = minimize_scalar(lambda d: -score(d), bounds=(shifts[index-1], shifts[index+1]), method="bounded", options={"xatol": 1e-7})
        if fit.success and np.isfinite(fit.fun) and -fit.fun > best:
            shift, best = float(fit.x), float(-fit.fun)
    if np.isfinite(before) and best <= before + 1e-8:
        shift, best = 0.0, before
    return shift, {"status": "bounded rigid shift of B; no warping", "window_ppm": [low, high],
                   "r_before": before, "r_after": best, "at_limit": bool(bound and abs(shift) >= bound * 0.99)}


def preprocess_pair(a: Spectrum, b: Spectrum, settings: ComparisonSettings | None = None) -> ComparisonResult:
    defaults = default_settings(a, b)
    s = ComparisonSettings(**asdict(settings or defaults))
    for name in ("ppm_min", "ppm_max", "grid_step"):
        if getattr(s, name) is None:
            setattr(s, name, getattr(defaults, name))
    numeric = [s.ppm_min, s.ppm_max, s.grid_step, s.edge_fraction, s.max_shift_ppm, s.gaussian_fwhm_ppm]
    numeric += [v for v in (s.alignment_min, s.alignment_max) if v is not None]
    if not np.all(np.isfinite(numeric)):
        raise ValueError("Preprocessing parameters must be finite.")
    if s.ppm_max <= s.ppm_min or s.grid_step <= 0:
        raise ValueError("Use an increasing ppm range and a positive grid step.")
    if not 0 < s.edge_fraction <= 0.25 or not 0 <= s.max_shift_ppm <= 100 or s.gaussian_fwhm_ppm < 0:
        raise ValueError("Edge fraction: (0, 0.25]; maximum shift: 0–100 ppm; Gaussian FWHM: >= 0.")
    if s.alignment_min is not None and s.alignment_max is not None and s.alignment_min >= s.alignment_max:
        raise ValueError("Alignment minimum must be less than maximum.")
    if s.normalization not in {"Maximum absolute intensity", "Total absolute area", "None"}:
        raise ValueError("Unknown normalization method.")
    intervals = int(math.ceil((s.ppm_max - s.ppm_min) / s.grid_step - 1e-9))
    if intervals < 2 or intervals + 1 > MAX_GRID_POINTS:
        raise ValueError(f"The common grid must contain 3–{MAX_GRID_POINTS:,} points. Adjust the range or grid step.")
    x = np.linspace(s.ppm_min, s.ppm_max, intervals + 1)
    actual_step = float(x[1] - x[0])
    native = [_arrays(a), _arrays(b)]
    stages, corrected, baselines = {}, [], []
    baseline_log = []
    for label, (nx, ny) in zip(("A", "B"), native):
        curve = linear_endpoints_baseline(nx, ny, s.edge_fraction) if s.baseline else np.zeros_like(ny)
        baseline_log.append({"spectrum": label, "native_range_ppm": [float(nx[0]), float(nx[-1])],
                             "baseline_at_low": float(curve[0]), "baseline_at_high": float(curve[-1]),
                             "edge_points": max(3, min(len(ny)//4, int(round(len(ny)*s.edge_fraction)))) if s.baseline else 0})
        baselines.append(curve)
        corrected.append(ny - curve)
        stages[label + "_raw"] = np.interp(x, nx, ny, left=np.nan, right=np.nan)
        stages[label + "_baseline"] = np.interp(x, nx, curve, left=np.nan, right=np.nan)
        stages[label + "_baseline_corrected"] = np.interp(x, nx, ny - curve, left=np.nan, right=np.nan)
    shift, alignment = (0.0, {"status": "disabled"})
    if s.align:
        # Limit the optimization to the requested processing range.
        align_s = ComparisonSettings(**asdict(s))
        align_s.alignment_min = max(s.ppm_min, s.alignment_min if s.alignment_min is not None else s.ppm_min)
        align_s.alignment_max = min(s.ppm_max, s.alignment_max if s.alignment_max is not None else s.ppm_max)
        shift, alignment = _alignment(native[0][0], corrected[0], native[1][0], corrected[1], actual_step, align_s)
    processed = []
    for i, label in enumerate(("A", "B")):
        nx = native[i][0] + (shift if i else 0)
        values = np.interp(x, nx, corrected[i], left=np.nan, right=np.nan)
        stages[label + "_aligned"] = values.copy()
        finite = np.flatnonzero(np.isfinite(values))
        if len(finite) < 3:
            raise ValueError("The selected grid has insufficient coverage for a spectrum.")
        if s.gaussian_fwhm_ppm:
            sigma = s.gaussian_fwhm_ppm / (2 * np.sqrt(2 * np.log(2))) / actual_step
            if sigma > len(x):
                raise ValueError("Gaussian broadening is larger than the processing range.")
            values[finite] = gaussian_filter1d(values[finite], sigma, mode="reflect", truncate=4.0)
        stages[label + "_smoothed"] = values.copy()
        processed.append(values)
    common = np.isfinite(processed[0]) & np.isfinite(processed[1])
    if common.sum() < 3:
        raise ValueError("The spectra have fewer than three overlapping points after alignment.")
    factors = []
    for i, label in enumerate(("A", "B")):
        values = processed[i][common]
        if s.normalization == "Maximum absolute intensity":
            factor = float(np.max(np.abs(values)))
        elif s.normalization == "Total absolute area":
            factor = float(trapezoid(np.abs(values), x[common]))
        else:
            factor = 1.0
        # A zero signal is left unchanged and yields undefined correlation.
        factors.append(factor)
        processed[i] = processed[i] / (factor if factor else 1.0)
        stages[label + "_normalized"] = processed[i].copy()
    log = {"phase": PHASE_NOTE, "settings": asdict(s), "grid_points": len(x), "actual_grid_step_ppm": actual_step,
           "grid_policy": "union by default; linear interpolation; outside measured support = NaN, never zero-filled",
           "baseline": {"method": "native full-range median edge line" if s.baseline else "none", "spectra": baseline_log},
           "alignment": {**alignment, "B_shift_added_ppm": shift, "convention": "B_aligned(x) = B_original(x - shift)"},
           "smoothing": {"method": "Gaussian convolution in ppm (shared kernel); reflected edges", "fwhm_ppm": s.gaussian_fwhm_ppm},
           "normalization": {"method": s.normalization, "divisors_A_B": factors,
                             "window_ppm": [float(x[common][0]), float(x[common][-1])], "points": int(common.sum())},
           "inputs": [{"name": sp.name, "source": sp.source, "sha256": sp.metadata.get("sha256"), "metadata": sp.metadata} for sp in (a, b)]}
    return ComparisonResult((a.name, b.name), x, processed[0], processed[1], s, log, stages)


def comparison_metrics(result: ComparisonResult, low: float, high: float) -> dict:
    if not np.isfinite([low, high]).all() or low >= high:
        raise ValueError("Comparison minimum must be less than maximum and both must be finite.")
    mask = (result.x >= low) & (result.x <= high) & np.isfinite(result.a) & np.isfinite(result.b)
    x, a, b = result.x[mask], result.a[mask], result.b[mask]
    if len(x) < 3:
        raise ValueError("Comparison needs at least three common measured points.")
    da, db = a - np.mean(a), b - np.mean(b)
    residual = a - b
    sse, sst, ssb, cross = (float(np.sum(v)) for v in (residual**2, da**2, db**2, da*db))
    tolerance = np.finfo(float).eps * max(float(np.dot(a, a)), np.finfo(float).tiny) * 32
    r = _corr(a, b)
    direct = 1 - sse / sst if sst > tolerance else float("nan")
    return {"requested_range_ppm": [low, high], "used_range_ppm": [float(x[0]), float(x[-1])], "n": len(x),
            "mean_A": float(np.mean(a)), "mean_B": float(np.mean(b)), "SSE": sse, "SST_A": sst, "SS_B": ssb, "cross_sum": cross,
            "R2": direct, "r": r, "r2": r*r, "x": x, "a": a, "b": b, "residual": residual,
            "A_centered": da, "B_centered": db,
            "definition": "A is the reference. Direct R² = 1 - sum((A-B)^2)/sum((A-mean(A))^2); no fitted gain/offset. Pearson r² = r*r; it discards the sign of r. R² may be negative. Constant signals: undefined."}


def region_integral(x, y, low: float, high: float) -> dict:
    if not np.isfinite([low, high]).all() or low >= high:
        raise ValueError("Integral bounds must be finite and increasing.")
    finite = np.isfinite(y)
    indices = np.flatnonzero(finite)
    if len(indices) < 2 or low < x[indices[0]] or high > x[indices[-1]]:
        raise ValueError(f"Integral region {low:g}–{high:g} ppm is not fully covered by measured data.")
    inside = (x > low) & (x < high)
    if not np.all(finite[inside]):
        raise ValueError("The integral region contains a missing-data gap.")
    xx = np.concatenate(([low], x[inside], [high]))
    yy = np.interp(xx, x[finite], y[finite])
    pieces = np.diff(xx) * (yy[:-1] + yy[1:]) / 2
    return {"range_ppm": [low, high], "area": float(np.sum(pieces)), "x": xx, "y": yy, "pieces": pieces,
            "absolute_area": float(trapezoid(np.abs(yy), xx))}


def comparison_region_metrics(result: ComparisonResult, comparison, aliphatic=(0., 50.), aromatic=(90., 160.)) -> dict:
    """Evaluate all three ranges on the same processed curves, without renormalizing."""
    output = {}
    for name, bounds in (("Comparison range", comparison), ("Aliphatic region", aliphatic), ("Aromatic region", aromatic)):
        try:
            output[name] = comparison_metrics(result, *bounds)
        except (ValueError, TypeError) as exc:
            output[name] = {"error": str(exc), "requested_range_ppm": list(bounds)}
    return output


def regional_metrics_audit(result: ComparisonResult, regions: dict, region_results: dict | None = None) -> str:
    policy = ("Aliphatic and aromatic statistics use independent preprocessing from the original spectra over each requested region. "
              "Comparison range uses the currently displayed processing result.\n" if region_results is not None else
              "All regions use the same processed spectra. No region-specific renormalization.\n")
    sections = [policy +
                "Pearson r = sum((A-mean_A)*(B-mean_B)) / sqrt(SST_A*SS_B); r² = r*r.\n"]
    for name, values in regions.items():
        source = (region_results or {}).get(name, result)
        sections.append(name + "\n" + (json.dumps(values, indent=2) if "error" in values else
                        json.dumps({"preprocessing": source.log}, indent=2, default=str) + "\n" + metrics_audit(source, values)))
    return "\n\n".join(sections)


def regional_preprocessing_audit(region_results: dict) -> str:
    return "\n\n".join(label + "\n" + preprocessing_audit(result) for label, result in region_results.items())


def integral_ratios(result: ComparisonResult, aliphatic=(0.0, 50.0), aromatic=(90.0, 160.0)) -> list[dict]:
    output = []
    for name, y in zip(result.names, (result.a, result.b)):
        numerator = region_integral(result.x, y, *aliphatic)
        denominator = region_integral(result.x, y, *aromatic)
        tolerance = max(1e-14, denominator["absolute_area"] * 1e-12)
        ratio = numerator["area"] / denominator["area"] if abs(denominator["area"]) > tolerance else float("nan")
        output.append({"name": name, "aliphatic": numerator, "aromatic": denominator, "ratio": ratio,
                       "definition": "Signed trapezoidal integral on ascending ppm, with linearly interpolated exact endpoints; no clipping/absolute-value rectification. Ratio = aliphatic / aromatic. Near-zero denominator = undefined."})
    return output


def _csv(headers, rows) -> str:
    out = StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([format(float(v), ".17g") if isinstance(v, (float, np.floating)) else v for v in row])
    return out.getvalue()


def preprocessing_audit(result: ComparisonResult) -> str:
    keys = list(result.stages)
    return json.dumps(result.log, indent=2, ensure_ascii=False, default=str) + "\n\n" + _csv(["ppm"]+keys, zip(result.x, *(result.stages[k] for k in keys)))


def metrics_audit(result: ComparisonResult, values: dict) -> str:
    summary = {k:v for k,v in values.items() if not isinstance(v, np.ndarray)}
    summary["reference_A"], summary["candidate_B"] = result.names
    table = _csv(["ppm", "A", "B", "A-B", "(A-B)^2", "A-mean_A", "B-mean_B", "(A-mean_A)^2", "(B-mean_B)^2", "centered_cross"],
                 zip(values["x"], values["a"], values["b"], values["residual"], values["residual"]**2,
                     values["A_centered"], values["B_centered"], values["A_centered"]**2, values["B_centered"]**2, values["A_centered"]*values["B_centered"]))
    return json.dumps(summary, indent=2, ensure_ascii=False) + "\n\n" + table


def integrals_audit(result: ComparisonResult, ratios: list[dict]) -> str:
    sections = []
    for row in ratios:
        sections.append(f"Spectrum: {row['name']}\n{row['definition']}\nRatio = {row['aliphatic']['area']:.17g} / {row['aromatic']['area']:.17g} = {row['ratio']:.17g}\n")
        for label in ("aliphatic", "aromatic"):
            item = row[label]; x, y, parts = item["x"], item["y"], item["pieces"]
            sections.append(f"{label}: {item['range_ppm']}; area = sum(segment area) = {item['area']:.17g}\n")
            sections.append(_csv(["ppm_left", "ppm_right", "I_left", "I_right", "delta_ppm", "segment_area", "cumulative_area"],
                                 zip(x[:-1], x[1:], y[:-1], y[1:], np.diff(x), parts, np.cumsum(parts))))
    return "\n".join(sections)


def comparison_csv(result: ComparisonResult) -> str:
    return _csv(["ppm", "A: "+result.names[0], "B: "+result.names[1]], zip(result.x, result.a, result.b))
