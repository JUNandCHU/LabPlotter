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
from scipy.optimize import minimize_scalar
from .hnmr_decomposition import (DecompositionSettings, DecompositionResult, decompose,
    decomposition_values, decomposition_csv, restore_decomposition)


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
    aromatic_min: float = 5.5
    aromatic_max: float = 9.
    core_scaling: str = "mass"
    method: str = "decomposition"
    fit_min: float = -20.
    fit_max: float = 25.
    fwhm_min: float = .15
    fwhm_max: float = 25.
    line_shape: str = "pseudo_voigt"
    overlap_band: bool = False
    sample_core_mass_mg: float | None = None
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
        if self.standard_basis not in ("ppm", "point_sum", "hz") or self.method != "decomposition":
            raise ValueError("Unsupported integration or calibration method.")
        if self.core_scaling != "mass":
            raise ValueError("Aromatic-area mass inference is retired. Use entered core / reference masses.")
        if self.sample_core_mass_mg is not None and (not np.isfinite(self.sample_core_mass_mg) or not 0 < self.sample_core_mass_mg <= self.sample_mass_mg):
            raise ValueError("Core mass must be positive and no greater than entered sample mass.")
        self.decomposition_settings().validate()
        if not self.core.strip() or not self.ligand.strip():
            raise ValueError("Choose a core and a ligand (use a hypothetical ligand for a pristine-core blank check).")
        if not np.isfinite([self.aliphatic_min, self.aliphatic_max, self.aromatic_min, self.aromatic_max]).all():
            raise ValueError("Region bounds must be finite.")
        if not self.aliphatic_min < self.aliphatic_max < self.aromatic_min < self.aromatic_max:
            raise ValueError("Use separate increasing aliphatic and aromatic regions, with a gap between them.")
        self.standard_ppm_area()
        return self

    def decomposition_settings(self):
        return DecompositionSettings(**{key: getattr(self, key) for key in DecompositionSettings.__dataclass_fields__})

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
    for key, value in spectrum.metadata.get("decomposition_settings", {}).items():
        if key in DecompositionSettings.__dataclass_fields__: setattr(q, key, value)
    return q


def restored_quant_settings(spectrum, parameters):
    """Migrate saved 0.10.0 choices without accepting old quantitation claims."""
    q = quant_defaults(spectrum, parameters)
    saved = spectrum.metadata.get("analysis_parameters", {})
    for key, value in saved.items():
        if key in QuantSettings.__dataclass_fields__: setattr(q, key, value)
    if saved.get("method") != "decomposition":
        q.method, q.core_scaling = "decomposition", "mass"
        q.calibration_verified = q.acquisition_verified = q.assignments_verified = False
        q.aromatic_min = 5.5
    for key, value in spectrum.metadata.get("decomposition_settings", {}).items():
        if key in DecompositionSettings.__dataclass_fields__: setattr(q, key, value)
    return q


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
    sample_fit: DecompositionResult
    reference_fit: DecompositionResult
    quantitative_status: str


def quantify(sample: HNMRSpectrum, reference: HNMRSpectrum, q: QuantSettings) -> QuantResult:
    q.validate()
    if q.use_prepared:
        p, r = sample.processing, reference.processing
        if not p.get("prepared") or not r.get("prepared") or not p.get("group_id") or p.get("group_id") != r.get("group_id") or p.get("settings") != r.get("settings"):
            raise ValueError("Prepare sample and pristine reference together, or uncheck 'Use saved common preprocessing'.")
        a, b = preview_spectrum(sample), preview_spectrum(reference)
    else:
        settings = common_settings([sample, reference])
        switches = sample.processing.get("settings", {})
        settings.phase = switches.get("phase", True); settings.baseline = switches.get("baseline", True)
        a = process_hnmr(sample, settings, sample.metadata.get("manual_phase0"))
        b = process_hnmr(reference, settings, reference.metadata.get("manual_phase0"))
    if len(a.x) != len(b.x) or not np.allclose(a.x, b.x, rtol=0, atol=1e-9):
        raise ValueError("Sample and reference must share the same grid.")
    settings = q.decomposition_settings()
    def fitted(s, processed):
        prior = restore_decomposition(processed, s.metadata.get("decomposition"))
        if prior and prior.audit["settings"] == asdict(settings): return prior
        return decompose(processed, settings)
    fit_a, fit_b = fitted(sample, a), fitted(reference, b)
    area_a, aromatic_a = fit_a.areas["aliphatic"], fit_a.areas["aromatic"]
    area_b, aromatic_b = fit_b.areas["aliphatic"], fit_b.areas["aromatic"]
    # No aromatic-intensity mass estimate. Known core mass is preferred; weighed
    # total mass is an explicit approximation, requiring assignment review.
    core_mass = q.sample_core_mass_mg if q.sample_core_mass_mg is not None else q.sample_mass_mg
    alpha = core_mass/q.reference_mass_mg
    excess = area_a*q.response_factor-alpha*area_b*q.reference_response_factor
    n_h = excess/q.standard_ppm_area()*q.standard_mmol_h*1000
    n_lig = n_h/q.effective_h
    loading = n_lig/q.sample_mass_mg
    coverage = 100*loading/q.capacity_umol_mg
    ligand_mass = n_lig*q.molecular_weight/1000
    blockers = []
    if not q.calibration_verified: blockers.append("standard area unit and absolute response scale")
    if not q.acquisition_verified: blockers.append("quantitative acquisition / response factors")
    if not q.assignments_verified: blockers.append("component assignment, H per ligand and core background model")
    warnings = ["Sample: "+w for w in fit_a.warnings]+["Reference: "+w for w in fit_b.warnings]
    if any(f.audit["fit_R2"] < .98 for f in (fit_a, fit_b)):
        blockers.append("inadequate decomposition fit (R2 < 0.98)")
    if q.sample_core_mass_mg is None:
        warnings.append("Core background uses entered total sample mass as an approximation. Enter independently known core mass if available; aromatic area is not used to estimate mass.")
    status = "Withheld: verify " + "; ".join(blockers) if blockers else "Model-based ligand-equivalent coverage"
    if blockers: warnings.insert(0, status+". Component areas remain available; signal fraction is NOT surface coverage.")
    if coverage < 0 or coverage > 100:
        warnings.append("The calibration/model algebra is outside 0–100%; it has NOT been clipped. This is not a validated surface coverage.")
        if not blockers: status = "Outside 0–100%: calibration / core / capacity model inconsistent"
    if ligand_mass > q.sample_mass_mg:
        warnings.append("Ligand-equivalent mass exceeds the entered sample mass: absolute calibration/response or assignment is inconsistent.")
    warnings.append("NMR component assignments are model dependent. Aliphatic includes intrinsic core H; water/OH/NH and background can overlap. NMR alone does not establish covalent grafting or surface-only binding.")
    values = decomposition_values(fit_a)
    values.update(reference_aliphatic_integral=area_b, reference_aromatic_integral=aromatic_b,
                  quant_aliphatic_area=area_a, quant_aromatic_area=aromatic_a,
                  reference_quant_aliphatic_area=area_b, reference_quant_aromatic_area=aromatic_b,
                  core_scale=alpha, core_mass_used_mg=core_mass, excess_aliphatic_area=excess,
                  reference_fit_R2=fit_b.audit["fit_R2"],
                  capacity_umol=q.capacity_umol_mg*q.sample_mass_mg,
                  standard_area_intensity_ppm=q.standard_ppm_area())
    absolute = {"excess_H_umol": n_h, "ligand_umol": n_lig, "loading_umol_mg": loading,
                "apparent_coverage_percent": coverage, "ligand_equivalent_mass_mg": ligand_mass,
                "ligand_equivalent_mass_percent": 100*ligand_mass/q.sample_mass_mg}
    values.update({k: None if blockers else v for k, v in absolute.items()})
    # Window integrals are diagnostic only and never drive this calculation.
    for label, processed in (("sample", a), ("reference", b)):
        values[label+"_window_aliphatic_area"] = integrate(processed.x, processed.y, q.aliphatic_min, q.aliphatic_max)
        values[label+"_window_aromatic_area"] = integrate(processed.x, processed.y, q.aromatic_min, q.aromatic_max)
    core_curve = alpha*fit_b.curves["aliphatic"]*q.reference_response_factor
    excess_curve = fit_a.curves["aliphatic"]*q.response_factor-core_curve
    audit = {"sample": {"name": sample.name, "uid": sample.uid, "source": sample.source},
             "reference": {"name": reference.name, "uid": reference.uid, "source": reference.source},
             "parameters": asdict(q), "sample_preprocessing": a.audit, "reference_preprocessing": b.audit,
             "sample_fit": fit_a.audit, "reference_fit": fit_b.audit, "results": values,
             "quantitative_status": status, "unvalidated_algebra_only": absolute if blockers else None, "warnings": warnings}
    equations = ("Fit processed real spectrum = aliphatic + aromatic [+ unassigned]. Residual = data - sum.\n"
                 "Pseudo-Voigt = height * [(1-eta)*exp(-4*ln(2)*((ppm-center)/FWHM)^2) + eta/(1+4*((ppm-center)/FWHM)^2)].\n"
                 "Component areas use analytic integrals between fit_min and fit_max, INCLUDING overlapping tails. Center bounds are not integration cutoffs.\n"
                 "No maximum/area normalization; no aromatic-based mass inference.\n"
                 "alpha = entered core mass / pristine-reference mass (total sample mass approximation if core mass blank)\n"
                 "DeltaA = fitted Aliph_sample * response_sample - alpha * fitted Aliph_core * response_core\n"
                 "nH [umol] = DeltaA / standard_area[intensity*ppm] * standard_mmol_H * 1000\n"
                 "nLigand [umol] = nH / H_atoms_represented_per_ligand (stoichiometry, NOT particle mass estimation)\n"
                 "Coverage [%] = 100 * nLigand / (entered_mass_mg * maximum_capacity_umol_mg)\n"
                 "Signal fraction [%] = 100 * A_aliphatic / (A_aliphatic + A_aromatic); NOT grafting efficiency or coverage.\n"
                 "point_sum standard: multiply by STANDARD original ppm step; Hz area: divide by MHz.\n"
                 "Absolute amounts are withheld until calibration, acquisition and assignments are reviewed.\n\n")
    return QuantResult(a, b, values, asdict(q), warnings, core_curve, excess_curve,
                       list(fit_a.curves.values()), equations+json.dumps(audit, indent=2, ensure_ascii=False, allow_nan=False),
                       fit_a, fit_b, status)


def result_csv(result):
    import io
    f, r = result.sample_fit, result.reference_fit
    stream = io.StringIO()
    arrays = [f.x, f.observed, *f.curves.values(), f.total, f.residual,
              r.observed, r.curves["aliphatic"], r.curves["aromatic"], r.total, r.residual,
              result.core_curve, result.excess_curve]
    header = ("ppm,sample_processed,"+",".join("fit_"+k for k in f.curves)+
              ",sample_total_fit,sample_residual,reference_processed,reference_fit_aliphatic,reference_fit_aromatic,reference_total_fit,reference_residual,scaled_core_aliphatic,excess_aliphatic")
    np.savetxt(stream, np.column_stack(arrays), delimiter=",", header=header, comments="", fmt="%.12g")
    return stream.getvalue()
