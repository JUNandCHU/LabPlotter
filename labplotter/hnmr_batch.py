"""Reviewable batch plans and explicitly provisional H NMR reports."""
from dataclasses import dataclass, asdict
import csv
import io
import json

from .hnmr import infer_identity, restored_quant_settings
from .hnmr_decomposition import MODEL_LABELS


@dataclass
class QuantRequest:
    sample: object
    reference: object
    settings: object
    error: str = ''


def batch_plan(spectra, parameters):
    """Preserve entered parameters; never invent a missing ligand/mass/reference."""
    plan = []
    for sample in spectra:
        q = restored_quant_settings(sample, parameters)
        q.show_provisional = True
        saved_uid = sample.metadata.get('analysis_reference_uid')
        candidates = [s for s in spectra if infer_identity(s.name) == (q.core, '')]
        reference = next((s for s in candidates if s.uid == saved_uid), None)
        if reference is None and len(candidates) == 1: reference = candidates[0]
        error = ''
        if reference is None:
            error = 'Load one matching pristine core, or select a reference in individual Quantitative analysis.'
        else:
            p, r = sample.processing, reference.processing
            q.use_prepared = bool(q.use_prepared and p.get('prepared') and r.get('prepared')
                and p.get('group_id') and p.get('group_id') == r.get('group_id') and p.get('settings') == r.get('settings'))
        try: q.validate()
        except (ValueError, TypeError) as exc: error = str(exc)
        plan.append(QuantRequest(sample, reference, q, error))
    return plan


def remember_result(sample, reference, settings, result):
    sample.metadata.update(analysis_parameters=asdict(settings), analysis_audit=result.audit,
        analysis_reference_uid=reference.uid, decomposition=result.sample_fit.record(),
        decomposition_settings=result.sample_fit.audit['settings'])
    if not settings.use_prepared:
        audit = result.sample.audit
        sample.processing = {'prepared':False,'group_id':'','settings':audit['settings'],
                             'phase0':audit.get('auto_phase0_deg'),'phase1':audit.get('auto_phase1_deg'),
                             'shift':audit.get('shift_added_ppm',0.),'audit':audit}


def summary_row(request, result=None, error=''):
    q = request.settings
    row = {'sample': request.sample.name,
           'reference': request.reference.name if request.reference else '',
           'core': q.core, 'ligand': q.ligand, 'sample_mass_mg': q.sample_mass_mg,
           'reference_mass_mg': q.reference_mass_mg, 'standard_area': q.standard_area,
           'standard_basis': q.standard_basis, 'standard_umol_H': q.standard_umol_h,
           'normalization_method': q.core_scaling,
           'decomposition_model': MODEL_LABELS[q.model],
           'include_linkage_nh':q.include_linkage_nh,
           'response_factor': q.response_factor, 'reference_response_factor': q.reference_response_factor,
           'H_per_ligand': q.effective_h, 'capacity_umol_mg': q.capacity_umol_mg,
           'provisional': result.provisional if result else True,
           'status': result.quantitative_status if result else error or request.error or 'Ready; provisional mode'}
    for key in ('apparent_coverage_percent', 'ligand_umol', 'loading_umol_mg', 'excess_aliphatic_area',
                'coverage_lower_percent','coverage_upper_percent','coverage_schiff_percent','coverage_michael_percent',
                'schiff_H_per_ligand','michael_H_per_ligand','ligand_integral','core_template_integral','core_template_scale',
                'aliphatic_integral', 'aromatic_integral', 'aliphatic_signal_fraction_percent',
                'reference_aliphatic_integral', 'reference_aromatic_integral', 'aromatic_normalization_factor',
                'sample_aliphatic_H_umol_per_mg', 'sample_aromatic_H_umol_per_mg',
                'reference_aliphatic_H_umol_per_mg', 'reference_aromatic_H_umol_per_mg',
                'normalized_sample_aliphatic_H_umol_per_mg', 'excess_aliphatic_H_umol_per_mg',
                'sample_fit_R2', 'reference_fit_R2'):
        row[key] = result.values.get(key) if result else None
    row['unresolved_checks'] = '; '.join(result.validation_issues) if result else ''
    row['warnings'] = '\n'.join(result.warnings) if result else ''
    row['parameters_json'] = json.dumps(asdict(q), ensure_ascii=False, allow_nan=False)
    return row


def summary_csv(rows):
    stream = io.StringIO(newline='')
    if rows:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    return stream.getvalue()
