"""Read-only phase sensitivity checks. No sample identity enters the fit objective."""
from dataclasses import asdict, replace
import numpy as np
from .hnmr import HNMRSettings, common_settings, process_hnmr
from .hnmr_decomposition import decompose, decomposition_defaults


def phase_sensitivity(sample, reference=None, *, settings=None, phase_step=2.,
                      sample_mass=1., reference_mass=1., sample_response=1., reference_response=1.):
    """Refit PH0 +/- step with PH1 held fixed and baseline recomputed.

    These scenarios are not statistical confidence intervals. Different samples
    may have independent phase errors, so range-overlap is checked as well as
    the nominal ordering. Does not store any fit or processing changes.
    """
    try:
        phase_step, sample_mass, reference_mass, sample_response, reference_response = map(
            float, (phase_step, sample_mass, reference_mass, sample_response, reference_response))
    except (ValueError, TypeError) as exc:
        raise ValueError('Enter a phase step, both masses and response factors before running sensitivity.') from exc
    if not np.isfinite([phase_step, sample_mass, reference_mass, sample_response, reference_response]).all() or not 0 < phase_step <= 20 or min(sample_mass, reference_mass, sample_response, reference_response) <= 0:
        raise ValueError('Use a phase step >0 and <=20 degrees, and positive masses / response factors.')
    spectra=[sample] if reference is None or reference.uid == sample.uid else [sample, reference]
    model=(settings or decomposition_defaults(sample)).validate()
    saved=[s.processing for s in spectra]
    same=all(p.get('settings') and p.get('settings') == saved[0].get('settings') for p in saved)
    cfg=HNMRSettings(**saved[0]['settings']) if same else common_settings(spectra)
    if not cfg.phase:
        raise ValueError('Enable phase correction before testing phase sensitivity.')
    # A known fitting rate must also govern preprocessing masks.
    if model.mas_hz:
        cfg=replace(cfg, mas_hz=model.mas_hz, proton_mhz=model.proton_mhz).validate()
    if model.model == 'core_template':
        if reference is None:
            raise ValueError('model Ver2 phase sensitivity requires the pristine core reference.')
        variants = []
        for s in (sample,reference):
            stored = s.processing if same else {}
            base = process_hnmr(s,cfg,stored.get('phase0',s.metadata.get('manual_phase0')),
                               stored.get('shift',0.),stored.get('phase1'))
            variants.append([(offset,process_hnmr(s,replace(cfg,phase0_offset=cfg.phase0_offset+offset),
                              base.audit['auto_phase0_deg'],base.audit['shift_added_ppm'],base.audit['auto_phase1_deg']))
                             for offset in (-phase_step,0.,phase_step)])
        rows = []
        for sample_offset,p in variants[0]:
            for core_offset,r in variants[1]:
                if sample.uid == reference.uid and sample_offset != core_offset: continue
                fit = decompose(p,model,r,{'name':reference.name,'uid':reference.uid})
                a,b = fit.areas['ligand'],fit.areas['core_template']
                scale = fit.audit['core_scale']
                rows.append({'sample':sample.name,'uid':sample.uid,'phase_offset_deg':sample_offset,
                             'reference_phase_offset_deg':core_offset,'ligand_area':a,'core_template_area':b,
                             'core_scale':scale,'ligand_reference_area_per_mg':a/scale*reference_response/reference_mass if scale>1e-12 else None,
                             'ligand_fraction_percent':100*a/(a+b) if a+b else None,
                             'fit_R2':fit.audit['fit_R2'],'warnings':fit.warnings})
        return {'phase_step_deg':phase_step,'preprocessing':asdict(cfg),'decomposition':asdict(model),'rows':rows,
                'note':'model Ver2: independently perturbed sample and pristine PH0; PH1 fixed, baseline recomputed, template and ligand refitted. Reference-equivalent area is not a measured mass or coverage. Scenarios are not confidence intervals.'}
    rows=[]
    for i,s in enumerate(spectra):
        mass=sample_mass if i == 0 else reference_mass
        response=sample_response if i == 0 else reference_response
        stored=s.processing if same else {}
        base=process_hnmr(s,cfg,stored.get('phase0',s.metadata.get('manual_phase0')),
                          stored.get('shift',0.),stored.get('phase1'))
        scan_model = model
        phase0,phase1 = base.audit['auto_phase0_deg'],base.audit['auto_phase1_deg']
        if model.model == 'broad_core3':
            # Perturb the displayed joint-fit phase; keep every scenario fixed,
            # including zero. Otherwise only zero would re-optimize its phase.
            from .hnmr_decomposition import restore_decomposition
            nominal = restore_decomposition(base,s.metadata.get('decomposition'))
            if nominal is None or nominal.audit['settings'] != asdict(model): nominal = decompose(base,model)
            phase0 = nominal.audit['phase0_deg']-cfg.phase0_offset
            phase1 = nominal.audit['phase1_deg']-cfg.phase1_deg
            scan_model = replace(model,joint_phase=False)
        for offset in (-phase_step,0.,phase_step):
            p=process_hnmr(s,replace(cfg,phase0_offset=cfg.phase0_offset+offset),phase0,
                           base.audit['shift_added_ppm'],phase1)
            fit=decompose(p,scan_model);a=fit.areas['aliphatic'];b=fit.areas['aromatic']
            rows.append({'sample':s.name,'uid':s.uid,'phase_offset_deg':offset,
                         'phase0_deg':fit.audit.get('phase0_deg',p.audit['auto_phase0_deg']+cfg.phase0_offset+offset),
                         'phase1_deg':fit.audit.get('phase1_deg',p.audit['auto_phase1_deg']+cfg.phase1_deg),
                         'aliphatic_area':a,'aromatic_area':b,'aliphatic_per_mg':a*response/mass,
                         'aliphatic_fraction_percent':100*a/(a+b) if a+b else None,
                         'fit_R2':fit.audit['fit_R2'],'assignment_ambiguous':fit.audit.get('assignment_ambiguous',False),
                         'warnings':fit.warnings})
    report={'phase_step_deg':phase_step,'preprocessing':asdict(cfg),'decomposition':asdict(model),'rows':rows,
            'note':'Ver2 is anchored to its nominal joint-fit phase with phase refinement disabled in every scenario. PH0 perturbations with fixed PH1, recomputed baseline and fresh component fits; no normalization, clipping, or forced sample ordering. Sensitivity scenarios are not confidence intervals.'}
    if len(spectra)==2:
        a=[r for r in rows if r['uid']==sample.uid];b=[r for r in rows if r['uid']==reference.uid]
        def comparison(key):
            av=[r[key] for r in a];bv=[r[key] for r in b]
            if any(v is None for v in av+bv):return {'nominal_difference':None,'ordering':'undefined'}
            return {'nominal_difference':av[1]-bv[1],
                    'sample_range':[min(av),max(av)],'reference_range':[min(bv),max(bv)],
                    'ordering':'sample above reference throughout' if min(av)>max(bv) else
                               'sample below reference throughout' if max(av)<min(bv) else 'phase-sensitive / ranges overlap'}
        report['comparison']={k:comparison(k) for k in ('aliphatic_per_mg','aliphatic_fraction_percent')}
    return report
