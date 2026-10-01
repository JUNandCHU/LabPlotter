"""Ver2: complex MAS families with a broad, explicitly unassigned component.

This ports the ANP broad_core3 investigation. It does not use carbon area ratios,
expected sample ordering, or a pristine template to constrain the fitted areas.
"""
from dataclasses import asdict
import hashlib

import numpy as np
from scipy.optimize import least_squares, lsq_linear, nnls
from scipy.special import dawsn
from threadpoolctl import threadpool_limits

from .hnmr_decomposition import (DecompositionResult, DecompositionSettings, _domain,
                                 fingerprint, profile, profile_area)
from .hnmr_quality import sideband_diagnostics

FAMILIES = ('aliphatic', 'aromatic', 'unassigned')


def complex_profile(x, center, width, eta):
    u = 2*(np.asarray(x)-center)/width
    v = np.sqrt(np.log(2))*u
    return ((1-eta)*(np.exp(-v*v)+1j*2/np.sqrt(np.pi)*dawsn(v))
            + eta*(1+1j*u)/(1+u*u))


def complex_fingerprint(p):
    h = hashlib.sha256()
    for a in (p.x, p.y, p.imaginary, p.baseline, p.raw_x, p.raw_complex):
        if a is not None: h.update(np.asarray(a, dtype='<c16').tobytes())
    # The same arrays with a different manual override must not reuse a joint fit.
    import json
    h.update(json.dumps(p.audit, sort_keys=True, allow_nan=False).encode())
    return h.hexdigest()


def corrected_complex(p, audit, x=None):
    """The displayed data, fit residual and CSV all share this correction."""
    x = p.x if x is None else np.asarray(x)
    if not audit.get('joint_complex'):
        return np.interp(x, p.x, p.y)+1j*np.interp(x, p.x, p.imaginary)
    rx, rz = p.raw_x, p.raw_complex
    z = np.interp(x, rx, rz.real)+1j*np.interp(x, rx, rz.imag)
    t = (x-audit['phase_pivot_ppm'])/audit['phase_span_ppm']
    b0, b1, bi0, bi1 = audit['complex_background']
    # Background is fitted in the raw frame, before the phase rotation.
    z -= b0+b1*t+1j*(bi0+bi1*t)
    return z*np.exp(1j*np.deg2rad(audit['phase0_deg']+audit['phase1_deg']*t))


def restore_family(p, audit):
    settings = DecompositionSettings(**audit['settings']).validate()
    x, _ = _domain(p, settings)
    y = corrected_complex(p, audit, x).real
    curves = {name: np.zeros_like(x) for name in FAMILIES}
    for line in audit['lines']:
        curves[line['family']] += profile(x, *line['parameters'])
    total = sum(curves.values())
    return DecompositionResult(x, y, curves, total, y-total, dict(audit['areas']), audit)


def fit_family(p, settings):
    # Avoid BLAS thread oversubscription in the many small bounded least squares.
    with threadpool_limits(limits=1):
        return _fit_family(p, settings)


def _fit_family(p, s):
    _domain(p, s)  # Validate the integration domain independently of the fit window.
    orders = [0]+[n for k in range(1, s.sideband_order+1) for n in (-k,k)] if s.sidebands else [0]
    spacing = s.mas_hz/s.proton_mhz if s.mas_hz else s.sideband_spacing
    nlines = len(FAMILIES)*len(orders)
    low = np.array([s.aliphatic_min,s.fwhm_min,0, s.aromatic_min,s.fwhm_min,0,
                    s.unassigned_min,s.unassigned_fwhm_min,0], float)
    high = np.array([s.aliphatic_max,s.fwhm_max,1, s.aromatic_max,s.fwhm_max,1,
                     s.unassigned_max,s.unassigned_fwhm_max,1], float)
    fixed = {}
    for i, fraction in enumerate((s.aliphatic_gaussian_fraction, s.aromatic_gaussian_fraction, None)):
        if s.line_shape != 'pseudo_voigt': fixed[3*i+2] = float(s.line_shape == 'lorentzian')
        elif fraction is not None: fixed[3*i+2] = 1-fraction
    free = np.array([i for i in range(9) if i not in fixed])

    def expand(v):
        out = np.empty(9); out[free] = v
        for i, value in fixed.items(): out[i] = value
        return out.reshape(3,3)

    def matrix(x, rows, complex_=False):
        fn = complex_profile if complex_ else lambda xx,mu,w,e: profile(xx,1.,mu,w,e)
        return np.column_stack([fn(x,mu+spacing*n,w*(s.sideband_width_scale if n else 1.),eta)
                                for mu,w,eta in rows for n in orders])

    mask = np.flatnonzero((p.x >= s.fit_min)&(p.x <= s.fit_max))[::3]
    xseed, yseed = p.x[mask], p.y[mask]
    scale = float(np.max(np.abs(yseed)))
    if not np.isfinite(scale) or scale <= 0 or np.std(yseed) <= scale*1e-10:
        raise ValueError('A flat spectrum cannot be decomposed.')
    yseed = yseed/scale

    def seed_eval(v):
        m = matrix(xseed,expand(v))
        h, _ = nnls(m,yseed,maxiter=600)
        return m@h-yseed,h

    def solve(fun, start, lo, hi, count, tol):
        return least_squares(fun, np.clip(start, lo+1e-7, hi-1e-7), bounds=(lo,hi),
                             max_nfev=count,ftol=tol,xtol=tol,gtol=tol)

    rng = np.random.default_rng(7121); seeds = []
    for i in range(8):
        start = low+(high-low)*rng.uniform(.1,.9,9)
        if i == 0: start = np.array([1,5,.6,7,8,.2,5,25,.8])
        fit = solve(lambda v: seed_eval(v)[0], start[free], low[free], high[free],500,1e-10)
        if np.isfinite(fit.cost): seeds.append(fit)
    if not seeds: raise ValueError('Ver2 did not find a finite fit. Review data and bounds.')
    seed = min(seeds,key=lambda f:f.cost)
    cfg = p.audit.get('settings', {})
    pivot = float(p.audit.get('phase_pivot_ppm',(p.x[0]+p.x[-1])/2))
    span = float(cfg.get('ppm_max',p.x[-1])-cfg.get('ppm_min',p.x[0]))
    warnings = ['Ver2 chemical assignments remain model-dependent. The broad unassigned area is excluded from both aliphatic and aromatic coverage terms. High fit R2 does not validate the partition.']
    joint = (p.raw_x is not None and p.raw_complex is not None
             and np.any(np.abs(p.raw_complex.imag) > 0) and not cfg.get('gaussian_fwhm',0))
    if not joint:
        warnings.append('Real-only fit on the processed spectrum: complex source is absent or smoothing is active. Joint phase/background refinement was not applied.')
    phase_on = cfg.get('phase',True)
    p0 = (float(p.audit.get('auto_phase0_deg',0))+cfg.get('phase0_offset',0)) if phase_on else 0.
    p1 = (float(p.audit.get('auto_phase1_deg',0))+cfg.get('phase1_deg',0)) if phase_on else 0.
    refine_phase = (joint and phase_on and s.joint_phase
                    and 'manual' not in p.audit.get('phase_source','').lower()
                    and not cfg.get('phase0_offset',0) and not cfg.get('phase1_deg',0))
    background = bool(cfg.get('baseline',True))
    bg = np.zeros(4); complex_r2 = None
    fits = seeds; best = seed; rows = expand(best.x); _, heights = seed_eval(best.x)
    phase_hits = []
    fit_window = [s.fit_min,s.fit_max]
    if joint:
        lo_x, hi_x = max(s.complex_fit_min,p.x[0]), min(s.complex_fit_max,p.x[-1])
        if lo_x > s.fit_min or hi_x < s.fit_max:
            raise ValueError('Ver2 complex fitting window must enclose the component integration range.')
        ids = np.flatnonzero((p.raw_x>=lo_x)&(p.raw_x<=hi_x))[::4]
        x, z = p.raw_x[ids], p.raw_complex[ids]/scale
        if len(x) < 40: raise ValueError('Ver2 complex fitting needs at least 40 sampled points.')
        fit_window = [lo_x,hi_x]
        t = (x-pivot)/span
        background_columns = np.column_stack((np.ones(len(x)),t,1j*np.ones(len(x)),1j*t))
        target = np.r_[z.real,z.imag]
        low2 = np.r_[low[free],-s.joint_phase0_limit,-s.joint_phase1_limit] if refine_phase else low[free]
        high2 = np.r_[high[free],s.joint_phase0_limit,s.joint_phase1_limit] if refine_phase else high[free]

        def evaluate(v):
            ph0,ph1 = v[-2:] if refine_phase else (p0,p1)
            r = expand(v[:-2] if refine_phase else v)
            m = matrix(x,r,True)*np.exp(-1j*np.deg2rad(ph0+ph1*t))[:,None]
            if background: m = np.column_stack((m,background_columns))
            m = np.r_[m.real,m.imag]
            bounds = (np.r_[np.zeros(nlines),[-np.inf]*4] if background else np.zeros(nlines), np.inf)
            h = lsq_linear(m,target,bounds=bounds,tol=1e-10,lsq_solver='exact').x
            return m@h-target,h

        rng = np.random.default_rng(123); fits = []
        for i in range(3):
            start = seed.x.copy()
            if i: start *= .85+.3*rng.random(len(start))
            if refine_phase: start = np.r_[start,p0,p1]
            f = solve(lambda v:evaluate(v)[0],start,low2,high2,250,1e-9)
            if np.isfinite(f.cost): fits.append(f)
        if not fits: raise ValueError('Ver2 complex fitting did not find a finite solution.')
        best = min(fits,key=lambda f:f.cost)
        res,h = evaluate(best.x); rows = expand(best.x[:-2] if refine_phase else best.x)
        heights = h[:nlines]
        if background: bg = h[nlines:]*scale
        if refine_phase:
            p0,p1 = map(float,best.x[-2:])
            phase_hits = [name for name,value,limit in zip(('PH0','PH1'),(p0,p1),(s.joint_phase0_limit,s.joint_phase1_limit)) if limit-abs(value) < .002*limit]
            if phase_hits: warnings.append('Joint phase at bound: '+', '.join(phase_hits)+'. Review the phase limits and family-area sensitivity.')
        denom = float(np.sum(abs(z-z.mean())**2))
        complex_r2 = float(1-res@res/denom) if denom else None

    def line_areas(shape_rows, hh):
        return {name:float(sum(hh[i*len(orders)+j]*scale*profile_area(s.fit_min,s.fit_max,1,mu+spacing*n,
                        w*(s.sideband_width_scale if n else 1.),eta) for j,n in enumerate(orders)))
                for i,(name,(mu,w,eta)) in enumerate(zip(FAMILIES,shape_rows))}

    areas = line_areas(rows,heights)
    lines = []; params = {}
    for i,(name,(mu,w,eta)) in enumerate(zip(FAMILIES,rows)):
        params[name] = [float(heights[i*len(orders)]*scale),float(mu),float(w),float(eta)]
        for j,n in enumerate(orders):
            height = float(heights[i*len(orders)+j]*scale)
            width = float(w*(s.sideband_width_scale if n else 1.))
            pars = [height,float(mu+n*spacing),width,float(eta)]
            full = height*width*((1-eta)*np.sqrt(np.pi)/(2*np.sqrt(np.log(2)))+eta*np.pi/2)
            lines.append({'family':name,'order':int(n),'parameters':pars,
                          'area':profile_area(s.fit_min,s.fit_max,*pars),'full_profile_area':float(full)})
    spread = {}; starts = []
    for f in fits:
        if joint:
            _,h = evaluate(f.x); shapes = expand(f.x[:-2] if refine_phase else f.x)
        else:
            _,h = seed_eval(f.x); shapes = expand(f.x)
        starts.append({'relative_SSE':float(f.cost/max(best.cost,1e-30)), 'converged':bool(f.success), 'areas':line_areas(shapes,h)})
    for name in FAMILIES:
        near = [r['areas'][name] for r,f in zip(starts,fits) if f.cost <= best.cost+max(.01*best.cost,1e-14)]
        spread[name] = max(near)-min(near)
        if spread[name] > max(areas[name],1e-30)*.1:
            warnings.append(name+': near-equivalent starts differ by >10% in area.')
    bound_hits = []
    for i,v in enumerate(rows.ravel()):
        if i in fixed: continue
        if min(v-low[i],high[i]-v) < .002*(high[i]-low[i]):
            label = FAMILIES[i//3]+': '+('center','FWHM','Lorentzian fraction')[i%3]
            bound_hits.append(label)
            warnings.append(label+' is at a fitting bound; review area sensitivity.')
    if not best.success: warnings.append('Optimizer reached its evaluation limit; inspect convergence before interpreting component areas.')
    breakdown = {name:{'central':sum(v['area'] for v in lines if v['family']==name and v['order']==0),
                       'sidebands':sum(v['area'] for v in lines if v['family']==name and v['order']!=0)} for name in FAMILIES}
    full_areas = {name:sum(v['full_profile_area'] for v in lines if v['family']==name) for name in FAMILIES}
    audit = {'version':5,'model_name':'broad_core3','settings':asdict(s),'processed_sha256':fingerprint(p),
             'complex_sha256':complex_fingerprint(p),'parameters':params,'lines':lines,'areas':areas,
             'area_breakdown':breakdown,'full_profile_areas':full_areas,
             'area_domain_ppm':[s.fit_min,s.fit_max], 'fit_window_ppm':fit_window,
             'area_method':'Analytic finite-domain sum of central and included MAS lines for each family. Broad unassigned area is kept separate.',
             'joint_complex':bool(joint),'joint_phase_refined':bool(refine_phase),'complex_background_fitted':bool(joint and background),
             'phase0_deg':p0,'phase1_deg':p1,'phase_pivot_ppm':pivot,'phase_span_ppm':span,
             'complex_background':bg.tolist(),'complex_fit_R2':complex_r2,'spacing_ppm':spacing,
             'phase_bound_hits':phase_hits,'parameter_bound_hits':bound_hits,'starts':starts,'near_solution_area_spread':spread,
             'converged_starts':sum(bool(f.success) for f in fits),'fit_points':len(x) if joint else len(xseed),
             'warnings':warnings,'assignment_ambiguous':bool(bound_hits or phase_hits or not best.success or any(spread[k]>.1*max(areas[k],1e-30) for k in areas)),
             'assignment_note':'Broad unassigned signal is not assumed aliphatic or aromatic. No 13C ratio or expected sample ordering is imposed.'}
    result = restore_family(p,audit)
    y,res = result.observed,result.residual
    denom = float(np.sum((y-y.mean())**2))
    audit.update(fit_R2=float(1-res@res/denom) if denom else 0.,RMSE=float(np.sqrt(np.mean(res**2))),
                 max_residual_percent_of_peak=float(np.max(np.abs(res))/max(np.max(np.abs(y)),1e-30)*100))
    if audit['fit_R2'] < .98: warnings.append('Fit R2 < 0.98: the chosen families do not reproduce the spectrum adequately.')
    full_y = corrected_complex(p,audit).real
    diag = sideband_diagnostics(p.x,full_y,spacing,max_order=s.sideband_order if s.sidebands else 0,
                               anchor_min=cfg.get('baseline_anchor_min',0))
    audit['sideband_diagnostics'] = diag
    warnings.extend(diag['warnings'])
    local = []
    for n in orders:
        m = np.abs(result.x-(4.5+n*spacing))<=20
        if np.any(m): local.append({'order':int(n),'RMSE_over_local_peak':float(np.sqrt(np.mean(res[m]**2))/max(np.max(abs(y[m])),1e-30))})
    audit['local_fit_errors'] = local
    return result
