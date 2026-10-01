"""Constrained 1H envelope fits; chemical assignments remain explicit hypotheses.

The two family curves are integrated over the measured fit domain, including
shared tails. Center bounds are NOT integration windows. No intensity
normalization or aromatic-based mass inference is performed.
"""
from dataclasses import asdict, dataclass
from copy import deepcopy
import hashlib
import io
import json

import numpy as np
from scipy.optimize import least_squares
from scipy.special import erf

MODEL_LABELS = {'envelopes': 'model Ver1', 'broad_core3': 'model Ver2',
                'core_template': 'Legacy core template (0.10.7-0.10.8)'}
SCALING_LABELS = {'aromatic_reference': 'On - aromatic reference', 'mass': 'Off - entered masses',
                  'core_reference': 'Legacy core template scaling'}


@dataclass
class DecompositionSettings:
    model: str = 'envelopes'
    fit_min: float = -20.
    fit_max: float = 25.
    aliphatic_min: float = 0.
    aliphatic_max: float = 4.5
    aromatic_min: float = 5.5
    aromatic_max: float = 9.
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

    def validate(self):
        if self.model not in MODEL_LABELS:
            raise ValueError('Choose a supported decomposition model.')
        numbers = [v for k, v in asdict(self).items() if k not in ("line_shape", 'model') and v is not None and not isinstance(v, bool)]
        if not np.isfinite(numbers).all():
            raise ValueError("Decomposition bounds must be finite.")
        if not self.fit_min < self.aliphatic_min < self.aliphatic_max < self.aromatic_min < self.aromatic_max < self.fit_max:
            raise ValueError("Fit range must enclose separate increasing aliphatic / aromatic center bounds.")
        if not 0 < self.fwhm_min < self.fwhm_max <= 2*(self.fit_max-self.fit_min):
            raise ValueError("Use positive increasing FWHM bounds, at most twice the fit span.")
        if self.model == 'core_template' and not self.fit_min < self.ligand_min < self.ligand_max < self.fit_max:
            raise ValueError('Fit range must enclose the additional ligand center bounds.')
        if self.model == 'core_template' and not 0 < self.ligand_fwhm_min < self.ligand_fwhm_max <= 2*(self.fit_max-self.fit_min):
            raise ValueError('Use positive increasing ligand FWHM bounds within twice the fit span.')
        if not 0 <= self.template_shift_max <= 10 or not 0 <= self.template_broadening_max <= 20:
            raise ValueError('Core template shift: 0–10 ppm; extra Gaussian FWHM: 0–20 ppm (0 = fixed).')
        if self.line_shape not in ("pseudo_voigt", "gaussian", "lorentzian"):
            raise ValueError("Choose pseudo_voigt, gaussian or lorentzian.")
        for fraction in (self.aliphatic_gaussian_fraction, self.aromatic_gaussian_fraction):
            if fraction is not None and not 0 <= fraction <= 1:
                raise ValueError('Fixed Gaussian fraction must be 0–1, or blank for free fitting.')
        if self.line_shape != 'pseudo_voigt' and (self.aliphatic_gaussian_fraction is not None or (self.model == 'envelopes' and self.aromatic_gaussian_fraction is not None)):
            raise ValueError('Use pseudo_voigt for per-family fixed G fractions, or leave them blank.')
        if self.model == 'envelopes' and not self.sidebands and (self.aliphatic_gaussian_fraction is not None or self.aromatic_gaussian_fraction is not None):
            raise ValueError('Per-family fixed Gaussian fractions require the linked MAS model.')
        if self.sideband_order != int(self.sideband_order) or not 1 <= self.sideband_order <= 4:
            raise ValueError("Sideband order must be an integer from 1 to 4 (each side).")
        self.sideband_order = int(self.sideband_order)
        if not 10 <= self.sideband_spacing <= 200 or not .25 <= self.sideband_width_scale <= 8:
            raise ValueError("Sideband spacing: 10–200 ppm; width multiplier: 0.25–8.")
        if self.mas_hz < 0 or self.proton_mhz < 0 or bool(self.mas_hz) != bool(self.proton_mhz):
            raise ValueError("Enter both MAS rate (Hz) and 1H frequency (MHz), or leave both at 0 (unknown).")
        spacing = self.mas_hz/self.proton_mhz if self.mas_hz else self.sideband_spacing
        lower = self.ligand_min if self.model == 'core_template' else self.aliphatic_min
        upper = (self.aliphatic_max if self.overlap_band else self.ligand_max) if self.model == 'core_template' else self.aromatic_max
        if self.model == 'core_template' and self.overlap_band: upper = self.aromatic_min
        if self.sidebands and (spacing < 10 or self.fit_min > lower-self.sideband_order*spacing or
                              self.fit_max < upper+self.sideband_order*spacing):
            raise ValueError("Fit range must cover all selected sideband centers. Expand preprocessing and fit bounds.")
        if self.model == 'broad_core3':
            if not self.fit_min < self.unassigned_min < self.unassigned_max < self.fit_max:
                raise ValueError('Fit range must enclose the broad unassigned center bounds.')
            if not 0 < self.unassigned_fwhm_min < self.unassigned_fwhm_max <= 2*(self.fit_max-self.fit_min):
                raise ValueError('Use positive increasing broad unassigned FWHM bounds.')
            if not self.complex_fit_min < self.complex_fit_max:
                raise ValueError('Complex fitting bounds must increase.')
            if not 0 < self.joint_phase0_limit <= 180 or not 0 < self.joint_phase1_limit <= 720:
                raise ValueError('Joint phase limits: PH0 >0 to 180, PH1 >0 to 720 degrees.')
            if self.allow_negative_sidebands or self.fit_sideband_width or (self.refine_spacing and not self.mas_hz):
                raise ValueError('Ver2 uses nonnegative amplitudes and fixed MAS spacing / width multiplier.')
        return self


def select_model(settings, model):
    """Explicit model selection presets; never migrate a saved legacy template fit."""
    settings = deepcopy(settings)
    if settings.model != model and model == 'broad_core3':
        settings.aliphatic_min, settings.aliphatic_max = -.5, 3.5
        settings.aromatic_min, settings.aromatic_max = 5.5, 9.
        settings.fwhm_min, settings.fwhm_max = .3, 15.
        settings.line_shape = 'pseudo_voigt'
        settings.aliphatic_gaussian_fraction = settings.aromatic_gaussian_fraction = None
        settings.refine_spacing = settings.fit_sideband_width = settings.allow_negative_sidebands = False
        settings.sideband_width_scale = 1.
        settings.overlap_band = False  # Ver2 always includes its broad unassigned family.
    settings.model = model
    if hasattr(settings, 'core_scaling'):
        if model == 'core_template' and settings.core_scaling == 'aromatic_reference': settings.core_scaling = 'core_reference'
        elif model != 'core_template' and settings.core_scaling == 'core_reference': settings.core_scaling = 'aromatic_reference'
    return settings


def decomposition_defaults(spectrum, use_saved=True):
    """Data-aware defaults; old saved central-only models remain inspectable."""
    saved = spectrum.metadata.get('decomposition_settings') if use_saved else None
    if saved:
        return DecompositionSettings(**saved).validate()
    if spectrum.x[0] <= -150 and spectrum.x[-1] >= 160:
        from .hnmr_quality import estimate_spacing, instrument_preset
        mas, mhz = instrument_preset(spectrum)
        spacing = mas/mhz if mas else estimate_spacing(spectrum.x, spectrum.real+1j*spectrum.imag)[0]
        return DecompositionSettings(fit_min=-145., fit_max=155., sidebands=True, sideband_spacing=spacing,
                                     mas_hz=mas, proton_mhz=mhz, refine_spacing=not bool(mas))
    return DecompositionSettings()


def profile(x, amplitude, center, fwhm, eta):
    """Height-normalized Gaussian/Lorentzian mixture with a shared FWHM."""
    u = (np.asarray(x)-center)/fwhm
    return amplitude*((1-eta)*np.exp(-4*np.log(2)*u*u)+eta/(1+4*u*u))


def profile_area(low, high, amplitude, center, fwhm, eta):
    u = (np.asarray([low, high])-center)/fwhm
    gaussian = fwhm*np.sqrt(np.pi)/(4*np.sqrt(np.log(2)))*np.diff(erf(2*np.sqrt(np.log(2))*u))[0]
    lorentzian = fwhm/2*np.diff(np.arctan(2*u))[0]
    return float(amplitude*((1-eta)*gaussian+eta*lorentzian))


def fingerprint(p):
    return hashlib.sha256(np.column_stack((p.x, p.y)).astype('<f8').tobytes()).hexdigest()


@dataclass
class DecompositionResult:
    x: np.ndarray
    observed: np.ndarray
    curves: dict
    total: np.ndarray
    residual: np.ndarray
    areas: dict
    audit: dict

    @property
    def warnings(self):
        return self.audit["warnings"]

    def record(self):
        return self.audit


def _domain(p, settings):
    lo, hi = settings.fit_min, settings.fit_max
    if lo < p.x[0]-1e-9 or hi > p.x[-1]+1e-9:
        raise ValueError("Fit range exceeds processed data. Expand preprocessing or narrow the fit range.")
    x = np.r_[lo, p.x[(p.x > lo) & (p.x < hi)], hi]
    if len(x) < 40 or np.min(np.diff(x)) <= 0:
        raise ValueError("Decomposition needs at least 40 distinct points in the fit range.")
    return x, np.interp(x, p.x, p.y)


def _result(p, audit):
    audit = deepcopy(audit)
    if audit.get('version') == 5:
        from .hnmr_family import restore_family
        return restore_family(p, audit)
    if audit.get('version') == 4:
        from .hnmr_template import restore_template
        return restore_template(p, audit)
    settings = DecompositionSettings(**audit['settings']).validate()
    x, y = _domain(p, settings)
    if audit.get('lines'):
        curves = {name: np.zeros_like(x) for name in audit['areas']}
        for line in audit['lines']:
            curves[line['family']] += profile(x, *line['parameters'])
    else:
        curves = {name: profile(x, *params) for name, params in audit['parameters'].items()}
    total = sum(curves.values())
    params = audit['parameters']
    if 'aliphatic' in params and 'aromatic' in params:
        separation = abs(params['aromatic'][1]-params['aliphatic'][1])
        ratio = params['aliphatic'][2]/max(separation, 1e-12)
        audit['aliphatic_width_over_center_separation'] = float(ratio)
        if ratio > 2:
            message = ('Aliphatic FWHM exceeds twice the separation between assigned centers: '
                       'the broad component can capture shared peak tails. Review model sensitivity '
                       'before interpreting its full area as chemical aliphatic H.')
            if message not in audit['warnings']: audit['warnings'].append(message)
            audit['broad_aliphatic_overlap'] = True
    return DecompositionResult(x, y, curves, total, y-total, dict(audit['areas']), audit)


def restore_decomposition(p, record, reference=None):
    """A stored fit is never reused after data, phase, grid or baseline changes."""
    if not record or record.get('version') not in (1, 2, 3, 4, 5) or record.get('processed_sha256') != fingerprint(p):
        return None
    if record.get('version') == 5:
        from .hnmr_family import complex_fingerprint
        if record.get('complex_sha256') != complex_fingerprint(p): return None
    if reference is not None and record.get('version') == 4 and record.get('reference_processed_sha256') != fingerprint(reference):
        return None
    try:
        return _result(p, record)
    except (KeyError, TypeError, ValueError):
        return None


def decompose(p, settings=None, reference=None, reference_info=None, fixed_core_scale=None):
    settings = (settings or DecompositionSettings()).validate()
    if settings.model == 'broad_core3':
        from .hnmr_family import fit_family
        return fit_family(p, settings)
    if settings.model == 'core_template':
        from .hnmr_template import fit_template
        return fit_template(p, reference, settings, reference_info=reference_info, fixed_core_scale=fixed_core_scale)
    if settings.sidebands:
        from .hnmr_sidebands import fit_sidebands
        return fit_sidebands(p, settings)
    x, y = _domain(p, settings)
    scale = float(np.max(np.abs(y)))
    if scale <= 0 or np.std(y) <= scale*1e-10:
        raise ValueError("A flat spectrum cannot be decomposed.")
    names = ['aliphatic', 'aromatic']
    bounds = [(settings.aliphatic_min, settings.aliphatic_max), (settings.aromatic_min, settings.aromatic_max)]
    if settings.overlap_band:
        names.append('unassigned'); bounds.append((settings.aliphatic_max, settings.aromatic_min))
    variable_eta = settings.line_shape == 'pseudo_voigt'
    stride = 4 if variable_eta else 3
    def expand(v):
        rows = np.asarray(v).reshape(-1, stride)
        if variable_eta: return rows
        return np.column_stack((rows, np.full(len(rows), float(settings.line_shape == 'lorentzian'))))
    def model(v):
        return sum(profile(x, *row) for row in expand(v))
    low, high = [], []
    for lo, hi in bounds:
        low.extend([0., lo, settings.fwhm_min]); high.extend([5., hi, settings.fwhm_max])
        if variable_eta: low.append(0.); high.append(1.)
    candidates = []
    for fraction, width in ((.18, 5.), (.55, 9.), (.85, 2.)):
        initial = []
        for i, (lo, hi) in enumerate(bounds):
            center = lo+fraction*(hi-lo) if i == 0 else (lo+hi)/2
            initial.extend([.5, center, np.clip(width, settings.fwhm_min*1.01, settings.fwhm_max*.99)])
            if variable_eta: initial.append(.5)
        fit = least_squares(lambda v: model(v)-y/scale, initial, bounds=(low, high),
                            max_nfev=600, ftol=1e-9, xtol=1e-9, gtol=1e-9)
        if fit.success and np.isfinite(fit.cost): candidates.append(fit)
    if not candidates:
        raise ValueError("Decomposition did not converge. Review phase, baseline and fit bounds.")
    best = min(candidates, key=lambda f: f.cost)
    rows = expand(best.x).copy(); rows[:, 0] *= scale
    params = {name: row.tolist() for name, row in zip(names, rows)}
    areas = {name: profile_area(settings.fit_min, settings.fit_max, *row) for name, row in zip(names, rows)}
    total = model(best.x)*scale; residual = y-total
    r2 = float(1-np.sum(residual**2)/np.sum((y-y.mean())**2))
    warnings = []
    if r2 < .98: warnings.append('Fit R2 < 0.98: the chosen envelopes do not reproduce the spectrum adequately.')
    for name, row, bound in zip(names, rows, bounds):
        if min(row[1]-bound[0], bound[1]-row[1]) < .005*(bound[1]-bound[0]):
            warnings.append(f'{name}: center is at a bound; review assignment and center range.')
        if min(row[2]-settings.fwhm_min, settings.fwhm_max-row[2]) < .002*(settings.fwhm_max-settings.fwhm_min):
            warnings.append(f'{name}: FWHM is at a bound; component area may be poorly determined.')
    # Local covariance is diagnostic only: it excludes assignment / baseline uncertainty.
    jac = best.jac
    covariance = np.linalg.pinv(jac.T@jac)*2*best.cost/max(1, len(x)-len(best.x))
    errors = np.sqrt(np.maximum(0, np.diag(covariance)))
    denominator = np.outer(errors, errors)
    corr = np.divide(covariance, denominator, out=np.zeros_like(covariance), where=denominator>0)
    np.fill_diagonal(corr, 0)
    max_corr = float(np.max(np.abs(corr)))
    if max_corr > .98: warnings.append('Strong parameter correlation (>0.98): similar fits can have different component areas.')
    area_spread = {}
    near = [f for f in candidates if f.cost <= best.cost+max(best.cost*.01, 1e-14)]
    for i, name in enumerate(names):
        values = [profile_area(settings.fit_min, settings.fit_max, *expand(f.x)[i])*scale for f in near]
        area_spread[name] = float(max(values)-min(values))
        if area_spread[name] > max(areas[name], 1e-30)*.1:
            warnings.append(f'{name}: near-equivalent starting solutions differ by >10% in area.')
    total_areas = {name: float(row[0]*row[2]*((1-row[3])*np.sqrt(np.pi)/(2*np.sqrt(np.log(2)))+row[3]*np.pi/2)) for name, row in zip(names, rows)}
    audit = {'version': 1, 'settings': asdict(settings), 'processed_sha256': fingerprint(p),
             'parameters': params, 'parameter_order': ['height', 'center_ppm', 'FWHM_ppm', 'Lorentzian_fraction'],
             'areas': areas, 'area_domain_ppm': [settings.fit_min, settings.fit_max],
             'area_method': 'Analytic finite-domain integral of each fitted component; not ppm-window cutting.',
             'fraction_of_full_profile_in_domain': {k: areas[k]/v if v else None for k, v in total_areas.items()},
             'fit_R2': r2, 'RMSE': float(np.sqrt(np.mean(residual**2))),
             'max_residual_percent_of_peak': float(np.max(np.abs(residual))/scale*100),
             'max_abs_parameter_correlation': max_corr, 'near_solution_area_spread': area_spread,
             'fit_points': len(x), 'converged_starts': len(candidates), 'warnings': warnings,
             'assignment_note': 'Aliphatic/aromatic are model assignments. Exchangeable H, water, rotor/background and broad overlap can contribute. High R2 does not establish unique assignments or grafting.'}
    return _result(p, audit)


def decomposition_values(fit):
    if fit.audit.get('version') == 4:
        from .hnmr_template import template_values
        return template_values(fit)
    a, b = fit.areas['aliphatic'], fit.areas['aromatic']
    values = {'aliphatic_integral': a, 'aromatic_integral': b,
            'unassigned_integral': fit.areas.get('unassigned', 0.),
            'aliphatic_aromatic_ratio': a/b if b else None,
            'aliphatic_signal_fraction_percent': 100*a/(a+b) if a+b else None,
            'sample_fit_R2': fit.audit['fit_R2'], 'fit_RMSE': fit.audit['RMSE']}
    for family, parts in fit.audit.get('area_breakdown', {}).items():
        values[family+'_central_integral'] = parts['central']
        values[family+'_sideband_integral'] = parts['sidebands']
    if 'spacing_ppm' in fit.audit:
        values['sideband_spacing_ppm'] = fit.audit['spacing_ppm']
        values['detected_sideband_envelopes'] = fit.audit['sideband_diagnostics']['detected_sideband_envelopes']
    for family, area in fit.audit.get('full_profile_areas', {}).items():
        values[family+'_full_profile_integral'] = area
    for family in ('aliphatic','aromatic'):
        params = fit.audit['parameters'][family]
        values[family+'_center_ppm'] = params[1]
        values[family+'_FWHM_ppm'] = params[2]
        values[family+'_Gaussian_fraction'] = 1-params[3]
    return values


def decomposition_csv(fit):
    stream = io.StringIO()
    lines = fit.audit.get('lines', [])
    extra = [profile(fit.x, *line['parameters']) for line in lines]
    labels = [f"{line['family']}_order_{line['order']:+d}" for line in lines]
    np.savetxt(stream, np.column_stack([fit.x, fit.observed, *fit.curves.values(), fit.total, fit.residual, *extra]),
               delimiter=',', header=','.join(['ppm','processed',*fit.curves,'total_fit','residual',*labels]), comments='', fmt='%.12g')
    return stream.getvalue()
