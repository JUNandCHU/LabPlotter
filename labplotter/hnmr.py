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
    decomposition_values, decomposition_csv, restore_decomposition, decomposition_defaults)
from .hnmr_quality import estimate_spacing, masked_baseline, phase_zero_first, sideband_diagnostics, instrument_preset


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
    auto_phase1: bool = False
    balance_sidebands: bool = False
    masked_baseline: bool = False
    baseline_degree: int = 2
    baseline_exclusion: float = 20.
    baseline_anchor_min: float = 0.
    sideband_spacing: float = 55.
    mas_hz: float = 0.
    proton_mhz: float = 0.

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
        if self.baseline_degree != int(self.baseline_degree) or not 0 <= self.baseline_degree <= 2:
            raise ValueError("Baseline degree must be 0, 1 or 2.")
        self.baseline_degree = int(self.baseline_degree)
        if self.mas_hz < 0 or self.proton_mhz < 0 or bool(self.mas_hz) != bool(self.proton_mhz):
            raise ValueError('Enter both MAS Hz and 1H MHz, or both 0 for estimated spacing.')
        if self.mas_hz:
            self.sideband_spacing = self.mas_hz/self.proton_mhz
        if not 10 <= self.sideband_spacing <= 200 or not 3 <= self.baseline_exclusion < self.sideband_spacing/2:
            raise ValueError("Baseline exclusion half-width must be at least 3 ppm and less than half the sideband spacing (10–200 ppm).")
        if self.baseline_anchor_min < 0: raise ValueError('Baseline anchor distance must be nonnegative.')
        return self


def common_settings(spectra: list[HNMRSpectrum]) -> HNMRSettings:
    if not spectra:
        raise ValueError("Activate at least one spectrum.")
    low = max(float(s.x[0]) for s in spectra)
    high = min(float(s.x[-1]) for s in spectra)
    # Wide signal-free candidate edges for these broad solid-state 1H exports.
    wide = low <= -150 and high >= 160
    low, high = max(low, -200. if wide else -40.), min(high, 210. if wide else 50.)
    step = max(float(np.median(np.diff(s.x))) for s in spectra)
    instruments = {instrument_preset(s) for s in spectra} if wide else {(0., 0.)}
    if len(instruments) != 1:
        raise ValueError('Selected spectra have different MAS/frequency settings. Prepare compatible acquisitions together.')
    mas_hz, proton_mhz = instruments.pop()
    spacing = mas_hz/proton_mhz if mas_hz else float(np.median([estimate_spacing(s.x,s.real+1j*s.imag)[0] for s in spectra])) if wide else 55.
    return HNMRSettings(ppm_min=low, ppm_max=high, grid_step=step, auto_phase1=wide, balance_sidebands=wide,
                        masked_baseline=wide, baseline_degree=1 if wide else 2,
                        baseline_anchor_min=min(145.,(high-low)*.40) if wide else 0., sideband_spacing=spacing,
                        mas_hz=mas_hz, proton_mhz=proton_mhz).validate()


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
    raw_x: np.ndarray | None = None
    raw_complex: np.ndarray | None = None


def process_hnmr(spectrum: HNMRSpectrum, settings: HNMRSettings,
                 phase0: float | None = None, shift: float = 0., phase1: float | None = None) -> ProcessedH:
    settings.validate()
    if not np.isfinite(shift):
        raise ValueError("Chemical-shift correction must be finite.")
    lo, hi = settings.ppm_min, settings.ppm_max
    if lo < spectrum.x[0]+shift-1e-8 or hi > spectrum.x[-1]+shift+1e-8:
        raise ValueError(f"{spectrum.name}: common range exceeds measured coverage; no extrapolation is allowed.")
    count = int(np.ceil((hi-lo)/settings.grid_step))+1
    x = np.linspace(lo, hi, count)
    z = np.interp(x-shift, spectrum.x, spectrum.real) + 1j*np.interp(x-shift, spectrum.x, spectrum.imag)
    p0 = p1 = 0.
    phase_audit = {'method':'disabled','warnings':[]}
    if settings.phase:
        p0 = automatic_phase(x, z, settings.edge_fraction) if phase0 is None else float(phase0)
        if phase0 is None and settings.auto_phase1:
            p0, p1, phase_audit = phase_zero_first(x, z, p0, settings.sideband_spacing,
                                                  settings.baseline_exclusion, settings.baseline_degree,
                                                  settings.baseline_anchor_min, settings.balance_sidebands)
        else:
            p1 = float(phase1 or 0.)
            phase_audit = deepcopy(spectrum.processing.get('audit',{}).get('phase_diagnostics',
                                   {'method':'zero-order / saved correction','warnings':[]}))
        if 'manual_phase0' in spectrum.metadata or 'manual_phase1' in spectrum.metadata:
            anchor=spectrum.metadata.get('manual_phase_reference',{'pivot':(lo+hi)/2,'span':hi-lo})
            old_span=float(anchor['span']);old_pivot=float(anchor['pivot'])
            if not np.isfinite([old_span,old_pivot]).all() or old_span<=0: raise ValueError('Invalid manual phase reference.')
            slope=float(spectrum.metadata.get('manual_phase1', 0.))/old_span
            p0=float(spectrum.metadata.get('manual_phase0',p0))+slope*((lo+hi)/2-old_pivot)
            p1=slope*(hi-lo)
            phase_audit = {'method':'manual PH0/PH1 override','warnings':[]}
        if not np.isfinite([p0,p1]).all(): raise ValueError('Phase angles must be finite.')
        phase = p0 + settings.phase0_offset + (p1+settings.phase1_deg)*(x-(lo+hi)/2)/(hi-lo)
        z = z*np.exp(1j*np.deg2rad(phase))
    if settings.baseline and settings.masked_baseline:
        baseline, baseline_audit = masked_baseline(x, z.real, settings.sideband_spacing,
                                                   settings.baseline_exclusion, settings.baseline_degree, settings.baseline_anchor_min)
        coeff = None
    else:
        baseline, coeff = _baseline(x, z.real, settings.edge_fraction) if settings.baseline else (np.zeros_like(x), [0.,0.])
        baseline_audit = {'mode':'linear edges' if settings.baseline else 'disabled', 'slope_intercept':coeff}
    y = z.real-baseline
    if settings.gaussian_fwhm:
        sigma = settings.gaussian_fwhm/(2*np.sqrt(2*np.log(2))*(x[1]-x[0]))
        y = gaussian_filter1d(y, sigma, mode="reflect")
    audit = {"settings": asdict(settings), "auto_phase0_deg": p0, "auto_phase1_deg": p1, "shift_added_ppm": shift,
             "phase_source": phase_audit['method'], "phase_diagnostics":phase_audit,
             "phase_pivot_ppm": (lo+hi)/2, "baseline_slope_intercept": coeff,
             "baseline_diagnostics":baseline_audit,
             "actual_grid_step_ppm": float(x[1]-x[0]), "points": count,
             "normalization": "None (quantitative intensity preserved)",
             "source_sha256": hashlib.sha256(np.column_stack((spectrum.x, spectrum.real, spectrum.imag)).tobytes()).hexdigest()}
    if hi-lo >= 200:
        audit['sideband_diagnostics'] = sideband_diagnostics(x,y,settings.sideband_spacing,anchor_min=settings.baseline_anchor_min)
    return ProcessedH(x, y, z.imag, baseline, audit, spectrum.x+shift, spectrum.real+1j*spectrum.imag)


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
                results[i] = process_hnmr(spectrum, settings, result.audit["auto_phase0_deg"], shift, result.audit['auto_phase1_deg'])
    group = uuid4().hex
    for spectrum, result in zip(spectra, results):
        spectrum.metadata['acquisition'] = {'mas_hz': settings.mas_hz, 'proton_mhz': settings.proton_mhz,
                                           'source': 'editable processing preset; verify against acquisition'}
        spectrum.processing = {"prepared": bool(prepared), "group_id": group if prepared else "",
                               "settings": asdict(settings),
                               "phase0": result.audit["auto_phase0_deg"] if settings.phase else spectrum.metadata.get("manual_phase0"),
                               "phase1": result.audit['auto_phase1_deg'] if settings.phase else spectrum.metadata.get('manual_phase1'),
                               "shift": result.audit["shift_added_ppm"], "audit": result.audit}
    return results


def preview_spectrum(spectrum):
    if not spectrum.processing:
        prepare_spectra([spectrum], common_settings([spectrum]), prepared=False)
    p = spectrum.processing
    result = process_hnmr(spectrum, HNMRSettings(**p["settings"]), p.get("phase0"), p.get("shift", 0.), p.get('phase1'))
    # Keep the last enabled phase angle when temporarily hiding correction.
    if p["settings"]["phase"]:
        p["phase0"] = result.audit["auto_phase0_deg"]
        p['phase1'] = result.audit['auto_phase1_deg']
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
                  "ANP": 38.38, "ANP-C6": 19.20, "ANP-C18": 17.75, "ANP-DMEN(+)": 55.18, "ANP-Arg": 15.78}


def default_parameters():
    return {"format": "LabPlotter H NMR parameters", "version": 2,
            "standards": [{"name": "Supplied internal standard", "area": 42565812.55, "umol_h": 1.861273386,
                           "basis": "ppm", "grid_step": None, "frequency_mhz": None,
                           "verified": False, "includes_sidebands": True}],
            "cores": [{"name": "PDA", "capacity": 0.0693}, {"name": "ANP", "capacity": 0.1619}],
            "ligands": [{"name": "C6", "mw": 101.19, "effective_h": 13., 'schiff_h':None, 'michael_h':None},
                        {"name": "C18", "mw": 269.51, "effective_h": 37., 'schiff_h':None, 'michael_h':None},
                        {"name": "DMEN(+)", "mw": 88.15, "effective_h": 10., 'schiff_h':None, 'michael_h':None},
                        {"name": "Arg", "mw": 174.20, "effective_h": 7., 'schiff_h':None, 'michael_h':None},
                        {"name": "Lys", "mw": 146.19, "effective_h": None, 'schiff_h':None, 'michael_h':None}],
            "samples": [{"name": k, "mass_mg": v} for k, v in DEFAULT_MASSES.items()]}


def infer_identity(name):
    tokens = re.split(r"[^A-Z0-9+]+", name.upper())
    core = "ANP" if "ANP" in tokens else "PDA" if "PDA" in tokens else ""
    ligand = next((v for v in ("C18", "C6", "ARG", "LYS", "DMEN", "PLUS") if v in tokens), "")
    ligand = {"ARG": "Arg", "LYS": "Lys", "DMEN": "DMEN(+)", "PLUS": "DMEN(+)"}.get(ligand, ligand)
    return core, ligand


@dataclass
class QuantSettings:
    model: str = 'envelopes'
    core: str = "PDA"
    ligand: str = "C6"
    sample_mass_mg: float = 18.33
    reference_mass_mg: float = 18.33
    capacity_umol_mg: float = 0.0693
    molecular_weight: float = 101.19
    effective_h: float = 13.
    schiff_h: float | None = None
    michael_h: float | None = None
    include_linkage_nh: bool = True
    standard_area: float = 42565812.55
    standard_umol_h: float = 1.861273386
    standard_basis: str = "ppm"
    standard_grid_step: float | None = None
    frequency_mhz: float | None = None
    response_factor: float = 1.
    reference_response_factor: float = 1.
    aliphatic_min: float = 0.
    aliphatic_max: float = 4.5
    aromatic_min: float = 5.5
    aromatic_max: float = 9.
    core_scaling: str = "aromatic_reference"
    method: str = "decomposition"
    fit_min: float = -20.
    fit_max: float = 25.
    fwhm_min: float = .15
    fwhm_max: float = 25.
    line_shape: str = "pseudo_voigt"
    overlap_band: bool = False
    sidebands: bool = False
    sideband_order: int = 2
    sideband_spacing: float = 55.
    refine_spacing: bool = True
    mas_hz: float = 0.
    proton_mhz: float = 0.
    sideband_width_scale: float = 1.
    fit_sideband_width: bool = False
    allow_negative_sidebands: bool = False
    aliphatic_gaussian_fraction: float | None = None
    aromatic_gaussian_fraction: float | None = None
    ligand_min: float = -.5
    ligand_max: float = 3.
    ligand_fwhm_min: float = .3
    ligand_fwhm_max: float = 15.
    template_shift_max: float = .3
    template_broadening_max: float = 0.
    unassigned_min: float = 2.
    unassigned_max: float = 9.
    unassigned_fwhm_min: float = 14.
    unassigned_fwhm_max: float = 50.
    complex_fit_min: float = -170.
    complex_fit_max: float = 180.
    joint_phase: bool = True
    joint_phase0_limit: float = 30.
    joint_phase1_limit: float = 180.
    standard_includes_sidebands: bool = False
    sideband_scope_verified: bool = False
    sample_core_mass_mg: float | None = None
    calibration_verified: bool = False
    acquisition_verified: bool = False
    assignments_verified: bool = False
    use_prepared: bool = True
    show_provisional: bool = True

    def validate(self):
        for key in ("sample_mass_mg", "reference_mass_mg", "capacity_umol_mg", "molecular_weight", "effective_h",
                    "standard_area", "standard_umol_h", "response_factor", "reference_response_factor"):
            value = getattr(self, key)
            if value is None or not np.isfinite(value) or value <= 0:
                raise ValueError(f"{key}: enter a finite positive value (Lys proton count is intentionally blank).")
        for name in ('schiff_h', 'michael_h'):
            value = getattr(self,name)
            if value is not None and (not np.isfinite(value) or value <= 0):
                raise ValueError(name+': enter positive H atoms captured per ligand, or leave blank for automatic counts.')
        if self.standard_basis not in ("ppm", "point_sum", "hz") or self.method != "decomposition":
            raise ValueError("Unsupported integration or calibration method.")
        if self.model == 'core_template' and self.core_scaling == 'aromatic_reference':
            self.core_scaling = 'core_reference'
        elif self.model != 'core_template' and self.core_scaling == 'core_reference':
            self.core_scaling = 'aromatic_reference'
        if self.core_scaling not in ("mass", "aromatic_reference", 'core_reference'):
            raise ValueError("Choose aromatic_reference normalization or mass-based core subtraction.")
        if self.sample_core_mass_mg is not None and (not np.isfinite(self.sample_core_mass_mg) or not 0 < self.sample_core_mass_mg <= self.sample_mass_mg):
            raise ValueError("Core mass must be positive and no greater than entered sample mass.")
        # Desktop number fields and JSON may supply 2.0 for the integer order.
        # Keep the validated canonical value, not only the temporary copy.
        self.sideband_order = self.decomposition_settings().validate().sideband_order
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
            q.schiff_h, q.michael_h = row.get('schiff_h'), row.get('michael_h')
    masses = {r["name"]: r["mass_mg"] for r in parameters["samples"]}
    q.sample_mass_mg = masses.get(core+("-"+ligand if ligand else ""))
    q.reference_mass_mg = masses.get(core)
    standard = parameters["standards"][0]
    for target, source in (("standard_area", "area"), ("standard_umol_h", "umol_h"),
                           ("standard_basis", "basis"), ("standard_grid_step", "grid_step"),
                           ("frequency_mhz", "frequency_mhz"), ("calibration_verified", "verified")):
        setattr(q, target, standard[source])
    q.use_prepared = bool(spectrum.processing.get("prepared"))
    q.standard_includes_sidebands = bool(standard.get('includes_sidebands', False))
    for key, value in asdict(decomposition_defaults(spectrum)).items():
        if key in DecompositionSettings.__dataclass_fields__: setattr(q, key, value)
    return q


def restored_quant_settings(spectrum, parameters):
    """Migrate legacy defaults; preserve custom calibration amounts and masses."""
    q = quant_defaults(spectrum, parameters)
    saved = deepcopy(spectrum.metadata.get("analysis_parameters", {}))
    if saved and 'standard_umol_h' not in saved:
        old_amount = saved.pop('standard_mmol_h', None)
        supplied = (old_amount == 1.861273386 and saved.get('standard_area') == 42565812.55
                    and not saved.get('calibration_verified', False))
        if old_amount is not None:
            saved['standard_umol_h'] = old_amount if supplied else old_amount*1000
        saved['core_scaling'] = 'aromatic_reference'
        saved['assignments_verified'] = False
        old_masses = {'ANP': 19.25, 'ANP-DMEN(+)': 18.27}
        core, ligand = infer_identity(spectrum.name)
        identity = core+('-'+ligand if ligand else '')
        for field, name in (('sample_mass_mg', identity), ('reference_mass_mg', core)):
            if name in old_masses and saved.get(field) == old_masses[name]:
                saved[field] = next((r['mass_mg'] for r in parameters['samples'] if r['name'] == name), DEFAULT_MASSES[name])
        spectrum.metadata['quantitation_migration_note'] = (
            '0.10.5: aromatic-reference normalization selected. The unverified supplied standard is interpreted as '
            '1.861273386 umol H; custom/verified mmol amounts are converted to umol without changing their amount. '
            'Unchanged legacy ANP mass defaults use the updated parameter library. Review before calculation.')
    for key, value in saved.items():
        if key in QuantSettings.__dataclass_fields__: setattr(q, key, value)
    if saved.get("method") != "decomposition":
        q.method, q.core_scaling = "decomposition", "aromatic_reference"
        q.calibration_verified = q.acquisition_verified = q.assignments_verified = False
        q.aromatic_min = 5.5
    if saved and 'standard_includes_sidebands' not in saved:
        q.sideband_scope_verified = False
    for key, value in spectrum.metadata.get("decomposition_settings", {}).items():
        if key in DecompositionSettings.__dataclass_fields__: setattr(q, key, value)
    if saved and not spectrum.metadata.get('analysis_audit'):
        q.assignments_verified = q.sideband_scope_verified = False
    return q


def coverage_algebra(area_a, aromatic_a, area_b, aromatic_b, q):
    """Auditable area -> umol H -> aromatic matching -> core subtraction.

    In aromatic_reference mode the normalized sample is expressed on the
    pristine reference's per-mg scale. This is a reference-equivalent loading,
    not an independent mass measurement. Spectrum display arrays stay raw.
    """
    q.validate()
    if not np.isfinite([area_a, aromatic_a, area_b, aromatic_b]).all():
        raise ValueError('Component areas must be finite.')
    k = q.standard_umol_h/q.standard_ppm_area()
    ms, mc = q.sample_mass_mg, q.reference_mass_mg
    ali_s = area_a*q.response_factor/ms
    aro_s = aromatic_a*q.response_factor/ms
    ali_c = area_b*q.reference_response_factor/mc
    aro_c = aromatic_b*q.reference_response_factor/mc
    factor = 1.
    core_mass = q.sample_core_mass_mg if q.sample_core_mass_mg is not None else ms
    if q.core_scaling == 'aromatic_reference':
        if aro_s <= 0 or aro_c <= 0:
            raise ValueError('Aromatic-reference normalization requires positive sample and pristine aromatic integrals.')
        factor = aro_c/aro_s
        core_mass = ms
    alpha = core_mass/mc
    normalized_area = area_a*q.response_factor*factor
    excess = normalized_area-alpha*area_b*q.reference_response_factor
    n_h = excess*k
    n_lig = n_h/q.effective_h
    loading = n_lig/ms
    ligand_mass = n_lig*q.molecular_weight/1000
    absolute = {'excess_H_umol': n_h, 'ligand_umol': n_lig, 'loading_umol_mg': loading,
                'apparent_coverage_percent': 100*loading/q.capacity_umol_mg,
                'ligand_equivalent_mass_mg': ligand_mass, 'ligand_equivalent_mass_percent': 100*ligand_mass/ms}
    values = {'standard_H_umol_per_area': k, 'standard_H_umol': q.standard_umol_h,
              'sample_aliphatic_area_per_mg': ali_s, 'sample_aromatic_area_per_mg': aro_s,
              'reference_aliphatic_area_per_mg': ali_c, 'reference_aromatic_area_per_mg': aro_c,
              'sample_aliphatic_H_umol': area_a*q.response_factor*k,
              'sample_aromatic_H_umol': aromatic_a*q.response_factor*k,
              'sample_aliphatic_H_umol_per_mg': ali_s*k, 'sample_aromatic_H_umol_per_mg': aro_s*k,
              'reference_aliphatic_H_umol_per_mg': ali_c*k, 'reference_aromatic_H_umol_per_mg': aro_c*k,
              'aromatic_normalization_factor': factor, 'normalized_sample_aliphatic_area': normalized_area,
              'normalized_sample_aliphatic_H_umol_per_mg': normalized_area*k/ms,
              'normalized_sample_aromatic_H_umol_per_mg': aro_s*factor*k,
              'excess_aliphatic_H_umol_per_mg': n_h/ms,
              'maximum_ligand_H_umol_per_mg': q.effective_h*q.capacity_umol_mg,
              'core_scale': alpha, 'core_mass_used_mg': core_mass, 'excess_aliphatic_area': excess,
              'aliphatic_area_per_mg_difference': ali_s-ali_c,
              'capacity_umol': q.capacity_umol_mg*ms, 'standard_area_intensity_ppm': q.standard_ppm_area()}
    from .hnmr_reactions import reaction_coverage
    counts, endpoints = reaction_coverage(n_h/ms, q)
    values.update(counts); absolute.update(endpoints)
    if not all(np.isfinite(v) for v in list(values.values())+list(absolute.values())):
        raise ValueError('Quantitative algebra overflowed. Check calibration and mass inputs.')
    return values, absolute


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
    validation_issues: list[str] = field(default_factory=list)
    provisional: bool = False


def quantify(sample: HNMRSpectrum, reference: HNMRSpectrum, q: QuantSettings) -> QuantResult:
    q.validate()
    if q.use_prepared:
        p, r = sample.processing, reference.processing
        if not p.get("prepared") or not r.get("prepared") or not p.get("group_id") or p.get("group_id") != r.get("group_id") or p.get("settings") != r.get("settings"):
            raise ValueError("Prepare sample and pristine reference together, or uncheck 'Use saved common preprocessing'.")
        a, b = preview_spectrum(sample), preview_spectrum(reference)
    else:
        settings = common_settings([sample, reference])
        if q.sidebands and q.mas_hz:
            settings.mas_hz, settings.proton_mhz = q.mas_hz, q.proton_mhz
            settings.validate()
        switches = sample.processing.get("settings", {})
        settings.phase = switches.get("phase", True); settings.baseline = switches.get("baseline", True)
        a = process_hnmr(sample, settings, sample.metadata.get("manual_phase0"))
        b = process_hnmr(reference, settings, reference.metadata.get("manual_phase0"))
    if len(a.x) != len(b.x) or not np.allclose(a.x, b.x, rtol=0, atol=1e-9):
        raise ValueError("Sample and reference must share the same grid.")
    settings = q.decomposition_settings()
    if settings.model == 'core_template':
        from .hnmr_template import quantify_template
        return quantify_template(sample, reference, q, a, b)
    def fitted(s, processed):
        prior = restore_decomposition(processed, s.metadata.get("decomposition"))
        if prior and prior.audit["settings"] == asdict(settings): return prior
        return decompose(processed, settings)
    fit_a = fitted(sample, a)
    fit_b = fit_a if sample.uid == reference.uid else fitted(reference, b)
    area_a, aromatic_a = fit_a.areas["aliphatic"], fit_a.areas["aromatic"]
    area_b, aromatic_b = fit_b.areas["aliphatic"], fit_b.areas["aromatic"]
    algebra, absolute = coverage_algebra(area_a, aromatic_a, area_b, aromatic_b, q)
    alpha = algebra['core_scale']
    coverage = absolute['apparent_coverage_percent']
    ligand_mass = absolute['ligand_equivalent_mass_mg']
    blockers = []
    if not q.calibration_verified: blockers.append("standard area unit and absolute response scale")
    if not q.acquisition_verified: blockers.append("quantitative acquisition / response factors")
    if not q.assignments_verified: blockers.append("component assignment, H per ligand and core background model")
    if q.standard_includes_sidebands != q.sidebands:
        blockers.append('sample / standard sideband integration scopes do not match')
    if q.sidebands and not q.sideband_scope_verified:
        blockers.append('sideband coverage, weak peaks and phase/baseline review')
    warnings = ["Sample: "+w for w in fit_a.warnings]+["Reference: "+w for w in fit_b.warnings]
    for label, processed in (('Sample',a),('Reference',b)):
        warnings += [label+': '+w for w in processed.audit.get('phase_diagnostics',{}).get('warnings',[])]
    if q.sidebands:
        for label, fit in (('sample',fit_a),('reference',fit_b)):
            diag=fit.audit['sideband_diagnostics']
            detected={row['order'] for row in diag['envelopes'] if row['status']=='detected'}
            if any(not row['included'] and row['status']=='detected' for row in diag['envelopes']):
                blockers.append(label+' has detected signal outside the included sideband orders')
            if any(row['included'] and row['status']=='detected' and (row['negative_fraction'] or 0)>.15 for row in diag['envelopes']):
                blockers.append(label+' has substantial negative sideband signal: review phase/baseline')
            if any(row['order'] in detected and row['RMSE_over_local_peak']>.25 for row in fit.audit['local_fit_errors'] if row['order']):
                blockers.append(label+' sideband fit has substantial local residuals')
    if any(f.audit["fit_R2"] < .98 for f in (fit_a, fit_b)):
        blockers.append("inadequate decomposition fit (R2 < 0.98)")
    for label, fit in (('sample', fit_a), ('reference', fit_b)):
        if fit.audit.get('preprocessing_spacing_mismatch'):
            blockers.append(label+' preprocessing and fixed fitting spacings differ')
        if fit.audit.get('assignment_ambiguous'):
            blockers.append(label+' component separation is ambiguous (bounds, correlation or alternate solutions)')
        if any(line['area'] < 0 for line in fit.audit.get('lines', [])):
            blockers.append(label+' has signed negative fitted sideband areas')
    if q.core_scaling == 'aromatic_reference':
        warnings.append('Aromatic-reference normalization assumes unchanged aromatic H signal per unit core mass. '
                        'The sample mass cancels from loading/coverage; pristine-reference mass remains. '
                        'Amounts are reference-equivalent values, not independent grafted-mass measurements.')
        if q.sample_core_mass_mg is not None:
            warnings.append('Known sample core mass is used only in mass mode; aromatic_reference uses the pristine per-mg scale.')
    elif q.sample_core_mass_mg is None:
        warnings.append("Core background uses entered total sample mass as an approximation. Enter independently known core mass if available; aromatic area is not used to estimate mass.")
    provisional = bool(blockers) and q.show_provisional
    status = (f"Provisional estimate; {len(blockers)} unresolved checks. See Calculation details."
              if provisional else "Withheld: verify " + "; ".join(blockers)
              if blockers else "Model-based ligand-equivalent coverage")
    if blockers:
        warnings.insert(0, "Unresolved checks: " + "; ".join(blockers))
        warnings.insert(0, "Provisional amounts use the entered calibration, response, H count and core model; they are not validated coverage."
                        if provisional else "Reviewed-only mode hides absolute amounts until the checks are resolved.")
    if coverage < 0 or coverage > 100:
        warnings.append("The calibration/model algebra is outside 0–100%; it has NOT been clipped. This is not a validated surface coverage.")
        if not blockers: status = "Outside 0–100%: calibration / core / capacity model inconsistent"
    if ligand_mass > q.sample_mass_mg:
        warnings.append("Ligand-equivalent mass exceeds the entered sample mass: absolute calibration/response or assignment is inconsistent.")
    warnings.append("NMR component assignments are model dependent. Aliphatic includes intrinsic core H; water/OH/NH and background can overlap. NMR alone does not establish covalent grafting or surface-only binding.")
    from .hnmr_reactions import REACTION_NOTE
    warnings.append(REACTION_NOTE)
    values = decomposition_values(fit_a)
    values.update(reference_aliphatic_integral=area_b, reference_aromatic_integral=aromatic_b,
                  reference_aliphatic_signal_fraction_percent=100*area_b/(area_b+aromatic_b) if area_b+aromatic_b else None,
                  quant_aliphatic_area=area_a, quant_aromatic_area=aromatic_a,
                  reference_quant_aliphatic_area=area_b, reference_quant_aromatic_area=aromatic_b,
                  reference_fit_R2=fit_b.audit["fit_R2"])
    values.update(algebra)
    if values['aliphatic_area_per_mg_difference'] < 0:
        warnings.append('Sample fitted aliphatic area per entered mg is below its pristine reference. Check component assignment, phase and response scales; the fit was not forced to satisfy an expected ordering.')
    values.update({k: None if blockers and not q.show_provisional else v for k, v in absolute.items()})
    # Window integrals are diagnostic only and never drive this calculation.
    for label, processed, fitted in (("sample", a, fit_a), ("reference", b, fit_b)):
        xx,yy = (fitted.x,fitted.observed) if fitted.audit.get('version') == 5 else (processed.x,processed.y)
        values[label+"_window_aliphatic_area"] = integrate(xx, yy, q.aliphatic_min, q.aliphatic_max)
        values[label+"_window_aromatic_area"] = integrate(xx, yy, q.aromatic_min, q.aromatic_max)
    core_curve = alpha*fit_b.curves["aliphatic"]*q.reference_response_factor
    excess_curve = fit_a.curves["aliphatic"]*q.response_factor*algebra['aromatic_normalization_factor']-core_curve
    audit = {"sample": {"name": sample.name, "uid": sample.uid, "source": sample.source},
             "reference": {"name": reference.name, "uid": reference.uid, "source": reference.source},
             "parameters": asdict(q), "sample_preprocessing": a.audit, "reference_preprocessing": b.audit,
             "sample_fit": fit_a.audit, "reference_fit": fit_b.audit, "results": values,
             "quantitative_status": status, "provisional": provisional, "validation_issues": blockers,
             "assumptions": {
                 "standard_area_basis": q.standard_basis, "standard_area_intensity_ppm": q.standard_ppm_area(),
                 "standard_umol_H": q.standard_umol_h,
                 "sample_response_multiplier": q.response_factor, "reference_response_multiplier": q.reference_response_factor,
                 "equal_response_assumed": not q.acquisition_verified and q.response_factor == q.reference_response_factor == 1.,
                 "calibration_verified": q.calibration_verified, "acquisition_verified": q.acquisition_verified,
                 "core_background": q.core_scaling,
                 "normalization_preserves_aromatic_H_per_core_mg": q.core_scaling == 'aromatic_reference',
                 "migration_note": sample.metadata.get('quantitation_migration_note', ''),
                 "coverage_clipped": False},
             "unvalidated_algebra_only": absolute if blockers else None, "warnings": warnings}
    equations = ("Fit absorption spectrum = aliphatic + aromatic [+ unassigned]. Ver2 jointly fits both quadratures with phase and affine background; unassigned area is excluded from coverage. Residual = data - sum.\n"
                 "MAS model: each family = sum of order 0 and independent +/- sidebands; center_n = center_0 + n * spacing. spacing[ppm] = MAS[Hz] / 1H[MHz] when provided.\n"
                 "Family integral = sum of measured finite-domain integrals of every included order, not central area times number of peaks. No +/- height symmetry is imposed.\n"
                 "Pseudo-Voigt = height * [(1-eta)*exp(-4*ln(2)*((ppm-center)/FWHM)^2) + eta/(1+4*((ppm-center)/FWHM)^2)].\n"
                 "Component areas use analytic integrals between fit_min and fit_max, INCLUDING overlapping tails. Center bounds are not integration cutoffs.\n"
                 "Preprocessing and displayed fit retain the intensity scale. Quantitative normalization is a separate algebraic step.\n"
                 "k = standard_H_umol / standard_area[intensity*ppm]. No mmol-to-umol multiplier is applied to a umol input.\n"
                 "Sample ali/aro H per mg = fitted component area * sample_response * k / sample_mass_mg.\n"
                 "Core ali/aro H per mg = fitted component area * core_response * k / reference_mass_mg.\n"
                 "AROMATIC_REFERENCE: f = core_aromatic_H_per_mg / sample_aromatic_H_per_mg.\n"
                 "Normalized sample aliphatic H per mg = sample_aliphatic_H_per_mg * f.\n"
                 "Excess H per mg = normalized sample aliphatic H per mg - core_aliphatic_H_per_mg.\n"
                 "Coverage [%] = 100 * excess_H_per_mg / (H_per_ligand * maximum_capacity_umol_mg).\n"
                 "Sample mass cancels in this reference-equivalent coverage. Reference mass does not cancel. The normalization factor is NOT a measured mass ratio.\n"
                 "MASS MODE: f = 1; alpha = entered sample core mass / reference_mass_mg (sample total mass if core mass is blank).\n"
                 "AROMATIC_REFERENCE MODE: alpha = sample_mass_mg / reference_mass_mg.\n"
                 "DeltaA = fitted Aliph_sample * response_sample * f - alpha * fitted Aliph_core * response_core.\n"
                 "nH [umol] = DeltaA * k; in aromatic_reference mode this is a normalized reference-equivalent amount.\n"
                 "nLigand [umol] = nH / H_atoms_represented_per_ligand (stoichiometry, NOT particle mass estimation)\n"
                 "Coverage [%] = 100 * nLigand / (entered_mass_mg * maximum_capacity_umol_mg)\n"
                 "Signal fraction [%] = 100 * A_aliphatic / (A_aliphatic + A_aromatic); NOT grafting efficiency or coverage.\n"
                 "point_sum standard: multiply by STANDARD original ppm step; Hz area: divide by MHz.\n"
                 "Default: show provisional absolute amounts with unresolved checks. Optional reviewed-only mode hides them.\n"
                 "Negative and >100% results are retained; no expected sample ordering is imposed.\n\n")
    equations += ('Reaction endpoints: coverage_Schiff = 100 * excess_H_per_mg / (H_Schiff * capacity); '
                  'coverage_Michael = 100 * excess_H_per_mg / (H_Michael * capacity). Sort numerically for lower/upper, including negative results.\n'+REACTION_NOTE+'\n\n')
    return QuantResult(a, b, values, asdict(q), warnings, core_curve, excess_curve,
                       list(fit_a.curves.values()), equations+json.dumps(audit, indent=2, ensure_ascii=False, allow_nan=False),
                       fit_a, fit_b, status, blockers, provisional)


def result_csv(result):
    import io
    f, r = result.sample_fit, result.reference_fit
    stream = io.StringIO()
    if result.parameters.get('model') == 'core_template':
        arrays = [f.x, f.observed, *f.curves.values(), f.total, f.residual,
                  np.interp(f.x, r.x, r.observed), result.core_curve, result.excess_curve]
        header = ','.join(['ppm', 'sample_processed', *('fit_'+k for k in f.curves),
                           'sample_total_fit', 'sample_residual', 'pristine_reference_processed',
                           'scaled_core_template', 'ligand_area_on_calculation_scale'])
        np.savetxt(stream, np.column_stack(arrays), delimiter=',', header=header, comments='', fmt='%.12g')
        return stream.getvalue()
    arrays = [f.x, f.observed, *f.curves.values(), f.total, f.residual,
              r.observed, r.curves["aliphatic"], r.curves["aromatic"], r.total, r.residual,
              result.core_curve, result.excess_curve,
              result.core_curve+result.excess_curve]
    header = ("ppm,sample_processed,"+",".join("fit_"+k for k in f.curves)+
              ",sample_total_fit,sample_residual,reference_processed,reference_fit_aliphatic,reference_fit_aromatic,reference_total_fit,reference_residual,scaled_core_aliphatic,excess_aliphatic,normalized_sample_aliphatic")
    np.savetxt(stream, np.column_stack(arrays), delimiter=",", header=header, comments="", fmt="%.12g")
    return stream.getvalue()
