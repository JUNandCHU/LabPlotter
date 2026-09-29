"""Complex 1H NMR processing and auditable, reference-corrected quantitation.

The export has no acquisition metadata: absolute calibration is never inferred
from an intensity value. Raw arrays are immutable inputs to every calculation.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

import numpy as np
from scipy.integrate import trapezoid
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import least_squares, minimize_scalar


@dataclass
class HNMRSpectrum:
    name: str
    x: np.ndarray
    real: np.ndarray
    imag: np.ndarray
    source: str = ""
    metadata: dict = field(default_factory=dict)
    processing: dict = field(default_factory=dict)
    uid: str = field(default_factory=lambda: uuid4().hex)

    def validate(self):
        arrays = [np.asarray(v, dtype=float) for v in (self.x, self.real, self.imag)]
        if any(v.ndim != 1 for v in arrays) or not (8 <= len(arrays[0]) <= 2_000_000):
            raise ValueError("H NMR needs 8 to 2,000,000 one-dimensional data points.")
        if any(len(v) != len(arrays[0]) or not np.all(np.isfinite(v)) for v in arrays):
            raise ValueError("Complex data must have equal lengths and finite values.")
        order = np.argsort(arrays[0])
        self.x, self.real, self.imag = [v[order].copy() for v in arrays]
        if np.any(np.diff(self.x) <= 0):
            raise ValueError("Chemical shifts must be distinct.")
        if not self.name.strip():
            raise ValueError("A spectrum name is required.")
        return self


def parse_hnmr_text(text: str, name: str = "H NMR", source: str = "") -> HNMRSpectrum:
    """Read the TopSpin LEFT/RIGHT/SIZE complex export, without eval().

    Also accepts an explicitly headed ppm, real, imag table. Four-column
    carbon exports are deliberately not reinterpreted as proton data.
    """
    text = text.lstrip("\ufeff")
    rows = [(i, line.strip()) for i, line in enumerate(text.splitlines(), 1)
            if line.strip() and not line.lstrip().startswith("#")]
    left = re.search(r"\bLEFT\s*=\s*([-+\d.eE]+)", text)
    right = re.search(r"\bRIGHT\s*=\s*([-+\d.eE]+)", text)
    size = re.search(r"\bSIZE\s*=\s*(\d+)", text)
    values = []
    if left and right and size:
        for line_no, line in rows:
            try:
                values.append(complex(re.sub(r"\s+", "", line).replace("I", "j").replace("i", "j")))
            except ValueError as exc:
                raise ValueError(f"Line {line_no}: expected one complex number (real+imaginary i).") from exc
        if len(values) != int(size.group(1)):
            raise ValueError(f"SIZE says {size.group(1)} points, but {len(values)} were read.")
        z = np.asarray(values, dtype=complex)
        x = np.linspace(float(left.group(1)), float(right.group(1)), len(z))
    else:
        if not rows or re.split(r"[,;\s]+", rows[0][1].lower()) != ["ppm", "real", "imag"]:
            raise ValueError("Expected TopSpin LEFT / RIGHT / SIZE headers, or a 'ppm real imag' table.")
        for line_no, line in rows[1:]:
            try:
                row = [float(v) for v in re.split(r"[,;\s]+", line)]
                if len(row) != 3:
                    raise ValueError()
                values.append(row)
            except ValueError as exc:
                raise ValueError(f"Line {line_no}: expected ppm, real, imag.") from exc
        data = np.asarray(values)
        if len(data) < 8:
            raise ValueError("At least eight points are required.")
        x, z = data[:, 0], data[:, 1] + 1j * data[:, 2]
    spectrum = HNMRSpectrum(name, x, z.real, z.imag, source).validate()
    spectrum.metadata.update(raw_step_ppm=float(np.median(np.diff(spectrum.x))),
                             import_format="TopSpin complex ASCII", nucleus="1H")
    return spectrum


def parse_hnmr_ascii(path: str | Path) -> HNMRSpectrum:
    path = Path(path)
    return parse_hnmr_text(path.read_text(encoding="utf-8-sig"), path.stem, str(path))


@dataclass
class HNMRSettings:
    ppm_min: float = -40.0
    ppm_max: float = 50.0
    grid_step: float = 0.038175372291959775
    phase: bool = True
    baseline: bool = True
    edge_fraction: float = 0.12
    phase0_offset: float = 0.0
    phase1_deg: float = 0.0
    gaussian_fwhm: float = 0.0
    align: bool = False
    max_shift: float = 0.3
    alignment_min: float = 6.0
    alignment_max: float = 9.0

    def validate(self):
        numbers = [v for v in asdict(self).values() if not isinstance(v, bool)]
        if not all(np.isfinite(v) for v in numbers):
            raise ValueError("Preprocessing parameters must be finite numbers.")
        if self.ppm_min >= self.ppm_max or self.grid_step <= 0:
            raise ValueError("Use increasing ppm bounds and a positive grid step.")
        count = (self.ppm_max-self.ppm_min)/self.grid_step
        if not 16 <= count <= 200_000:
            raise ValueError("The common grid must contain 17 to 200,001 points.")
        if not 0.01 <= self.edge_fraction <= 0.25 or self.gaussian_fwhm < 0 or self.max_shift < 0:
            raise ValueError("Baseline edge fraction: 0.01–0.25; broadening and shift limit: nonnegative.")
        if self.alignment_min >= self.alignment_max:
            raise ValueError("Alignment bounds must increase.")
        return self


def common_settings(spectra: list[HNMRSpectrum]) -> HNMRSettings:
    if not spectra:
        raise ValueError("Activate at least one spectrum.")
    low = max(float(s.x[0]) for s in spectra)
    high = min(float(s.x[-1]) for s in spectra)
    # Wide signal-free candidate edges for these broad solid-state 1H exports.
    low, high = max(low, -40.), min(high, 50.)
    step = max(float(np.median(np.diff(s.x))) for s in spectra)
    return HNMRSettings(ppm_min=low, ppm_max=high, grid_step=step).validate()


def _baseline(x, y, fraction):
    count = max(3, int(len(x)*fraction))
    indices = np.r_[0:count, len(x)-count:len(x)]
    xx, yy = x[indices], y[indices]
    # Robust edge-only linear regression, never fitting through the broad peak.
    keep = np.ones(len(xx), dtype=bool)
    for _ in range(4):
        coeff = np.polyfit(xx[keep], yy[keep], 1)
        residual = yy-np.polyval(coeff, xx)
        mad = np.median(np.abs(residual-np.median(residual)))
        if mad <= np.finfo(float).eps * max(1., np.max(np.abs(yy))):
            break
        candidate = np.abs(residual-np.median(residual)) <= 4.5*mad
        if candidate.sum() < 4:
            break
        keep = candidate
    return np.polyval(coeff, x), coeff.tolist()


def automatic_phase(x, z, fraction=0.12):
    """Zero-order ACME-style derivative entropy with a negative-area penalty.

    A bounded global scan prevents local optimizers selecting the inverted
    spectrum. First-order phase is an explicit manual parameter, not guessed.
    """
    scale = np.max(np.abs(z))
    if scale == 0:
        return 0.0
    # Real-only data have no quadrature information: entropy is invariant under
    # positive cosine scaling and must not choose an arbitrary attenuating phase.
    if np.max(np.abs(z.imag)) < scale*1e-12:
        return 0.0 if trapezoid(z.real, x) >= 0 else 180.0
    z = z/scale
    def score(deg):
        y = (z*np.exp(1j*np.deg2rad(deg))).real
        baseline, _ = _baseline(x, y, fraction)
        y = y-baseline
        d = np.abs(np.diff(y)); total = d.sum()
        p = d/total if total > 1e-15 else d
        entropy = -np.sum(p[p > 0]*np.log(p[p > 0]))
        negative = np.minimum(y, 0)
        return float(entropy + 1000*np.sum(negative**2)/(np.sum(y**2)+1e-30))
    grid = np.arange(-180., 180., 10.)
    start = float(grid[np.argmin([score(v) for v in grid])])
    result = minimize_scalar(score, bounds=(start-10, start+10), method="bounded")
    return float((result.x+180) % 360-180)


@dataclass
class ProcessedH:
    x: np.ndarray
    y: np.ndarray
    imaginary: np.ndarray
    baseline: np.ndarray
    audit: dict


def process_hnmr(spectrum: HNMRSpectrum, settings: HNMRSettings,
                 phase0: float | None = None, shift: float = 0.) -> ProcessedH:
    settings.validate()
    if not np.isfinite(shift):
        raise ValueError("Chemical-shift correction must be finite.")
    lo, hi = settings.ppm_min, settings.ppm_max
    if lo < spectrum.x[0]+shift-1e-8 or hi > spectrum.x[-1]+shift+1e-8:
        raise ValueError(f"{spectrum.name}: common range exceeds measured coverage; no extrapolation is allowed.")
    count = int(np.ceil((hi-lo)/settings.grid_step))+1
    x = np.linspace(lo, hi, count)
    z = np.interp(x-shift, spectrum.x, spectrum.real) + 1j*np.interp(x-shift, spectrum.x, spectrum.imag)
    p0 = 0.
    if settings.phase:
        p0 = automatic_phase(x, z, settings.edge_fraction) if phase0 is None else float(phase0)
        phase = p0 + settings.phase0_offset + settings.phase1_deg*(x-(lo+hi)/2)/(hi-lo)
        z = z*np.exp(1j*np.deg2rad(phase))
    baseline, coeff = _baseline(x, z.real, settings.edge_fraction) if settings.baseline else (np.zeros_like(x), [0., 0.])
    y = z.real-baseline
    if settings.gaussian_fwhm:
        sigma = settings.gaussian_fwhm/(2*np.sqrt(2*np.log(2))*(x[1]-x[0]))
        y = gaussian_filter1d(y, sigma, mode="reflect")
    audit = {"settings": asdict(settings), "auto_phase0_deg": p0, "shift_added_ppm": shift,
             "phase_source": "manual override" if "manual_phase0" in spectrum.metadata else "automatic zero-order",
             "phase_pivot_ppm": (lo+hi)/2, "baseline_slope_intercept": coeff,
             "actual_grid_step_ppm": float(x[1]-x[0]), "points": count,
             "normalization": "None (quantitative intensity preserved)",
             "source_sha256": hashlib.sha256(np.column_stack((spectrum.x, spectrum.real, spectrum.imag)).tobytes()).hexdigest()}
    return ProcessedH(x, y, z.imag, baseline, audit)


def prepare_spectra(spectra: list[HNMRSpectrum], settings: HNMRSettings, prepared=True):
    """All-or-nothing preparation; persist the exact individual phase and shift."""
    if not spectra:
        raise ValueError("Activate at least one spectrum.")
    settings.validate()
    results = [process_hnmr(s, settings, s.metadata.get("manual_phase0")) for s in spectra]
    if settings.align and len(results) > 1:
        reference = results[0]
        mask = (reference.x >= settings.alignment_min) & (reference.x <= settings.alignment_max)
        if mask.sum() < 8:
            raise ValueError("Alignment window needs at least eight common points.")
        x = reference.x[mask]; a = reference.y[mask]
        if np.std(a) <= 1e-15:
            raise ValueError("Alignment reference is flat.")
        for i, (spectrum, result) in enumerate(zip(spectra[1:], results[1:]), 1):
            def score(shift):
                b = np.interp(x-shift, result.x, result.y)
                if np.std(b) <= 1e-15:
                    return 2.
                return float(1-np.corrcoef(a, b)[0, 1])
            if settings.max_shift > 0:
                search = np.linspace(-settings.max_shift, settings.max_shift, 61)
                shift = float(search[np.argmin([score(v) for v in search])])
                results[i] = process_hnmr(spectrum, settings, result.audit["auto_phase0_deg"], shift)
    group = uuid4().hex
    for spectrum, result in zip(spectra, results):
        spectrum.processing = {"prepared": bool(prepared), "group_id": group if prepared else "",
                               "settings": asdict(settings),
                               "phase0": result.audit["auto_phase0_deg"] if settings.phase else spectrum.metadata.get("manual_phase0"),
                               "shift": result.audit["shift_added_ppm"], "audit": result.audit}
    return results


def preview_spectrum(spectrum):
    if not spectrum.processing:
        prepare_spectra([spectrum], common_settings([spectrum]), prepared=False)
    p = spectrum.processing
    result = process_hnmr(spectrum, HNMRSettings(**p["settings"]), p.get("phase0"), p.get("shift", 0.))
    # Keep the last enabled phase angle when temporarily hiding correction.
    if p["settings"]["phase"]:
        p["phase0"] = result.audit["auto_phase0_deg"]
    p["audit"] = result.audit
    return result


def integrate(x, y, low, high):
    if not np.isfinite([low, high]).all() or low >= high:
        raise ValueError("Integration bounds must be finite and increasing.")
    if low < x[0]-1e-8 or high > x[-1]+1e-8:
        raise ValueError("An integration region lies outside the processed range.")
    keep = (x > low) & (x < high)
    xx = np.r_[low, x[keep], high]
    yy = np.r_[np.interp(low, x, y), y[keep], np.interp(high, x, y)]
    return float(trapezoid(yy, xx))


DEFAULT_MASSES = {"PDA": 18.33, "PDA-C6": 17.28, "PDA-C18": 16.56, "PDA-DMEN(+)": 18.54, "PDA-Arg": 16.18,
                  "ANP": 19.25, "ANP-C6": 19.20, "ANP-C18": 17.75, "ANP-DMEN(+)": 18.27, "ANP-Arg": 15.78}


def default_parameters():
    return {"format": "LabPlotter H NMR parameters", "version": 1,
            "standards": [{"name": "Supplied internal standard", "area": 42565812.55, "mmol_h": 1.861273386,
                           "basis": "ppm", "grid_step": None, "frequency_mhz": None,
                           "verified": False}],
            "cores": [{"name": "PDA", "capacity": 0.0693}, {"name": "ANP", "capacity": 0.1619}],
            "ligands": [{"name": "C6", "mw": 101.19, "effective_h": 13.},
                        {"name": "C18", "mw": 269.51, "effective_h": 37.},
                        {"name": "DMEN(+)", "mw": 88.15, "effective_h": 10.},
                        {"name": "Arg", "mw": 174.20, "effective_h": 7.},
                        {"name": "Lys", "mw": 146.19, "effective_h": None}],
            "samples": [{"name": k, "mass_mg": v} for k, v in DEFAULT_MASSES.items()]}


def infer_identity(name):
    tokens = re.split(r"[^A-Z0-9+]+", name.upper())
    core = "ANP" if "ANP" in tokens else "PDA" if "PDA" in tokens else ""
    ligand = next((v for v in ("C18", "C6", "ARG", "LYS", "DMEN", "PLUS") if v in tokens), "")
    ligand = {"ARG": "Arg", "LYS": "Lys", "DMEN": "DMEN(+)", "PLUS": "DMEN(+)"}.get(ligand, ligand)
    return core, ligand


@dataclass
class QuantSettings:
    core: str = "PDA"
    ligand: str = "C6"
    sample_mass_mg: float = 18.33
    reference_mass_mg: float = 18.33
    capacity_umol_mg: float = 0.0693
    molecular_weight: float = 101.19
    effective_h: float = 13.
    standard_area: float = 42565812.55
    standard_mmol_h: float = 1.861273386
    standard_basis: str = "ppm"
    standard_grid_step: float | None = None
    frequency_mhz: float | None = None
    response_factor: float = 1.
    reference_response_factor: float = 1.
    aliphatic_min: float = 0.
    aliphatic_max: float = 4.5
    aromatic_min: float = 6.
    aromatic_max: float = 9.
    core_scaling: str = "aromatic"
    method: str = "regions"
    calibration_verified: bool = False
    acquisition_verified: bool = False
    assignments_verified: bool = False
    use_prepared: bool = True

    def validate(self):
        for key in ("sample_mass_mg", "reference_mass_mg", "capacity_umol_mg", "molecular_weight", "effective_h",
                    "standard_area", "standard_mmol_h", "response_factor", "reference_response_factor"):
            value = getattr(self, key)
            if value is None or not np.isfinite(value) or value <= 0:
                raise ValueError(f"{key}: enter a finite positive value (Lys proton count is intentionally blank).")
        if self.standard_basis not in ("ppm", "point_sum", "hz") or self.method not in ("regions", "gaussian"):
            raise ValueError("Unsupported integration or calibration method.")
        if self.core_scaling not in ("aromatic", "mass"):
            raise ValueError("Choose aromatic or mass core scaling.")
        if not self.core.strip() or not self.ligand.strip():
            raise ValueError("Choose a core and a ligand (use a hypothetical ligand for a pristine-core blank check).")
        if not np.isfinite([self.aliphatic_min, self.aliphatic_max, self.aromatic_min, self.aromatic_max]).all():
            raise ValueError("Region bounds must be finite.")
        if not self.aliphatic_min < self.aliphatic_max < self.aromatic_min < self.aromatic_max:
            raise ValueError("Use separate increasing aliphatic and aromatic regions, with a gap between them.")
        self.standard_ppm_area()
        return self

    def standard_ppm_area(self):
        if self.standard_basis == "ppm":
            return self.standard_area
        value = self.standard_grid_step if self.standard_basis == "point_sum" else self.frequency_mhz
        if value is None or not np.isfinite(value) or value <= 0:
            raise ValueError("Point-sum calibration needs the STANDARD's original ppm step; Hz calibration needs MHz.")
        return self.standard_area*value if self.standard_basis == "point_sum" else self.standard_area/value


def quant_defaults(spectrum, parameters):
    core, ligand = infer_identity(spectrum.name)
    q = QuantSettings(core=core, ligand=ligand or "C6")
    for row in parameters["cores"]:
        if row["name"] == core:
            q.capacity_umol_mg = row["capacity"]
    for row in parameters["ligands"]:
        if row["name"] == q.ligand:
            q.molecular_weight, q.effective_h = row["mw"], row["effective_h"]
    masses = {r["name"]: r["mass_mg"] for r in parameters["samples"]}
    q.sample_mass_mg = masses.get(core+("-"+ligand if ligand else ""))
    q.reference_mass_mg = masses.get(core)
    standard = parameters["standards"][0]
    for target, source in (("standard_area", "area"), ("standard_mmol_h", "mmol_h"),
                           ("standard_basis", "basis"), ("standard_grid_step", "grid_step"),
                           ("frequency_mhz", "frequency_mhz"), ("calibration_verified", "verified")):
        setattr(q, target, standard[source])
    q.use_prepared = bool(spectrum.processing.get("prepared"))
    return q


def _gaussian_decomposition(x, y, q):
    """Three positive bands; an exploratory model, not a unique peak assignment."""
    bounds = [(q.aliphatic_min, q.aliphatic_max), (q.aliphatic_max, q.aromatic_min), (q.aromatic_min, q.aromatic_max)]
    # Fit broad tails too. Integrate components only within the recorded range.
    scale = max(float(np.max(np.abs(y))), 1e-30)
    def components(p):
        return [scale*p[i*3]*np.exp(-0.5*((x-p[i*3+1])/p[i*3+2])**2) for i in range(3)]
    initial, low, high = [], [], []
    for lo, hi in bounds:
        initial.extend([0.5, (lo+hi)/2, max(0.3, (hi-lo)/2)])
        low.extend([0., lo, 0.05]); high.extend([10., hi, max(1., (x[-1]-x[0])/2)])
    fit = least_squares(lambda p: (sum(components(p))-y)/scale, initial, bounds=(low, high), max_nfev=1500)
    if not fit.success:
        raise ValueError("Gaussian decomposition did not converge. Inspect the regions or use region integrals.")
    curves = components(fit.x)
    denominator = np.sum((y-y.mean())**2)
    r2 = float(1-np.sum((sum(curves)-y)**2)/denominator) if denominator else None
    return {"aliphatic": float(trapezoid(curves[0], x)), "aromatic": float(trapezoid(curves[2], x)),
            "curves": curves, "audit": {"fit_R2": r2, "amplitude_center_sigma": fit.x.reshape(3, 3).tolist(),
                "amplitude_scale": scale, "center_bounds_ppm": bounds,
                "area_domain_ppm": [float(x[0]), float(x[-1])], "nfev": fit.nfev}}


@dataclass
class QuantResult:
    sample: ProcessedH
    reference: ProcessedH
    values: dict
    parameters: dict
    warnings: list[str]
    core_curve: np.ndarray
    excess_curve: np.ndarray
    components: list[np.ndarray]
    audit: str


def quantify(sample: HNMRSpectrum, reference: HNMRSpectrum, q: QuantSettings) -> QuantResult:
    q.validate()
    if q.use_prepared:
        p, r = sample.processing, reference.processing
        if not p.get("prepared") or not r.get("prepared") or not p.get("group_id") or p.get("group_id") != r.get("group_id") or p.get("settings") != r.get("settings"):
            raise ValueError("Prepare sample and pristine reference together, or uncheck 'Use saved common preprocessing'.")
        a, b = preview_spectrum(sample), preview_spectrum(reference)
    else:
        settings = common_settings([sample, reference])
        # Honor the preview's correction switches; apply exactly the same policy to both.
        switches = sample.processing.get("settings", {})
        settings.phase = switches.get("phase", True); settings.baseline = switches.get("baseline", True)
        a = process_hnmr(sample, settings, sample.metadata.get("manual_phase0"))
        b = process_hnmr(reference, settings, reference.metadata.get("manual_phase0"))
    if len(a.x) != len(b.x) or not np.allclose(a.x, b.x, rtol=0, atol=1e-9):
        raise ValueError("Sample and reference must share the same grid.")
    ar = integrate(a.x, a.y, q.aliphatic_min, q.aliphatic_max)
    aa = integrate(a.x, a.y, q.aromatic_min, q.aromatic_max)
    br = integrate(b.x, b.y, q.aliphatic_min, q.aliphatic_max)
    ba = integrate(b.x, b.y, q.aromatic_min, q.aromatic_max)
    area_a, aromatic_a, area_b, aromatic_b = ar, aa, br, ba
    fit_a = fit_b = None
    components = []
    warnings = []
    if q.method == "gaussian":
        fit_a, fit_b = _gaussian_decomposition(a.x, a.y, q), _gaussian_decomposition(b.x, b.y, q)
        area_a, aromatic_a, area_b, aromatic_b = fit_a["aliphatic"], fit_a["aromatic"], fit_b["aliphatic"], fit_b["aromatic"]
        components = fit_a["curves"]
        warnings.append("Three-band Gaussian decomposition is a non-unique model. Inspect the fit and assignments; band areas include tails outside nominal regions.")
        if any(f["audit"]["fit_R2"] is None or f["audit"]["fit_R2"] < .98 for f in (fit_a, fit_b)):
            warnings.append("The Gaussian model does not closely reproduce at least one spectrum (fit R2 < 0.98). Review the decomposition before using its areas.")
    if q.core_scaling == "aromatic":
        if aromatic_b <= max(1e-20, abs(area_b)*1e-10) or aromatic_a <= 0:
            raise ValueError("Positive aromatic reference and sample areas are required for core scaling.")
        alpha = aromatic_a*q.response_factor/(aromatic_b*q.reference_response_factor)
    else:
        alpha = q.sample_mass_mg/q.reference_mass_mg
    excess = area_a*q.response_factor-alpha*area_b*q.reference_response_factor
    n_h = excess/q.standard_ppm_area()*q.standard_mmol_h*1000
    n_lig = n_h/q.effective_h
    loading = n_lig/q.sample_mass_mg
    coverage = 100*loading/q.capacity_umol_mg
    ligand_mass = n_lig*q.molecular_weight/1000
    if not q.calibration_verified:
        warnings.append("PROVISIONAL: standard area unit/processing scale has not been verified. ppm is only a provisional interpretation of the supplied area.")
    if not q.acquisition_verified:
        warnings.append("PROVISIONAL: confirm quantitative excitation, relaxation, scan count, receiver gain, filling and response factors against the standard and core reference.")
    if not q.assignments_verified:
        warnings.append("PROVISIONAL: effective H is a structural non-exchangeable-H count, not proof that the selected band captures all of those protons. Broad tails/overlap need checking.")
    if coverage < 0 or coverage > 100:
        warnings.append("Coverage is outside 0–100%; it has NOT been clipped. Check calibration, regions, reference scaling, proton count and the capacity model.")
    if ligand_mass > q.sample_mass_mg:
        warnings.append("Ligand-equivalent mass exceeds the entered mass: absolute calibration/response is inconsistent.")
    warnings.append("Apparent ligand-equivalent coverage under the selected core/capacity model; 1H NMR alone does not establish covalent grafting or surface-only binding. Capacity denominator uses the entered mass (default: weighed sample mass).")
    values = {"aliphatic_integral": ar, "aromatic_integral": aa, "reference_aliphatic_integral": br,
              "reference_aromatic_integral": ba, "aliphatic_aromatic_ratio": ar/aa if aa else None,
              "quant_aliphatic_area": area_a, "quant_aromatic_area": aromatic_a,
              "reference_quant_aliphatic_area": area_b, "reference_quant_aromatic_area": aromatic_b,
              "core_scale": alpha, "excess_aliphatic_area": excess,
              "excess_H_umol": n_h, "ligand_umol": n_lig, "loading_umol_mg": loading,
              "capacity_umol": q.capacity_umol_mg*q.sample_mass_mg,
              "apparent_coverage_percent": coverage, "ligand_equivalent_mass_mg": ligand_mass,
              "ligand_equivalent_mass_percent": 100*ligand_mass/q.sample_mass_mg,
              "standard_area_intensity_ppm": q.standard_ppm_area()}
    if fit_a:
        values.update(sample_fit_R2=fit_a["audit"]["fit_R2"], reference_fit_R2=fit_b["audit"]["fit_R2"])
    core_curve = alpha*b.y*q.reference_response_factor
    excess_curve = a.y*q.response_factor-core_curve
    audit = {"sample": {"name": sample.name, "uid": sample.uid, "source": sample.source},
             "reference": {"name": reference.name, "uid": reference.uid, "source": reference.source},
             "parameters": asdict(q), "sample_preprocessing": a.audit, "reference_preprocessing": b.audit,
             "sample_fit": fit_a["audit"] if fit_a else None, "reference_fit": fit_b["audit"] if fit_b else None,
             "results": values, "warnings": warnings}
    equations = ("All signed integrals use the trapezoidal rule on increasing ppm with interpolated exact endpoints.\n"
                 "No maximum/area normalization; imaginary data are rotated with real data.\n"
                 "alpha = (Arom_sample * response_sample) / (Arom_core * response_core), or mass_sample / mass_core\n"
                 "DeltaA = Aliph_sample * response_sample - alpha * Aliph_core * response_core\n"
                 "nH [umol] = DeltaA / standard_area[intensity*ppm] * standard_mmol_H * 1000\n"
                 "nLigand [umol] = nH / effective_H\n"
                 "Loading [umol/mg] = nLigand / entered_mass_mg\n"
                 "Coverage [%] = 100 * Loading / maximum_capacity_umol_mg\n"
                 "Ligand-equivalent mass [mg] = nLigand * parent_ligand_MW / 1000\n"
                 "point_sum standard converts to intensity*ppm by multiplying STANDARD original ppm step; Hz area divides by MHz.\n\n")
    return QuantResult(a, b, values, asdict(q), warnings, core_curve, excess_curve, components,
                       equations+json.dumps(audit, indent=2, ensure_ascii=False, allow_nan=False))


def result_csv(result):
    import io
    stream = io.StringIO()
    arrays = [result.sample.x, result.sample.y, result.sample.imaginary, result.reference.y,
              result.core_curve, result.excess_curve] + result.components
    header = "ppm,sample_processed,sample_imaginary,reference_processed,scaled_core,excess_response_corrected"
    if result.components:
        header += ",fit_aliphatic,fit_middle,fit_aromatic"
    np.savetxt(stream, np.column_stack(arrays), delimiter=",", header=header, comments="", fmt="%.12g")
    return stream.getvalue()
