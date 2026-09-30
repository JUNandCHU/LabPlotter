"""Constrained 1H envelope fits; chemical assignments remain explicit hypotheses.

The two family curves are integrated over the measured fit domain, including
shared tails. Center bounds are NOT integration windows. No intensity
normalization or aromatic-based mass inference is performed.
"""
from dataclasses import asdict, dataclass
import hashlib
import io
import json

import numpy as np
from scipy.optimize import least_squares
from scipy.special import erf


@dataclass
class DecompositionSettings:
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

    def validate(self):
        numbers = [v for k, v in asdict(self).items() if k not in ("line_shape", "overlap_band")]
        if not np.isfinite(numbers).all():
            raise ValueError("Decomposition bounds must be finite.")
        if not self.fit_min < self.aliphatic_min < self.aliphatic_max < self.aromatic_min < self.aromatic_max < self.fit_max:
            raise ValueError("Fit range must enclose separate increasing aliphatic / aromatic center bounds.")
        if not 0 < self.fwhm_min < self.fwhm_max <= 2*(self.fit_max-self.fit_min):
            raise ValueError("Use positive increasing FWHM bounds, at most twice the fit span.")
        if self.line_shape not in ("pseudo_voigt", "gaussian", "lorentzian"):
            raise ValueError("Choose pseudo_voigt, gaussian or lorentzian.")
        return self


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
    settings = DecompositionSettings(**audit['settings']).validate()
    x, y = _domain(p, settings)
    curves = {name: profile(x, *params) for name, params in audit['parameters'].items()}
    total = sum(curves.values())
    return DecompositionResult(x, y, curves, total, y-total, dict(audit['areas']), audit)


def restore_decomposition(p, record):
    """A stored fit is never reused after data, phase, grid or baseline changes."""
    if not record or record.get('version') != 1 or record.get('processed_sha256') != fingerprint(p):
        return None
    try:
        return _result(p, record)
    except (KeyError, TypeError, ValueError):
        return None


def decompose(p, settings=None):
    settings = (settings or DecompositionSettings()).validate()
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
    a, b = fit.areas['aliphatic'], fit.areas['aromatic']
    return {'aliphatic_integral': a, 'aromatic_integral': b,
            'unassigned_integral': fit.areas.get('unassigned', 0.),
            'aliphatic_aromatic_ratio': a/b if b else None,
            'aliphatic_signal_fraction_percent': 100*a/(a+b) if a+b else None,
            'sample_fit_R2': fit.audit['fit_R2'], 'fit_RMSE': fit.audit['RMSE']}


def decomposition_csv(fit):
    stream = io.StringIO()
    np.savetxt(stream, np.column_stack([fit.x, fit.observed, *fit.curves.values(), fit.total, fit.residual]),
               delimiter=',', header='ppm,processed,'+','.join(fit.curves)+',total_fit,residual', comments='', fmt='%.12g')
    return stream.getvalue()
