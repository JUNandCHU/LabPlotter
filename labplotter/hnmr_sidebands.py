"""Empirical MAS sideband families, following DMfit's linked-ssb approach.

This is not a DMfit file reader or a CSA/dipolar spin simulation. The optional
common satellite-width multiplier relaxes DMfit's equal-width constraint for
these broad proton envelopes. +/- heights are independent, never mirrored.
"""
from dataclasses import asdict
import numpy as np
from scipy.optimize import least_squares
from threadpoolctl import threadpool_limits
from .hnmr_decomposition import _domain, _result, fingerprint, profile, profile_area
from .hnmr_quality import sideband_diagnostics, estimate_spacing


def fit_sidebands(p, settings):
    x, y = _domain(p, settings)
    scale = float(np.max(abs(y)))
    if scale <= 0 or np.std(y) <= scale*1e-10:
        raise ValueError('A flat spectrum cannot be decomposed.')
    names = ['aliphatic', 'aromatic']
    bounds = [(settings.aliphatic_min, settings.aliphatic_max), (settings.aromatic_min, settings.aromatic_max)]
    if settings.overlap_band:
        names.append('unassigned'); bounds.append((settings.aliphatic_max, settings.aromatic_min))
    orders = list(range(-settings.sideband_order, settings.sideband_order+1))
    # Keep the central band well sampled even for a very fine imported grid.
    ids = np.unique(np.r_[np.arange(0, len(x), max(1, len(x)//2500)),
                          np.flatnonzero((x > -15) & (x < 20))[::max(1, int(1/(x[1]-x[0])/12))]])
    xx, yy = x[ids], y[ids]/scale
    variable_eta = settings.line_shape == 'pseudo_voigt'
    shape_layout = []
    cursor = 0
    for name in names:
        gaussian = getattr(settings, name+'_gaussian_fraction', None)
        free_eta = variable_eta and gaussian is None
        fixed_eta = 1.-gaussian if gaussian is not None else float(settings.line_shape == 'lorentzian')
        shape_layout.append((cursor, free_eta, fixed_eta))
        cursor += 3 if free_eta else 2
    spacing = settings.mas_hz/settings.proton_mhz if settings.mas_hz else settings.sideband_spacing
    variable_spacing = settings.refine_spacing and not settings.mas_hz
    shape_end = cursor
    amp_end = shape_end+len(names)*len(orders)

    def expand(v):
        shapes = [(v[offset], v[offset+1], v[offset+2] if free else fixed)
                  for offset, free, fixed in shape_layout]
        amps = v[shape_end:amp_end].reshape(len(names), len(orders))
        cursor = amp_end
        delta = v[cursor] if variable_spacing else spacing
        cursor += int(variable_spacing)
        width_scale = v[cursor] if settings.fit_sideband_width else settings.sideband_width_scale
        return [(name, order, [amps[i,j], shapes[i][0]+order*delta,
                shapes[i][1]*(width_scale if order else 1.), shapes[i][2]])
                for i,name in enumerate(names) for j,order in enumerate(orders)], float(delta), float(width_scale)

    def model(v, grid=xx):
        return sum(profile(grid, *row) for _,_,row in expand(v)[0])

    low, high = [], []
    for (lo, hi), (_, free_eta, _) in zip(bounds, shape_layout):
        low.extend([lo, settings.fwhm_min]); high.extend([hi, settings.fwhm_max])
        if free_eta: low.append(0.); high.append(1.)
    low += [-5. if settings.allow_negative_sidebands and order else 0. for _ in names for order in orders]
    high += [5.]*(len(names)*len(orders))
    if variable_spacing:
        # Fit all centers inside measured data, even at the search boundaries.
        upper = min(spacing*1.12, (settings.aliphatic_min-settings.fit_min)/settings.sideband_order,
                    (settings.fit_max-settings.aromatic_max)/settings.sideband_order)
        low.append(max(10., spacing*.88)); high.append(upper)
    if settings.fit_sideband_width: low.append(.5); high.append(5.)
    candidates = []
    with threadpool_limits(limits=1):
        for fraction, width, eta0 in ((.2, 5., .3), (.7, 9., .7), (.4, 3., .05)):
            initial = []
            for i, (lo, hi) in enumerate(bounds):
                initial.extend([lo+(fraction if i==0 else .5)*(hi-lo), np.clip(width, settings.fwhm_min*1.01, settings.fwhm_max*.99)])
                if shape_layout[i][1]: initial.append(eta0)
            for _ in names:
                initial += [.5 if order==0 else (.025 if abs(order)==1 else .003) for order in orders]
            if variable_spacing: initial.append(np.clip(spacing, low[-1-int(settings.fit_sideband_width)] if settings.fit_sideband_width else low[-1],
                                                          high[-1-int(settings.fit_sideband_width)] if settings.fit_sideband_width else high[-1]))
            if settings.fit_sideband_width: initial.append(np.clip(settings.sideband_width_scale, .501, 4.999))
            fit = least_squares(lambda v: model(v)-yy, initial, bounds=(low, high),
                                max_nfev=400, ftol=2e-8, xtol=2e-8, gtol=2e-8)
            if fit.success and np.isfinite(fit.cost): candidates.append(fit)
    if not candidates:
        raise ValueError('Sideband fit did not converge. Inspect phase/baseline and model bounds.')
    best = min(candidates, key=lambda f:f.cost)
    expanded, delta, width_scale = expand(best.x)
    diagnostics = sideband_diagnostics(p.x, p.y, delta, settings.sideband_order,
                    anchor_min=p.audit.get('settings',{}).get('baseline_anchor_min',0.))
    detected = {row['order']:row['status']=='detected' for row in diagnostics['envelopes']}
    lines, breakdown = [], {name:{'central':0.,'sidebands':0.} for name in names}
    warnings = list(diagnostics['warnings'])
    for name, order, params in expanded:
        params = [float(v) for v in params]; params[0] *= scale
        area = profile_area(settings.fit_min, settings.fit_max, *params)
        full_area = params[0]*params[2]*((1-params[3])*np.sqrt(np.pi)/(2*np.sqrt(np.log(2)))+params[3]*np.pi/2)
        lines.append({'family':name, 'order':int(order), 'parameters':params, 'area':area, 'full_profile_area':float(full_area),
                      'envelope_detected':bool(order==0 or detected.get(order,False))})
        breakdown[name]['central' if order==0 else 'sidebands'] += area
    areas = {name:sum(parts.values()) for name,parts in breakdown.items()}
    total = model(best.x, x)*scale; residual = y-total
    r2 = float(1-np.sum(residual**2)/np.sum((y-y.mean())**2))
    if r2 < .98: warnings.append('Fit R2 < 0.98: inspect phase/baseline and envelope model.')
    if any(not detected.get(n,False) for n in orders if n):
        warnings.append('One or more included satellite envelopes are weak / unresolved. Fitted areas are model estimates, not independent peak detections; no missing peak was mirrored or set to zero.')
    local_errors = []
    for n in orders:
        mask = abs(x-(4.5+n*delta)) < min(22.,delta*.42)
        peak = float(np.max(abs(y[mask])))
        relative = float(np.sqrt(np.mean(residual[mask]**2))/max(peak, scale*1e-8))
        local_errors.append({'order':n,'RMSE_over_local_peak':relative})
        if n and detected.get(n,False) and relative>.25:
            warnings.append(f'Order {n:+d}: local fit RMSE exceeds 25% of its peak; the global R2 can hide this mismatch.')
    boundary_components = []
    for i, (name, bound) in enumerate(zip(names, bounds)):
        offset = shape_layout[i][0]
        shape = best.x[offset:offset+2]
        if min(shape[0]-bound[0],bound[1]-shape[0]) < .005*(bound[1]-bound[0]):
            boundary_components.append(name)
            warnings.append(f'{name}: center reached an assignment bound; component separation is uncertain.')
        if min(shape[1]-settings.fwhm_min,settings.fwhm_max-shape[1]) < .002*(settings.fwhm_max-settings.fwhm_min):
            boundary_components.append(name)
            warnings.append(f'{name}: width reached a bound; component area needs review.')
    # Covariance reports identifiability only, not calibrated confidence limits.
    with threadpool_limits(limits=1):
        covariance = np.linalg.pinv(best.jac.T@best.jac)*2*best.cost/max(1,len(xx)-len(best.x))
    sd = np.sqrt(np.maximum(np.diag(covariance),0)); denom=np.outer(sd,sd)
    corr=np.divide(covariance,denom,out=np.zeros_like(covariance),where=denom>0);np.fill_diagonal(corr,0)
    correlation=float(np.max(abs(corr)))
    if correlation>.98: warnings.append('Strong parameter correlation (>0.98): chemical-family areas are not uniquely established by a good fit.')
    fractions={}; full_areas={}
    for name in names:
        infinite=sum(row['parameters'][0]*row['parameters'][2]*((1-row['parameters'][3])*np.sqrt(np.pi)/(2*np.sqrt(np.log(2)))+row['parameters'][3]*np.pi/2)
                     for row in lines if row['family']==name)
        fractions[name]=areas[name]/infinite if infinite else None
        full_areas[name]=float(infinite)
    if any(v is not None and v<.98 for v in fractions.values()):
        warnings.append('More than 2% of a fitted infinite profile lies beyond the integration bounds. Reported integrals use measured finite bounds only.')
    if any(line['area'] < 0 for line in lines):
        warnings.append('Signed satellite fit contains negative component areas. They are retained, not clipped; this diagnostic model does not establish physical populations.')
    observed_spacing, observed_source = estimate_spacing(p.x, p.y+1j*p.imaginary)
    processing = p.audit.get('settings', {})
    processing_spacing = processing.get('sideband_spacing', delta)
    processing_mismatch = bool(settings.mas_hz and (processing.get('phase') or processing.get('baseline'))
                               and abs(processing_spacing-delta) > .02*delta)
    if processing_mismatch:
        warnings.append('Preprocessing exclusion spacing differs from the fixed fitting spacing. Reapply common preprocessing with the same MAS/MHz before quantitation.')
    if settings.mas_hz and abs(observed_spacing-delta)/delta > .05 and observed_source.startswith('estimated'):
        warnings.append(f'Envelope-based spacing estimate {observed_spacing:.3f} ppm differs from MAS/MHz = {delta:.3f} ppm. Overlap/phase can move maxima; verify acquisition and ppm calibration. The axis was not rescaled.')
    alternatives=[]
    for candidate in candidates:
        component_areas={name:0. for name in names}
        for name, _, pars in expand(candidate.x)[0]:
            component_areas[name] += profile_area(settings.fit_min, settings.fit_max, *pars)*scale
        alternatives.append({'relative_cost':float(candidate.cost/max(best.cost,1e-30)), 'areas':component_areas})
    near=[a for a in alternatives if a['relative_cost'] <= 1.01]
    spread={name:float(max(a['areas'][name] for a in near)-min(a['areas'][name] for a in near)) for name in names}
    unstable=any(spread[name] > .1*max(abs(areas[name]),1e-30) for name in names)
    if unstable: warnings.append('Near-equivalent fits differ by more than 10% in component area; assignments are not stable.')
    audit = {'version':3,'settings':asdict(settings),'processed_sha256':fingerprint(p),
             'model':'Empirical linked MAS sidebands; not a CSA/dipolar simulation',
             'lines':lines,'parameters':{row['family']:row['parameters'] for row in lines if row['order']==0},
             'parameter_order':['height','center_ppm','FWHM_ppm','Lorentzian_fraction'],
             'areas':areas,'area_breakdown':breakdown,'area_domain_ppm':[settings.fit_min,settings.fit_max],
             'full_profile_areas':full_areas, 'full_profile_note':'Analytic extrapolation to infinite profile tails, for DMfit-style comparison; not substituted for measured-domain integrals.',
             'area_method':'Sum of analytic finite-domain integrals of order 0 and every fitted +/- order, including tails. No central-area multiplier.',
             'spacing_ppm':delta,'spacing_source':'MAS_Hz / 1H_MHz (fixed)' if settings.mas_hz else 'estimated / fitted from data; acquisition metadata unconfirmed',
             'width_multiplier':width_scale,'fit_R2':r2,'RMSE':float(np.sqrt(np.mean(residual**2))),
             'dmfit_width_link':not settings.fit_sideband_width and settings.sideband_width_scale == 1.,
             'observed_envelope_spacing_ppm':observed_spacing, 'observed_spacing_source':observed_source,
             'preprocessing_spacing_mismatch':processing_mismatch,
             'boundary_components':sorted(set(boundary_components)),
             'assignment_ambiguous':bool(boundary_components or correlation>.98 or unstable),
             'starting_solutions':alternatives,'near_solution_area_spread':spread,
             'max_residual_percent_of_peak':float(np.max(abs(residual))/scale*100),
             'fit_points':len(x),'optimizer_points':len(xx),'converged_starts':len(candidates),
             'max_abs_parameter_correlation':correlation,'fraction_of_full_profile_in_domain':fractions,
             'sideband_diagnostics':diagnostics,'local_fit_errors':local_errors,'warnings':warnings,
             'assignment_note':'Centers follow delta_family + order * spacing. +/- intensities are independent. Weak outer envelopes do not determine unique aliphatic/aromatic contributions. Review assignments, phase, baseline and scope before absolute quantitation.'}
    return _result(p,audit)
