"""Phase/baseline and MAS-envelope diagnostics without equal-height assumptions.

Sidebands are constrained by their spacing, not by equal +/- intensities.
The peak count is a prominence/SNR diagnostic, not a molecular assignment.
"""
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import minimize
from scipy.signal import find_peaks


# Editable lab preset supplied by the user; not recovered acquisition metadata.
LAB_PROTON_MHZ = 400.
LAB_MAS_HZ = 20000.


def instrument_preset(spectrum):
    saved = spectrum.metadata.get('acquisition', {})
    return float(saved.get('mas_hz', LAB_MAS_HZ)), float(saved.get('proton_mhz', LAB_PROTON_MHZ))


def noise_sigma(y):
    y = np.asarray(y)
    if len(y) < 4: return 0.
    d = np.diff(y)
    return float(np.median(np.abs(d-np.median(d)))/(.67448975*np.sqrt(2)))


def estimate_spacing(x, z):
    """Propose ppm spacing from visible envelopes; never invent MAS Hz or SF."""
    x, z = np.asarray(x), np.asarray(z)
    if x[0] > -110 or x[-1] < 120: return 55., 'default estimate; insufficient wide-range support'
    step = np.median(np.diff(x)); magnitude = gaussian_filter1d(abs(z), max(1., .3/step))
    indices, _ = find_peaks(magnitude, prominence=max(magnitude)*.001, distance=max(1, int(20/step)))
    positive = [x[i] for i in indices if 35 < x[i] < 85]
    negative = [x[i] for i in indices if -80 < x[i] < -25]
    if not positive or not negative: return 55., 'default estimate; first-order pair unresolved'
    spacing = min(((a-b)/2 for a in positive for b in negative), key=lambda v: abs(v-55))
    outer_p = [x[i] for i in indices if 90 < x[i] < 145]
    outer_m = [x[i] for i in indices if -140 < x[i] < -85]
    if outer_p and outer_m:
        outer = min(((a-b)/4 for a in outer_p for b in outer_m), key=lambda v: abs(v-spacing))
        spacing = (spacing+2*outer)/3
    return float(spacing), 'estimated from magnitude-envelope positions; verify MAS_Hz / 1H_MHz'


def signal_free_mask(x, spacing, half_width=20., center=4.5):
    mask = np.ones(len(x), dtype=bool)
    count = int(max(abs(x[0]-center), abs(x[-1]-center))/spacing)+1
    for order in range(-count, count+1):
        mask &= abs(x-(center+order*spacing)) > half_width
    return mask


def masked_baseline(x, y, spacing, half_width=20., degree=2, anchor_min=0.):
    mask = signal_free_mask(x, spacing, half_width)
    mask &= abs(x-4.5) >= anchor_min
    if mask.sum() < max(20, (degree+1)*8):
        raise ValueError('Too few baseline anchors. Reduce exclusion width or expand preprocessing range.')
    # Scaling the abscissa avoids ill-conditioned powers of ppm.
    mid=(x[0]+x[-1])/2; span=x[-1]-x[0]; u=(x-mid)/span
    keep=mask.copy()
    for _ in range(5):
        coeff=np.polyfit(u[keep], y[keep], degree)
        residual=y-np.polyval(coeff,u)
        median=np.median(residual[keep]); mad=np.median(abs(residual[keep]-median))
        if mad <= np.finfo(float).eps*max(1.,np.max(abs(y))): break
        candidate=mask & (abs(residual-median)<=4.5*mad)
        if candidate.sum()<20 or np.array_equal(candidate,keep): break
        keep=candidate
    curve=np.polyval(coeff,u)
    return curve, {'mode':'masked_polynomial', 'degree':int(degree), 'coefficients':coeff.tolist(),
                   'coordinate':'(ppm-midpoint)/span', 'midpoint_ppm':float(mid), 'span_ppm':float(span),
                   'anchor_points':int(keep.sum()), 'excluded_half_width_ppm':float(half_width),
                   'anchor_min_distance_from_4_5_ppm':float(anchor_min),
                   'spacing_ppm':float(spacing), 'anchor_RMS':float(np.sqrt(np.mean((y[keep]-curve[keep])**2)))}


def phase_zero_first(x, z, start_phase, spacing, half_width=20., degree=2, anchor_min=0., balance_sidebands=False):
    """Bounded ACME-style 0/1-order phase, with masked-baseline diagnostics.

    Does not minimize differences between +/- sideband amplitudes. First order
    is across this processing range, not an undocumented instrument convention.
    """
    scale=float(np.max(abs(z))); span=float(x[-1]-x[0]); pivot=float((x[0]+x[-1])/2)
    if scale<=0 or np.max(abs(z.imag))<scale*1e-12:
        return start_phase, 0., {'method':'zero-order fallback; no complex phase information','warnings':[]}
    stride=max(1,len(x)//3500); xx=x[::stride]; zz=z[::stride]/scale
    u=(xx-pivot)/span
    def score(v):
        y=(zz*np.exp(1j*np.deg2rad(v[0]+v[1]*u))).real
        baseline,_=masked_baseline(xx,y,spacing,half_width,degree,anchor_min)
        y=y-baseline; derivative=abs(np.diff(y)); total=derivative.sum()
        prob=derivative/total if total else derivative
        entropy=-np.sum(prob[prob>0]*np.log(prob[prob>0]))
        energy=np.sum(y*y)+1e-30
        return float(entropy+1000*np.sum(np.minimum(y,0)**2)/energy)
    fits=[]
    for first in (-90.,0.,90.):
        fit=minimize(score,[start_phase,first],method='Nelder-Mead',bounds=[(start_phase-90,start_phase+90),(-180,180)],
                     options={'maxiter':240,'xatol':.01,'fatol':1e-8})
        if fit.success and np.isfinite(fit.fun): fits.append(fit)
    if not fits: return start_phase,0.,{'method':'zero-order fallback','warnings':['First-order phase did not converge.']}
    best=min(fits,key=lambda f:f.fun); warnings=[]
    if abs(best.x[1])>170:
        warnings.append('Automatic PH1 reached its +/-180 degree limit; retained zero-order correction. Review manual PH0/PH1 and baseline.')
        return start_phase,0.,{'method':'zero-order fallback; PH1 limit','candidate_phase0':float(best.x[0]),
                              'candidate_phase1':float(best.x[1]),'warnings':warnings}
    if best.fun >= score([start_phase,0.]):
        return start_phase,0.,{'method':'zero-order fallback; no objective improvement','warnings':[]}
    selected = best.x
    refinement = None
    if balance_sidebands:
        selected, refinement = refine_sideband_phase(xx, zz, best.x, spacing, half_width, degree, anchor_min)
        warnings += refinement['warnings']
    return float((selected[0]+180)%360-180),float(selected[1]),{
        'method':'bounded zero/first-order entropy + negative energy; peak-excluded baseline',
        'objective_before':score([start_phase,0.]),'objective_after':score(selected),
        'sideband_refinement':refinement,
        'pivot_ppm':pivot,'span_ppm':span,'warnings':warnings}


def refine_sideband_phase(x, z, initial, spacing, half_width=20., degree=1, anchor_min=145.):
    """Bounded, noise-aware per-envelope refinement of an existing PH0/PH1.

    A global negative-energy score can ignore weak satellites. Each resolved
    envelope contributes here relative to its OWN fixed complex energy. One
    global linear phase is fitted; no peak-wise rotations, sign flipping,
    equal +/- heights or specimen/ligand names enter the objective. Baseline
    anchors are refitted at each trial. This is a proposal, not a guarantee of
    purely absorptive lines (pulse/dead-time/background errors can remain).
    """
    x, z, initial = np.asarray(x), np.asarray(z), np.asarray(initial, dtype=float)
    u=(x-(x[0]+x[-1])/2)/(x[-1]-x[0])
    central=abs(x-4.5)<min(22., spacing*.42)
    off=signal_free_mask(x,spacing,half_width) & (abs(x-4.5)>=anchor_min)
    noise=max(noise_sigma(z.real[off]),noise_sigma(z.imag[off]),float(max(abs(z)))*1e-5)
    magnitude=gaussian_filter1d(abs(z),max(.15/np.median(np.diff(x)),.5))
    windows=[]; orders=[]
    for order in (-2,-1,1,2):
        center=4.5+order*spacing; half=min(22.,spacing*.42)
        mask=abs(x-center)<=half
        if x[0]>center-half or x[-1]<center+half or mask.sum()<12: continue
        _, peaks=find_peaks(magnitude[mask],prominence=max(5*noise,max(magnitude)*.0005))
        if len(peaks['prominences']): windows.append(mask); orders.append(order)
    def corrected(v):
        y=(z*np.exp(1j*np.deg2rad(v[0]+v[1]*u))).real
        base,_=masked_baseline(x,y,spacing,half_width,degree,anchor_min)
        return y-base
    before=corrected(initial)
    energies=[float(np.sum(abs(z[m])**2))+1e-30 for m in windows]
    def negative(y):
        return float(np.mean([np.sum(np.minimum(y[m]+3*noise,0)**2)/energy
                              for m,energy in zip(windows,energies)])) if windows else 0.
    initial_negative=negative(before)
    report={'enabled':True,'accepted':False,'resolved_orders':orders,
            'phase0_before':float(initial[0]),'phase1_before':float(initial[1]),
            'negative_score_before':initial_negative,'negative_score_after':initial_negative,
            'phase0_bound_deg':5.,'phase1_bound_deg':60.,'warnings':[]}
    if not windows or initial_negative<1e-8:
        report['reason']='No resolved negative satellite signal above the noise threshold.'
        return initial,report
    energy=float(np.sum(before**2))+1e-30
    central_area=float(np.sum(np.maximum(before[central],0)))
    initial_cneg=float(np.sum(np.minimum(before[central],0)**2)/energy)
    def score(v):
        y=corrected(v)
        # Keep the main envelope close while allowing weak sidebands to matter.
        change=np.sum((y[central]-before[central])**2)/energy
        delta=(v-initial)/np.array([5.,60.])
        return 10*negative(y)+change+.002*float(np.sum(delta**2))
    bounds=[(initial[0]-5.,initial[0]+5.),(max(-170.,initial[1]-60.),min(170.,initial[1]+60.))]
    fits=[minimize(score,[initial[0],np.clip(initial[1]+d,*bounds[1])],method='Nelder-Mead',bounds=bounds,
                   options={'maxiter':180,'xatol':.01,'fatol':1e-9}) for d in (-30.,0.,30.)]
    candidates=[f for f in fits if f.success and np.isfinite(f.fun)]
    if not candidates:
        report['reason']='Refinement did not converge; retained initial correction.'
        return initial,report
    best=min(candidates,key=lambda f:f.fun);after=corrected(best.x)
    ratio=float(np.sum(np.maximum(after[central],0))/(central_area+1e-30))
    cneg=float(np.sum(np.minimum(after[central],0)**2)/energy)
    accepted=bool(best.fun<score(initial) and negative(after)<initial_negative*.98 and
                  .9<=ratio<=1.1 and cneg<=max(initial_cneg*1.25,1e-4))
    report.update(accepted=accepted,candidate_phase0=float(best.x[0]),candidate_phase1=float(best.x[1]),
                  candidate_negative_score=negative(after),central_positive_area_ratio=ratio,
                  reason='Reduced resolved-satellite negative energy with central-envelope guard.' if accepted
                  else 'No acceptable improvement; retained initial correction.')
    if accepted:
        report['negative_score_after']=negative(after)
        if any(abs(best.x[i]-b)<.1 for i in (0,1) for b in bounds[i]):
            report['warnings'].append('Sideband phase refinement reached a bound; inspect the candidate and remaining negative lobes.')
    return best.x if accepted else initial,report


def sideband_diagnostics(x, y, spacing, max_order=2, snr_threshold=5., center=4.5, anchor_min=0.):
    x,y=np.asarray(x),np.asarray(y); step=float(np.median(np.diff(x)))
    smooth=gaussian_filter1d(y,max(.15/step, .5))
    off=signal_free_mask(x,spacing,min(20.,spacing*.36),center)
    off &= abs(x-4.5) >= anchor_min
    sigma=noise_sigma(y[off]) if off.sum()>10 else noise_sigma(y)
    # Slow baseline error is included as a floor; narrow-point noise alone can
    # misleadingly label broad residual waves as very high-SNR sidebands.
    drift=float(np.median(abs(y[off]-np.median(y[off])))/.67448975) if off.sum()>10 else 0.
    effective_noise=max(sigma,drift,float(np.max(abs(y)))*1e-5)
    rows=[]; warnings=[]; central=float(np.max(abs(y)))
    for order in range(-int(max_order)-1,int(max_order)+2):
        if order==0: continue
        expected=center+order*spacing; half=min(22.,spacing*.42)
        mask=(x>=expected-half)&(x<=expected+half)
        row={'order':order,'included':abs(order)<=max_order,'expected_envelope_ppm':expected,
             'covered':bool(x[0]<=expected-half and x[-1]>=expected+half)}
        if mask.sum()<12 or not row['covered']:
            row.update(status='outside measured range',peak_ppm=None,SNR=None,prominence=0.,negative_fraction=None)
        else:
            xx=x[mask]; yy=smooth[mask]; original=y[mask]
            ids,props=find_peaks(yy,prominence=effective_noise, distance=max(1,int(1/step)))
            if len(ids):
                j=int(np.argmax(props['prominences'])); idx=ids[j]; prominence=float(props['prominences'][j]);peak=float(xx[idx])
            else:prominence=0.;peak=None
            snr=prominence/effective_noise
            detectable=snr>=snr_threshold and prominence>=central*.0005
            row.update(status='detected' if detectable else 'weak / unresolved',peak_ppm=peak,SNR=snr,prominence=prominence,
                       negative_fraction=float(np.sum(np.maximum(-original,0))/(np.sum(abs(original))+1e-30)))
            if row['included'] and row['negative_fraction']>.15:
                warnings.append(f'Order {order:+d}: substantial negative signal; inspect phase/baseline before assigning area.')
            if not row['included'] and detectable:
                warnings.append(f'Order {order:+d}: a candidate peak lies outside the included orders; review the integration scope.')
        rows.append(row)
    pairs=[]
    for n in range(1,int(max_order)+1):
        minus=next(r for r in rows if r['order']==-n);plus=next(r for r in rows if r['order']==n)
        a,b=minus['peak_ppm'],plus['peak_ppm']
        pairs.append({'order':n,'midpoint_ppm':(a+b)/2 if a is not None and b is not None else None,
                      'spacing_from_peak_pair_ppm':(b-a)/(2*n) if a is not None and b is not None else None})
    return {'noise_sigma':sigma,'baseline_drift_sigma':drift,'effective_noise':effective_noise,
            'noise_anchor_min_distance_ppm':float(anchor_min),'noise_anchor_points':int(off.sum()),
            'threshold_SNR':snr_threshold,'envelopes':rows,'position_pairs':pairs,
            'detected_sideband_envelopes':sum(r['included'] and r['status']=='detected' for r in rows),
            'warnings':warnings,
            'note':'A detected envelope can contain both chemical families. Peak maxima can shift with overlap/phase. Equal +/- heights are NOT required; weak fitted components are not independent detections.'}
