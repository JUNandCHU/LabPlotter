"""Read-only comparison of assignment models on identical corrected data."""
from dataclasses import asdict, replace
from .hnmr_decomposition import decompose


def model_review(processed, settings, reference=None, reference_info=None, fixed_core_scale=None):
    variants = [('Current model', settings)]
    for shape in ('pseudo_voigt', 'gaussian', 'lorentzian'):
        candidate = replace(settings, line_shape=shape, aliphatic_gaussian_fraction=None,
                            aromatic_gaussian_fraction=None)
        if asdict(candidate) != asdict(settings): variants.append((shape, candidate))
    if not settings.overlap_band and settings.model != 'broad_core3':
        variants.append(('Unassigned overlap added', replace(settings, overlap_band=True)))
    if settings.model == 'broad_core3':
        variants.extend([('Joint phase fixed at preprocessing', replace(settings,joint_phase=False)),
                         ('Broad family FWHM up to 60 ppm', replace(settings,unassigned_fwhm_max=60.))])
    modern = settings.model == 'core_template'
    if modern:
        variants.extend([('Fixed core position',replace(settings,template_shift_max=0.)),
                         ('Core shift up to 1 ppm',replace(settings,template_shift_max=1.)),
                         ('Core broadening up to 4 ppm',replace(settings,template_broadening_max=4.))])
    rows = []
    for label, candidate in variants:
        try:
            fit = decompose(processed, candidate, reference, reference_info, fixed_core_scale)
            first,second = ('ligand','core_template') if modern else ('aliphatic','aromatic')
            a, b = fit.areas[first], fit.areas[second]
            rows.append({'model': label, first+'_integral': a, second+'_integral': b,
                         'unassigned_integral': fit.areas.get('unassigned', 0.),
                         first+'_fraction_of_assigned_percent': 100*a/(a+b) if a+b else None,
                         first+'_fraction_of_all_components_percent': 100*a/sum(fit.areas.values()) if sum(fit.areas.values()) else None,
                         'fit_R2': fit.audit['fit_R2'], 'RMSE': fit.audit['RMSE'],
                         'assignment_ambiguous': fit.audit.get('assignment_ambiguous', False),
                         'warnings': fit.warnings, 'fit': fit.record()})
        except ValueError as exc:
            rows.append({'model': label, 'error': str(exc)})
    return {'rows': rows, 'model':settings.model, 'note': 'Same source spectrum, fit bounds, MAS spacing and integration domain. Ver2 refines complex phase/background per model; inspect their audit values. '
        'Diagnostic scenarios only; no spectrum or saved fit is changed. A better R2 after adding a component '
        'does not establish its chemical identity. Fraction of assigned excludes the unassigned component; '
        'fraction of all includes it. These are not confidence intervals.'}
