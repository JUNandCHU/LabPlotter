"""Measured pristine-core template plus additional, linked ligand envelopes.

This empirical model does not identify all core H as aromatic, infer a measured
mass from signal intensity, or certify covalent/surface-specific binding.
"""
from copy import deepcopy
from dataclasses import asdict
import json

import numpy as np
from scipy.integrate import trapezoid
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import least_squares
from threadpoolctl import threadpool_limits

from .hnmr_decomposition import (DecompositionResult, DecompositionSettings, _domain,
                                fingerprint, profile, profile_area)
from .hnmr_quality import sideband_diagnostics


def template_processed(record):
    """Stored reference enables library-only redraw and model review, not refitting an altered reference."""
    from .hnmr import ProcessedH
    row = record['template']
    x, y = np.asarray(row['x'], dtype=float), np.asarray(row['y'], dtype=float)
    if x.ndim != 1 or y.shape != x.shape or len(x) < 40 or len(x) > 2_000_000:
        raise ValueError('Invalid stored core template.')
    if not np.isfinite(x).all() or not np.isfinite(y).all() or np.any(np.diff(x) <= 0):
        raise ValueError('Invalid stored core template grid.')
    return ProcessedH(x, y, np.zeros_like(y), np.zeros_like(y), deepcopy(row.get('audit', {})))


def _core_curve(reference, grid, scale, shift, broadening):
    y = reference.y
    if broadening > 0:
        step = float(np.median(np.diff(reference.x)))
        if not np.allclose(np.diff(reference.x), step, rtol=1e-5, atol=1e-9):
            raise ValueError('Core broadening requires an evenly spaced processed reference grid.')
        y = gaussian_filter1d(y, broadening/2.354820045/step, mode='nearest')
    if grid[0]-shift < reference.x[0]-1e-8 or grid[-1]-shift > reference.x[-1]+1e-8:
        raise ValueError('Core template does not cover the shifted fit range. Expand common preprocessing.')
    return scale*np.interp(grid-shift, reference.x, y)


def restore_template(processed, audit):
    settings = DecompositionSettings(**audit['settings']).validate()
    x, y = _domain(processed, settings)
    reference = template_processed(audit)
    if fingerprint(reference) != audit['reference_processed_sha256']:
        raise ValueError('Stored core template fingerprint does not match.')
    curves = {'core_template': _core_curve(reference, x, audit['core_scale'],
                  audit['core_shift_ppm'], audit['core_broadening_FWHM_ppm'])}
    for line in audit.get('lines', []):
        curves.setdefault(line['family'], np.zeros_like(x))
        curves[line['family']] += profile(x, *line['parameters'])
    total = sum(curves.values())
    return DecompositionResult(x, y, curves, total, y-total, dict(audit['areas']), audit)


def fit_template(processed, reference, settings, *, reference_info=None, fixed_core_scale=None):
    settings = settings.validate()
    if reference is None:
        raise ValueError('The core_template model requires a measured pristine core reference. Load and select PDA or ANP.')
    x, y = _domain(processed, settings)
    if (reference.x.ndim != 1 or reference.x.shape != reference.y.shape or len(reference.x) < 3
            or not np.isfinite(reference.x).all() or not np.isfinite(reference.y).all() or np.any(np.diff(reference.x) <= 0)):
        raise ValueError('Core template must contain finite, increasing processed data.')
    shift_max = settings.template_shift_max
    if x[0]-shift_max < reference.x[0]-1e-8 or x[-1]+shift_max > reference.x[-1]+1e-8:
        raise ValueError('Reference must cover the fit range plus the allowed core shift. Expand common preprocessing.')
    scale = float(np.max(np.abs(y)))
    core_peak = float(np.max(np.abs(reference.y)))
    if scale <= 0 or np.std(y) < scale*1e-10 or core_peak <= 0 or np.std(reference.y) < core_peak*1e-10:
        raise ValueError('A flat sample or pristine core cannot be decomposed.')
    if fixed_core_scale is not None and (not np.isfinite(fixed_core_scale) or fixed_core_scale <= 0):
        raise ValueError('Fixed core scale must be finite and positive.')
    # Work in stable relative units without changing exported intensity units.
    from .hnmr import ProcessedH
    normalized = ProcessedH(reference.x, reference.y/core_peak, np.zeros_like(reference.y),
                            np.zeros_like(reference.y), reference.audit)
    ids = np.arange(0, len(x), max(1, len(x)//2700))
    xx, yy = x[ids], y[ids]/scale
    orders = list(range(-settings.sideband_order, settings.sideband_order+1)) if settings.sidebands else [0]
    spacing = settings.mas_hz/settings.proton_mhz if settings.mas_hz else settings.sideband_spacing
    families = [('ligand', settings.ligand_min, settings.ligand_max,
                 settings.ligand_fwhm_min, settings.ligand_fwhm_max)]
    if settings.overlap_band:
        families.append(('unassigned', settings.aliphatic_max, settings.aromatic_min,
                         settings.fwhm_min, settings.fwhm_max))
    low, high, initial, indexes = [], [], [], {}
    def variable(key, lo, hi, value):
        indexes[key] = len(low); low.append(lo); high.append(hi)
        initial.append(float(np.clip(value, lo+1e-8*(hi-lo), hi-1e-8*(hi-lo))))
    if fixed_core_scale is None: variable('scale', 0., 5., .74*core_peak/scale)
    if shift_max: variable('shift', -shift_max, shift_max, 0.)
    if settings.template_broadening_max: variable('broadening', 0., settings.template_broadening_max, .2)
    for name, lo, hi, wlo, whi in families:
        variable(name+'_center', lo, hi, np.clip(0. if name == 'ligand' else (lo+hi)/2, lo, hi))
        variable(name+'_width', wlo, whi, 6.)
        fixed_g = settings.aliphatic_gaussian_fraction if name == 'ligand' else None
        if settings.line_shape == 'pseudo_voigt' and fixed_g is None:
            variable(name+'_eta', 0., 1., .9)
        for n in orders:
            variable((name, n), -5. if n and settings.allow_negative_sidebands else 0., 5., .4 if not n else .003)
    spacing_free = settings.sidebands and settings.refine_spacing and not settings.mas_hz
    if spacing_free:
        upper = min(spacing*1.12, (families[0][1]-x[0])/settings.sideband_order,
                    (x[-1]-max(row[2] for row in families))/settings.sideband_order)
        lower = max(10., spacing*.88)
        if upper <= lower: raise ValueError('Fit bounds leave no room to refine sideband spacing.')
        variable('spacing', lower, upper, spacing)
    if settings.sidebands and settings.fit_sideband_width: variable('width_scale', .5, 5., settings.sideband_width_scale)

    def expand(v, grid):
        a = v[indexes['scale']]*scale/core_peak if fixed_core_scale is None else fixed_core_scale
        shift = v[indexes['shift']] if shift_max else 0.
        broad = v[indexes['broadening']] if settings.template_broadening_max else 0.
        core = _core_curve(normalized, grid, a*core_peak/scale, shift, broad)
        delta = v[indexes['spacing']] if spacing_free else spacing
        width_factor = v[indexes['width_scale']] if 'width_scale' in indexes else settings.sideband_width_scale
        lines = []
        for name, *_ in families:
            fixed_g = settings.aliphatic_gaussian_fraction if name == 'ligand' else None
            eta = (v[indexes[name+'_eta']] if name+'_eta' in indexes else
                   1.-fixed_g if fixed_g is not None else float(settings.line_shape == 'lorentzian'))
            for n in orders:
                pars = [v[indexes[(name,n)]], v[indexes[name+'_center']]+n*delta,
                        v[indexes[name+'_width']]*(width_factor if n else 1.), eta]
                lines.append((name, n, pars))
        return core, lines, float(a), float(shift), float(broad), float(delta), float(width_factor)

    def residual(v):
        core, lines, *_ = expand(v, xx)
        return core+sum(profile(xx, *pars) for _, _, pars in lines)-yy

    candidates = []
    with threadpool_limits(limits=1):
        for width in (3., 7.):
            start = initial.copy()
            for name, _, _, wlo, whi in families:
                start[indexes[name+'_width']] = float(np.clip(width, wlo+(whi-wlo)*.001, whi-(whi-wlo)*.001))
            fit = least_squares(residual, start, bounds=(low, high), max_nfev=400,
                                ftol=1e-9, xtol=1e-9, gtol=1e-9)
            if fit.success and np.isfinite(fit.cost): candidates.append(fit)
    if not candidates: raise ValueError('Core template fit did not converge. Review phase, reference and bounds.')
    best = min(candidates, key=lambda row: row.cost)
    if fingerprint(processed) == fingerprint(reference) and (fixed_core_scale is None or fixed_core_scale == 1.):
        # Identity subtraction is exactly zero; it is not independent chemical validation.
        if 'scale' in indexes: best.x[indexes['scale']] = core_peak/scale
        for name in ('shift','broadening'):
            if name in indexes: best.x[indexes[name]] = 0.
        for key,i in indexes.items():
            if isinstance(key,tuple): best.x[i] = 0.
    core, expanded, a, shift, broad, delta, width_factor = expand(best.x, x)
    core *= scale
    lines, parts, full_areas = [], {}, {}
    total = core.copy()
    for name, n, pars in expanded:
        pars = [float(v) for v in pars]; pars[0] *= scale
        area = profile_area(x[0], x[-1], *pars)
        full = pars[0]*pars[2]*((1-pars[3])*np.sqrt(np.pi)/(2*np.sqrt(np.log(2)))+pars[3]*np.pi/2)
        lines.append({'family':name, 'order':int(n), 'parameters':pars, 'area':area, 'full_profile_area':float(full)})
        parts.setdefault(name, {'central':0., 'sidebands':0.})['central' if not n else 'sidebands'] += area
        full_areas[name] = full_areas.get(name, 0.)+float(full)
        total += profile(x, *pars)
    areas = {'core_template':float(trapezoid(core, x)), **{name:sum(row.values()) for name,row in parts.items()}}
    residual_y = y-total
    r2 = float(1-np.sum(residual_y**2)/np.sum((y-y.mean())**2))
    warnings = ['Empirical core-template model: core H is not assigned as aromatic. Additional signal may include core changes, water/OH, background or unbound ligand; it is not proof of grafting.',
                'Additional central heights are nonnegative; a positive fitted ligand area does not validate the assignment.']
    if r2 < .98: warnings.append('Fit R2 < 0.98: inspect phase/baseline, core invariance and additional envelopes.')
    bounds_reached = [str(key) for key,i in indexes.items() if not isinstance(key,tuple)
                      and min(best.x[i]-low[i],high[i]-best.x[i]) < .002*(high[i]-low[i])]
    if bounds_reached: warnings.append('Template parameters reached bounds: '+', '.join(bounds_reached)+'. Areas may be model dependent.')
    with threadpool_limits(limits=1):
        cov = np.linalg.pinv(best.jac.T@best.jac)
    sd = np.sqrt(np.maximum(np.diag(cov),0.)); den = np.outer(sd,sd)
    corr = np.divide(cov,den,out=np.zeros_like(cov),where=den>0); np.fill_diagonal(corr,0.)
    correlation = float(np.max(np.abs(corr)))
    if correlation > .98: warnings.append('Strong parameter correlation (>0.98): similar fits can have different ligand areas.')
    alternatives = []
    for candidate in candidates:
        _, candidate_lines, *_ = expand(candidate.x, x)
        candidate_areas = {}
        for name, _, pars in candidate_lines:
            candidate_areas[name] = candidate_areas.get(name,0.)+profile_area(x[0],x[-1],*pars)*scale
        alternatives.append({'relative_cost':float(candidate.cost/max(best.cost,1e-30)), 'areas':candidate_areas})
    near = [row for row in alternatives if row['relative_cost'] <= 1.01]
    spread = {name:float(max(row['areas'][name] for row in near)-min(row['areas'][name] for row in near))
              for name in full_areas}
    unstable = any(spread[name] > .1*max(abs(areas[name]),1e-30) for name in spread)
    if unstable: warnings.append('Near-equivalent fits differ by more than 10% in additional area; assignments are not stable.')
    fractions = {name:areas[name]/full if full else None for name,full in full_areas.items()}
    if any(value is not None and value < .98 for value in fractions.values()):
        warnings.append('More than 2% of an additional profile lies beyond the integration bounds. Reported areas use finite measured bounds.')
    mismatches = []
    if settings.sidebands and settings.mas_hz:
        for label,p in (('sample',processed),('reference',reference)):
            processing = p.audit.get('settings',{})
            if ((processing.get('phase') or processing.get('baseline'))
                    and abs(processing.get('sideband_spacing',delta)-delta) > .02*delta):
                mismatches.append(label)
                warnings.append(label+': preprocessing exclusion spacing differs from fixed fitting spacing. Reapply common preprocessing with the same MAS/MHz.')
    diagnostics, local_errors = None, []
    if settings.sidebands:
        diagnostics = sideband_diagnostics(processed.x, processed.y, delta, settings.sideband_order,
                           anchor_min=processed.audit.get('settings',{}).get('baseline_anchor_min',0.))
        warnings.extend(diagnostics['warnings'])
        for n in orders:
            mask = abs(x-(4.5+n*delta)) < min(22.,delta*.42)
            if not mask.any(): continue
            relative = float(np.sqrt(np.mean(residual_y[mask]**2))/max(np.max(np.abs(y[mask])),scale*1e-8))
            local_errors.append({'order':n,'RMSE_over_local_peak':relative})
            if n and relative > .25: warnings.append(f'Order {n:+d}: local residual exceeds 25% of its peak. Global R2 can hide this mismatch.')
    if any(line['area'] < 0 for line in lines): warnings.append('Signed sideband areas are diagnostic and are retained without clipping.')
    reference_audit = {'x':reference.x.tolist(),'y':reference.y.tolist(),'audit':deepcopy(reference.audit)}
    audit = {'version':4,'model':'Measured pristine core + additional ligand envelopes',
             'settings':asdict(settings),'processed_sha256':fingerprint(processed),
             'reference_processed_sha256':fingerprint(reference),'reference':dict(reference_info or {}),
             'template':reference_audit,'core_scale':a,'core_shift_ppm':shift,'core_broadening_FWHM_ppm':broad,
             'fixed_core_scale':fixed_core_scale,'lines':lines,
             'parameter_order':['height','center_ppm','FWHM_ppm','Lorentzian_fraction'],
             'parameters':{row['family']:row['parameters'] for row in lines if row['order']==0},
             'areas':areas,'area_breakdown':parts,'full_profile_areas':full_areas,
             'area_domain_ppm':[float(x[0]),float(x[-1])],
             'area_method':'Measured core: trapezoidal integral. Additional profiles: analytic finite-domain integrals including every fitted sideband. Core integral is not aromatic area.',
             'spacing_ppm':delta,'width_multiplier':width_factor,
             'spacing_source':'MAS_Hz / 1H_MHz (fixed)' if settings.mas_hz else 'estimated / fitted; acquisition unconfirmed',
             'preprocessing_spacing_mismatch':bool(mismatches), 'mismatched_preprocessing':mismatches,
             'fraction_of_full_profile_in_domain':fractions,
             'starting_solutions':alternatives,'near_solution_area_spread':spread,
             'sideband_diagnostics':diagnostics,'local_fit_errors':local_errors,
             'fit_R2':r2,'RMSE':float(np.sqrt(np.mean(residual_y**2))),
             'max_residual_percent_of_peak':float(np.max(np.abs(residual_y))/scale*100),
             'fit_points':len(x),'optimizer_points':len(xx),'converged_starts':len(candidates),
             'bounds_reached':bounds_reached,'max_abs_parameter_correlation':correlation,
             'assignment_ambiguous':bool(bounds_reached or correlation > .98 or unstable), 'warnings':warnings}
    return restore_template(processed,audit)


def template_values(fit):
    a, b = fit.areas.get('ligand',0.), fit.areas['core_template']
    values = {'ligand_integral':a,'core_template_integral':b,
              'unassigned_integral':fit.areas.get('unassigned',0.),
              'ligand_core_ratio':a/b if b else None,
              'ligand_signal_fraction_percent':100*a/(a+b) if a+b else None,
              'core_template_scale':fit.audit['core_scale'],
              'core_template_shift_ppm':fit.audit['core_shift_ppm'],
              'core_template_extra_FWHM_ppm':fit.audit['core_broadening_FWHM_ppm'],
              'sample_fit_R2':fit.audit['fit_R2'],'fit_RMSE':fit.audit['RMSE']}
    for name, parts in fit.audit.get('area_breakdown',{}).items():
        values[name+'_central_integral'] = parts['central']; values[name+'_sideband_integral'] = parts['sidebands']
    for name, pars in fit.audit['parameters'].items():
        values[name+'_center_ppm'] = pars[1]; values[name+'_FWHM_ppm'] = pars[2]
        values[name+'_Gaussian_fraction'] = 1-pars[3]
    if fit.audit['settings']['sidebands']: values['sideband_spacing_ppm'] = fit.audit['spacing_ppm']
    return values


def quantify_template(sample, reference, q, processed, core_processed):
    from .hnmr import QuantResult, integrate
    settings = q.decomposition_settings()
    fixed = None
    if q.core_scaling == 'mass':
        mass = q.sample_core_mass_mg if q.sample_core_mass_mg is not None else q.sample_mass_mg
        fixed = mass/q.reference_mass_mg*q.reference_response_factor/q.response_factor
    info = {'uid':reference.uid,'name':reference.name,'source':reference.source}
    # Always fit against the selected, current reference; no stale saved-template reuse.
    fit = fit_template(processed, core_processed, settings, reference_info=info, fixed_core_scale=fixed)
    a = fit.audit['core_scale']; area = fit.areas['ligand']
    k = q.standard_umol_h/q.standard_ppm_area()
    if a <= 1e-12 and q.core_scaling == 'core_reference':
        raise ValueError('Fitted core scale is zero: reference-equivalent coverage is undefined. Review the core reference or use an independently known mass.')
    # Express amounts on the same entered-mass equivalent convention as legacy aromatic normalization.
    factor = q.sample_mass_mg/q.reference_mass_mg*q.reference_response_factor/(a*q.response_factor) if q.core_scaling == 'core_reference' else 1.
    calc_area = area*q.response_factor*factor
    nh = calc_area*k; nlig = nh/q.effective_h; loading = nlig/q.sample_mass_mg
    absolute = {'excess_H_umol':nh,'ligand_umol':nlig,'loading_umol_mg':loading,
                'apparent_coverage_percent':100*loading/q.capacity_umol_mg,
                'ligand_equivalent_mass_mg':nlig*q.molecular_weight/1000,
                'ligand_equivalent_mass_percent':100*nlig*q.molecular_weight/1000/q.sample_mass_mg}
    from .hnmr_reactions import reaction_coverage, REACTION_NOTE
    counts, endpoints = reaction_coverage(nh/q.sample_mass_mg,q)
    absolute.update(endpoints)
    if not np.isfinite(list(absolute.values())).all(): raise ValueError('Coverage algebra overflowed; review the core scale and calibration.')
    values = template_values(fit)
    values.update(counts)
    values.update(standard_H_umol_per_area=k, standard_H_umol=q.standard_umol_h,
                  standard_area_intensity_ppm=q.standard_ppm_area(), core_normalization_factor=factor,
                  reference_equivalent_ligand_area=area/a if a > 1e-12 else None,
                  ligand_area_on_calculation_scale=calc_area,
                  ligand_H_umol_per_mg=nh/q.sample_mass_mg,
                  maximum_ligand_H_umol_per_mg=q.effective_h*q.capacity_umol_mg,
                  capacity_umol=q.capacity_umol_mg*q.sample_mass_mg)
    for label,p in (('sample',processed),('reference',core_processed)):
        values[label+'_window_aliphatic_area'] = integrate(p.x,p.y,q.aliphatic_min,q.aliphatic_max)
        values[label+'_window_aromatic_area'] = integrate(p.x,p.y,q.aromatic_min,q.aromatic_max)
    blockers = []
    for verified,label in ((q.calibration_verified,'standard area unit and absolute response scale'),
                           (q.acquisition_verified,'quantitative acquisition / response factors'),
                           (q.assignments_verified,'core invariance and additional-signal ligand assignment')):
        if not verified: blockers.append(label)
    if q.standard_includes_sidebands != q.sidebands: blockers.append('sample / standard sideband integration scopes do not match')
    if q.sidebands and not q.sideband_scope_verified: blockers.append('sideband coverage, weak peaks and phase/baseline review')
    if fit.audit['fit_R2'] < .98: blockers.append('inadequate decomposition fit (R2 < 0.98)')
    if fit.audit['assignment_ambiguous']: blockers.append('core-template separation is model-sensitive (bounds or correlation)')
    if fit.audit.get('preprocessing_spacing_mismatch'): blockers.append('preprocessing and fixed fitting spacings differ')
    if any(line['area'] < 0 for line in fit.audit['lines']): blockers.append('signed negative fitted sideband areas')
    if q.sidebands:
        for name,p in (('sample',processed),('reference',core_processed)):
            diag = sideband_diagnostics(p.x,p.y,fit.audit['spacing_ppm'],q.sideband_order,
                         anchor_min=p.audit.get('settings',{}).get('baseline_anchor_min',0.))
            if any(row['status']=='detected' and not row['included'] for row in diag['envelopes']):
                blockers.append(name+' has detected signal outside the included sideband orders')
            if any(row['status']=='detected' and row['included'] and (row['negative_fraction'] or 0)>.15 for row in diag['envelopes']):
                blockers.append(name+' has substantial negative sideband signal')
        if any(row['order'] and row['RMSE_over_local_peak']>.25 for row in fit.audit['local_fit_errors']):
            blockers.append('sideband model has substantial local residuals')
    provisional = bool(blockers) and q.show_provisional
    status = (f'Provisional core-template estimate; {len(blockers)} unresolved checks. See Calculation details.' if provisional else
              'Withheld: verify '+'; '.join(blockers) if blockers else 'Model-based core-template ligand-equivalent coverage')
    warnings = list(fit.warnings)
    warnings.append(REACTION_NOTE)
    if blockers: warnings.insert(0,'Unresolved checks: '+'; '.join(blockers))
    if q.core_scaling == 'core_reference':
        warnings.append('Core-reference equivalents assume unchanged measured core response per mg. Sample mass cancels from coverage; reference mass remains. Fitted core scale is not a measured mass ratio.')
    elif q.sample_core_mass_mg is None:
        warnings.append('Mass mode fixes core amplitude using total sample mass as an approximation; enter independently known core mass if available.')
    if absolute['apparent_coverage_percent'] < 0 or absolute['apparent_coverage_percent'] > 100:
        warnings.append('Coverage is outside 0–100%; it has not been clipped.')
    for name,p in (('Sample',processed),('Reference',core_processed)):
        warnings.extend(name+': '+w for w in p.audit.get('phase_diagnostics',{}).get('warnings',[]))
    values.update({key:None if blockers and not q.show_provisional else value for key,value in absolute.items()})
    rx, ry = _domain(core_processed,settings)
    ref_fit = DecompositionResult(rx,ry,{'core_template':ry.copy()},ry.copy(),np.zeros_like(ry),
                                 {'core_template':float(trapezoid(ry,rx))},
                                 {'model':'Measured pristine reference (not independently decomposed)',
                                  'fit_R2':1.,'warnings':[],'parameters':{},'areas':{'core_template':float(trapezoid(ry,rx))}})
    audit = {'sample':{'name':sample.name,'uid':sample.uid},'reference':info,
             'parameters':asdict(q),'sample_preprocessing':processed.audit,'reference_preprocessing':core_processed.audit,
             'sample_fit':fit.audit,'results':values,'quantitative_status':status,
             'provisional':provisional,'validation_issues':blockers,'warnings':warnings,
             'unvalidated_algebra_only':absolute if blockers else None,
             'assumptions':{'core_response_per_mg_invariant':True,'all_added_signal_is_ligand':True,
                            'nonnegative_central_amplitudes':True,'core_scale_is_measured_mass_ratio':False,
                            'coverage_clipped':False}}
    equations = ('MODEL: sample(ppm) = a * measured_core(ppm-shift, optional broadening) + ligand [+ unassigned].\n'
        'Core is not assigned as aromatic. Ligand = additional fitted envelope and its independent +/- sidebands.\n'
        'Ligand area includes finite-domain overlapping tails; optional unassigned area is excluded.\n'
        'k = standard_H_umol / standard_area[intensity*ppm].\n'
        'CORE_REFERENCE: loading = (ligand_area/a) * reference_response * k / (H_per_ligand * reference_mass_mg).\n'
        'MASS: a is fixed to core_mass/reference_mass * reference_response/sample_response; loading = ligand_area * sample_response * k / (H_per_ligand * sample_mass_mg).\n'
        'coverage[%] = 100 * loading / capacity[umol/mg].\n'
        'Ligand amount = loading * entered sample mass (reference-equivalent in core_reference mode).\n'
        'No conversion from mmol is applied to a umol input. Hz standard area is divided by MHz; point_sum uses the STANDARD original ppm step.\n'
        'Reaction endpoint coverage = 100 * H_umol_per_mg / (scenario_H_per_ligand * capacity). Sort both for lower/upper.\n'
        'A positive fitted ligand area, a zero pristine blank, or high R2 does not independently validate grafting.\n'+REACTION_NOTE+'\n\n')
    return QuantResult(processed,core_processed,values,asdict(q),warnings,fit.curves['core_template'],
                       fit.curves['ligand']*q.response_factor*factor,list(fit.curves.values()),
                       equations+json.dumps(audit,ensure_ascii=False,indent=2,allow_nan=False),fit,ref_fit,status,blockers,provisional)
